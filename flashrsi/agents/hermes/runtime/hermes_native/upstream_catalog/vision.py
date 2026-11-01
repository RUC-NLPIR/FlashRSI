from __future__ import annotations
from typing import Any,Optional,Iterable
_BOOL_TOKENS = {
    **dict.fromkeys(("true", "yes", "on", "1"), True),
    **dict.fromkeys(("false", "no", "off", "0"), False),
}


def _coerce_capability_bool(raw: Any) -> Optional[bool]:
    """Strict boolean coercion for capability overrides: real bools, 0/1 and YAML
    boolean tokens only; anything else is None so the caller falls through to
    models.dev. ``bool("false")`` is True, so a quoted ``supports_vision: "false"``
    would otherwise silently enable native routing on a model that can't handle it."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return bool(raw) if raw in (0, 1) else None
    return _BOOL_TOKENS.get(raw.strip().lower()) if isinstance(raw, str) else None


def _dict_or_empty(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _clean_str(raw: Any) -> str:
    return str(raw or "").strip()


def _model_supports_vision_override(models_cfg: Any, model: str) -> Optional[bool]:
    """Per-model ``supports_vision`` (or ``vision`` alias) from a ``models`` mapping."""
    per_model = _dict_or_empty(_dict_or_empty(models_cfg).get(model))
    return _coerce_capability_bool(per_model.get("supports_vision", per_model.get("vision")))


def _custom_provider_entries(cfg: dict[str, Any], names: Iterable[str]) -> Iterable[dict[str, Any]]:
    """Yield legacy ``custom_providers`` entries matching ``names`` (case-insensitive);
    ``names`` is the outer loop so list order cannot let a persisted default shadow the live route."""
    entries = _custom_provider_list(cfg)
    for wanted in (n.strip().lower() for n in names):
        yield from (e for e in entries if _clean_str(e.get("name")).lower() == wanted)


def _custom_provider_list(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Dict entries of the legacy ``custom_providers`` list (empty when absent/malformed)."""
    raw = cfg.get("custom_providers")
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def _supports_vision_override(
    cfg: Optional[dict[str, Any]],
    provider: str,
    model: str,
    *,
    requested_provider: str = "",
) -> Optional[bool]:
    """Resolve user-declared vision capability from config.yaml; None when unset.

    First hit wins: ``model.supports_vision`` → ``providers.<p>.models.<model>``
    → legacy ``custom_providers[].models.<model>``. Named custom providers are
    rewritten to ``provider="custom"`` at runtime while config keeps the user's
    name under ``model.provider``, so the requested, runtime and config
    identities are all tried, plus the bare ``<name>`` of any ``custom:<name>``.
    """
    if not isinstance(cfg, dict):
        return None
    model_cfg = _dict_or_empty(cfg.get("model"))
    top = _coerce_capability_bool(model_cfg.get("supports_vision"))
    if top is not None:
        return top

    candidates: list[str] = []
    for candidate in filter(None, (requested_provider, provider, _clean_str(model_cfg.get("provider")))):
        candidates.append(candidate)
        if candidate.startswith("custom:") and candidate[len("custom:"):]:
            candidates.append(candidate[len("custom:"):])
    candidates = list(dict.fromkeys(candidates))

    providers_cfg = _dict_or_empty(cfg.get("providers"))
    model_maps = [_dict_or_empty(providers_cfg.get(p)).get("models") for p in candidates]
    model_maps += [entry.get("models") for entry in _custom_provider_entries(cfg, candidates)]
    return next((v for v in (_model_supports_vision_override(m, model) for m in model_maps) if v is not None), None)

