from __future__ import annotations
from typing import Any

_TEXT_PART_TYPES = {"text", "input_text", "output_text"}


_IMAGE_PART_TYPES = {"image_url", "input_image"}


def _nonempty_str(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def _str_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _part_type(part: dict[str, Any]) -> str:
    return str(part.get("type") or "").strip().lower()


def _iter_content_parts(content: list) -> Iterator[tuple[str, Any]]:
    """Yield ``("text", str)`` / ``("image", part)`` for recognized chat parts."""
    for part in content:
        if isinstance(part, str) and part:
            yield "text", part
        elif isinstance(part, dict):
            ptype = _part_type(part)
            if ptype in _TEXT_PART_TYPES and _nonempty_str(part.get("text")):
                yield "text", part["text"]
            elif ptype in _IMAGE_PART_TYPES:
                yield "image", part


def _summarize_user_message_for_log(content: Any, *, sep: str = " ") -> str:
    """Flatten message content to plain text: text parts joined with ``sep`` (``" "`` for logs; ``"\\n"`` for memory
    providers feeding regexes), images → ``[N image(s)]`` marker, ``""`` for None, ``str(content)`` for other scalars."""
    if not isinstance(content, list):
        try:
            return _str_or_empty(content)
        except Exception:
            return ""
    parts = list(_iter_content_parts(content))
    text_bits = [payload for kind, payload in parts if kind == "text"]
    image_count = len(parts) - len(text_bits)
    note = f"[{image_count} image{'s' if image_count != 1 else ''}]" if image_count else ""
    return " ".join(bit for bit in (note, sep.join(text_bits).strip()) if bit)
