from __future__ import annotations
from typing import Any, Optional, Iterator
from ..upstream_compaction.responses_boundaries import normalize_route_base_url

def _entries_for_route(
    base_url: str,
    custom_providers: Optional[list[dict[str, Any]]],
    config: Optional[dict[str, Any]]):
    """Yield entries whose normalized route identity equals *base_url*.

    None *custom_providers* → ``get_compatible_custom_providers(config)`` (failure → none).
    """
    from .boundaries import get_compatible_custom_providers
    if custom_providers is None:
        try:
            custom_providers = get_compatible_custom_providers(config)
        except Exception:
            custom_providers = []
    if not base_url or not isinstance(custom_providers, list):
        return
    target_url = normalize_route_base_url(base_url)
    if not target_url:
        return
    for entry in custom_providers:
        if not isinstance(entry, dict):
            continue
        entry_url = normalize_route_base_url(entry.get("base_url"))
        if entry_url and entry_url == target_url:
            yield entry


def _route_model_cfg(entry: dict[str, Any], model: str) -> Optional[dict[str, Any]]:
    """Return ``entry.models[model]`` when both are mappings, else None."""
    models = entry.get("models")
    if not isinstance(models, dict):
        return None
    model_cfg = models.get(model)
    return model_cfg if isinstance(model_cfg, dict) else None


def _route_model_cfgs(
    model: str,
    base_url: str,
    custom_providers: Optional[list[dict[str, Any]]],
    config: Optional[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Yield the ``models.<model>`` mapping of every entry matching *base_url*."""
    for entry in _entries_for_route(base_url, custom_providers, config):
        model_cfg = _route_model_cfg(entry, model)
        if model_cfg is not None:
            yield model_cfg


def get_custom_provider_model_capability(
    model: str,
    base_url: str,
    capability: str,
    custom_providers: Optional[list[dict[str, Any]]] = None,
    config: Optional[dict[str, Any]] = None) -> Optional[bool]:
    """Explicit boolean capability for one custom-provider model, or ``None``. Scoped to the
    normalized route + exact runtime model id so aliases can declare capabilities."""
    from .boundaries import get_compatible_custom_providers, load_config_readonly
    if not model or not base_url or not capability:
        return None
    if custom_providers is None:
        try:
            if config is None:
                # Read-only path: entries are never mutated and get_compatible_custom_providers
                # shallow-copies each one, so the no-deepcopy cache is safe (~135us saved per call).
                config = load_config_readonly()
            custom_providers = get_compatible_custom_providers(config)
        except Exception:
            return None

    for model_cfg in _route_model_cfgs(model, base_url, custom_providers, config):
        value = model_cfg.get(capability)
        if isinstance(value, bool):
            return value
    return None
