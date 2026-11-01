from __future__ import annotations
from typing import Any,Optional
from ..upstream_pricing.urls import base_url_hostname
def _is_oauth_token(key: str) -> bool:
    """True for Anthropic OAuth/setup tokens (sk-ant-oat*, eyJ JWTs, cc-); False for the Console
    API-key families sk-ant-api*, sk-ant-usr*, sk-ant-svc* and sk-ant-admin* (#133856) — they pay
    per token and authenticate as x-api-key, so the Claude Code identity must not ride along.
    Unknown sk-ant-* prefixes still classify as OAuth so OAuth prefixes Anthropic ships later keep working."""
    if not key or key.startswith(("sk-ant-api", "sk-ant-usr", "sk-ant-svc", "sk-ant-admin")):
        return False
    return key.startswith(("sk-ant-", "eyJ", "cc-"))


def is_native_anthropic_host(base_url: Any) -> bool:
    """True when *base_url* is exactly ``api.anthropic.com`` (an empty base_url is the native default)."""
    text = str(base_url or "").strip()
    return not text or base_url_hostname(text) == "api.anthropic.com"


def anthropic_route_is_oauth(base_url: Any, credential: Any, *, provider: Optional[str] = None) -> bool:
    """Claude Code OAuth identity for one Anthropic Messages route (#114967).

    The route qualifies when it is the ``anthropic`` provider itself or its host is exactly
    ``api.anthropic.com`` (an empty base_url is the native default) — a named custom provider
    pointed at the native host carries the same identity, while third-party Anthropic-protocol
    endpoints never do (Claude Code headers and tool-name transforms 401/403 there). ``credential``
    is a static string or a ``key_cmd``/per-request callable token source; a callable is
    materialized once for the shape test (``CommandTokenSource`` caches, so this never double-mints)
    and a mint failure classifies as non-OAuth — the wire client surfaces the real error.
    """
    if not (is_native_anthropic_host(base_url) or (provider or "").strip().lower() == "anthropic"):
        return False
    if callable(credential) and not isinstance(credential, str):
        try:
            credential = credential()
        except Exception:
            return False
    return isinstance(credential, str) and _is_oauth_token(credential)

