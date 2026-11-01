"""Pinned Hermes custom-provider defaults plus explicit Snapshot overrides.

The four private helpers are verbatim agent/agent_init.py:255-320 from
v0.22.5 (bf0203a794a07aac3ff764972ab9087baa4e4f4e). They read only their
arguments; the Snapshot wrapper does not load ambient Hermes configuration.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, Optional


def _normalized_custom_base_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip("/")


def _custom_provider_model_matches(agent_model: str, entry: dict[str, Any]) -> bool:
    agent_model_norm = str(agent_model or "").strip().lower()
    # Multi-model entries (`providers.<name>.models` mapping / legacy `models:` list):
    # matching ANY catalog entry counts, else a provider whose `model` differs from the
    # session model drops its extra_body (e.g. OpenAI service_tier) → wrong billing tier.
    models = entry.get("models")
    catalog = (
        [str(m).strip().lower() for m in models]
        if isinstance(models, (dict, list, tuple))
        else []
    )
    if catalog and agent_model_norm in catalog:
        return True
    provider_model = str(entry.get("model", "") or "").strip().lower()
    return (not provider_model and not catalog) or provider_model == agent_model_norm


def _custom_provider_extra_body_for_agent(
    *, provider: str, model: str, base_url: str, custom_providers: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    provider_norm = (provider or "").strip().lower()
    if provider_norm != "custom" and not provider_norm.startswith("custom:"):
        return None
    provider_key_filter = provider_norm.partition(":")[2].strip()
    target_url = _normalized_custom_base_url(base_url)
    if not target_url:
        return None

    fallback: Optional[dict[str, Any]] = None
    for entry in custom_providers or []:
        if not isinstance(entry, dict):
            continue
        entry_keys = {
            str(entry.get("provider_key", "") or "").strip().lower(),
            str(entry.get("name", "") or "").strip().lower(),
        }
        if provider_key_filter and provider_key_filter not in entry_keys:
            continue
        if _normalized_custom_base_url(entry.get("base_url")) != target_url:
            continue
        extra_body = entry.get("extra_body")
        if not isinstance(extra_body, dict) or not extra_body:
            continue
        if str(entry.get("model", "") or "").strip():
            if _custom_provider_model_matches(model, entry):
                return dict(extra_body)
        elif fallback is None:
            fallback = dict(extra_body)
    return fallback


def _merge_custom_provider_extra_body(
    agent, custom_providers: list[dict[str, Any]]
) -> None:
    extra_body = _custom_provider_extra_body_for_agent(
        provider=agent.provider,
        model=agent.model,
        base_url=agent.base_url,
        custom_providers=custom_providers,
    )
    if not extra_body:
        return
    overrides = dict(getattr(agent, "request_overrides", {}) or {})
    merged_extra_body = dict(extra_body)
    existing_extra_body = overrides.get("extra_body")
    if isinstance(existing_extra_body, dict):
        merged_extra_body.update(existing_extra_body)
    overrides["extra_body"] = merged_extra_body
    agent.request_overrides = overrides


def resolve_extra_body_overrides(settings, route, model) -> dict:
    """Return provider defaults merged with explicit request overrides.

    Source semantics merge a selected custom_providers entry below existing
    request_overrides.extra_body. The explicit Snapshot boundary additionally
    accepts route.extra_body; precedence for extra-body keys is provider defaults,
    settings.request_overrides, route.extra_body, route.request_overrides.
    Nested values use the source's shallow replacement semantics. Top-level
    request overrides retain settings-then-route precedence.
    """
    settings_overrides = copy.deepcopy(settings.get("request_overrides") or {})
    route_overrides = copy.deepcopy(route.get("request_overrides") or {})
    overrides = {**settings_overrides, **route_overrides}
    parts = (
        settings_overrides.get("extra_body"),
        route.get("extra_body"),
        route_overrides.get("extra_body"),
    )
    if any(isinstance(part, dict) for part in parts):
        merged = {}
        for part in parts:
            if isinstance(part, dict):
                merged.update(copy.deepcopy(part))
        overrides["extra_body"] = merged
    agent = SimpleNamespace(
        provider=route.get("provider") or "",
        model=model,
        base_url=route.get("base_url") or "https://api.openai.com/v1",
        request_overrides=overrides,
    )
    _merge_custom_provider_extra_body(
        agent, route.get("custom_providers", settings.get("custom_providers", []))
    )
    return copy.deepcopy(agent.request_overrides)
