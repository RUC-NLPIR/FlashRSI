from __future__ import annotations
from typing import Optional
from .provider_labels import _PROVIDER_LABELS, _PROVIDER_ALIASES

def normalize_provider(provider: Optional[str]) -> str:
    """Normalize provider aliases to canonical ids. ``"auto"`` passes through — use
    ``hermes_cli.auth.resolve_provider()`` to resolve it from credentials."""
    normalized = (provider or "openrouter").strip().lower()
    return _PROVIDER_ALIASES.get(normalized, normalized)


def provider_label(provider: Optional[str]) -> str:
    """Return a human-friendly label for a provider id or alias."""
    original = (provider or "openrouter").strip()
    normalized = original.lower()
    if normalized == "auto":
        return "Auto"
    normalized = normalize_provider(normalized)
    return _PROVIDER_LABELS.get(normalized, original or "OpenRouter")
