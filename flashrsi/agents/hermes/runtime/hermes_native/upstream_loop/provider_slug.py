from __future__ import annotations


def custom_provider_slug(display_name: str, provider_key: str = "") -> str:
    """Stable ``custom:`` identity for a configured provider: keyed ``providers:`` entries use their
    config key (survives display-name changes); legacy ``custom_providers:`` entries have no key,
    so their normalized display name is the identity."""
    identity = str(provider_key or "").strip() or str(display_name or "").strip()
    normalized = identity.lower().replace(" ", "-")
    return normalized if normalized.startswith("custom:") else f"custom:{normalized}"
