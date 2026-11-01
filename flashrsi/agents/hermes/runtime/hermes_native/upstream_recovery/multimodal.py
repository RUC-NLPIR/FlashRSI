from __future__ import annotations
import json
from typing import Any

def _is_multimodal_tool_result(value: Any) -> bool:
    """True for the multimodal envelope: dict with ``_multimodal=True`` and a ``content`` list."""
    return isinstance(value, dict) and value.get("_multimodal") is True and isinstance(value.get("content"), list)


def _is_text_part(p: Any) -> bool:
    return isinstance(p, dict) and p.get("type") == "text"


def _multimodal_text_summary(value: Any) -> str:
    """Plain-text view of a tool result (logging, previews, string-only providers)."""
    if isinstance(value, str):
        return value
    if _is_multimodal_tool_result(value):
        if value.get("text_summary"):
            return str(value["text_summary"])
        parts = [str(p.get("text", "")) for p in value.get("content") or [] if _is_text_part(p)]
        return "\n".join(parts) if parts else "[multimodal tool result]"
    try:
        return json.dumps(value, default=str)
    except Exception:
        return str(value)
