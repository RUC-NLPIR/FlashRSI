"""Explicit endpoint configuration shared by web tools and preflight."""

import os
from urllib.parse import urlparse


class WebToolError(RuntimeError):
    """A configured network tool cannot safely complete its request."""


def endpoint(tool: str) -> str:
    name = {"web_search": "FLASHRSI_SEARCH_URL", "read_url": "FLASHRSI_BROWSE_URL"}[
        tool
    ]
    value = os.environ.get(name, "")
    if not value:
        raise WebToolError(
            f"{tool} requires an explicit {name} endpoint; configure a trusted "
            "search/browse service or remove this tool from agent.yaml"
        )
    parsed = urlparse(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise WebToolError(
            f"{name} must be a URL without credentials, query, or fragment"
        )
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise WebToolError(
            f"{name} requires HTTPS (HTTP is permitted only for loopback tests)"
        )
    return value


def validate_config(names) -> None:
    for name in names:
        if name in {"web_search", "read_url"}:
            endpoint(name)


def headers() -> dict:
    secret = os.environ.get("FLASHRSI_WEB_API_KEY")
    return {"Authorization": "Bearer " + secret} if secret else {}
