"""Pi v1.4.0 canonical transcript conversion for Anthropic Messages.

Ports ``api/transform-messages.ts`` and ``api/anthropic-messages.ts`` at the
commit recorded in UPSTREAM.md: request construction, canonical replay and
completed responses. The caller owns HTTP transport, retries and cancellation.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable, Mapping

from .compaction import content_text, model_metadata
from .constrained_sampling import resolve_strict, strict_parameters
from .provider_options import anthropic_options
from .session import current_system_message

_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
_ERROR_IMAGE_NOTE = "(image attached after the tool results)"
_CC_NAMES = {
    name.lower(): name
    for name in (
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Grep",
        "Glob",
        "AskUserQuestion",
        "EnterPlanMode",
        "ExitPlanMode",
        "KillShell",
        "NotebookEdit",
        "Skill",
        "Task",
        "TaskOutput",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
    )
}


def _tool_name(name: str, oauth: bool) -> str:
    return _CC_NAMES.get(name.lower(), name) if oauth else name


def _text(value: str) -> str:
    # JavaScript's sanitizeSurrogates preserves pairs and removes lone units.
    return value.encode("utf-16-le", errors="surrogatepass").decode(
        "utf-16-le", errors="ignore"
    )


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content or [])


def _image(block: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": block["mimeType"],
            "data": block["data"],
        },
    }


def _content_blocks(blocks: list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    if not any(block.get("type") == "image" for block in blocks):
        return _text("\n".join(block.get("text", "") for block in blocks))
    converted = [
        _image(block)
        if block.get("type") == "image"
        else {"type": "text", "text": _text(block.get("text", ""))}
        for block in blocks
    ]
    if not any(block["type"] == "text" for block in converted):
        converted.insert(0, {"type": "text", "text": "(see attached image)"})
    return converted


def _transform(
    context: list[dict[str, Any]],
    provider: str,
    model: str,
    *,
    supports_images: bool = True,
) -> list[dict[str, Any]]:
    """Strip invalid replay metadata and complete interrupted tool turns."""
    transformed = []
    normalized_ids: dict[str, str] = {}
    for original in context:
        message = copy.deepcopy(original)
        role = message.get("role")
        if role not in {"user", "system"} or not isinstance(
            message.get("content"), str
        ):
            message["content"] = _blocks(message.get("content"))
        if (
            not supports_images
            and role in {"user", "toolResult"}
            and isinstance(message["content"], list)
        ):
            placeholder = (
                "(image omitted: model does not support images)"
                if role == "user"
                else "(tool image omitted: model does not support images)"
            )
            blocks = []
            previous = False
            for block in message["content"]:
                if block.get("type") == "image":
                    if not previous:
                        blocks.append({"type": "text", "text": placeholder})
                    previous = True
                else:
                    blocks.append(block)
                    previous = block.get("text") == placeholder
            message["content"] = blocks
        if role == "assistant":
            same_model = (
                message.get("provider") == provider
                and message.get("api") == "anthropic-messages"
                and message.get("model") == model
            )
            content = []
            for block in message["content"]:
                kind = block.get("type")
                if kind == "thinking":
                    # Signatures and readable thinking only replay on the model
                    # that produced them. Upstream drops cross-model thinking.
                    if not same_model:
                        continue
                    if not (
                        block.get("redacted")
                        or block.get("thinkingSignature")
                        or block.get("thinking", "").strip()
                    ):
                        continue
                elif kind == "text" and not same_model:
                    block = {"type": "text", "text": block.get("text", "")}
                elif kind == "toolCall" and not same_model:
                    block.pop("thoughtSignature", None)
                    original_id = block.get("id", "")
                    normalized_id = re.sub(r"[^a-zA-Z0-9_-]", "_", original_id)[:64]
                    if normalized_id != original_id:
                        normalized_ids[original_id] = normalized_id
                        block["id"] = normalized_id
                content.append(block)
            message["content"] = content
        elif role == "toolResult":
            call_id = message.get("toolCallId", "")
            message["toolCallId"] = normalized_ids.get(call_id, call_id)
        transformed.append(message)

    result = []
    pending: list[dict[str, Any]] = []
    answered: set[str] = set()
    held_systems = []

    def close_pending():
        for call in pending:
            if call["id"] not in answered:
                result.append(
                    {
                        "role": "toolResult",
                        "toolCallId": call["id"],
                        "toolName": call.get("name", ""),
                        "content": [{"type": "text", "text": "No result provided"}],
                        "isError": True,
                    }
                )
        pending.clear()
        answered.clear()
        result.extend(held_systems)
        held_systems.clear()

    for message in transformed:
        role = message.get("role")
        if role == "assistant":
            close_pending()
            if message.get("stopReason") in {"error", "aborted"}:
                continue
            pending.extend(
                block for block in message["content"] if block.get("type") == "toolCall"
            )
        elif role == "user":
            close_pending()
        elif role == "toolResult":
            answered.add(message.get("toolCallId", ""))
        elif role == "system" and pending:
            held_systems.append(message)
            continue
        result.append(message)
    close_pending()
    return result


def _anthropic_context_messages(
    context: list[dict[str, Any]],
    provider: str,
    model: str,
    *,
    managed_effort: str | None = None,
    allow_empty_signature: bool = False,
    supports_images: bool = True,
    native_system_messages: bool = False,
    convert_tools: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    cache_control: dict[str, Any] | None = None,
    oauth: bool = False,
) -> list[dict[str, Any]]:
    """Convert canonical Pi messages while retaining Anthropic replay metadata."""
    messages = _transform(context, provider, model, supports_images=supports_images)
    result: list[dict[str, Any]] = []
    pending_systems = []
    index = 0
    while index < len(messages):
        message = messages[index]
        role, content = message.get("role"), message["content"]
        index += 1
        if role == "system":
            if not native_system_messages:
                continue
            parts = [content_text(content)]
            for name, value in (message.get("sections") or {}).items():
                parts.append(
                    f'Removed system prompt section "{name}".'
                    if value is None
                    else f'Updated system prompt section "{name}":\n\n{value}'
                )
            text = "\n\n".join(part for part in parts if part)
            blocks = [{"type": "text", "text": _text(text)}] if text else []
            if convert_tools:
                added = message.get("toolsAdded") or []
                redefined = {tool["name"] for tool in added}
                blocks.extend(
                    {
                        "type": "tool_removal",
                        "tool": {
                            "type": "tool_reference",
                            "name": _tool_name(tool["name"], oauth),
                        },
                    }
                    for tool in message.get("toolsRemoved") or []
                    if tool["name"] not in redefined
                )
                blocks.extend(
                    {
                        "type": "tool_addition",
                        "tool": {"type": "tool_definition", "definition": definition},
                    }
                    for definition in convert_tools(added)
                )
            if blocks:
                pending_systems.append({"role": "system", "content": blocks})
        elif role == "user":
            if isinstance(content, str):
                if content.strip():
                    result.append({"role": "user", "content": _text(content)})
                continue
            blocks = [
                _image(block)
                if block.get("type") == "image"
                else {"type": "text", "text": _text(block.get("text", ""))}
                for block in content
                if block.get("type") == "image" or block.get("text", "").strip()
            ]
            if blocks:
                result.append({"role": "user", "content": blocks})
        elif role == "assistant":
            result.extend(pending_systems)
            pending_systems.clear()
            blocks = []
            for block in content:
                kind = block.get("type")
                if kind == "text" and block.get("text", "").strip():
                    blocks.append({"type": "text", "text": _text(block["text"])})
                elif kind == "thinking":
                    signature = block.get("thinkingSignature")
                    if block.get("redacted"):
                        blocks.append({"type": "redacted_thinking", "data": signature})
                        continue
                    thinking = block.get("thinking", "")
                    signed = isinstance(signature, str) and bool(signature.strip())
                    if not thinking.strip() and not signed:
                        continue
                    if signed or allow_empty_signature:
                        blocks.append(
                            {
                                "type": "thinking",
                                "thinking": _text(thinking),
                                "signature": signature if signed else "",
                            }
                        )
                    else:
                        blocks.append({"type": "text", "text": _text(thinking)})
                elif kind == "toolCall":
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": block["id"],
                            "name": _tool_name(block["name"], oauth),
                            "input": block["arguments"]
                            if block.get("arguments") is not None
                            else {},
                        }
                    )
            if not blocks:
                continue
            historical = message.get("providerThinkingLevel")
            if (
                managed_effort is not None
                and message.get("api") == "anthropic-messages"
                and message.get("provider") == provider
                and isinstance(historical, str)
                and historical in _EFFORTS
            ):
                result.append(
                    {
                        "role": "system",
                        "content": [],
                        "output_config": {"effort": historical},
                    }
                )
            result.append({"role": "assistant", "content": blocks})
        elif role == "toolResult":
            tool_results, error_images = [], []
            while True:
                blocks = message["content"]
                images = [block for block in blocks if block.get("type") == "image"]
                if message.get("isError") and images:
                    text_blocks = []
                    previous_note = False
                    for block in blocks:
                        if block.get("type") == "image":
                            if not previous_note:
                                text_blocks.append(
                                    {"type": "text", "text": _ERROR_IMAGE_NOTE}
                                )
                            previous_note = True
                        else:
                            text_blocks.append(block)
                            previous_note = block.get("text") == _ERROR_IMAGE_NOTE
                    blocks = text_blocks
                    error_images.append(
                        {
                            "type": "text",
                            "text": f"Images from the error result of tool call {message['toolCallId']} ({message.get('toolName', '')}):",
                        }
                    )
                    error_images.extend(_image(block) for block in images)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": message.get("toolCallId", ""),
                        "content": _content_blocks(blocks),
                        "is_error": message.get("isError", False),
                    }
                )
                if (
                    index >= len(messages)
                    or messages[index].get("role") != "toolResult"
                ):
                    break
                message = messages[index]
                index += 1
            result.append({"role": "user", "content": tool_results + error_images})
    result.extend(pending_systems)
    if cache_control and result and result[-1]["role"] in {"user", "system"}:
        last = result[-1]
        if isinstance(last["content"], str):
            last["content"] = [
                {
                    "type": "text",
                    "text": last["content"],
                    "cache_control": copy.deepcopy(cache_control),
                }
            ]
        elif last["content"] and last["content"][-1].get("type") in {
            "text",
            "image",
            "tool_result",
            "tool_addition",
            "tool_removal",
        }:
            last["content"][-1]["cache_control"] = copy.deepcopy(cache_control)
    if managed_effort is not None:
        result.append(
            {
                "role": "system",
                "content": [],
                "output_config": {"effort": managed_effort},
            }
        )
    return result


_STRICT_UNSUPPORTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "maxItems",
    "uniqueItems",
    "minContains",
    "maxContains",
    "minProperties",
    "maxProperties",
}
_STRICT_FORMATS = {
    "date-time",
    "time",
    "date",
    "duration",
    "email",
    "hostname",
    "uri",
    "ipv4",
    "ipv6",
    "uuid",
}


def _unsupported(key: str, value: Any) -> bool:
    return (
        key in _STRICT_UNSUPPORTED
        or key == "minItems"
        and (isinstance(value, bool) or value not in (0, 1))
        or key == "format"
        and (not isinstance(value, str) or value not in _STRICT_FORMATS)
    )


def build_anthropic_payload(
    config: Mapping[str, Any],
    context: list[dict[str, Any]],
    reasoning: str | None,
    *,
    tools_override: list[dict[str, Any]] | None = None,
    cache_retention: str | None = None,
    disable_preferred_strict: bool = False,
) -> tuple[dict[str, Any], list[str], str | None]:
    """Build the canonical Pi Anthropic request; transport/auth belong to the caller.

    ``tools_override`` is used only for untyped callers with no declarations in
    their transcript. Normal Snapshot calls persist declarations on system
    messages, so native tool changes and historical tool definitions survive.
    """
    metadata = model_metadata(config)
    llm = config.get("llm", {})
    configured = str(llm.get("model_name", "")).strip()
    if "/" in configured:
        provider, model = configured.split("/", 1)
    else:
        provider, model = str(llm.get("provider_name", "")), configured
    provider, model = provider.strip().lower(), model.strip()
    compat = metadata.get("compat") or {}
    oauth = "sk-ant-oat" in str(llm.get("api_key", ""))
    context = copy.deepcopy(context)
    if tools_override and not any(
        m.get("toolsAdded") for m in context if m.get("role") == "system"
    ):
        tools = [copy.deepcopy(tool.get("function", tool)) for tool in tools_override]
        if context and context[0].get("role") == "system":
            context[0]["toolsAdded"] = tools
        else:
            context.insert(
                0,
                {"role": "system", "content": "", "toolsAdded": tools, "timestamp": 0},
            )
    options, betas, managed = anthropic_options(config, context, reasoning)
    native_system = compat.get("supportsMidConvoSystemMessages") is True
    if not native_system:
        system = current_system_message(context)
        context = ([system] if system else []) + [
            m for m in context if m.get("role") != "system"
        ]
    initial = context[0] if context and context[0].get("role") == "system" else None
    initial_tools = (initial or {}).get("toolsAdded") or []
    native_tools = (
        native_system
        and compat.get("supportsMidConvoToolChanges") is True
        and bool(initial_tools)
    )
    retention = cache_retention or config.get(
        "cache_retention", llm.get("cache_retention", "short")
    )
    cache = (
        None
        if retention == "none"
        else {
            "type": "ephemeral",
            **(
                {"ttl": "1h"}
                if retention == "long"
                and compat.get("supportsLongCacheRetention", True)
                else {}
            ),
        }
    )

    def convert(definitions, tool_cache=None):
        converted = []
        for index, tool in enumerate(definitions):
            setting = tool.get("constrainedSampling") or {}
            strict = (
                None
                if disable_preferred_strict
                and setting.get("type") == "json_schema"
                and setting.get("strict") == "prefer"
                else resolve_strict(
                    tool, compat.get("supportsStrictTools", False), _unsupported
                )
            )
            parameters = strict_parameters(tool, strict)
            schema = {
                "type": "object",
                "properties": parameters.get("properties", {}),
                "required": parameters.get("required", []),
            }
            if strict:
                schema = {**parameters, **schema}
            converted.append(
                {
                    "name": _tool_name(tool["name"], oauth),
                    "description": tool.get("description", ""),
                    **(
                        {"eager_input_streaming": True}
                        if compat.get("supportsEagerToolInputStreaming", True)
                        else {}
                    ),
                    **({"strict": True} if strict else {}),
                    "input_schema": schema,
                    **(
                        {"cache_control": copy.deepcopy(tool_cache)}
                        if tool_cache and index == len(definitions) - 1
                        else {}
                    ),
                }
            )
        return converted

    conversation = context[1:] if initial else context
    payload = {
        "model": model,
        **options,
        "messages": _anthropic_context_messages(
            conversation,
            provider,
            model,
            managed_effort=managed,
            allow_empty_signature=compat.get("allowEmptySignature", False),
            supports_images="image" in metadata.get("input", ["text", "image"]),
            native_system_messages=native_system,
            convert_tools=convert if native_tools else None,
            cache_control=cache,
            oauth=oauth,
        ),
    }
    system_text = (
        "\n\n".join(
            part
            for part in [
                content_text(initial.get("content", "")),
                *(initial.get("sections") or {}).values(),
            ]
            if part
        )
        if initial
        else ""
    )
    system_blocks = []
    if oauth:
        system_blocks.append(
            {
                "type": "text",
                "text": "You are Claude Code, Anthropic's official CLI for Claude.",
                **({"cache_control": copy.deepcopy(cache)} if cache else {}),
            }
        )
    if system_text:
        system_blocks.append(
            {
                "type": "text",
                "text": _text(system_text),
                **({"cache_control": copy.deepcopy(cache)} if cache else {}),
            }
        )
    if system_blocks:
        payload["system"] = system_blocks
    current_tools = (current_system_message(context) or {}).get("toolsAdded", [])
    tool_cache = cache if compat.get("supportsCacheControlOnTools", True) else None
    if native_tools:
        payload["tools"] = convert(initial_tools, tool_cache) + [
            {
                "name": "__pi_deferred_placeholder__",
                "description": "Reserved placeholder. Never available. Never call this.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
                "defer_loading": True,
            }
        ]
    elif current_tools:
        payload["tools"] = convert(current_tools, tool_cache)
    if oauth:
        betas = ["claude-code-20250219", "oauth-2025-04-20", *betas]
    if current_tools and not compat.get("supportsEagerToolInputStreaming", True):
        betas.insert(2 if oauth else 0, "fine-grained-tool-streaming-2025-05-14")
    if native_tools:
        betas.append("inline-tools-2026-09-15")
    for headers in (
        metadata.get("headers") or {},
        llm.get("headers", config.get("headers", {})) or {},
    ):
        for key, value in headers.items():
            if key.lower() == "anthropic-beta":
                betas = (
                    []
                    if value is None
                    else list(
                        dict.fromkeys(
                            feature.strip()
                            for feature in value.split(",")
                            if feature.strip()
                        )
                    )
                )
    tool_choice = config.get("tool_choice", llm.get("tool_choice"))
    if tool_choice:
        payload["tool_choice"] = (
            {"type": tool_choice}
            if isinstance(tool_choice, str)
            else copy.deepcopy(tool_choice)
        )
    return payload, list(dict.fromkeys(betas)), managed


def anthropic_response(
    config: Mapping[str, Any],
    data: Mapping[str, Any],
    *,
    context: list[dict[str, Any]] | None = None,
    managed_effort: str | None = None,
) -> dict[str, Any]:
    """Convert a completed JSON response using Pi's canonical provider semantics.

    Streaming transport may pass its accumulated final message in the same
    shape. Refusals and unknown stop reasons are errors, even with partial text.
    """
    configured = str(config.get("llm", {}).get("model_name", "")).strip()
    provider, model = (
        configured.split("/", 1)
        if "/" in configured
        else (str(config.get("llm", {}).get("provider_name", "")), configured)
    )
    provider, model = provider.strip().lower(), model.strip()
    result: dict[str, Any] = {
        "role": "assistant",
        "api": "anthropic-messages",
        "provider": provider,
        "model": model,
        "content": [],
    }
    if data.get("id"):
        result["responseId"] = data["id"]
    response_model = data.get("model", model)
    if response_model != model:
        result["responseModel"] = response_model
    if managed_effort:
        result["providerThinkingLevel"] = managed_effort
    current_tools = (current_system_message(context or []) or {}).get("toolsAdded", [])
    oauth = "sk-ant-oat" in str(config.get("llm", {}).get("api_key", ""))
    for block in data.get("content") or []:
        kind = block.get("type")
        if kind == "text":
            result["content"].append({"type": "text", "text": block.get("text", "")})
        elif kind == "thinking":
            result["content"].append(
                {
                    "type": "thinking",
                    "thinking": block.get("thinking", ""),
                    "thinkingSignature": block.get("signature", ""),
                }
            )
        elif kind == "redacted_thinking":
            result["content"].append(
                {
                    "type": "thinking",
                    "thinking": "[Reasoning redacted]",
                    "thinkingSignature": block.get("data"),
                    "redacted": True,
                }
            )
        elif kind == "tool_use":
            name = block.get("name", "")
            if oauth:
                name = next(
                    (
                        tool["name"]
                        for tool in current_tools
                        if tool["name"].lower() == name.lower()
                    ),
                    name,
                )
            result["content"].append(
                {
                    "type": "toolCall",
                    "id": block.get("id", ""),
                    "name": name,
                    "arguments": block.get("input") or {},
                }
            )
    reason = data.get("stop_reason")
    result["rawStopReason"] = reason
    if reason in {"end_turn", "pause_turn", "stop_sequence"}:
        result["stopReason"] = "stop"
    elif reason == "max_tokens":
        result["stopReason"] = "length"
    elif reason == "tool_use":
        result["stopReason"] = "toolUse"
    else:
        result["stopReason"] = "error"
        result["errorMessage"] = (
            (data.get("stop_details") or {}).get("explanation")
            or "The model refused to complete the request"
            if reason == "refusal"
            else "Provider stopped with: sensitive"
            if reason == "sensitive"
            else "Anthropic stream ended without a stop reason"
            if reason is None
            else f"Unhandled stop reason: {reason}"
        )
    result["usage"] = normalize_anthropic_usage(
        data.get("usage") or {}, config, response_model=response_model
    )
    # An unknown stop label throws before the final usage delta is consumed.
    if reason not in {
        None,
        "end_turn",
        "pause_turn",
        "stop_sequence",
        "max_tokens",
        "tool_use",
        "refusal",
        "sensitive",
    }:
        result["usage"].pop("reasoning", None)
    return result


def normalize_anthropic_usage(
    raw: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    response_model: str | None = None,
) -> dict[str, Any]:
    """Pi token counters and model/fallback cost rates for an Anthropic reply."""
    metadata = model_metadata(config)
    provider = metadata.get("provider", "")
    model = metadata.get("id")
    usage = {
        name: raw.get(key) or 0
        for name, key in (
            ("input", "input_tokens"),
            ("output", "output_tokens"),
            ("cacheRead", "cache_read_input_tokens"),
            ("cacheWrite", "cache_creation_input_tokens"),
        )
    }
    usage["cacheWrite1h"] = (raw.get("cache_creation") or {}).get(
        "ephemeral_1h_input_tokens"
    ) or 0
    reasoning = (raw.get("output_tokens_details") or {}).get("thinking_tokens")
    if reasoning is not None:
        usage["reasoning"] = reasoning
    usage["totalTokens"] = sum(
        usage[key] for key in ("input", "output", "cacheRead", "cacheWrite")
    )
    rates = metadata.get("cost") or {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
    }
    if response_model != model:
        rates = next(
            (
                fallback["cost"]
                for fallback in (metadata.get("compat") or {}).get(
                    "allowedFallbackModels", []
                )
                if fallback.get("provider") == provider
                and fallback.get("model") == response_model
            ),
            rates,
        )
    matched = -1
    for tier in rates.get("tiers", []):
        threshold = tier["inputTokensAbove"]
        if (
            usage["input"] + usage["cacheRead"] + usage["cacheWrite"]
            > threshold
            > matched
        ):
            matched, selected = threshold, tier
    if matched >= 0:
        rates = selected
    cost = {
        key: rates.get(key, 0) / 1000000 * usage[key]
        for key in ("input", "output", "cacheRead")
    }
    cost["cacheWrite"] = (
        rates.get("cacheWrite", 0) * (usage["cacheWrite"] - usage["cacheWrite1h"])
        + rates.get("input", 0) * 2 * usage["cacheWrite1h"]
    ) / 1000000
    cost["total"] = (
        cost["input"] + cost["output"] + cost["cacheRead"] + cost["cacheWrite"]
    )
    usage["cost"] = cost
    return usage
