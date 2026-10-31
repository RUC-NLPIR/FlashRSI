"""Pi's built-in filesystem and shell tools, implemented in Python.

The public functions use JSON-compatible values and intentionally avoid any
FlashRSI imports.  This lets a Snapshot run the same code when it is exported
to a temporary directory for a rollout.
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024
GREP_MAX_LINE_LENGTH = 500


@dataclass
class ToolResult:
    """A tool response in the shape consumed by the Pi agent loop."""

    content: str
    is_error: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def as_message_content(self) -> str:
        return self.content


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


def truncate_head(
    content: str,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[str, dict[str, Any]]:
    """Keep complete lines from the beginning, matching Pi's truncateHead."""

    if not content:
        lines: list[str] = []
    else:
        lines = content.split("\n")
        if content.endswith("\n"):
            lines.pop()
    total_bytes = len(content.encode("utf-8"))
    if len(lines) <= max_lines and total_bytes <= max_bytes:
        return content, {
            "truncated": False,
            "truncated_by": None,
            "total_lines": len(lines),
            "total_bytes": total_bytes,
            "output_lines": len(lines),
            "output_bytes": total_bytes,
            "first_line_exceeds_limit": False,
            "last_line_partial": False,
            "max_lines": max_lines,
            "max_bytes": max_bytes,
        }
    first_bytes = len(lines[0].encode("utf-8")) if lines else 0
    if first_bytes > max_bytes:
        return "", {
            "truncated": True,
            "truncated_by": "bytes",
            "total_lines": len(lines),
            "total_bytes": total_bytes,
            "output_lines": 0,
            "output_bytes": 0,
            "first_line_exceeds_limit": True,
            "last_line_partial": False,
            "max_lines": max_lines,
            "max_bytes": max_bytes,
        }
    selected: list[str] = []
    used = 0
    truncated_by = "lines"
    for index, line in enumerate(lines[:max_lines]):
        line_bytes = len(line.encode("utf-8")) + (1 if index else 0)
        if used + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        selected.append(line)
        used += line_bytes
    # Pi keeps the default "lines" label when every complete line fits but
    # the final newline itself puts the original content over the byte cap.
    if len(selected) >= max_lines and used <= max_bytes:
        truncated_by = "lines"
    output = "\n".join(selected)
    return output, {
        "truncated": True,
        "truncated_by": truncated_by,
        "total_lines": len(lines),
        "total_bytes": total_bytes,
        "output_lines": len(selected),
        "output_bytes": len(output.encode("utf-8")),
        "first_line_exceeds_limit": False,
        "last_line_partial": False,
        "max_lines": max_lines,
        "max_bytes": max_bytes,
    }


def truncate_tail(
    content: str,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[str, dict[str, Any]]:
    """Keep complete lines from the end, except a long final line."""

    lines = content.split("\n") if content else []
    if content.endswith("\n") and lines:
        lines.pop()
    total_bytes = len(content.encode("utf-8"))
    if len(lines) <= max_lines and total_bytes <= max_bytes:
        return content, {
            "truncated": False,
            "truncated_by": None,
            "total_lines": len(lines),
            "total_bytes": total_bytes,
            "output_lines": len(lines),
            "output_bytes": total_bytes,
            "last_line_partial": False,
            "first_line_exceeds_limit": False,
            "max_lines": max_lines,
            "max_bytes": max_bytes,
        }
    selected: list[str] = []
    used = 0
    partial = False
    truncated_by = "lines"
    for line in reversed(lines):
        if len(selected) >= max_lines:
            break
        line_bytes = len(line.encode("utf-8")) + (1 if selected else 0)
        if used + line_bytes > max_bytes:
            truncated_by = "bytes"
            if not selected:
                raw = line.encode("utf-8")[-max_bytes:] if max_bytes else b""
                while raw and raw[0] & 0xC0 == 0x80:
                    raw = raw[1:]
                selected.append(raw.decode("utf-8", errors="ignore"))
                used = len(selected[0].encode("utf-8"))
                partial = True
            break
        selected.insert(0, line)
        used += line_bytes
        if len(selected) >= max_lines:
            break
    output = "\n".join(selected)
    if len(selected) >= max_lines and used <= max_bytes:
        truncated_by = "lines"
    return output, {
        "truncated": True,
        "truncated_by": truncated_by,
        "total_lines": len(lines),
        "total_bytes": total_bytes,
        "output_lines": len(selected),
        "output_bytes": len(output.encode("utf-8")),
        "last_line_partial": partial,
        "first_line_exceeds_limit": False,
        "max_lines": max_lines,
        "max_bytes": max_bytes,
    }


def _resolve(path: str | None, cwd: str | Path) -> Path:
    value = "." if path is None or not str(path).strip() else str(path)
    if value.startswith("@"):
        value = value[1:]
    value = os.path.expanduser(value).replace("\u202f", " ")
    candidate = Path(value)
    return (candidate if candidate.is_absolute() else Path(cwd) / candidate).resolve()


def _result(text: str, **details: Any) -> ToolResult:
    return ToolResult(text, details=details)


def _error(text: str, **details: Any) -> ToolResult:
    return ToolResult(text, is_error=True, details=details)


def _read(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    path_text = str(args.get("path", ""))
    if not path_text.strip():
        return _error("read requires a non-empty path")
    path = _resolve(path_text, cwd)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _error(f"Could not read {path_text}: {exc}")
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        return _result(f"Read image file [{_mime(path.suffix.lower())}]")
    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\n")
    offset = args.get("offset")
    try:
        start = max(0, int(offset) - 1) if offset is not None else 0
    except (TypeError, ValueError):
        return _error("offset must be an integer")
    if start >= len(lines):
        return _error(
            f"Offset {offset} is beyond end of file ({len(lines)} lines total)"
        )
    limit = args.get("limit")
    try:
        end = min(start + int(limit), len(lines)) if limit is not None else len(lines)
    except (TypeError, ValueError):
        return _error("limit must be an integer")
    selected = "\n".join(lines[start:end])
    output, truncation = truncate_head(selected)
    if truncation.get("first_line_exceeds_limit"):
        first_size = format_size(len(lines[start].encode("utf-8")))
        output = (
            f"[Line {start + 1} is {first_size}, exceeds {format_size(DEFAULT_MAX_BYTES)} "
            f"limit. Use bash: sed -n '{start + 1}p' {path_text} | head -c {DEFAULT_MAX_BYTES}]"
        )
    elif truncation.get("truncated"):
        last = start + int(truncation["output_lines"])
        next_offset = last + 1
        suffix = f"[Showing lines {start + 1}-{last} of {len(lines)}. Use offset={next_offset} to continue.]"
        if truncation["truncated_by"] == "bytes":
            suffix = (
                f"[Showing lines {start + 1}-{last} of {len(lines)} "
                f"({format_size(DEFAULT_MAX_BYTES)} limit). Use offset={next_offset} to continue.]"
            )
        output += "\n\n" + suffix
    elif limit is not None and end < len(lines):
        output += f"\n\n[{len(lines) - end} more lines in file. Use offset={end + 1} to continue.]"
    return _result(
        output, **({"truncation": truncation} if truncation.get("truncated") else {})
    )


def _mime(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suffix, "application/octet-stream")


def _write(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    path_text = str(args.get("path", ""))
    content = args.get("content")
    if not path_text.strip() or not isinstance(content, str):
        return _error("write requires path and string content")
    path = _resolve(path_text, cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    except OSError as exc:
        return _error(f"Could not write {path_text}: {exc}")
    return _result(f"Successfully wrote to {path_text}")


def _normalize_for_fuzzy_match(text: str) -> str:
    """Apply Pi's conservative whitespace and punctuation normalization.

    Pi first attempts an exact replacement, then retries with this normalized
    representation so common model formatting differences (smart quotes,
    Unicode dashes, trailing spaces, and special spaces) do not make an edit
    fail.  The normalized representation is only used when exact matching
    fails; unchanged lines retain their original bytes when possible.
    """

    value = text.replace("\r\n", "\n").replace("\r", "\n")
    # Keep the import local so the small runtime remains cheap to import.
    import unicodedata

    value = unicodedata.normalize("NFKC", value)
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    value = re.sub(r"[\u2018\u2019\u201a\u201b]", "'", value)
    value = re.sub(r"[\u201c\u201d\u201e\u201f]", '"', value)
    value = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", value)
    return re.sub(r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]", " ", value)


def _find_edit_match(content: str, old_text: str) -> tuple[int, int, bool]:
    """Return ``(offset, length, used_fuzzy)`` for one unique match."""

    exact = content.find(old_text)
    if exact >= 0:
        return exact, len(old_text), False
    normalized_content = _normalize_for_fuzzy_match(content)
    normalized_old = _normalize_for_fuzzy_match(old_text)
    fuzzy = normalized_content.find(normalized_old)
    if fuzzy >= 0:
        return fuzzy, len(normalized_old), True
    return -1, 0, False


def _split_lines_with_endings(content: str) -> list[str]:
    """Split text like Pi's ``splitLinesWithEndings`` helper."""

    return re.findall(r"[^\n]*\n|[^\n]+", content)


def _generate_edit_diff(
    old: str, new: str, context_lines: int = 4
) -> tuple[str, int | None]:
    """Render Pi's display diff, with line numbers and bounded context."""

    before = _split_lines_with_endings(old)
    after = _split_lines_with_endings(new)
    parts: list[tuple[str, list[str]]] = []
    for tag, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(
        None, before, after, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            parts.append(("equal", before[old_start:old_end]))
        else:
            if old_end > old_start:
                parts.append(("removed", before[old_start:old_end]))
            if new_end > new_start:
                parts.append(("added", after[new_start:new_end]))

    width = len(str(max(len(old.split("\n")), len(new.split("\n")))))
    old_line = new_line = 1
    first_changed: int | None = None
    output: list[str] = []
    last_was_change = False
    for index, (kind, lines) in enumerate(parts):
        raw = [line.removesuffix("\n") for line in lines]
        if kind != "equal":
            if first_changed is None:
                first_changed = new_line
            for line in raw:
                if kind == "added":
                    output.append(f"+{new_line:>{width}} {line}")
                    new_line += 1
                else:
                    output.append(f"-{old_line:>{width}} {line}")
                    old_line += 1
            last_was_change = True
            continue

        trailing_change = index + 1 < len(parts) and parts[index + 1][0] != "equal"
        if last_was_change and trailing_change:
            leading = min(len(raw), context_lines)
            trailing = max(leading, len(raw) - context_lines)
            shown = set(range(leading)) | set(range(trailing, len(raw)))
        elif last_was_change:
            shown = set(range(min(len(raw), context_lines)))
        elif trailing_change:
            shown = set(range(max(0, len(raw) - context_lines), len(raw)))
        else:
            shown = set()
        skipped = False
        for line_index, line in enumerate(raw):
            if line_index in shown:
                output.append(f" {old_line:>{width}} {line}")
                skipped = False
            elif not skipped and (last_was_change or trailing_change):
                output.append(" " + " " * width + " ...")
                skipped = True
            old_line += 1
            new_line += 1
        last_was_change = False
    return "\n".join(output), first_changed


def _generate_edit_patch(path: str, old: str, new: str) -> str:
    """Render Pi's unified patch with explicit counts and EOF markers."""

    lines = difflib.unified_diff(
        _split_lines_with_endings(old),
        _split_lines_with_endings(new),
        fromfile=path,
        tofile=path,
        n=4,
    )
    output: list[str] = []
    for line in lines:
        if line.startswith("@@ "):
            line = re.sub(r"([+-][0-9]+)(?= )", r"\1,1", line)
        if not line.endswith("\n"):
            line += "\n\\ No newline at end of file\n"
        output.append(line)
    return "".join(output)


def _apply_fuzzy_replacements_preserving_lines(
    original: str,
    normalized: str,
    replacements: list[tuple[int, int, str]],
) -> str:
    """Apply fuzzy replacements while preserving untouched original lines.

    Fuzzy matching trims line trailing whitespace and normalizes Unicode
    punctuation.  Rewriting the whole normalized file would silently remove
    formatting from unrelated lines.  Pi widens each replacement to the
    complete lines it touches, rewrites only those spans, and copies all
    other line blocks from the original content.  This also handles edits
    that add or remove lines inside a fuzzy matched span.
    """

    original_lines = _split_lines_with_endings(original)
    normalized_lines = _split_lines_with_endings(normalized)
    if len(original_lines) != len(normalized_lines):
        # The normalizer itself never changes line count, but retaining this
        # fallback keeps the operation safe if a future normalizer does.
        result = normalized
        for start, end, new in reversed(replacements):
            result = result[:start] + new + result[end:]
        return result

    spans: list[tuple[int, int]] = []
    offset = 0
    for line in normalized_lines:
        spans.append((offset, offset + len(line)))
        offset += len(line)

    groups: list[list[Any]] = []
    for replacement in sorted(replacements, key=lambda item: item[0]):
        start, end, _ = replacement
        start_line = next(
            (
                index
                for index, (line_start, line_end) in enumerate(spans)
                if line_start <= start < line_end
            ),
            -1,
        )
        if start_line < 0:
            raise ValueError("Replacement range is outside the base content")
        end_line = start_line
        while end_line < len(spans) and spans[end_line][1] < end:
            end_line += 1
        if end_line >= len(spans):
            raise ValueError("Replacement range is outside the base content")
        group = groups[-1] if groups else None
        if group is not None and start_line < group[1]:
            group[1] = max(group[1], end_line + 1)
            group[2].append(replacement)
        else:
            groups.append([start_line, end_line + 1, [replacement]])

    result_parts: list[str] = []
    original_line_index = 0
    for start_line, end_line, group_replacements in groups:
        result_parts.extend(original_lines[original_line_index:start_line])
        group_start = spans[start_line][0]
        group_end = spans[end_line - 1][1]
        group_text = normalized[group_start:group_end]
        for start, end, new in reversed(group_replacements):
            group_text = (
                group_text[: start - group_start]
                + new
                + group_text[end - group_start :]
            )
        result_parts.append(group_text)
        original_line_index = end_line
    result_parts.extend(original_lines[original_line_index:])
    return "".join(result_parts)


def _edit(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    path_text = str(args.get("path", ""))
    edits = args.get("edits")
    if isinstance(edits, str):
        try:
            parsed = json.loads(edits)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            edits = parsed
        elif (
            isinstance(parsed, dict)
            and isinstance(parsed.get("oldText"), str)
            and isinstance(parsed.get("newText"), str)
        ):
            edits = [parsed]
    elif (
        isinstance(edits, dict)
        and isinstance(edits.get("oldText"), str)
        and isinstance(edits.get("newText"), str)
    ):
        edits = [edits]
    if isinstance(args.get("oldText"), str) and isinstance(args.get("newText"), str):
        edits = list(edits) if isinstance(edits, list) else []
        edits.append({"oldText": args["oldText"], "newText": args["newText"]})
    if not path_text.strip() or not isinstance(edits, list) or not edits:
        return _error(
            "Edit tool input is invalid. edits must contain at least one replacement."
        )
    normalized: list[tuple[str, str]] = []
    for edit in edits:
        if (
            not isinstance(edit, dict)
            or not isinstance(edit.get("oldText"), str)
            or not isinstance(edit.get("newText"), str)
        ):
            return _error("Each edit must contain string oldText and newText")
        normalized.append(
            (
                edit["oldText"].replace("\r\n", "\n").replace("\r", "\n"),
                edit["newText"].replace("\r\n", "\n").replace("\r", "\n"),
            )
        )
    path = _resolve(path_text, cwd)
    try:
        # read_bytes preserves CRLF and a UTF-8 BOM.  Node's fs.readFile
        # behaves the same; Path.read_text would silently translate newlines.
        raw = path.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        return _error(f"Could not edit file: {path_text}. {exc}")
    bom = "\ufeff" if raw.startswith("\ufeff") else ""
    content = raw[len(bom) :]
    # Match Pi's detectLineEnding: only a CRLF sequence that appears before
    # the first LF selects CRLF; lone CR files are normalized to LF.
    crlf_index = content.find("\r\n")
    lf_index = content.find("\n")
    ending = "\r\n" if crlf_index >= 0 and crlf_index < lf_index else "\n"
    base = content.replace("\r\n", "\n").replace("\r", "\n")
    for index, (old, _) in enumerate(normalized):
        if not old:
            field_name = (
                "oldText" if len(normalized) == 1 else f"edits[{index}].oldText"
            )
            return _error(f"{field_name} must not be empty in {path_text}.")

    # Exact matching is performed against the normalized LF content.  If any
    # edit needs fuzzy matching, Pi applies every edit in the normalized view
    # and overlays changed lines on top of the original text.
    matches = [_find_edit_match(base, old) for old, _ in normalized]
    used_fuzzy = any(item[2] for item in matches)
    replacement_base = _normalize_for_fuzzy_match(base) if used_fuzzy else base
    indexed_positions: list[tuple[int, int, str, int]] = []
    for index, (old, new) in enumerate(normalized):
        match_start, match_len, _ = _find_edit_match(replacement_base, old)
        if match_start < 0:
            if len(normalized) > 1:
                return _error(
                    f"Could not find edits[{index}] in {path_text}. The oldText must match exactly including all whitespace and newlines."
                )
            return _error(
                f"Could not find the exact text in {path_text}. The old text must match exactly including all whitespace and newlines."
            )
        # Pi always checks duplicates in fuzzy-normalized space, even when
        # the replacement itself uses an exact match.
        fuzzy_base = _normalize_for_fuzzy_match(replacement_base)
        fuzzy_old = _normalize_for_fuzzy_match(old)
        occurrences = (
            fuzzy_base.count(fuzzy_old) if fuzzy_old else max(0, len(fuzzy_base) - 1)
        )
        if occurrences > 1:
            if len(normalized) > 1:
                return _error(
                    f"Found {occurrences} occurrences of edits[{index}] in {path_text}. Each oldText must be unique. Please provide more context to make it unique."
                )
            return _error(
                f"Found {occurrences} occurrences of the text in {path_text}. The text must be unique. Please provide more context to make it unique."
            )
        indexed_positions.append((match_start, match_start + match_len, new, index))
    indexed_positions.sort(key=lambda item: item[0])
    for previous, current in zip(indexed_positions, indexed_positions[1:]):
        if previous[1] > current[0]:
            return _error(
                f"edits[{previous[3]}] and edits[{current[3]}] overlap in {path_text}. Merge them into one edit or target disjoint regions."
            )
    positions = [(start, end, new) for start, end, new, _ in indexed_positions]
    updated = replacement_base
    for start, end, new in reversed(positions):
        updated = updated[:start] + new + updated[end:]
    # Fuzzy replacements operate in normalized space.  Preserve untouched
    # lines from the original file so only the targeted formatting changes.
    if used_fuzzy:
        updated = _apply_fuzzy_replacements_preserving_lines(
            base, replacement_base, positions
        )
    if updated == base:
        if len(normalized) > 1:
            return _error(
                f"No changes made to {path_text}. The replacements produced identical content."
            )
        return _error(
            f"No changes made to {path_text}. The replacement produced identical content. This might indicate an issue with special characters or the text not existing as expected."
        )
    restored = updated if ending == "\n" else updated.replace("\n", ending)
    try:
        path.write_text(bom + restored, encoding="utf-8", newline="")
    except OSError as exc:
        return _error(f"Could not write edited file: {exc}")
    diff, first_changed_line = _generate_edit_diff(base, updated)
    patch = _generate_edit_patch(path_text, base, updated)
    return _result(
        f"Successfully replaced {len(normalized)} block(s) in {path_text}.",
        diff=diff,
        patch=patch,
        firstChangedLine=first_changed_line,
    )


def _bash(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return _error("bash requires a non-empty command")
    timeout = args.get("timeout")
    try:
        timeout_value = float(timeout) if timeout is not None else None
    except (TypeError, ValueError):
        return _error("timeout must be a number")
    try:
        # Pi selects bash independently of the user's login shell. In
        # particular, zsh uses different array indices and container /bin/sh
        # may be dash, which rejects bash syntax altogether.
        shell = (
            "/bin/bash" if Path("/bin/bash").exists() else shutil.which("bash") or "sh"
        )
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_value,
            executable=shell,
        )
        output = completed.stdout + completed.stderr
        code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired carries bytes even when subprocess.run(text=True).
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        output = (
            stdout.decode("utf-8", errors="replace")
            if isinstance(stdout, bytes)
            else stdout
        ) + (
            stderr.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes)
            else stderr
        )
        shown, _ = truncate_tail(output)
        status = f"Command timed out after {timeout_value:g} seconds"
        return _error(f"{shown}\n\n{status}" if shown else status)
    except OSError as exc:
        return _error(f"Failed to execute command: {exc}")
    shown, truncation = truncate_tail(output)
    if truncation.get("truncated"):
        shown += f"\n\n[{format_size(DEFAULT_MAX_BYTES)} output limit reached]"
    text = shown or "(no output)"
    if code != 0:
        text += f"\n\nCommand exited with code {code}"
    return ToolResult(
        text,
        is_error=code != 0,
        details={"exit_code": code, "truncation": truncation},
    )


def _load_ignore_rules(root: Path) -> list[tuple[Path, str, bool]]:
    """Load the common gitignore forms used by Pi's rg/fd-backed tools."""

    rules: list[tuple[Path, str, bool]] = []
    for ignore_file in root.rglob(".gitignore"):
        if not ignore_file.is_file() or ".git" in ignore_file.parts:
            continue
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            negated = value.startswith("!")
            if negated:
                value = value[1:]
            rules.append((ignore_file.parent, value, negated))
    return rules


def _is_ignored(path: Path, root: Path, rules: list[tuple[Path, str, bool]]) -> bool:
    if any(part in {".git", "node_modules"} for part in path.relative_to(root).parts):
        return True
    ignored = False
    for base, pattern, negated in rules:
        try:
            relative = path.relative_to(base).as_posix()
        except ValueError:
            continue
        directory_pattern = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        matched = (
            fnmatch.fnmatch(relative, pattern)
            or fnmatch.fnmatch(path.name, pattern)
            or ("/" not in pattern and fnmatch.fnmatch(relative, f"**/{pattern}"))
        )
        if directory_pattern and (matched or relative.startswith(pattern + "/")):
            matched = True
        if matched:
            ignored = not negated
    return ignored


def _iter_files(root: Path):
    rules = _load_ignore_rules(root)
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs if not _is_ignored(Path(current) / d, root, rules)
        )
        for name in sorted(files):
            path = Path(current) / name
            if path.is_file() and not _is_ignored(path, root, rules):
                yield path


def _grep(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    pattern = args.get("pattern")
    if not isinstance(pattern, str):
        return _error("grep requires a string pattern")
    root = _resolve(args.get("path") or ".", cwd)
    if not root.exists():
        return _error(f"Path not found: {root}")
    literal = bool(args.get("literal"))
    flags = re.IGNORECASE if args.get("ignoreCase") else 0
    try:
        matcher = re.compile(re.escape(pattern) if literal else pattern, flags)
    except re.error as exc:
        return _error(f"Invalid regex: {exc}")
    limit = max(1, int(args.get("limit") or 100))
    context = max(0, int(args.get("context") or 0))
    glob = args.get("glob")
    files = [root] if root.is_file() else list(_iter_files(root))
    matches: list[tuple[Path, int, list[str]]] = []
    for path in files:
        relative = path.name if root.is_file() else path.relative_to(root).as_posix()
        if glob and not fnmatch.fnmatch(relative, str(glob)):
            continue
        try:
            lines = (
                path.read_text(encoding="utf-8", errors="replace")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .split("\n")
            )
        except OSError:
            continue
        for index, line in enumerate(lines):
            if not matcher.search(line):
                continue
            start = max(0, index - context)
            end = min(len(lines), index + context + 1)
            matches.append((path, index + 1, lines[start:end]))
            if len(matches) >= limit:
                break
        if len(matches) >= limit:
            break
    if not matches:
        return _result("No matches found")
    output: list[str] = []
    line_truncated = False
    for path, line_number, block in matches:
        base = path.name if root.is_file() else path.relative_to(root).as_posix()
        first = max(1, line_number - context) if context else line_number
        for offset, line in enumerate(block):
            current = first + offset
            if len(line) > GREP_MAX_LINE_LENGTH:
                line = line[:GREP_MAX_LINE_LENGTH] + "..."
                line_truncated = True
            if current == line_number:
                output.append(f"{base}:{current}: {line}")
            else:
                # Match ripgrep's context convention used by Pi: context
                # lines use a dash before and after the line number.
                output.append(f"{base}-{current}- {line}")
    text, truncation = truncate_head("\n".join(output), max_lines=10**9)
    notices = []
    if len(matches) >= limit:
        notices.append(
            f"{limit} matches limit reached. Use limit={limit * 2} for more, or refine pattern"
        )
    if truncation.get("truncated"):
        notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
    if line_truncated:
        notices.append(
            f"Some lines truncated to {GREP_MAX_LINE_LENGTH} chars. Use read tool to see full lines"
        )
    if notices:
        text += "\n\n[" + ". ".join(notices) + "]"
    return _result(text, truncation=truncation if truncation.get("truncated") else None)


def _find(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return _error("find requires a glob pattern")
    root = _resolve(args.get("path") or ".", cwd)
    if not root.exists():
        return _error(f"Path not found: {root}")
    limit = max(1, int(args.get("limit") or 1000))
    results: list[str] = []
    rules = _load_ignore_rules(root)
    candidates = sorted(
        root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()
    )
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        if _is_ignored(path, root, rules):
            continue
        if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern):
            results.append(relative + "/" if path.is_dir() else relative)
            if len(results) >= limit:
                break
    if not results:
        return _result("No files found matching pattern")
    output, truncation = truncate_head("\n".join(results), max_lines=10**9)
    notices = []
    if len(results) >= limit:
        notices.append(f"{limit} results limit reached")
    if truncation.get("truncated"):
        notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
    if notices:
        output += "\n\n[" + ". ".join(notices) + "]"
    return _result(
        output, truncation=truncation if truncation.get("truncated") else None
    )


def _ls(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    path = _resolve(args.get("path") or ".", cwd)
    if not path.exists():
        return _error(f"Path not found: {path}")
    if not path.is_dir():
        return _error(f"Not a directory: {path}")
    limit = max(1, int(args.get("limit") or 500))
    entries = sorted(path.iterdir(), key=lambda item: item.name.casefold())
    selected = entries[:limit]
    output = "\n".join(item.name + ("/" if item.is_dir() else "") for item in selected)
    if not output:
        return _result("(empty directory)")
    notices = []
    if len(entries) > limit:
        notices.append(f"{limit} entries limit reached. Use limit={limit * 2} for more")
    output, truncation = truncate_head(output, max_lines=10**9)
    if truncation.get("truncated"):
        notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
    if notices:
        output += "\n\n[" + ". ".join(notices) + "]"
    return _result(
        output, truncation=truncation if truncation.get("truncated") else None
    )


_SCHEMAS: dict[str, dict[str, Any]] = {
    "read": {
        "description": "Read the contents of a file. Supports text files and images. For text files, output is truncated to 2000 lines or 50KB; use offset and limit for large files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "bash": {
        "description": "Execute a shell command in the current working directory. Returns stdout and stderr, truncated to the last 2000 lines or 50KB.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    "edit": {
        "description": "Edit a single file using exact text replacement. Every oldText must match a unique, non-overlapping region of the original file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "oldText": {"type": "string"},
                            "newText": {"type": "string"},
                        },
                        "required": ["oldText", "newText"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["path", "edits"],
            "additionalProperties": False,
        },
    },
    "write": {
        "description": "Write content to a file. Creates parent directories and overwrites an existing file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    "grep": {
        "description": "Search file contents for a regex or literal pattern. Returns matching lines with file paths and line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "glob": {"type": "string"},
                "ignoreCase": {"type": "boolean"},
                "literal": {"type": "boolean"},
                "context": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    "find": {
        "description": "Search for files by glob pattern. Returns paths relative to the search directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    "ls": {
        "description": "List directory contents alphabetically, including dotfiles; directories have a trailing slash.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
}


def tool_schemas(
    enabled: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    names = list(["read", "bash", "edit", "write"] if enabled is None else enabled)
    return [
        {"type": "function", "function": {"name": name, **_SCHEMAS[name]}}
        for name in names
        if name in _SCHEMAS
    ]


def execute_tool(name: str, arguments: dict[str, Any], cwd: str | Path) -> ToolResult:
    handlers = {
        "read": _read,
        "bash": _bash,
        "edit": _edit,
        "write": _write,
        "grep": _grep,
        "find": _find,
        "ls": _ls,
    }
    handler = handlers.get(name)
    if handler is None:
        return _error(f"Unknown tool: {name}")
    try:
        return handler(arguments, cwd)
    except Exception as exc:  # Keep tool failures in the model-visible protocol.
        return _error(f"{name} failed: {type(exc).__name__}: {exc}")


__all__ = [
    "ToolResult",
    "execute_tool",
    "tool_schemas",
    "truncate_head",
    "truncate_tail",
]
