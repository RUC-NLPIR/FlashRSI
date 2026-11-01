"""Pi provider token estimates and Anthropic thinking options, ported from v1.4.0.

Provider estimates intentionally differ from coding-agent compaction estimates:
the original provider code uses 3.5 characters per token and a 4096-token margin.
"""

from __future__ import annotations

from typing import Any, Mapping

from .compaction import (
    calculate_context_tokens,
    content_text,
    js_json,
    js_length,
    model_limits,
    model_metadata,
)
from .openai_options import adjust_max_tokens_for_thinking


def _text_tokens(text: str) -> int:
    return (js_length(text) * 2 + 6) // 7


def estimate_message_tokens(message: Mapping[str, Any]) -> int:
    role, content = message.get("role"), message.get("content") or []
    if role == "system":
        parts = [content_text(content)] + [
            value for value in (message.get("sections") or {}).values() if value
        ]
        return _text_tokens("\n\n".join(value for value in parts if value)) + sum(
            _text_tokens(js_json(message[key])) if message.get(key) else 0
            for key in ("toolsAdded", "toolsRemoved")
        )
    if isinstance(content, str):
        return _text_tokens(content)
    chars = 0
    for block in content:
        if block.get("type") == "text":
            chars += js_length(block.get("text", ""))
        elif role in {"user", "toolResult"}:
            chars += 4800
        elif block.get("type") == "thinking":
            chars += js_length(block.get("thinking", ""))
        else:
            chars += js_length(block.get("name", "")) + js_length(
                js_json(block.get("arguments", {}))
            )
    return (chars * 2 + 6) // 7


def estimate_context_tokens(messages: list[dict[str, Any]]) -> dict[str, Any]:
    latest_timestamp = float("-inf")
    latest_usage = None
    for index, message in enumerate(messages):
        usage = message.get("usage") or {}
        timestamp = message.get("timestamp", 0)
        if (
            message.get("role") == "assistant"
            and timestamp >= latest_timestamp
            and message.get("stopReason") not in {"error", "aborted"}
            and calculate_context_tokens(usage) > 0
        ):
            latest_usage = (index, calculate_context_tokens(usage))
        latest_timestamp = max(latest_timestamp, timestamp)
    index, usage_tokens = latest_usage if latest_usage else (None, 0)
    trailing = sum(
        estimate_message_tokens(message)
        for message in messages[index + 1 if index is not None else 0 :]
    )
    return {
        "tokens": usage_tokens + trailing,
        "usageTokens": usage_tokens,
        "trailingTokens": trailing,
        "lastUsageIndex": index,
    }


def clamp_max_tokens(
    context_window: int, messages: list[dict[str, Any]], max_tokens: int
) -> int:
    if context_window <= 0:
        return max(1, max_tokens)
    available = context_window - estimate_context_tokens(messages)["tokens"] - 4096
    return min(max_tokens, max(1, available))


def anthropic_options(
    config: Mapping[str, Any],
    messages: list[dict[str, Any]],
    reasoning: str | None,
) -> tuple[dict[str, Any], list[str], str | None]:
    """Return shared simple-provider options, beta features and managed effort.

    The same builder handles normal turns and one-off summaries. The caller
    supplies the canonical transcript so provider usage and tool definitions
    participate in the original provider's remaining-context calculation.
    """
    metadata = model_metadata(config)
    compat = metadata.get("compat") or {}
    level_map = metadata.get("thinkingLevelMap") or {}
    context_window, model_max_tokens = model_limits(config)
    llm = config.get("llm", {})
    requested = config.get("max_tokens", llm.get("max_tokens", model_max_tokens))
    if requested is None:
        requested = model_max_tokens
    cap = clamp_max_tokens(context_window, messages, int(requested))
    reasoning = reasoning if metadata.get("reasoning") else None
    if reasoning and reasoning not in {
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        raise ValueError(
            "Pi thinking must be off, minimal, low, medium, high, xhigh or max"
        )
    adaptive = compat.get("forceAdaptiveThinking") is True
    disabled = (
        metadata.get("reasoning")
        and not reasoning
        and level_map.get("off", "off") is not None
    )
    managed = compat.get("supportsMidConvoEffort") is True and not disabled
    effort = None
    if reasoning and adaptive:
        effort = level_map.get(reasoning)
        if not isinstance(effort, str):
            effort = {"minimal": "low", "low": "low", "medium": "medium"}.get(
                reasoning, "high"
            )
    budget = None
    if reasoning and not adaptive:
        adjusted = adjust_max_tokens_for_thinking(
            cap,
            model_max_tokens,
            reasoning,
            config.get(
                "thinking_budgets",
                config.get("thinkingBudgets", llm.get("thinking_budgets")),
            ),
        )
        cap, budget = adjusted["maxTokens"], adjusted["thinkingBudget"]
        cap = clamp_max_tokens(context_window, messages, cap)
        budget = min(budget, max(0, cap - 1024))
    result: dict[str, Any] = {"max_tokens": cap}
    if compat.get("allowedFallbackModels"):
        result["fallbacks"] = [
            {"model": fallback["model"]} for fallback in compat["allowedFallbackModels"]
        ]
    if disabled:
        result["thinking"] = {"type": "disabled"}
    elif managed:
        result["thinking"] = {
            "type": "adaptive",
            "display": "summarized",
            "block_binding": {"prefix_mismatch_behavior": "drop_block"},
        }
        result["output_config"] = {"effort": "high"}
    elif reasoning:
        result["thinking"] = (
            {"type": "adaptive", "display": "summarized"}
            if adaptive
            else {
                "type": "enabled",
                "display": "summarized",
                "budget_tokens": budget or 1024,
            }
        )
        if effort:
            result["output_config"] = {"effort": effort}
    temperature = config.get("temperature", llm.get("temperature"))
    if (
        temperature is not None
        and not reasoning
        and not compat.get("supportsMidConvoEffort")
        and compat.get("supportsTemperature", True)
    ):
        result["temperature"] = temperature
    betas = []
    if reasoning and not adaptive:
        betas.append("interleaved-thinking-2025-05-14")
    if compat.get("allowedFallbackModels"):
        betas.append("server-side-fallback-2026-07-01")
    if compat.get("supportsMidConvoEffort"):
        betas += [
            "mid-conversation-output-config-2026-07-01",
            "thinking-binding-controls-2026-08-01",
        ]
    return result, betas, (effort or "high") if managed else None
