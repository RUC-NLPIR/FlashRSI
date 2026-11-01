from __future__ import annotations
import re
from typing import Any, Optional

GEMINI_DEFAULT_MAX_OUTPUT_TOKENS = 65535


def bare_gemini_model_id(model: str) -> str:
    """Strip Gemini's own provider prefix from an aggregator-style model id."""
    name = (model or "").strip()
    for prefix in ("google/", "gemini/"):
        if name.lower().startswith(prefix):
            return name[len(prefix):].strip() or name
    return name


def _gemini_version(model: str) -> tuple[int, int]:
    """(major, minor) of a Gemini model id: ``gemini-4-argon`` -> (4, 0), ``google/gemini-3.8-flash`` ->
    (3, 8); (0, 0) for non-Gemini and unversioned ids (``gemini-flash-latest``, ``gemini-exp-1206``)."""
    match = re.match(r"gemini-(\d+)(?:\.(\d+))?", bare_gemini_model_id(model).lower())
    return (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)


def gemini_uses_thinking_level(model: str) -> bool:
    """Gemini 3 and every later generation steer thinking with the ``thinkingLevel`` enum (``thinkingBudget``
    is deprecated there), as do the ``gemini-*-latest`` aliases, which Google hot-swaps to the newest
    release of each variant. A version-number gate, not a ``gemini-3`` prefix, so a new generation
    (``gemini-4-argon``) isn't silently treated as legacy."""
    bare = bare_gemini_model_id(model).lower()
    return (bare.startswith("gemini-") and bare.endswith("-latest")) or _gemini_version(bare) >= (3, 0)


def is_vertex_express_base_url(base_url: str) -> bool:
    """An aiplatform host speaking the native API with an API key: the bare express surface, or its
    ``…/projects/{p}/locations/{l}`` form, which reaches models served only in ``global`` (Gemini 4).
    The OAuth Vertex provider's ``…/endpoints/openapi`` base is OpenAI-compatible and must stay off
    the native adapter."""
    normalized = str(base_url or "").strip().lower()
    return "aiplatform.googleapis.com" in normalized and "/endpoints/" not in normalized


def is_native_gemini_base_url(base_url: str) -> bool:
    """True when the endpoint speaks Gemini's native REST API (not ``/openai``)."""
    normalized = str(base_url or "").strip().rstrip("/").lower()
    if normalized.endswith("/openai"):
        return False
    return "generativelanguage.googleapis.com" in normalized or is_vertex_express_base_url(normalized)


_THINKING_KEYS = (
    ("thinkingBudget", "thinking_budget", (int, float), int),
    ("includeThoughts", "include_thoughts", bool, lambda v: v),
    ("thinkingLevel", "thinking_level", str, lambda v: v.strip().lower()),
)


def _normalize_thinking_config(config: Any) -> Optional[dict[str, Any]]:
    if not isinstance(config, dict):
        return None
    values = {key: config.get(key, config.get(alias)) for key, alias, _, _ in _THINKING_KEYS}
    normalized = {key: norm(values[key]) for key, _, types, norm in _THINKING_KEYS
                  if isinstance(values[key], types) and (values[key].strip() if isinstance(values[key], str) else True)}
    return normalized or None


def _thinking_requests_output_headroom(thinking_config: Any) -> bool:
    """True when Gemini will spend output tokens on thinking: thought tokens bill against ``maxOutputTokens``,
    so a global 4096/16384 cap can be consumed entirely by high thinking (``finishReason=MAX_TOKENS``, no answer)."""
    normalized = _normalize_thinking_config(thinking_config) or {}
    if normalized.get("includeThoughts") is False:
        # Hidden thoughts = reasoning disabled/minimised: never ask for headroom, or a small
        # caller budget (title generation's 64 tokens) balloons to the model ceiling. Gemini 3
        # still carries a "low" thinkingLevel here (no off-switch), which must not re-enable the
        # bump. (#91927)
        return False
    budget = normalized.get("thinkingBudget")
    has_level = "thinkingLevel" in normalized
    return bool(normalized) and not (isinstance(budget, int) and budget <= 0 and not has_level)


def _effective_gemini_max_output_tokens(max_tokens: Optional[int], thinking_config: Any) -> int:
    """Native ``maxOutputTokens``: an omitted/invalid cap becomes the published ceiling (Gemini
    truncates on its low internal default); an explicit cap is raised to the ceiling when
    thinking is enabled so thoughts don't starve the answer."""
    try:
        requested = int(max_tokens)
    except (TypeError, ValueError):
        requested = 0
    if requested <= 0 or _thinking_requests_output_headroom(thinking_config):
        return max(requested, GEMINI_DEFAULT_MAX_OUTPUT_TOKENS)
    return requested

