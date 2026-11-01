from __future__ import annotations
OPENROUTER_VARIANT_SUFFIXES: frozenset[str] = frozenset(
    {"nitro", "floor", "exacto", "online"}
)


def openrouter_variant_base(model_id: str) -> str | None:
    """Return the base model id when ``model_id`` carries a recognized
    OpenRouter routing-variant suffix (e.g. ``x-ai/grok-4:nitro`` →
    ``x-ai/grok-4``), else ``None``.

    Lives here rather than in ``hermes_cli.models`` so the metadata layer
    (``agent.model_metadata``) can share one definition without importing the
    CLI — this module is dependency-free by contract.

    >>> openrouter_variant_base("x-ai/grok-4:nitro")
    'x-ai/grok-4'
    >>> openrouter_variant_base("x-ai/grok-4:free") is None
    True
    >>> openrouter_variant_base("x-ai/grok-4") is None
    True
    """
    base, sep, suffix = (model_id or "").rpartition(":")
    if not sep or not base:
        return None
    if suffix.lower() in OPENROUTER_VARIANT_SUFFIXES:
        return base
    return None

