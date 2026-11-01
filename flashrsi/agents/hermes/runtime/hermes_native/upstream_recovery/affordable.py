from __future__ import annotations
import re
from typing import Optional
from ..upstream_loop.error_classifier import _BILLING_PATTERNS

def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    """True when any needle is a substring of ``text``."""
    return any(kw in text for kw in needles)


_PAYMENT_KEYWORDS = _BILLING_PATTERNS + (
    "credits", "insufficient funds", "can only afford", "billing",
    "isn't available on the free tier", "key limit exceeded", "budget limit",
    "requires a subscription", "upgrade for access", "upgrade for higher limits",
    "reached your session usage limit", "quota exceeded", "quota_exceeded",
    "too many tokens per day", "daily limit", "tokens per day", "daily quota", "resource exhausted",
    "resource_exhausted", "resource-exhausted", "resourceexhausted",
    "weekly usage limit", "weekly limit",
)


def _is_payment_error(exc: Exception) -> bool:
    """Payment/credit/quota exhaustion: HTTP 402, or a billing/quota body on 403/404/429/no-status."""
    status = getattr(exc, "status_code", None)
    return status == 402 or (
        status in {403, 404, 429, None} and _contains_any(str(exc).lower(), _PAYMENT_KEYWORDS)
    )


_AFFORDABLE_TOKENS_RE = re.compile(r"can only afford\s+([0-9][0-9,]*)", re.IGNORECASE)


_AFFORDABLE_RETRY_FLOOR_TOKENS = 512


_AFFORDABLE_RETRY_MARGIN_TOKENS = 64


def _affordable_max_tokens_from_error(exc: Exception) -> Optional[int]:
    """Affordable output budget (minus margin) from an OpenRouter credit-limited 402
    ("...but can only afford 7117": credit exists, the cap was too large); ``None``
    when no count is present or the budget is too small to be useful."""
    if not _is_payment_error(exc):
        return None
    match = _AFFORDABLE_TOKENS_RE.search(str(exc))
    if not match:
        return None
    try:
        affordable = int(match.group(1).replace(",", ""))
    except (TypeError, ValueError):
        return None
    capped = affordable - _AFFORDABLE_RETRY_MARGIN_TOKENS
    return capped if capped >= _AFFORDABLE_RETRY_FLOOR_TOKENS else None
