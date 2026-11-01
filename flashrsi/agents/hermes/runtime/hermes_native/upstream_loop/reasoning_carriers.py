from __future__ import annotations
from typing import Any, Optional

CARRIER_TYPE = "hermes.native_assistant"


def field(obj: Any, name: str) -> Any:
    """``obj.<name>``, else the same key from pydantic ``model_extra`` (unknown SDK fields park there)."""
    value = getattr(obj, name, None)
    for side in ("model_extra", "provider_data"):  # pydantic unknown fields / normalized responses
        if value is None and isinstance(getattr(obj, side, None), dict):
            value = getattr(obj, side).get(name)
    dump = getattr(value, "model_dump", None)
    return dump() if callable(dump) else value


def thought_signature(extra: Any) -> Optional[str]:
    """Gemini signature inside an ``extra_content`` dict (``google.thought_signature`` or flat)."""
    if not isinstance(extra, dict):
        return None
    google = extra.get("google")
    sig = google.get("thought_signature") if isinstance(google, dict) else extra.get("thought_signature")
    return sig if isinstance(sig, str) and sig.strip() else None


def carrier_record(assistant_message: Any) -> Optional[dict]:
    """The private ``reasoning_details`` record for one response message, or None when it has no carrier."""
    record: dict[str, Any] = {}
    if sig := thought_signature(field(assistant_message, "extra_content")):
        record["extra_content"] = {"google": {"thought_signature": sig}}
    for key in ("reasoning_opaque", "reasoning_text"):
        value = field(assistant_message, key)
        if isinstance(value, str) and value:
            record[key] = value
    return {"type": CARRIER_TYPE, **record} if record else None
