"""Pure ports of Pi v1.4.0 OpenAI compatibility and cache options.

Callers supply the already clamped thinking level and response token ceiling.
Sampling parameters apply after these options, just as in the source provider.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

_MISSING = object()
_THINKING_BUDGETS = {"minimal": 1024, "low": 2048, "medium": 8192, "high": 16384}


def thinking_budget_for_level(
    level: str, budgets: Mapping[str, int] | None = None
) -> int:
    resolved = {**_THINKING_BUDGETS, **(budgets or {})}
    return resolved["high" if level in {"xhigh", "max"} else level]


def adjust_max_tokens_for_thinking(
    base_max_tokens: int | None,
    model_max_tokens: int,
    level: str,
    budgets: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Port the shared nonadaptive-thinking ceiling and budget calculation."""
    budget = thinking_budget_for_level(level, budgets)
    maximum = (
        model_max_tokens
        if base_max_tokens is None
        else min(base_max_tokens + budget, model_max_tokens)
    )
    if maximum <= budget:
        budget = min(budget, max(0, maximum - 1024))
    return {"maxTokens": maximum, "thinkingBudget": budget}


def _thinking_budget(model, level, max_tokens, thinking_budgets):
    if not level or not model.get("reasoning"):
        return None
    budget = thinking_budget_for_level(level, thinking_budgets)
    ceiling = model["maxTokens"] if max_tokens is None else max_tokens
    budget = min(budget, max(0, ceiling - 1024))
    return budget if budget > 0 else None


def _template_values(model, level, values, budget):
    result = {}
    mapping = model.get("thinkingLevelMap") or {}
    for key, value in (values or {}).items():
        if isinstance(value, dict):
            if not level and value.get("omitWhenOff"):
                continue
            variable = value.get("$var")
            if variable == "thinking.enabled":
                value = bool(level)
            elif variable == "thinking.budget":
                if budget is None:
                    continue
                value = budget
            else:
                mapped = mapping.get(level or "off", _MISSING)
                if mapped is _MISSING:
                    if level is None:
                        continue
                    value = level
                elif isinstance(mapped, str):
                    value = mapped
                else:
                    continue
        result[key] = copy.deepcopy(value)
    return result


def completion_options(
    model: Mapping[str, Any],
    compat: Mapping[str, Any],
    level: str | None,
    max_tokens: int | None,
    thinking_budgets: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Return the completions thinking, budget, priority, and routing fields.

    ``max_tokens`` is the ceiling after Pi's context estimate has been applied,
    before sampling parameters override named fields. ``level`` uses None for
    off and is already clamped against the model's supported thinking levels.
    """
    result: dict[str, Any] = {}
    budget = _thinking_budget(model, level, max_tokens, thinking_budgets)
    mapping = model.get("thinkingLevelMap") or {}
    mapped = mapping.get(level or "off", _MISSING)
    value = level if mapped is _MISSING else mapped
    nullish_value = level if mapped is _MISSING or mapped is None else mapped
    supports_effort = compat.get("supportsReasoningEffort")
    if model.get("reasoning"):
        form = compat.get("thinkingFormat")
        if form == "zai":
            result["thinking"] = (
                {"type": "enabled", "clear_thinking": False}
                if level
                else {"type": "disabled"}
            )
            if level and supports_effort and isinstance(value, str):
                result["reasoning_effort"] = value
        elif form == "qwen":
            result["enable_thinking"] = bool(level)
            if level and supports_effort and isinstance(nullish_value, str):
                result["reasoning_effort"] = nullish_value
        elif form == "qwen-chat-template":
            result["chat_template_kwargs"] = {
                "enable_thinking": bool(level),
                "preserve_thinking": True,
            }
        elif form in {"chat-template", "baseten"}:
            field = (
                "chat_template_kwargs"
                if form == "chat-template"
                else "chat_template_args"
            )
            descriptors = compat.get(
                "chatTemplateKwargs" if form == "chat-template" else "chatTemplateArgs"
            )
            values = _template_values(model, level, descriptors, budget)
            if values:
                result[field] = values
            if form == "baseten" and supports_effort and isinstance(value, str):
                result["reasoning_effort"] = value
        elif form == "deepseek":
            if level:
                result["thinking"] = {"type": "enabled"}
            elif mapping.get("off", _MISSING) is not None:
                result["thinking"] = {"type": "disabled"}
            if level and supports_effort:
                result["reasoning_effort"] = nullish_value
        elif form == "openrouter":
            if level:
                result["reasoning"] = {"effort": nullish_value}
            elif mapping.get("off", _MISSING) is not None:
                result["reasoning"] = {"effort": mapping.get("off", "none")}
        elif form == "ant-ling" and level:
            if isinstance(mapped, str):
                result["reasoning"] = {"effort": mapped}
        elif form == "together":
            result["reasoning"] = {"enabled": bool(level)}
            if level and supports_effort:
                result["reasoning_effort"] = nullish_value
        elif form == "string-thinking":
            if level:
                result["thinking"] = nullish_value
            elif mapping.get("off", _MISSING) is not None:
                result["thinking"] = mapping.get("off", "none")
        elif level and supports_effort:
            result["reasoning_effort"] = nullish_value
        elif not level and supports_effort and isinstance(mapped, str):
            result["reasoning_effort"] = mapped
    field = compat.get("thinkingTokenBudgetField") or (
        "thinking_token_budget" if compat.get("supportsThinkingTokenBudget") else None
    )
    if field and budget is not None:
        result[field] = budget
    explicit = model.get("compat") or {}
    if explicit.get("openRouterRouting") is not None:
        result["provider"] = copy.deepcopy(explicit["openRouterRouting"])
    routing = explicit.get("vercelGatewayRouting")
    if routing is not None:
        gateway = {
            key: copy.deepcopy(routing[key])
            for key in ("only", "order")
            if routing.get(key) is not None
        }
        if gateway:
            result["providerOptions"] = {"gateway": gateway}
    if compat.get("vllmPriority") is not None:
        result["priority"] = compat["vllmPriority"]
    return result


def is_chatgpt_sign_in(model: Mapping[str, Any], api_key: str | None) -> bool:
    return (
        model.get("provider") == "openai"
        and model.get("baseUrl") == "https://api.openai.com/v1"
        and api_key is not None
        and not api_key.startswith("sk-")
    )


def _cache_key(session_id: str) -> str:
    # Array.from in the source counts Unicode code points, joining valid UTF-16
    # surrogate pairs while preserving isolated surrogates.
    return session_id.encode("utf-16-le", "surrogatepass").decode(
        "utf-16-le", "surrogatepass"
    )[:64]


def prompt_cache_options(
    model: Mapping[str, Any],
    compat: Mapping[str, Any],
    api: str,
    retention: str,
    session_id: str | None,
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Return request-body cache fields, including the bounded session key."""
    result: dict[str, Any] = {}
    long = retention == "long" and compat.get("supportsLongCacheRetention")
    if api == "openai-completions":
        if session_id is not None and (
            ("api.openai.com" in model["baseUrl"] and retention != "none") or long
        ):
            result["prompt_cache_key"] = _cache_key(session_id)
        if long:
            result["prompt_cache_retention"] = "24h"
    else:
        if session_id is not None and retention != "none":
            result["prompt_cache_key"] = _cache_key(session_id)
        if is_chatgpt_sign_in(model, api_key):
            return result
        if compat.get("supportsExplicitPromptCacheMode"):
            if retention == "none":
                result["prompt_cache_options"] = {"mode": "explicit"}
            elif long:
                result["prompt_cache_options"] = {"ttl": "30m"}
        elif long:
            result["prompt_cache_retention"] = "24h"
    return result


def session_headers(
    compat: Mapping[str, Any], api: str, session_id: str | None
) -> dict[str, str]:
    """Return affinity headers; caller suppresses session_id for retention none.

    Merge these after model headers and before explicit request headers.
    """
    if not session_id or (
        api == "openai-completions" and not compat.get("sendSessionAffinityHeaders")
    ):
        return {}
    if compat.get("sessionAffinityFormat") == "openrouter":
        return {"x-session-id": session_id}
    result = {"x-client-request-id": session_id}
    if compat.get("sessionAffinityFormat") == "openai":
        result["session_id"] = session_id
    if api == "openai-completions":
        result["x-session-affinity"] = session_id
    return result


def apply_service_tier_pricing(
    usage: dict[str, Any], model_id: str, tier: str | None
) -> dict[str, Any]:
    """Adjust already calculated Responses costs for the returned service tier."""
    multiplier = (
        0.5
        if tier == "flex"
        else (
            (2.5 if model_id == "gpt-5.5" else 2) if tier in {"priority", "fast"} else 1
        )
    )
    if multiplier != 1:
        for key in ("input", "output", "cacheRead", "cacheWrite"):
            usage["cost"][key] *= multiplier
        cost = usage["cost"]
        cost["total"] = (
            cost["input"] + cost["output"] + cost["cacheRead"] + cost["cacheWrite"]
        )
    return usage


def apply_compat_cache_control(
    payload: dict[str, Any], compat: Mapping[str, Any], retention: str
) -> None:
    """Mutate completion text parts and the last tool using Anthropic caching."""
    if compat.get("cacheControlFormat") != "anthropic" or retention == "none":
        return
    control = {"type": "ephemeral"}
    if retention == "long" and compat.get("supportsLongCacheRetention"):
        control["ttl"] = "1h"

    def annotate(message):
        content = message.get("content")
        if isinstance(content, str) and content:
            message["content"] = [
                {"type": "text", "text": content, "cache_control": dict(control)}
            ]
            return True
        if isinstance(content, list):
            for part in reversed(content):
                if isinstance(part, dict) and part.get("type") == "text":
                    part["cache_control"] = dict(control)
                    return True
        return False

    messages = payload.get("messages") or []
    for message in messages:
        if message.get("role") in {"system", "developer"}:
            annotate(message)
            break
    tools = payload.get("tools") or []
    if tools:
        tools[-1]["cache_control"] = dict(control)
    for message in reversed(messages):
        if message.get("role") in {"user", "assistant", "tool"} and annotate(message):
            break
