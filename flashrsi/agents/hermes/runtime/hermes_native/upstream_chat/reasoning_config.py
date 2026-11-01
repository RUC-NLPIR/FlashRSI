from __future__ import annotations
import re

VALID_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def parse_reasoning_effort(effort) -> dict | None:
    """Parse a reasoning effort level into a config dict.

    ``None`` for empty/unrecognized input (caller uses the default); ``{"enabled": False}`` for
    "none"/"false"/"disabled"/YAML False — ``reasoning_effort: false`` must mean disabled.

    The dict form ``{"enabled": true, "effort": "<level>"}`` passes ``effort`` through verbatim so
    providers with bespoke thinking tiers (``fast``/``thinking`` relays) can be asked for their real
    level; bare strings stay strict so a typo like ``hgih`` never reaches the wire. The wire layer
    already tolerates unknown names (``agent.reasoning_effort.clamp_effort``).
    """
    if effort is None or effort is True:
        return None
    if isinstance(effort, dict):
        if effort.get("enabled", True) is False:
            return {"enabled": False}
        # ``or ""``: a falsy effort (0/False) is "no level", never the string "0" on the wire.
        level = str(effort.get("effort") or "").strip()
        return {"enabled": True, "effort": level} if level else None
    effort = str(effort).strip().lower()  # False -> "false" -> disabled; "" matches neither set
    if effort in {"none", "false", "disabled"}:
        return {"enabled": False}
    if effort in VALID_REASONING_EFFORTS:
        return {"enabled": True, "effort": effort}
    return None


def _canonical_model_variants(model: str) -> list[str]:
    """Spelling variants for tolerant override matching, exact first, deduped in order.

    Dot/dash recovery runs on EACH base form so ``x-4.5``, ``x-4-5`` and ``x.4.5`` share one variant set.
    """
    _dash_to_dot = lambda s: re.sub(r'(\d)-(\d)', r'\1.\2', s)
    _dot_to_dash = lambda s: re.sub(r'(\d)\.(\d)', r'\1-\2', s)
    seen: set[str] = set()
    variants: list[str] = []

    def _add(*values):
        for v in values:
            if v and v not in seen:
                seen.add(v)
                variants.append(v)

    def _add_with_derivatives(s):
        dashed, dotted = s.replace('.', '-'), s.replace('-', '.')
        _add(s, dashed, dotted, _dash_to_dot(s), _dot_to_dash(s), _dash_to_dot(dashed), _dot_to_dash(dotted))
    _add_with_derivatives(model)
    parts = model.split('/')
    if len(parts) >= 2:  # bare model (strip provider/aggregator prefix)
        _add_with_derivatives(parts[-1])
    if len(parts) >= 3:  # strip aggregator only: "openrouter/anthropic/x" → "anthropic/x"
        _add_with_derivatives('/'.join(parts[1:]))
    known_providers = (
        'anthropic', 'openai', 'google', 'openrouter', 'groq', 'mistral',
        'xai', 'cohere', 'perplexity', 'together', 'fireworks', 'deepseek',
    )
    for v in [v for v in variants if '/' not in v]:
        _add(*(f"{provider}/{v}" for provider in known_providers))
    known_aggregators = ('openrouter', 'opencode', 'fireworks', 'groq', 'together')
    for v in [v for v in variants if v.count('/') == 1]:
        _add(*(f"{agg}/{v}" for agg in known_aggregators))
    return variants


def resolve_per_model_reasoning_effort(model: str, overrides: dict | None) -> dict | None:
    """Per-model reasoning_effort override with spelling tolerance; first non-None parse wins.

    Order: exact → dots↔dashes → provider stripped → aggregator stripped → known prefixes added →
    reverse lookup of prefixed keys whose stripped forms match (custom provider slugs are not
    enumerable, so a key like ``ollama-local/qwen3.6:27b`` must still match the bare
    ``qwen3.6:27b`` model string a fallback swap feeds after stripping the prefix).
    """
    if not overrides or not isinstance(overrides, dict) or not model:
        return None
    variants = _canonical_model_variants(model)
    for variant in variants:
        if variant in overrides:
            result = parse_reasoning_effort(overrides[variant])
            if result is not None:
                return result
    # Reverse lookup: the key may carry a custom-provider prefix the model string lost
    # (fallback entries and custom-provider resolution feed the bare slug, while the
    # documented key spelling keeps the ``provider/model`` form). Direct and variant
    # matches above still win, so provider-qualified keys stay most specific.
    variant_set = set(variants)
    for key, raw in overrides.items():
        if not isinstance(key, str) or "/" not in key:
            continue
        parts = key.split("/")
        key_forms = _canonical_model_variants(parts[-1])
        if len(parts) >= 3:
            key_forms += _canonical_model_variants("/".join(parts[1:]))
        if any(form in variant_set for form in key_forms):
            result = parse_reasoning_effort(raw)
            if result is not None:
                return result
    return None


def resolve_reasoning_config(cfg: dict | None, model: str = "") -> dict | None:
    """Effective reasoning config for *model*: per-model override, then global ``agent.reasoning_effort``.

    Single chokepoint for every surface (CLI, gateway, TUI, cron, ``/model``, fallback activation).
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    agent_cfg = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}

    if not model:
        model_cfg = cfg.get("model")
        if isinstance(model_cfg, dict):
            model_cfg = model_cfg.get("default") or model_cfg.get("model") or ""
        model = model_cfg.strip() if isinstance(model_cfg, str) else ""
    per_model = resolve_per_model_reasoning_effort(model, agent_cfg.get("reasoning_overrides") or {})
    if per_model is not None:
        return per_model

    # Keep the raw value: ``or ""`` would turn a YAML False into "" and silently re-enable thinking.
    effort = agent_cfg.get("reasoning_effort", "")
    result = parse_reasoning_effort(effort)
    if effort and str(effort).strip() and result is None:
        import logging
        logging.getLogger(__name__).warning("Unknown reasoning_effort '%s', using default (medium)", effort)
    return result

