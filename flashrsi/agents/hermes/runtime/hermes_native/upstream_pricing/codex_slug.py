from __future__ import annotations
import re
from typing import Optional
from urllib.parse import urlparse

CODEX_CONTEXT_VARIANT_SUFFIX = "-900k"  # picker-only opt-in suffix; never sent on the wire


_CODEX_900K_SNAPSHOT_BASES = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-sol", "gpt-6-luna")


_CODEX_900K_ELIGIBLE_BASES = frozenset({*_CODEX_900K_SNAPSHOT_BASES, "gpt-5.4", "gpt-daybreak-blue-latest", "gpt-6-astra", "gpt-6.1-sol"})


_CODEX_900K_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _bare_codex_slug(model: Optional[str]) -> str:
    """Lowercased slug without ``vendor/`` (display/auxiliary callers pass ``openai/gpt-5.6-sol-900k``).

    Display/auxiliary callers pass ids like ``openai/gpt-5.6-sol-900k``; the main-agent path normalizes the
    namespace away earlier, but this resolver must accept both shapes (#92797 review).
    """
    return (model or "").strip().lower().rsplit("/", 1)[-1]


def is_codex_900k_base(model: Optional[str]) -> bool:
    """Single source of truth for ``-900k`` eligibility (picker, resolution, /model validation, wire stripping)."""
    slug = _bare_codex_slug(model)
    if not slug or slug.endswith(CODEX_CONTEXT_VARIANT_SUFFIX):
        return False
    # Dated snapshots of the routable tier bases (gpt-5.6-sol-2026-07-09, gpt-6-sol-2026-09-22) also qualify.
    return slug in _CODEX_900K_ELIGIBLE_BASES or any(
        slug.startswith(base + "-") and _CODEX_900K_SNAPSHOT_RE.match(slug[len(base) + 1:]) for base in _CODEX_900K_SNAPSHOT_BASES
    )


def _codex_variant_base(model: Optional[str]) -> Optional[str]:
    """Lowercased eligible base of a VALID ``-900k`` variant, else None (``gpt-5.5-900k`` is an invalid alias)."""
    slug = _bare_codex_slug(model)
    base = slug[: -len(CODEX_CONTEXT_VARIANT_SUFFIX)] if slug.endswith(CODEX_CONTEXT_VARIANT_SUFFIX) else None
    return base if base is not None and is_codex_900k_base(base) else None


def strip_codex_context_variant_suffix(model: Optional[str]) -> str:
    """Wire-safe slug with a VALID ``-900k`` suffix removed (vendor prefix kept); an ineligible alias is
    returned unchanged so it fails honestly at the API instead of running as another model."""
    raw = (model or "").strip()
    return raw[: -len(CODEX_CONTEXT_VARIANT_SUFFIX)] if _codex_variant_base(raw) is not None else raw

