from __future__ import annotations
from typing import Any

_FINISH_REASON_ALIASES = {
    "max_tokens": "length",  # Gemini-native / Anthropic-style cap reason
    "end": "stop",  # some gateways' clean-completion spelling
    "function_call": "tool_calls",  # OpenAI legacy pre-tools spelling
}


def normalize_finish_reason(raw: Any) -> Any:
    """Fold a wire ``finish_reason`` to the lowercase OpenAI contract value.

    Non-string and empty values pass through unchanged (callers keep their
    ``or "stop"`` defaults and the Poolside int-reason path); contract values
    are returned byte-identical.
    """
    if not isinstance(raw, str) or not raw:
        return raw
    lowered = raw.lower()
    return _FINISH_REASON_ALIASES.get(lowered, lowered)


def _tc_field(tc: Any, key: str) -> Any:
    """Read ``key`` from a tool-call entry that may be a dict or an SDK object."""
    return tc.get(key) if isinstance(tc, dict) else getattr(tc, key, None)


def coalesce_tool_call_id(tc: Any) -> str:
    """Effective call id of a tool_call entry (dict or object); ``""`` when none. Codex Responses
    carry ``call_id`` (authoritative pairing key), Chat Completions ``id`` only, and bridge ids
    may be ``call_id|response_item_id``."""
    for raw in (_tc_field(tc, "call_id"), _tc_field(tc, "id")):
        value = raw.strip() if isinstance(raw, str) else ""
        if value:
            return value.split("|", 1)[0].strip() or value
    return ""


def model_forces_max_completion_tokens(model: str) -> bool:
    """True for OpenAI families that reject ``max_tokens`` (HTTP 400 ``unsupported_parameter``)."""
    m = (model or "").strip().lower().rsplit("/", 1)[-1]
    return m.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3", "o4"))
