"""Pinned Hermes provider-routing policy with explicit Snapshot settings.

The three policy functions below are AST-selected from v0.22.5 commit
bf0203a794a07aac3ff764972ab9087baa4e4f4e. The two ambient imports inside
_provider_preferences_for_agent are removed: its config loader reads the
request-local mapping supplied here, and the model resolver is the original
pure function. No host configuration, plugin discovery, or network is read.
"""

from __future__ import annotations

import contextlib
import copy
import logging
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any, Optional

from .reasoning_config import _canonical_model_variants

logger = logging.getLogger(__name__)
_OPENROUTER_PROVIDER_SORT_VALUES = {"throughput", "latency", "price"}
_config = ContextVar("hermes_explicit_provider_routing", default={})


def load_config_readonly():
    return _config.get()


def resolve_per_model_provider_routing(model: str, models: dict | None) -> dict:
    """``provider_routing.models.<id>`` entry for *model*, spelling-tolerant like
    ``reasoning_overrides``; ``{}`` when none matches. Only the keys a user sets per model
    are returned so unset ones fall through to the flat ``provider_routing`` values."""
    if not model or not isinstance(models, dict):
        return {}
    for variant in _canonical_model_variants(model):
        entry = models.get(variant)
        if isinstance(entry, dict):
            return entry
    return {}


def _validated_openrouter_provider_sort(raw_sort: Any) -> Optional[str]:
    """Return a normalized OpenRouter provider.sort value or None."""
    if not isinstance(raw_sort, str):
        return None
    sort_value = raw_sort.strip().lower()
    if not sort_value:
        return None
    if sort_value in _OPENROUTER_PROVIDER_SORT_VALUES:
        return sort_value
    logger.warning(
        "Ignoring invalid OpenRouter provider.sort value %r (allowed: %s)",
        raw_sort,
        ", ".join(sorted(_OPENROUTER_PROVIDER_SORT_VALUES)),
    )
    return None


def _provider_preferences_for_agent(agent) -> dict[str, Any]:
    """Build the validated provider-routing object shared by request paths.

    ``provider_routing.models.<id>`` overlays the flat constructor values for the CURRENT
    ``agent.model`` (so ``/model`` switches, fallbacks, and delegated children on another
    model each get their own pins without any surface re-plumbing the kwargs)."""
    flat = {
        "only": agent.providers_allowed,
        "ignore": agent.providers_ignored,
        "order": agent.providers_order,
        "sort": agent.provider_sort,
        "require_parameters": agent.provider_require_parameters,
        "data_collection": agent.provider_data_collection,
    }
    per_model = {}
    with contextlib.suppress(Exception):
        _pr = load_config_readonly().get("provider_routing")
        per_model = resolve_per_model_provider_routing(
            agent.model, (_pr or {}).get("models") if isinstance(_pr, dict) else None
        )
    merged = {**flat, **{k: v for k, v in per_model.items() if k in flat}}
    merged["sort"] = _validated_openrouter_provider_sort(merged["sort"])
    merged["require_parameters"] = True if merged["require_parameters"] else None
    return {key: value for key, value in merged.items() if value}


_CONSTRUCTOR_FIELDS = {
    "only": "providers_allowed",
    "ignore": "providers_ignored",
    "order": "providers_order",
    "sort": "provider_sort",
    "require_parameters": "provider_require_parameters",
    "data_collection": "provider_data_collection",
}


def resolve_provider_preferences(settings, route, model):
    """Resolve standard routing, per-model settings, then explicit preferences.

    ``settings.provider_routing`` is the Snapshot's normal Hermes config.
    Optional route routing/constructor fields are request-local overrides.
    Existing explicit ``provider_preferences`` remain authoritative and retain
    extra provider keys supported by the prior Snapshot boundary.
    """
    routing = copy.deepcopy(settings.get("provider_routing") or {})
    if not isinstance(routing, dict):
        routing = {}
    route_routing = route.get("provider_routing")
    if isinstance(route_routing, dict):
        routing.update(copy.deepcopy(route_routing))
    fields = {}
    for key, name in _CONSTRUCTOR_FIELDS.items():
        fields[name] = route.get(name, settings.get(name, routing.get(key)))
    agent = SimpleNamespace(model=model, **fields)
    token = _config.set({"provider_routing": routing})
    try:
        result = _provider_preferences_for_agent(agent)
    finally:
        _config.reset(token)
    for explicit in (
        settings.get("provider_preferences"),
        route.get("provider_preferences"),
    ):
        if isinstance(explicit, dict):
            result.update(copy.deepcopy(explicit))
    return result


def resolve_request_settings(settings, route, model):
    """Return the two prepared transport inputs without mutating caller data."""
    from .custom_configuration import resolve_extra_body_overrides

    return {
        "provider_preferences": resolve_provider_preferences(settings, route, model),
        "request_overrides": resolve_extra_body_overrides(settings, route, model),
    }
