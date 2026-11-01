"""Original Hermes v0.22.5 stdlib document extractors (MIT).

Extracted verbatim functions; relative ansi import and explicit stdlib-only dispatcher.
Source and extraction boundaries recorded in DOCUMENT_SOURCES.json.
"""
from __future__ import annotations

# ruff: noqa: E741 -- original upstream lambda parameter retained
import contextlib
import functools
import itertools
import json
import os
import posixpath
import re
import shlex
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterator, Optional
from xml.etree import ElementTree as ET

EXTRACTABLE_EXTENSIONS = frozenset({".ipynb", ".docx", ".xlsx", ".db", ".sqlite", ".sqlite3"})

MAX_DOCUMENT_BYTES = 50 * 1024 * 1024

_MAX_XLSX_ROWS_PER_SHEET = 5000

_MAX_XLSX_COLS = 256

_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_NS_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

class ExtractionError(Exception):
    """Raised when a supported-looking document cannot be rendered as text."""

def _check_size(size: int, limit: int) -> None:
    if size > limit:
        raise ExtractionError(f"Document too large to convert ({size:,} bytes, limit is {limit:,})")

@contextlib.contextmanager
def _temp_copy(data: bytes, suffix: str) -> Iterator[str]:
    """Materialize backend bytes in a private host temp file; removed even when parsing fails."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(data)
    try:
        yield fh.name
    finally:
        with contextlib.suppress(OSError):
            os.unlink(fh.name)

def _joined(lines: list[str], empty_error: str) -> str:
    """Join extracted lines with a single trailing newline; raise when nothing non-blank."""
    if not any(line.strip() for line in lines):
        raise ExtractionError(empty_error)
    return "\n".join(lines).rstrip("\n") + "\n"

def _source_text(source) -> str:
    """Notebook source/text fields are a str or a list of str fragments."""
    if isinstance(source, list):
        source = "".join(item for item in source if isinstance(item, str))
    return source if isinstance(source, str) else ""

def _human_size(n_bytes: int) -> str:
    return f"{round(n_bytes / 1024)} KB" if n_bytes >= 1024 else f"{n_bytes} B"

def _base64_bytes(payload: str) -> int:
    """Approximate decoded size of a base64 payload (whitespace ignored)."""
    clean = re.sub(r"[^0-9+/=A-Za-z]", "", payload)
    return max(0, (len(clean) * 3) // 4 - min(2, len(clean) - len(clean.rstrip("="))))

def _clean_stream_text(text: str) -> str:
    """Strip ANSI escapes; keep only the final ``\\r`` frame of each line (tqdm redraws)."""
    from .ansi_strip import strip_ansi
    return "\n".join(([f for f in line.split("\r") if f] or [""])[-1]
                     for line in strip_ansi(text).replace("\r\n", "\n").split("\n"))

_MAX_OUTPUT_CHARS = 20_000

_V3_MIME_KEYS = (("png", "image/png"), ("jpeg", "image/jpeg"), ("svg", "image/svg+xml"), ("html", "text/html"))

def _notebook_output_text(output: Any) -> str:
    """One notebook output as compact text: stream/traceback/textual results kept; token-heavy
    payloads (images, HTML, widgets) become sized placeholders. Handles v4 and legacy v3 shapes."""
    if not isinstance(output, dict):
        return ""
    otype = output.get("output_type")
    if otype == "stream":
        body = _clean_stream_text(_source_text(output.get("text", "")))
        return body if body.strip() else ""
    if otype in {"error", "pyerr"}:
        tb = output.get("traceback")
        tb_text = _clean_stream_text("\n".join(filter(lambda l: isinstance(l, str), tb))
                                     if isinstance(tb, list) else "")
        header = f"Error: {output.get('ename', '')}: {output.get('evalue', '')}".rstrip(": ")
        return f"{header}\n{tb_text}".rstrip()
    if otype not in {"execute_result", "display_data", "pyout"}:
        return ""
    data = output.get("data")
    if not isinstance(data, dict):  # legacy v3: mime payloads sit flat on the output dict
        data = {"text/plain": output["text"]} if isinstance(output.get("text"), (str, list)) else {}
        data.update((mime, output[k]) for k, mime in _V3_MIME_KEYS if k in output)
    if "application/vnd.jupyter.widget-view+json" in data:
        return "[interactive widget — omitted]"
    for mime in ("text/plain", "text/markdown"):  # models consume text far better than markup
        body = _clean_stream_text(_source_text(data[mime])) if mime in data else ""
        if body.strip():
            return body
    for mime, value in data.items():
        if isinstance(mime, str) and mime.startswith("image/"):
            return f"[{mime} output — {_human_size(_base64_bytes(_source_text(value)))}, omitted]"
    if "text/html" in data:
        return f"[text/html output — {len(_source_text(data['text/html'])):,} chars, omitted]"
    return f"[{', '.join(str(m) for m in data) or 'unknown'} output — omitted]"

def _notebook_outputs(cell: dict, jq_pointer: str = "", filename: str = "") -> str:
    outputs = cell.get("outputs")
    if not isinstance(outputs, list):
        return ""
    joined = "\n".join(filter(None, map(_notebook_output_text, outputs)))
    if len(joined) <= _MAX_OUTPUT_CHARS:
        return joined
    hint = f" — full output: jq -r '{jq_pointer}' {shlex.quote(filename)}" if jq_pointer and filename else ""
    omitted = len(joined) - _MAX_OUTPUT_CHARS
    return joined[:_MAX_OUTPUT_CHARS] + f"\n… [{omitted:,} output chars truncated{hint}]"

_CELL_LABELS = {"markdown": "Markdown", "code": "Code", "raw": "Raw"}

def _extract_notebook(path: str, *, display_path: Optional[str] = None) -> str:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            nb = json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Not a valid notebook: {exc}") from exc
    if not isinstance(nb, dict):
        raise ExtractionError("Notebook root is not an object")
    raw_cells = nb.get("cells")
    if isinstance(raw_cells, list):
        cells = [(f".cells[{i}].outputs", cell) for i, cell in enumerate(raw_cells)]
    else:  # nbformat v3: cells live under worksheets
        cells = [
            (f".worksheets[{wi}].cells[{ci}].outputs", cell)
            for wi, ws in enumerate(nb.get("worksheets", [])) if isinstance(ws, dict)
            for ci, cell in enumerate(ws.get("cells", []))]
    if not cells:
        raise ExtractionError("Notebook contains no cells")
    # Backend bytes are parsed through a disposable host copy; recovery commands
    # must instead name the original notebook in the user's filesystem.
    nb_name = display_path if display_path is not None else path
    counts = dict.fromkeys(_CELL_LABELS, 0)
    out: list[str] = []
    for jq_pointer, cell in cells:
        typ = cell.get("cell_type") if isinstance(cell, dict) else None
        if typ not in _CELL_LABELS:
            continue
        counts[typ] += 1
        suffix = f" {counts[typ]}" if typ != "raw" else ""
        source = _source_text(cell.get("source", "")).rstrip("\n")
        out += [f"# ── {_CELL_LABELS[typ]} cell{suffix} ──", source, ""]
        rendered = _notebook_outputs(cell, jq_pointer, nb_name) if typ == "code" else ""
        if rendered:
            out += [f"# ── Output (cell {counts[typ]}) ──", rendered.rstrip("\n"), ""]
    return _joined(out, "Notebook contains no readable cells")

@contextlib.contextmanager
def _open_zip(path: str, kind: str) -> Iterator[zipfile.ZipFile]:
    """Open an OOXML package; bad-zip/OS failures (body included) become ExtractionError."""
    try:
        with zipfile.ZipFile(path) as zf:
            yield zf
    except (zipfile.BadZipFile, OSError) as exc:
        bad_zip = isinstance(exc, zipfile.BadZipFile)
        raise ExtractionError(f"Not a valid {kind}: {exc}" if bad_zip else str(exc)) from exc

def _zip_xml(zf: zipfile.ZipFile, name: str, optional: bool = False) -> Any:
    """Parse a package part; ``optional`` parts yield an empty element when absent or malformed."""
    try:
        return ET.fromstring(zf.read(name))
    except (KeyError, ET.ParseError) as exc:
        if optional:
            return ET.Element("missing")
        raise ExtractionError(
            f"Missing {name}" if isinstance(exc, KeyError) else f"Malformed XML in {name}: {exc}"
        ) from exc

def _extract_docx(path: str) -> str:
    with _open_zip(path, "DOCX") as zf:
        root = _zip_xml(zf, "word/document.xml")
    w = f"{{{_NS_W}}}"
    breaks = {f"{w}tab": "\t", f"{w}br": "\n", f"{w}cr": "\n"}
    lines: list[str] = []
    for para in root.iter(f"{w}p"):
        # w:rt is the ruby (phonetic) guide over w:rubyBase; it annotates the text, it is not text.
        guide = {n for rt in para.iter(f"{w}rt") for n in rt.iter()}
        text = "".join(
            (n.text or "") if n.tag == f"{w}t" else breaks.get(n.tag, "")
            for n in para.iter() if n not in guide)
        lines.extend(text.split("\n"))
    return _joined(lines, "DOCX contains no extractable text")

def _xlsx_string_text(item: ET.Element, s: str) -> str:
    """Base text of an si/is, excluding rPh phonetic annotations."""
    return "".join(
        (child.text or "") if child.tag == f"{s}t" else child.findtext(f"{s}t") or ""
        for child in item if child.tag in {f"{s}t", f"{s}r"})

def _extract_xlsx(path: str) -> str:
    s, r, pr = f"{{{_NS_S}}}", f"{{{_NS_REL}}}", f"{{{_NS_PKG_REL}}}"
    with _open_zip(path, "XLSX") as zf:
        names = set(zf.namelist())
        sst = _zip_xml(zf, "xl/sharedStrings.xml", optional=True)
        shared = [_xlsx_string_text(item, s) for item in sst.iter(f"{s}si")]
        rels_root = _zip_xml(zf, "xl/_rels/workbook.xml.rels", optional=True)
        rels = {rel.get("Id", ""): rel.get("Target", "")
                for rel in rels_root.iter(f"{pr}Relationship") if rel.get("Id")}
        out: list[str] = []
        for sheet in _zip_xml(zf, "xl/workbook.xml").iter(f"{s}sheet"):
            target = rels.get(sheet.get(f"{r}id", ""), "").lstrip("/")
            part = posixpath.normpath(target if target.startswith("xl/") else f"xl/{target}")
            if sheet.get("state", "visible") in {"hidden", "veryHidden"} or part not in names:
                continue
            with contextlib.suppress(ET.ParseError):
                rows = _sheet_rows(zf.read(part), shared)
                out += [f"# ── Sheet: {sheet.get('name', 'Sheet')} ──",
                        *(["\t".join(row) for row in rows] or ["(empty)"]), ""]
    return _joined(out, "XLSX has no visible sheets with content")

def _col_index(ref: str) -> int:
    """0-based column of a cell ref: ``A1`` -> 0, ``AB7`` -> 27 (bijective base-26 letters)."""
    idx = functools.reduce(lambda acc, ch: acc * 26 + ord(ch.upper()) - ord("A") + 1,
                           itertools.takewhile(str.isalpha, ref), 0)
    return max(idx - 1, 0)

def _sheet_rows(xml_bytes: bytes, shared: list[str]) -> list[list[str]]:
    root = ET.fromstring(xml_bytes)
    s = f"{{{_NS_S}}}"
    rows: list[list[str]] = []
    for row in itertools.islice(root.iter(f"{s}row"), _MAX_XLSX_ROWS_PER_SHEET):
        cells: dict[int, str] = {}
        max_col = -1
        for cell in row.iter(f"{s}c"):
            col = _col_index(cell.get("r", "")) if cell.get("r") else max_col + 1
            if col < _MAX_XLSX_COLS:
                cells[col] = _cell_value(cell, shared, s)
                max_col = max(max_col, col)
        rows.append([cells.get(i, "") for i in range(max_col + 1)])
    while rows and not any(value.strip() for value in rows[-1]):
        rows.pop()
    return rows

def _cell_value(cell: ET.Element, shared: list[str], s: str) -> str:
    value = cell.findtext(f"{s}v") or ""
    typ = cell.get("t", "")
    if typ == "s":
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return ""
    if typ == "inlineStr":
        inline = cell.find(f"{s}is")
        return "" if inline is None else _xlsx_string_text(inline, s)
    if typ == "b":
        return "TRUE" if value.strip() in {"1", "true", "TRUE"} else "FALSE"
    return (value or "#ERROR") if typ == "e" else value

_SQLITE_MAGIC = b"SQLite format 3\x00"

_SQLITE_PREVIEW_ROWS = 5

_SQLITE_MAX_TABLES = 200

_SQLITE_CELL_CHARS = 80

def _extract_sqlite(path: str) -> str:
    """Render a SQLite file as a schema overview: per table the CREATE statement, row count and the
    first rows. A ``.db`` that is not SQLite raises ExtractionError so read_file reports the real type."""
    import sqlite3

    with open(path, "rb") as fh:
        if fh.read(len(_SQLITE_MAGIC)) != _SQLITE_MAGIC:
            raise ExtractionError("not a SQLite database (magic bytes do not match)")
    # Read-only URI: never create or mutate; immutable=1 also skips WAL/journal sidecars so a live
    # database that another process has open is still readable without taking locks.
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        objs = con.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name"
        ).fetchall()
        out = ["# SQLite database", ""]
        tables = [o for o in objs if o[0] == "table"]
        others = [o for o in objs if o[0] != "table"]
        out.append(f"{len(tables)} table(s), {len(others)} index/view/trigger(s)")
        for _, name, sql in tables[:_SQLITE_MAX_TABLES]:
            quoted = '"' + name.replace('"', '""') + '"'
            count = con.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            out += ["", f"## {name}  ({count:,} rows)", sql.strip()]
            cur = con.execute(f"SELECT * FROM {quoted} LIMIT {_SQLITE_PREVIEW_ROWS}")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if rows:
                out.append("| " + " | ".join(cols) + " |")
                out.append("|" + "---|" * len(cols))
                for row in rows:
                    cells = [_sqlite_cell(v) for v in row]
                    out.append("| " + " | ".join(cells) + " |")
        if len(tables) > _SQLITE_MAX_TABLES:
            out.append(f"\n... {len(tables) - _SQLITE_MAX_TABLES} more tables omitted")
        if others:
            out += ["", "## Indexes / views / triggers"] + [f"- {t} {n}" for t, n, _ in others]
        out += ["", "Query it with the terminal: sqlite3 <path> 'SELECT ...'  (or Python's sqlite3 module)."]
        return "\n".join(out)
    except sqlite3.DatabaseError as exc:
        raise ExtractionError(f"SQLite read failed: {exc}") from exc
    finally:
        con.close()

def _sqlite_cell(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, bytearray)):
        return f"<blob {len(value)} bytes>"
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= _SQLITE_CELL_CHARS else text[:_SQLITE_CELL_CHARS - 1] + "…"

def extract_document_bytes(data: bytes, path: str) -> str:
    _check_size(len(data), MAX_DOCUMENT_BYTES)
    ext = Path(path).suffix.lower()
    extractors = {".ipynb": _extract_notebook, ".docx": _extract_docx, ".xlsx": _extract_xlsx,
                  ".db": _extract_sqlite, ".sqlite": _extract_sqlite, ".sqlite3": _extract_sqlite}
    if ext not in extractors:
        raise ExtractionError(f"Unsupported document type: {path!r}")
    with _temp_copy(data, ext) as temporary:
        if ext == ".ipynb":
            return _extract_notebook(temporary, display_path=path)
        return extractors[ext](temporary)
