from __future__ import annotations
import ipaddress
from urllib.parse import urlparse
from typing import Any, Optional

_TAILSCALE_CGNAT = ipaddress.IPv4Network("100.64.0.0/10")


def _parse_base_url(base_url: str, scheme: str = "http"):
    """``urlparse`` of the normalized URL (``scheme`` prepended when absent); None when empty."""
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return None
    return urlparse(normalized if "://" in normalized else f"{scheme}://{normalized}")


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


_CONTAINER_LOCAL_SUFFIXES = (".docker.internal", ".containers.internal", ".lima.internal")


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def is_local_endpoint(base_url: str) -> bool:
    """True for loopback, container-internal DNS, unqualified hosts, RFC-1918,
    link-local and Tailscale CGNAT (so a trusted Ollama box over Tailscale gets
    the same timeout auto-bumps as localhost)."""
    try:
        parsed = _parse_base_url(base_url)
        host = parsed.hostname or "" if parsed is not None else None
    except Exception:
        return False
    if host is None:
        return False
    # Unqualified hostnames (no dots) are local by definition — Docker Compose service names, /etc/hosts
    # entries, mDNS — as is `*.local` (RFC 6762 mDNS, LAN-only). IPv6 literals have no dots either, so
    # they are excluded here and classified by scope below (a global address is not local).
    if host in _LOCAL_HOSTS or host.endswith(_CONTAINER_LOCAL_SUFFIXES) or host.endswith(".local") or (host and "." not in host and ":" not in host):
        return True
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or (isinstance(addr, ipaddress.IPv4Address) and addr in _TAILSCALE_CGNAT):
            return True
    except ValueError:
        pass
    # Dotted quad that ipaddress rejected but still looks like a private range
    # (e.g. 172.26.x.x for WSL) or Tailscale CGNAT (100.64.x.x–100.127.x.x).
    parts = host.split(".")
    if len(parts) != 4:
        return False
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168) or (first == 100 and 64 <= second <= 127)
