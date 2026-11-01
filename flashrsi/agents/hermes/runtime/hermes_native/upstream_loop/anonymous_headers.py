from __future__ import annotations
from typing import Any, Mapping, Optional
from .retry_utils import parse_retry_after_seconds
from .rate_headers import _BUCKET_TAGS, _safe_float, _safe_int, has_rate_limit_headers, lower_headers

WELCOME_LONG_WAIT_SECONDS = 20.0


def welcome_refusal_from_headers(
    headers: Optional[Mapping[str, str]], *, body_wait: Optional[float] = None,
) -> dict[str, Any]:
    """A free-tier 429 that carried no structured ``reason``, read from its headers (else the wait
    its body named) into the ``parse_welcome_refusal`` shape. Long wait or an empty bucket =
    ``rate_limited``; a short or unexplained one = ``at_capacity``. A missing wait stays 0 so the
    breaker never trips on a guess."""
    buckets = _parse_buckets_from_headers(headers).values()
    # Only an empty bucket's reset is a wait; a healthy bucket's reset is just its window end.
    exhausted_wait = max((reset for remaining, reset in buckets
                          if remaining is not None and remaining <= 0 and (reset or 0) > 0), default=None)
    wait = (exhausted_wait or parse_retry_after_seconds(lower_headers(headers).get("retry-after"))
            or body_wait or 0.0)
    empty = any(remaining is not None and remaining <= 0 for remaining, _reset in buckets)
    reason = "rate_limited" if wait >= WELCOME_LONG_WAIT_SECONDS or empty else "at_capacity"
    return {"reason": reason, "retry_after": max(0, int(wait)), "alternates": [], "upgrade_url": ""}


def _parse_buckets_from_headers(
    headers: Optional[Mapping[str, str]],
) -> dict[str, tuple[Optional[int], Optional[float]]]:
    """(remaining, reset_seconds) per bucket from x-ratelimit-* headers ({} if none)."""
    lowered = lower_headers(headers)
    if not has_rate_limit_headers(lowered):
        return {}
    result: dict[str, tuple[Optional[int], Optional[float]]] = {}
    for _attr, tag in _BUCKET_TAGS:
        remaining = _safe_int(lowered.get(f"x-ratelimit-remaining-{tag}"), None)
        reset = _safe_float(lowered.get(f"x-ratelimit-reset-{tag}"), None)
        if remaining is not None or reset is not None:
            result[tag] = (remaining, reset)
    return result
