from __future__ import annotations
import re
from typing import Optional
from urllib.parse import urlparse

def _parse_base_url(base_url: str):
    """``urlparse`` that tolerates a bare ``host[:port][/path]`` (no scheme)."""
    raw = (base_url or "").strip()
    return urlparse(raw if "://" in raw else f"//{raw}") if raw else None


def _hostname_of(parsed) -> str:
    return (parsed.hostname or "").lower().rstrip(".") if parsed else ""


def base_url_hostname(base_url: str) -> str:
    """Lowercased hostname for a base URL, or ``""`` if absent.

    Compare exact hostnames against provider hosts instead of substring-matching the raw URL:
    ``https://api.openai.com.example/v1`` or ``https://proxy.test/api.openai.com/v1`` would
    otherwise pass as native endpoints and mis-route api_mode and auth.
    """
    return _hostname_of(_parse_base_url(base_url))


def base_url_origin(base_url: str) -> tuple[str, str, int]:
    """``(scheme, hostname, effective_port)`` for a base URL; ``("", "", 0)`` on no host/bad port.

    Origin, not just host: ``https://h`` vs ``http://h`` and two ports on one host are different
    trust boundaries, so handing a bearer secret to a new URL must compare all three — hostname
    alone would authorise an HTTPS→HTTP downgrade. Port defaults to 443/80 so ``https://h``
    equals ``https://h:443``.
    """
    parsed = _parse_base_url(base_url)
    hostname = _hostname_of(parsed)
    if not hostname:
        return ("", "", 0)
    scheme = (parsed.scheme or "").lower()
    try:
        port = parsed.port
    except ValueError:  # out-of-range or non-numeric port — not a usable origin
        return ("", "", 0)
    return (scheme, hostname, {"https": 443, "http": 80}.get(scheme, 0) if port is None else port)


def base_url_host_matches(base_url: str, domain: str) -> bool:
    """True when the base URL's hostname is ``domain`` or a subdomain.

    Safer than ``domain in base_url`` (``evil.com/moonshot.ai`` / ``moonshot.ai.evil`` must not
    match). Accepts bare hosts, full URLs, and URLs with paths.
    """
    hostname = base_url_hostname(base_url)
    domain = (domain or "").strip().lower().rstrip(".")
    return bool(hostname and domain) and (hostname == domain or hostname.endswith("." + domain))

