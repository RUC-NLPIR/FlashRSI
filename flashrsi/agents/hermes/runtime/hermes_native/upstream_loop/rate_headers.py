from __future__ import annotations
from typing import Any, Mapping, Optional

_BUCKET_TAGS = (
    ("requests_min", "requests"),
    ("requests_hour", "requests-1h"),
    ("tokens_min", "tokens"),
    ("tokens_hour", "tokens-1h"),
)


def _safe_float(value: Any, default: Any = 0.0) -> Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: Any = 0) -> Any:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def lower_headers(headers: Optional[Mapping[str, str]]) -> dict[str, str]:
    """Lowercase header names (HTTP header names are case-insensitive)."""
    return {k.lower(): v for k, v in headers.items()} if headers else {}


def has_rate_limit_headers(lowered: Mapping[str, str]) -> bool:
    return any(k.startswith("x-ratelimit-") for k in lowered)
