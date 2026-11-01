from __future__ import annotations
import re
import time
from typing import Any, Optional
from ..upstream_loop.retry_utils import parse_retry_after_seconds, reset_delay_from_message
from .timestamps import _parse_absolute_timestamp

def _set_reset_from_retry_after(context: dict[str, Any], retry_after: Any) -> None:
    if "reset_at" in context:
        return
    seconds = parse_retry_after_seconds(retry_after)
    if seconds is not None:
        context["reset_at"] = time.time() + seconds


_DURATION_COMPONENT_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


_DURATION_UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


_VENDOR_RESET_HEADERS = (
    "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens",
    "anthropic-ratelimit-requests-reset", "anthropic-ratelimit-tokens-reset",
)


def _duration_string_seconds(text: str) -> Optional[float]:
    raw = text.strip().lower()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    parts = _DURATION_COMPONENT_RE.findall(raw)
    if not parts or "".join(n + u for n, u in parts) != raw:
        return None
    return sum(float(n) * _DURATION_UNIT_SECONDS[u] for n, u in parts)


def _set_reset_from_vendor_headers(context: dict[str, Any], headers: Any) -> None:
    for name in _VENDOR_RESET_HEADERS:
        value = headers.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        seconds = _duration_string_seconds(value)
        if seconds is None:
            absolute = _parse_absolute_timestamp(value)
            seconds = None if absolute is None else absolute - time.time()
        if seconds is not None and seconds > 0:
            context["reset_at"] = time.time() + seconds
            return


def extract_api_error_context(error: Exception) -> dict[str, Any]:
    """Extract structured rate-limit details from provider errors."""
    context: dict[str, Any] = {}
    body = getattr(error, "body", None)
    payload = (body.get("error") if isinstance(body.get("error"), dict) else body) if isinstance(body, dict) else None
    if isinstance(payload, dict):
        reason = payload.get("code") or payload.get("type") or payload.get("error")
        if isinstance(reason, str) and reason.strip():
            context["reason"] = reason.strip()
        message = payload.get("message") or payload.get("error_description")
        if not message and isinstance(payload.get("error"), str):
            # xAI uses a top-level string ``error`` beside a structured ``code``.
            message = payload.get("error")
        if isinstance(message, str) and message.strip():
            context["message"] = message.strip()
        reset = next((payload.get(k) for k in ("resets_at", "reset_at") if payload.get(k) not in {None, ""}), None)
        if reset is not None:
            context["reset_at"] = reset
        elif isinstance(payload.get("resets_in_seconds"), (int, float)):
            # Codex/ChatGPT usage-limit bodies carry a relative window beside (or instead of) the epoch.
            context["reset_at"] = time.time() + float(payload["resets_in_seconds"])
        _set_reset_from_retry_after(context, payload.get("retry_after"))
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers:
        _set_reset_from_retry_after(context, headers)
        ratelimit_reset = headers.get("x-ratelimit-reset")
        if ratelimit_reset and "reset_at" not in context:
            context["reset_at"] = ratelimit_reset
        if "reset_at" not in context:
            _set_reset_from_vendor_headers(context, headers)
    if "message" not in context and str(error).strip():
        context["message"] = str(error).strip()[:500]
    if "reset_at" not in context and isinstance(context.get("message") or "", str):
        delay = reset_delay_from_message(context.get("message") or "")
        if delay is not None:
            context["reset_at"] = time.time() + delay
    return context
