from __future__ import annotations
import re
from typing import Any, Optional
from urllib.parse import urlparse

ANON_ACCOUNT_TIER = "anonymous"


def is_anonymous_request(provider: Any, api_key: Any) -> bool:
    """Select anonymous error UX from the credential actually sent, never the saved profile or URL.

    This is display/recovery metadata, not token verification; the gateway authenticates the JWT.
    Named free accounts and opaque API keys must retain normal provider errors.
    """
    from .jwt_claims import _decode_jwt_claims
    return provider == "nous" and _decode_jwt_claims(api_key).get("account_tier") == ANON_ACCOUNT_TIER


WELCOME_HOSTS = frozenset({"welcome-api.nousresearch.com"})


EXTRA_WELCOME_HOSTS_ENV = "HERMES_EXTRA_WELCOME_HOSTS"


def welcome_hosts() -> frozenset[str]:
    """``WELCOME_HOSTS`` plus any ``HERMES_EXTRA_WELCOME_HOSTS`` entries (lowercased hostnames)."""
    raw = {}.get(EXTRA_WELCOME_HOSTS_ENV) or ""
    extra = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return WELCOME_HOSTS | frozenset(extra) if extra else WELCOME_HOSTS


def route_is_welcome_host(base_url: Any) -> bool:
    """The routing predicate for the free tier: the welcome host serves exactly ``nous/welcome``.

    Keyed on the resolved endpoint, never on profile state, so a paid pool credential routed to the
    portal host keeps its model even when a guest singleton exists beside it.
    """
    from urllib.parse import urlparse
    try:
        host = (urlparse(str(base_url or "")).hostname or "").lower()
    except ValueError:
        return False
    return host in welcome_hosts()


WELCOME_REFUSAL_REASONS = frozenset(
    {"model_not_free", "feature_not_free", "at_capacity", "admission_closed", "rate_limited"})


WELCOME_TIER_GATE_REASONS = frozenset({"model_not_free", "feature_not_free"})


_WELCOME_ROUTE_REFUSALS = (
    ("anonymous accounts must use", "anon_on_paid_host"),
    ("serves anonymous hermes agent accounts only", "named_on_welcome_host"),
    ("anonymous accounts are not accepted", "tier_disabled"),
    # The gateway's answer to an expired or unreadable bearer: the credential, not the tier. A
    # retry that waited out a long rate limit outlives the 15-minute free-tier JWT and lands here.
    ("invalid jwt", "session_expired"),
)


def parse_welcome_refusal(body: Any) -> Optional[dict[str, Any]]:
    """The structured welcome-tier refusal in a gateway 429 body, or None for any other shape.

    Returns ``{"reason", "retry_after", "alternates", "upgrade_url"}`` with ``retry_after`` an int
    of whole seconds (0 when the gateway sent none) and ``alternates`` a list of model ids.
    """
    if not isinstance(body, dict):
        return None
    reason = body.get("reason")
    if not isinstance(reason, str) or reason not in WELCOME_REFUSAL_REASONS:
        return None
    raw_retry = body.get("retry_after")
    try:
        retry_after = max(0, int(float(raw_retry))) if raw_retry not in (None, "") else 0
    except (TypeError, ValueError):
        retry_after = 0
    raw_alternates = body.get("alternates")
    alternates = [str(a) for a in raw_alternates if isinstance(a, str) and a] if isinstance(raw_alternates, list) else []
    upgrade_url = body.get("upgrade_url")
    return {"reason": reason, "retry_after": retry_after, "alternates": alternates,
            "upgrade_url": upgrade_url if isinstance(upgrade_url, str) else ""}


def welcome_route_refusal(status: Any, message: Any, base_url: Any = None) -> Optional[str]:
    """Which host cross-refusal a gateway 400/403 is; None for any other error.

    ``"anon_on_paid_host"``: a free-tier JWT reached the paid host. ``"named_on_welcome_host"``: an
    account or API key reached the free tier's host. ``"tier_disabled"``: the tier is dark
    (``WELCOME_MODE=off``). Each is deterministic for the request: retrying cannot help.
    ``"session_expired"``: the 403 names the bearer (``invalid jwt``); a fresh credential heals it.

    The dark-tier 403 is keyed on the ROUTE, not the message: the gateway's permission error
    carries only its generic sentence (the detail stays in its logs), so any 403 answered by the
    welcome host means the tier refused this install. The message needles remain for gateways
    that do spell it out, and for the two wrong-host 400s."""
    if status not in (400, 403):
        return None
    text = str(message or "").lower()
    kind = next((kind for needle, kind in _WELCOME_ROUTE_REFUSALS if needle in text), None)
    if kind is None and status == 403 and route_is_welcome_host(base_url):
        return "tier_disabled"
    return kind
