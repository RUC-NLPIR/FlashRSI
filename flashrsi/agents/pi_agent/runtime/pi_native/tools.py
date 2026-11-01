"""Pi's built-in filesystem and shell tools, implemented in Python.

The public functions use JSON-compatible values and intentionally avoid any
FlashRSI imports.  This lets a Snapshot run the same code when it is exported
to a temporary directory for a rollout.
"""

from __future__ import annotations

import base64
import codecs
import copy
import difflib
import io
import json
import math
import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024
GREP_MAX_LINE_LENGTH = 500


@dataclass
class ToolResult:
    """A tool response in the shape consumed by the Pi agent loop."""

    content: str
    is_error: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    content_blocks: list[dict[str, Any]] | None = None
    structured_content: Any = None
    usage: dict[str, Any] | None = None
    terminate: bool | None = None

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
    value = "." if path is None else path
    value = re.sub("[\u00a0\u2000-\u200a\u202f\u205f\u3000]", " ", value)
    if value.startswith("@"):
        value = value[1:]
    if value == "~" or value.startswith("~/"):
        value = os.path.expanduser(value)
    if value.startswith("file://"):
        value = unquote(urlparse(value).path)
    return Path(os.path.abspath(os.path.join(str(cwd), value)))


def _resolve_read(path: str, cwd: str | Path) -> Path:
    resolved = _resolve(path, cwd)
    value = str(resolved)
    nfd = unicodedata.normalize("NFD", value)
    variants = [
        value,
        re.sub(
            r" (AM|PM)\.", lambda match: "\u202f" + match[1] + ".", value, flags=re.I
        ),
        nfd,
        value.replace("'", "\u2019"),
        nfd.replace("'", "\u2019"),
    ]
    return next((Path(item) for item in variants if Path(item).exists()), resolved)


def _image_mime(raw: bytes) -> str | None:
    raw = raw[:4100]
    if raw.startswith(b"\xff\xd8\xff"):
        return None if len(raw) > 3 and raw[3] == 0xF7 else "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(raw) < 16 or raw[8:16] != b"\x00\x00\x00\rIHDR":
            return None
        offset = 8
        while offset + 8 <= len(raw):
            size = int.from_bytes(raw[offset : offset + 4], "big")
            kind = raw[offset + 4 : offset + 8]
            if kind == b"acTL":
                return None
            if kind == b"IDAT":
                break
            offset += size + 12
        return "image/png"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith(b"BM") and len(raw) >= 26:
        size = int.from_bytes(raw[2:6], "little")
        offset = int.from_bytes(raw[10:14], "little")
        dib = int.from_bytes(raw[14:18], "little")
        if size and (size < 26 or offset >= size) or offset < 14 + dib:
            return None
        header = (
            22 if dib == 12 else 26 if 40 <= dib <= 124 and len(raw) >= 30 else None
        )
        if (
            header is not None
            and int.from_bytes(raw[header : header + 2], "little") == 1
            and int.from_bytes(raw[header + 2 : header + 4], "little")
            in {1, 4, 8, 16, 24, 32}
        ):
            return "image/bmp"
    return None


def _read_image(
    raw: bytes,
    mime: str,
    *,
    model: dict[str, Any] | None = None,
    auto_resize_images: bool = True,
) -> ToolResult:
    """Use original bytes below limits and Photon's original resampler/codecs."""
    from PIL import Image, ImageOps

    from .photon_image import encode_jpeg, encode_png, resize_rgba

    limits = ((model or {}).get("inputLimits") or {}).get("images", {}).get(
        "resize"
    ) or {}
    max_width = limits.get("maxWidth", 2000)
    max_height = limits.get("maxHeight", 2000)
    max_bytes = limits.get("maxBytes", 4.5 * 1024 * 1024)
    hints: list[str] = []
    converted_from = None
    try:
        decoded_webp = None
        if mime == "image/webp":
            try:
                from .photon_image import decode_webp_lossy

                decoded_webp = decode_webp_lossy(raw)
            except Exception:
                decoded_webp = None
        decoded_jpeg = None
        if mime == "image/jpeg":
            try:
                from .photon_image import decode_jpeg

                decoded_jpeg = decode_jpeg(raw)
            except Exception:
                decoded_jpeg = None
        if decoded_webp is not None:
            decoded_pixels, decoded_width, decoded_height = decoded_webp
            image = Image.frombytes("RGBA", (decoded_width, decoded_height), decoded_pixels)
            # VP8X WebP may carry EXIF orientation. Pixel values came from
            # image-rs above; use Pillow only to parse the TIFF tag and apply
            # the same exact flips/quarter-turns to that RGBA buffer.
            try:
                metadata = Image.open(io.BytesIO(raw)).getexif()
                orientation = int(metadata.get(274, 1))
                transforms = {
                    2: Image.Transpose.FLIP_LEFT_RIGHT,
                    3: Image.Transpose.ROTATE_180,
                    4: Image.Transpose.FLIP_TOP_BOTTOM,
                    5: Image.Transpose.TRANSPOSE,
                    6: Image.Transpose.ROTATE_270,
                    7: Image.Transpose.TRANSVERSE,
                    8: Image.Transpose.ROTATE_90,
                }
                if orientation in transforms:
                    image = image.transpose(transforms[orientation])
            except Exception:
                pass
        elif decoded_jpeg is not None:
            decoded_pixels, decoded_width, decoded_height = decoded_jpeg
            image = Image.frombytes("RGBA", (decoded_width, decoded_height), decoded_pixels)
            try:
                orientation = int(Image.open(io.BytesIO(raw)).getexif().get(274, 1))
                transforms = {
                    2: Image.Transpose.FLIP_LEFT_RIGHT,
                    3: Image.Transpose.ROTATE_180,
                    4: Image.Transpose.FLIP_TOP_BOTTOM,
                    5: Image.Transpose.TRANSPOSE,
                    6: Image.Transpose.ROTATE_270,
                    7: Image.Transpose.TRANSVERSE,
                    8: Image.Transpose.ROTATE_90,
                }
                if orientation in transforms:
                    image = image.transpose(transforms[orientation])
            except Exception:
                pass
        elif not auto_resize_images and mime != "image/bmp":
            image = None
        else:
            image = Image.open(io.BytesIO(raw))
            # Pi only reads TIFF orientation from JPEG APP1 and WebP EXIF.
            if mime in {"image/jpeg", "image/webp"}:
                image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA")
            image.load()
        if mime == "image/bmp":
            raw = encode_png(image.tobytes(), *image.size)
            mime, converted_from = "image/png", "image/bmp"
        width, height = image.size if image is not None else (0, 0)
        original_width, original_height = width, height
        if auto_resize_images and (
            width > max_width
            or height > max_height
            or len(base64.b64encode(raw)) >= max_bytes
        ):
            if width > max_width:
                height, width = math.floor(height * max_width / width + 0.5), max_width
            if height > max_height:
                width, height = (
                    math.floor(width * max_height / height + 0.5),
                    max_height,
                )
            while True:
                pixels = resize_rgba(
                    image.tobytes(), image.width, image.height, width, height
                )
                chosen = None
                for quality in [
                    None,
                    *dict.fromkeys([limits.get("jpegQuality", 80), 85, 70, 55, 40]),
                ]:
                    if quality is None:
                        data = encode_png(pixels, width, height)
                    else:
                        data = encode_jpeg(pixels, width, height, quality)
                    if len(base64.b64encode(data)) < max_bytes:
                        chosen = data, "image/png" if quality is None else "image/jpeg"
                        break
                if chosen:
                    raw, mime = chosen
                    hints.append(
                        f"[Image: original {original_width}x{original_height}, displayed at {width}x{height}. Multiply coordinates by {original_width / width:.2f} to map to original image.]"
                    )
                    break
                if width == height == 1:
                    raise ValueError("cannot fit image")
                width, height = (
                    max(1, math.floor(width * 0.75)),
                    max(1, math.floor(height * 0.75)),
                )
        if converted_from:
            hints.insert(0, f"[Image converted from {converted_from} to {mime}.]")
        note = f"Read image file [{mime}]" + ("\n" + "\n".join(hints) if hints else "")
        if model and "image" not in model.get("input", ["text"]):
            note += "\n[Current model does not support images. The image will be omitted from this request.]"
        return ToolResult(
            note,
            content_blocks=[
                {"type": "text", "text": note},
                {
                    "type": "image",
                    "data": base64.b64encode(raw).decode("ascii"),
                    "mimeType": mime,
                },
            ],
        )
    except Exception:
        failure = (
            "converted to a supported inline image format"
            if mime == "image/bmp"
            else "resized below the inline image size limit"
        )
        note = f"Read image file [{mime}]\n[Image omitted: could not be {failure}.]"
        if model and "image" not in model.get("input", ["text"]):
            note += "\n[Current model does not support images. The image will be omitted from this request.]"
        return _result(note)


def _public_truncation(details: dict[str, Any], content: str) -> dict[str, Any]:
    return {
        "content": content,
        **{
            re.sub(r"_([a-z])", lambda match: match[1].upper(), key): value
            for key, value in details.items()
        },
    }


def _number_text(value: float | int) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _result(text: str, **details: Any) -> ToolResult:
    return ToolResult(
        text,
        details={key: value for key, value in details.items() if value is not None},
    )


def _error(text: str, **details: Any) -> ToolResult:
    return ToolResult(text, is_error=True, details=details)


def _read(
    args: dict[str, Any],
    cwd: str | Path,
    *,
    model: dict[str, Any] | None = None,
    auto_resize_images: bool = True,
) -> ToolResult:
    path_text = str(args.get("path", ""))
    path = _resolve_read(path_text, cwd)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            return _error(f"ENOENT: no such file or directory, access '{path}'")
        if isinstance(exc, IsADirectoryError):
            return _error("EISDIR: illegal operation on a directory, read")
        if isinstance(exc, PermissionError):
            return _error(f"EACCES: permission denied, access '{path}'")
        return _error(str(exc))
    mime = _image_mime(raw)
    if mime:
        return _read_image(
            raw, mime, model=model, auto_resize_images=auto_resize_images
        )
    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\n")
    offset = args.get("offset")
    try:
        start = max(0, offset - 1) if offset else 0
    except (TypeError, ValueError):
        return _error("offset must be an integer")
    if start >= len(lines):
        return _error(
            f"Offset {offset} is beyond end of file ({len(lines)} lines total)"
        )
    limit = args.get("limit")
    try:
        end = min(start + limit, len(lines)) if limit is not None else len(lines)
    except (TypeError, ValueError):
        return _error("limit must be an integer")
    selected = "\n".join(lines[int(start) : int(end)])
    output, truncation = truncate_head(selected)
    public_truncation = _public_truncation(truncation, output)
    if truncation.get("first_line_exceeds_limit"):
        first_size = format_size(len(lines[int(start)].encode("utf-8")))
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
        output += f"\n\n[{_number_text(len(lines) - end)} more lines in file. Use offset={_number_text(end + 1)} to continue.]"
    return _result(
        output,
        **({"truncation": public_truncation} if truncation.get("truncated") else {}),
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
    if not isinstance(content, str):
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
    if not isinstance(edits, list) or not edits:
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


class _OutputAccumulator:
    """Pi's bounded UTF-8 display tail and full raw output spill."""

    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.tail = ""
        self.boundary = True
        self.total_bytes = 0
        self.completed_lines = 0
        self.line_bytes = 0
        self.raw = tempfile.SpooledTemporaryFile(max_size=DEFAULT_MAX_BYTES)
        self.full_path = None
        self._spill = None

    def append(self, data: bytes, *, final: bool = False):
        self.raw.write(data)
        if self._spill is not None:
            self._spill.write(data)
            self._spill.flush()
        text = self.decoder.decode(data, final=final)
        self.total_bytes += len(text.encode("utf-8"))
        self.tail += text
        if "\n" in text:
            self.completed_lines += text.count("\n")
            self.line_bytes = len(text.rsplit("\n", 1)[1].encode("utf-8"))
        else:
            self.line_bytes += len(text.encode("utf-8"))
        encoded = self.tail.encode("utf-8")
        if len(encoded) > DEFAULT_MAX_BYTES * 4:
            start = len(encoded) - DEFAULT_MAX_BYTES * 2
            while start < len(encoded) and encoded[start] & 0xC0 == 0x80:
                start += 1
            self.boundary = (
                start == 0 and self.boundary or (start > 0 and encoded[start - 1] == 10)
            )
            self.tail = encoded[start:].decode("utf-8")

    def snapshot(self, *, raw_display: bool = False):
        text = self.tail
        if not self.boundary and "\n" in text:
            text = text.split("\n", 1)[1]
        shown, truncation = truncate_tail(text)
        total_lines = self.completed_lines + int(self.line_bytes > 0)
        truncated = (
            total_lines > DEFAULT_MAX_LINES or self.total_bytes > DEFAULT_MAX_BYTES
        )
        truncation.update(
            truncated=truncated, total_lines=total_lines, total_bytes=self.total_bytes
        )
        if not truncated:
            return shown if raw_display else shown or "(no output)", {}
        if not truncation["truncated_by"]:
            truncation["truncated_by"] = (
                "bytes" if self.total_bytes > DEFAULT_MAX_BYTES else "lines"
            )
        if not self.full_path:
            with tempfile.NamedTemporaryFile(
                prefix="pi-bash-", suffix=".log", delete=False
            ) as output:
                self.full_path = output.name
                self.raw.seek(0)
                shutil.copyfileobj(self.raw, output)
            self._spill = open(self.full_path, "ab")
        start = total_lines - truncation["output_lines"] + 1
        if truncation["last_line_partial"]:
            note = f"Showing last {format_size(truncation['output_bytes'])} of line {total_lines} (line is {format_size(self.line_bytes)}). Full output: {self.full_path}"
        elif truncation["truncated_by"] == "lines":
            note = f"Showing lines {start}-{total_lines} of {total_lines}. Full output: {self.full_path}"
        else:
            note = f"Showing lines {start}-{total_lines} of {total_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). Full output: {self.full_path}"
        rendered = (
            shown if raw_display else (shown or "(no output)") + "\n\n[" + note + "]"
        )
        return rendered, {
            "truncation": _public_truncation(truncation, shown),
            "fullOutputPath": self.full_path,
        }

    def read_full_output(self, maximum: int = 1024 * 1024):
        self.raw.seek(0, os.SEEK_END)
        size = self.raw.tell()
        self.raw.seek(0)
        if size <= maximum:
            return self.raw.read().decode("utf-8", errors="replace"), False
        half = maximum // 2
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        head = decoder.decode(self.raw.read(half), final=False)
        self.raw.seek(size - (maximum - half))
        tail = self.raw.read()
        while tail and tail[0] & 0xC0 == 0x80:
            tail = tail[1:]
        return (
            f"{head}\n\n[... {size - maximum} bytes omitted ...]\n\n{tail.decode('utf-8', errors='replace')}",
            True,
        )

    def close(self):
        if self._spill is not None:
            self._spill.close()
        self.raw.close()


def _bash(
    args: dict[str, Any],
    cwd: str | Path,
    cancel_event: Any = None,
    on_update: Any = None,
) -> ToolResult:
    command = args["command"]
    timeout = args.get("timeout")
    if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
        return _error("Invalid timeout: must be a finite number of seconds")
    if timeout is not None and timeout > 2147483.647:
        return _error("Invalid timeout: maximum is 2147483.647 seconds")
    if cancel_event is not None and cancel_event.is_set():
        return _error("Command aborted")
    if not Path(cwd).exists():
        return _error(
            f"Working directory does not exist: {cwd}\nCannot execute bash commands."
        )
    shell = "/bin/bash" if Path("/bin/bash").exists() else shutil.which("bash") or "sh"
    accumulator = _OutputAccumulator()
    if on_update is not None:
        on_update(ToolResult("", content_blocks=[]))
    process = None
    status = None
    update_dirty = False
    last_update = 0.0

    def emit_update():
        nonlocal last_update, update_dirty
        if on_update is not None and update_dirty:
            update_dirty = False
            last_update = time.monotonic()
            shown, details = accumulator.snapshot(raw_display=True)
            on_update(ToolResult(shown, details=details))

    try:
        process = subprocess.Popen(
            [shell, "-c", command],
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        started = time.monotonic()
        last_data = started
        exited_at = None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                now = time.monotonic()
                if update_dirty and now - last_update >= 0.1:
                    emit_update()
                cancelled = cancel_event is not None and cancel_event.is_set()
                expired = timeout is not None and now - started >= timeout
                if (cancelled or expired) and status is None:
                    status = (
                        "Command aborted"
                        if cancelled
                        else f"Command timed out after {timeout:g} seconds"
                    )
                    try:
                        if os.name != "nt":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                if process.poll() is not None:
                    exited_at = exited_at or now
                    if now - max(exited_at, last_data) >= 0.1:
                        break
                for key, _ in selector.select(0.02):
                    data = os.read(key.fd, 65536)
                    if data:
                        accumulator.append(data)
                        update_dirty = True
                        last_data = time.monotonic()
                        if last_data - last_update >= 0.1:
                            emit_update()
                    else:
                        selector.unregister(key.fileobj)
        process.stdout.close()
        code = process.wait()
        if code < 0:
            code = 128 - code
        accumulator.append(b"", final=True)
        emit_update()
        shown, details = accumulator.snapshot()
        if status:
            shown = "" if shown == "(no output)" else shown
            return _error((shown + "\n\n" if shown else "") + status)
        if code != 0:
            shown += f"\n\nCommand exited with code {code}"
        full_output, full_truncated = accumulator.read_full_output()
        structured = {
            "output": full_output,
            "truncated": full_truncated,
            "exit_code": code,
            "wall_time_seconds": math.floor((time.monotonic() - started) * 10 + 0.5)
            / 10,
        }
        if full_truncated and accumulator.full_path:
            structured["full_output_path"] = accumulator.full_path
        return ToolResult(
            shown, is_error=code != 0, details=details, structured_content=structured
        )
    except OSError as exc:
        return _error(str(exc))
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()
        accumulator.close()


def _load_ignore_rules(root: Path, *, for_find: bool = False):
    from .ignore import IgnoreRules

    repository = next(
        (parent for parent in (root, *root.parents) if (parent / ".git").exists()), None
    )
    names = (
        (".gitignore", ".ignore", ".fdignore")
        if for_find
        else ((".gitignore", ".ignore") if repository else (".ignore",))
    )
    return IgnoreRules(repository or root, names=names, boundary=root)


def _is_ignored(path: Path, root: Path, rules) -> bool:
    return rules.is_ignored(path)


def _iter_files(root: Path):
    from .ignore import walk_lifo

    yield from walk_lifo(root, _load_ignore_rules(root))


def _grep(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    pattern = args.get("pattern")
    if not isinstance(pattern, str):
        return _error("grep requires a string pattern")
    root = _resolve(args.get("path") or ".", cwd)
    if not root.exists():
        return _error(f"Path not found: {root}")
    literal = bool(args.get("literal"))
    from .search_regex import SearchRegexError, compile_search

    try:
        matcher = compile_search(
            pattern, literal=literal, ignore_case=bool(args.get("ignoreCase"))
        )
    except SearchRegexError as exc:
        return _error(str(exc))
    limit = max(1, args.get("limit", 100))
    context = max(0, int(args.get("context") or 0))
    glob = args.get("glob")
    from .ignore import matches_glob

    files = [root] if root.is_file() else list(_iter_files(root))
    matches: list[tuple[Path, int, list[str]]] = []
    for path in files:
        relative = path.name if root.is_file() else path.relative_to(root).as_posix()
        if glob:
            negated = glob.startswith("!")
            selected_glob = glob[1:] if negated else glob
            glob_matches = matches_glob(
                relative, selected_glob, basename="/" not in selected_glob
            )
            if glob_matches == negated:
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
    text, truncation = truncate_head("\n".join(output), max_lines=9007199254740991)
    notices = []
    if len(matches) >= limit:
        notices.append(
            f"{_number_text(limit)} matches limit reached. Use limit={_number_text(limit * 2)} for more, or refine pattern"
        )
    if truncation.get("truncated"):
        notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
    if line_truncated:
        notices.append(
            f"Some lines truncated to {GREP_MAX_LINE_LENGTH} chars. Use read tool to see full lines"
        )
    if notices:
        text += "\n\n[" + ". ".join(notices) + "]"
    return _result(
        text,
        truncation=_public_truncation(truncation, text.rsplit("\n\n[", 1)[0])
        if truncation.get("truncated")
        else None,
        matchLimitReached=limit if len(matches) >= limit else None,
        linesTruncated=True if line_truncated else None,
    )


def _find(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return _error("find requires a glob pattern")
    root = _resolve(args.get("path") or ".", cwd)
    if not root.exists():
        return _error(f"Path not found: {root}")
    limit = args.get("limit", 1000)
    results: list[str] = []
    rules = _load_ignore_rules(root, for_find=True)
    from .ignore import matches_glob, walk_lifo

    candidates = walk_lifo(root, rules, directories=True, symlinks=True)
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        if _is_ignored(path, root, rules):
            continue
        if matches_glob(
            relative,
            pattern,
            basename="/" not in pattern,
            ignore_case=pattern.lower() == pattern,
        ):
            results.append(relative + "/" if path.is_dir() else relative)
            if len(results) >= limit:
                break
    if not results:
        return _result("No files found matching pattern")
    output, truncation = truncate_head("\n".join(results), max_lines=9007199254740991)
    notices = []
    if len(results) >= limit:
        notices.append(
            f"{_number_text(limit)} results limit reached. Use limit={_number_text(limit * 2)} for more, or refine pattern"
        )
    if truncation.get("truncated"):
        notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
    if notices:
        output += "\n\n[" + ". ".join(notices) + "]"
    return _result(
        output,
        truncation=_public_truncation(truncation, output.rsplit("\n\n[", 1)[0])
        if truncation.get("truncated")
        else None,
        resultLimitReached=limit if len(results) >= limit else None,
    )


def _ls(args: dict[str, Any], cwd: str | Path) -> ToolResult:
    path = _resolve(args.get("path") or ".", cwd)
    if not path.exists():
        return _error(f"Path not found: {path}")
    if not path.is_dir():
        return _error(f"Not a directory: {path}")
    limit = args.get("limit", 500)
    entries = sorted(path.iterdir(), key=lambda item: item.name.casefold())
    selected = [entry for entry in entries if entry.exists()][
        : max(0, math.ceil(limit))
    ]
    output = "\n".join(item.name + ("/" if item.is_dir() else "") for item in selected)
    if not output:
        return _result("(empty directory)")
    notices = []
    if len(entries) > limit:
        notices.append(
            f"{_number_text(limit)} entries limit reached. Use limit={_number_text(limit * 2)} for more"
        )
    output, truncation = truncate_head(output, max_lines=9007199254740991)
    if truncation.get("truncated"):
        notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
    if notices:
        output += "\n\n[" + ". ".join(notices) + "]"
    return _result(
        output,
        truncation=_public_truncation(truncation, output.rsplit("\n\n[", 1)[0])
        if truncation.get("truncated")
        else None,
        entryLimitReached=limit if len(entries) > limit else None,
    )


# Generated from pinned upstream tool definitions, including model-visible wording.
_MANIFEST = json.loads(
    Path(__file__).with_name("tool_manifest.json").read_text(encoding="utf-8")
)
_SCHEMAS = {
    name: {"description": entry["description"], "parameters": entry["parameters"]}
    for name, entry in _MANIFEST.items()
}


def _prepare_edit_arguments(arguments: Any) -> Any:
    if not isinstance(arguments, dict):
        return arguments
    args = copy.deepcopy(arguments)
    edits = args.get("edits")
    if isinstance(edits, str):
        try:
            parsed = json.loads(edits)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list) or _single_edit(parsed):
            args["edits"] = parsed if isinstance(parsed, list) else [parsed]
    elif _single_edit(edits):
        args["edits"] = [edits]
    if isinstance(args.get("oldText"), str) and isinstance(args.get("newText"), str):
        args["edits"] = (
            list(args["edits"]) if isinstance(args.get("edits"), list) else []
        ) + [{"oldText": args.pop("oldText"), "newText": args.pop("newText")}]
    return args


def _single_edit(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("oldText"), str)
        and isinstance(value.get("newText"), str)
    )


def _typebox_convert(value: Any, schema: dict[str, Any]) -> Any:
    kind = schema.get("type")
    if kind == "object" and isinstance(value, dict):
        required = schema.get("required", [])
        for key, prop in schema.get("properties", {}).items():
            if key not in value:
                continue
            if value[key] is None and key not in required:
                del value[key]
            else:
                value[key] = _typebox_convert(value[key], prop)
    elif kind == "array":
        value = value if isinstance(value, list) else [value]
        value = [_typebox_convert(item, schema["items"]) for item in value]
    elif kind == "string" and (value is None or isinstance(value, (bool, int, float))):
        value = (
            "null"
            if value is None
            else (
                "true" if value is True else "false" if value is False else str(value)
            )
        )
        if isinstance(value, str) and value.endswith(".0"):
            value = value[:-2]
    elif kind == "number":
        if isinstance(value, bool) or value is None:
            value = int(value or 0)
        elif isinstance(value, str):
            text = value.strip()
            try:
                if text.lower() in {"true", "false"}:
                    value = 1 if text.lower() == "true" else 0
                elif text.lower().startswith(("0x", "0o", "0b")):
                    value = int(text, 0)
                else:
                    converted = float(text) if text else 0
                    if math.isfinite(converted):
                        value = (
                            int(converted) if converted == int(converted) else converted
                        )
            except ValueError:
                pass
    elif kind == "boolean" and not isinstance(value, bool):
        if (
            value is None
            or value == 0
            or value == "0"
            or (isinstance(value, str) and value.lower() == "false")
        ):
            value = False
        elif (
            value == 1
            or value == "1"
            or (isinstance(value, str) and value.lower() == "true")
        ):
            value = True
    return value


def _validation_errors(value: Any, schema: dict[str, Any], path: str = "") -> list[str]:
    kind = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value),
        "boolean": isinstance(value, bool),
    }.get(kind, True)
    if not valid:
        return [f"  - {path or 'root'}: must be {kind}"]
    errors: list[str] = []
    if kind == "object":
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            target = f"{path}.{missing[0]}" if path else missing[0]
            errors.append(
                f"  - {target}: must have required properties {', '.join(required)}"
            )
        for key, prop in schema.get("properties", {}).items():
            if key in value:
                errors.extend(
                    _validation_errors(
                        value[key], prop, f"{path}.{key}" if path else key
                    )
                )
    elif kind == "array":
        for index, item in enumerate(value):
            errors.extend(_validation_errors(item, schema["items"], f"{path}.{index}"))
    return errors


def prepare_tool_arguments(
    name: str, arguments: Any, arguments_error: str | None = None
) -> dict[str, Any]:
    """Run Pi's prepareArguments + TypeBox conversion/validation before dispatch."""
    if arguments_error:
        raise ValueError(f'Invalid arguments for tool "{name}": {arguments_error}')
    if name not in _SCHEMAS:
        raise ValueError(f"Tool {name} not found")
    prepared = (
        _prepare_edit_arguments(arguments)
        if name == "edit"
        else copy.deepcopy(arguments)
    )
    received = copy.deepcopy(prepared)
    converted = _typebox_convert(prepared, _SCHEMAS[name]["parameters"])
    errors = _validation_errors(converted, _SCHEMAS[name]["parameters"])
    if errors:
        formatted = json.dumps(received, ensure_ascii=False, indent=2)
        raise ValueError(
            f'Validation failed for tool "{name}":\n'
            + "\n".join(errors)
            + "\n\nReceived arguments:\n"
            + formatted
        )
    return converted


def tool_schemas(
    enabled: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    names = list(["read", "bash", "edit", "write"] if enabled is None else enabled)
    return [
        {"type": "function", "function": {"name": name, **_SCHEMAS[name]}}
        for name in names
        if name in _SCHEMAS
    ]


_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    cwd: str | Path,
    *,
    cancel_event: Any = None,
    model: dict[str, Any] | None = None,
    auto_resize_images: bool = True,
    on_update: Any = None,
) -> ToolResult:
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
        args = prepare_tool_arguments(name, arguments)
        if name == "bash":
            return _bash(args, cwd, cancel_event, on_update)
        if cancel_event is not None and cancel_event.is_set():
            return _error("Operation aborted")
        if name == "read":
            result = _read(args, cwd, model=model, auto_resize_images=auto_resize_images)
            if not result.is_error:
                image = next(
                    (block for block in result.content_blocks or [] if block["type"] == "image"),
                    None,
                )
                result.structured_content = (
                    {**image, "note": result.content} if image else result.content
                )
            return result
        if name in {"write", "edit"}:
            key = str(_resolve(args["path"], cwd))
            with _FILE_LOCKS_GUARD:
                lock = _FILE_LOCKS.setdefault(key, threading.Lock())
            with lock:
                if cancel_event is not None and cancel_event.is_set():
                    return _error("Operation aborted")
                result = handler(args, cwd)
                if cancel_event is not None and cancel_event.is_set():
                    return _error("Operation aborted")
                return result
        return handler(args, cwd)
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # Keep tool failures in the model-visible protocol.
        return _error(f"{name} failed: {type(exc).__name__}: {exc}")


__all__ = [
    "ToolResult",
    "execute_tool",
    "tool_schemas",
    "prepare_tool_arguments",
    "truncate_head",
    "truncate_tail",
]
