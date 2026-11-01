"""SDK-free HTTP boundary around the pinned original Chat transport.

The original transport and selected provider profiles own wire conversion.
Catalog capabilities and cache scopes are explicit Snapshot inputs; this module
does not discover plugins, read host credentials or create an upstream client.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

from .upstream_chat.boundaries import request_settings
from .upstream_chat.chat_completions import (
    ChatCompletionsTransport,
    _rename_tool_search_bridge_for_xai,
)
from .upstream_chat.configuration import resolve_request_settings
from .upstream_chat.custom_profile import custom
from .upstream_chat.deepseek_profile import deepseek
from .upstream_chat.gemini_profile import gemini
from .upstream_chat.kimi_coding_profile import kimi, kimi_cn
from .upstream_chat.openrouter_profile import openrouter
from .upstream_chat.profile_registry import load_profiles
from .upstream_chat.reasoning_carriers import shape_wire_carriers
from .upstream_chat.reasoning_config import (
    parse_reasoning_effort,
    resolve_reasoning_config,
)
from .upstream_chat.wire_helpers import model_forces_max_completion_tokens
from .upstream_chat.xai_profile import xai
from .upstream_compaction.utils import base_url_host_matches, base_url_hostname

_PROFILES = {
    name: profile
    for profile in (custom, deepseek, kimi, kimi_cn, openrouter, gemini, xai)
    for name in (profile.name, *profile.aliases)
}
_PROFILES.update(load_profiles())
_REASONING_PREFIXES = (
    "deepseek/",
    "anthropic/",
    "openai/",
    "x-ai/",
    "google/gemini-2",
    "google/gemma-4",
    "qwen/qwen3",
    "tencent/hy",
    "xiaomi/",
)
_KNOWN_PROFILES = {
    name
    for profile in json.loads(
        (Path(__file__).parent / "upstream_chat/provider_profiles.json").read_text()
    )["profiles"]
    for name in (profile["name"], *profile["aliases"])
}


def provider_profile(provider):
    return _PROFILES.get(str(provider or "").strip().lower())


def validate_chat_route(route):
    provider = str(route.get("provider") or "").strip().lower()
    if provider in _KNOWN_PROFILES and provider not in _PROFILES:
        raise ValueError(
            f"Hermes provider profile {provider!r} is not implemented in this Snapshot"
        )


def chat_headers(route):
    profile = _PROFILES.get(str(route.get("provider") or "").strip().lower())
    headers = dict(profile.default_headers) if profile else {}
    headers.update(route.get("default_headers") or {})
    headers.update(route.get("extra_headers") or {})
    return headers


def _namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_namespace(item) for item in value]
    return value


def _plain(value):
    if isinstance(value, SimpleNamespace):
        return {key: _plain(item) for key, item in vars(value).items()}
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def prepare_chat(payload, route, settings):
    """Return original SDK kwargs plus request-local ``_wire_aliases``.

    The caller consumes timeout/extra_headers as HTTP options and flattens
    extra_body exactly once. Auxiliary calls opt out of main-loop defaults via
    ``_chat_auxiliary``. The payload is copied before provider conversion.
    """
    validate_chat_route(route)
    payload = copy.deepcopy(payload)
    explicit = {**settings, **route}
    token = request_settings.set(explicit)
    try:
        provider = str(route.get("provider") or "").strip().lower()
        profile = _PROFILES.get(provider)
        model = payload.get("model") or route.get("model_name") or ""
        base = route.get("base_url") or "https://api.openai.com/v1"
        messages = shape_wire_carriers(
            payload.pop("messages", []), model=model, base_url=base
        )
        tools = payload.pop("tools", None)
        payload.pop("model", None)
        effort = payload.pop("reasoning_effort", route.get("reasoning_effort"))
        reasoning = explicit.get("reasoning_config")
        if effort is not None:
            reasoning = parse_reasoning_effort(effort)
        elif reasoning is None and not explicit.get("_chat_auxiliary"):
            agent_settings = dict(settings.get("agent") or {})
            for name in ("reasoning_effort", "reasoning_overrides"):
                if name in settings:
                    agent_settings[name] = settings[name]
            reasoning = resolve_reasoning_config({"agent": agent_settings}, model)
        if reasoning is None and profile and not explicit.get("_chat_auxiliary"):
            if explicit.get("supports_reasoning") is not False:
                reasoning = profile.default_reasoning_config(model)
        recovery = explicit.get("_recovery_reasoning")
        if recovery is not None and not explicit.get("_chat_auxiliary"):
            reasoning = recovery.reasoning_for_wire(
                reasoning, ephemeral_off=effort in ("none", "off", False)
            )
        supports = explicit.get("supports_reasoning")
        if supports is None:
            supports = (
                base_url_host_matches(base, "nousresearch.com")
                or base_url_host_matches(base, "ai-gateway.vercel.sh")
                or (
                    base_url_host_matches(base, "openrouter.ai")
                    and model.lower().startswith(_REASONING_PREFIXES)
                )
            )
        if base_url_host_matches(base, "openrouter.ai"):
            caps = explicit.get("reasoning_capabilities")
            if isinstance(caps, dict) and model in caps:
                caps = caps[model]
            if isinstance(caps, dict) and "supports_reasoning" in caps:
                supports = bool(caps["supports_reasoning"])

        cap = payload.pop("max_completion_tokens", payload.pop("max_tokens", None))
        completion_cap = (
            base_url_hostname(base) == "api.openai.com"
            or base_url_host_matches(base, "openai.azure.com")
            or base_url_host_matches(base, "githubcopilot.com")
            or model_forces_max_completion_tokens(model)
        )
        params = {
            "base_url": base,
            "provider_name": provider,
            "provider_profile": profile,
            "max_tokens": cap,
            "max_tokens_param_fn": lambda value: {
                "max_completion_tokens" if completion_cap else "max_tokens": value
            },
            "reasoning_config": reasoning,
            "supports_reasoning": supports,
            "model_lower": model.lower(),
            "is_kimi": any(
                base_url_host_matches(base, host)
                for host in ("api.kimi.com", "moonshot.ai", "moonshot.cn")
            ),
            "is_tokenhub": base_url_host_matches(base, "tokenhub.tencentmaas.com"),
            "is_openrouter": base_url_host_matches(base, "openrouter.ai"),
            "is_github_models": any(
                base_url_host_matches(base, host)
                for host in ("models.github.ai", "githubcopilot.com")
            ),
        }
        for name in (
            "session_id",
            "cache_scope_id",
            "provider_preferences",
            "openrouter_min_coding_score",
            "ollama_num_ctx",
            "supports_prompt_cache_key",
            "lmstudio_reasoning_options",
            "qwen_session_metadata",
            "extra_body_additions",
            "github_reasoning_extra",
        ):
            if name in explicit:
                params[name] = explicit[name]
        resolved = resolve_request_settings(settings, route, model)
        params["provider_preferences"] = resolved["provider_preferences"]
        # Preserve explicitly configured sampling controls through the original
        # request_overrides entry point; main Hermes leaves temperature unset.
        overrides = {
            **payload,
            **resolved["request_overrides"],
        }
        params["request_overrides"] = overrides
        aliases = {}
        if tools and (
            provider in {"xai", "xai-oauth"} or base_url_hostname(base) == "api.x.ai"
        ):
            tools, aliases = _rename_tool_search_bridge_for_xai(tools)
        transport = ChatCompletionsTransport()
        transport._last_wire_aliases = aliases
        result = transport.build_kwargs(model, messages, tools, **params)
        result["_wire_aliases"] = aliases
        return result
    finally:
        request_settings.reset(token)


def ingest_chat(data, wire_aliases=None):
    """Normalize the actual transport response while retaining replay sidecars."""
    response = _namespace(data)
    transport = ChatCompletionsTransport()
    transport._last_wire_aliases = wire_aliases or {}
    if not transport.validate_response(response):
        raise ValueError(
            "Hermes provider returned an invalid response or router timeout shim"
        )
    normalized = transport.normalize_response(response)
    message = {"role": "assistant", "content": _plain(normalized.content)}
    if normalized.reasoning is not None:
        message["reasoning"] = _plain(normalized.reasoning)
    message.update(_plain(normalized.provider_data or {}))
    if normalized.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": _plain(call.arguments),
                    **(
                        {
                            "thought_signature": _plain(
                                call.provider_data["thought_signature"]
                            )
                        }
                        if (call.provider_data or {}).get("thought_signature")
                        is not None
                        else {}
                    ),
                },
                **{
                    key: _plain(value)
                    for key, value in (call.provider_data or {}).items()
                    if key != "thought_signature"
                },
            }
            for call in normalized.tool_calls
        ]
    result = {
        **data,
        "choices": [
            {
                **data["choices"][0],
                "message": message,
                "finish_reason": normalized.finish_reason,
            }
        ],
    }
    stats = transport.extract_cache_stats(response)
    if stats:
        usage = copy.deepcopy(data.get("usage") or {})
        details = usage.get("prompt_tokens_details")
        if not isinstance(details, dict):
            details = usage["prompt_tokens_details"] = {}
        details.update(
            cached_tokens=stats["cached_tokens"],
            cache_write_tokens=stats["creation_tokens"],
        )
        result["usage"] = usage
    return result
