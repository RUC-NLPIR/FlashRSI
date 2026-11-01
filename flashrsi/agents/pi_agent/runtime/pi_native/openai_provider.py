"""Source ports of Pi's OpenAI request shaping and canonical replay.

Transport uses complete JSON responses; the persisted message representation
retains the same reasoning and item identifiers required by the next request.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Mapping

from .compaction import content_text, js_json, model_limits, model_metadata
from .openai_options import (
    apply_compat_cache_control,
    apply_service_tier_pricing,
    completion_options,
    is_chatgpt_sign_in,
    prompt_cache_options,
    session_headers,
)
from .openai_tools import (
    convert_tools,
    declared_tools,
    grammar_input,
    grammar_properties,
    resolve_tools,
    tool_support,
)
from .provider_options import clamp_max_tokens
from .session import current_system_message, system_message_text


def parse_arguments(value: str | None) -> tuple[dict[str, Any], str | None]:
    if not value or not value.strip():
        return {}, None
    try:
        parsed = json.loads(value)
    except ValueError:
        repaired, inside, index = "", False, 0
        while index < len(value):
            char = value[index]
            if not inside:
                repaired += char
                if char == '"':
                    inside = True
            elif char == '"':
                repaired += char
                inside = False
            elif char == "\\":
                following = value[index + 1 : index + 2]
                if following and following in '"\\/bfnrt':
                    repaired += char + following
                    index += 1
                elif following == "u" and re.fullmatch(
                    r"[0-9a-fA-F]{4}", value[index + 2 : index + 6] or ""
                ):
                    repaired += value[index : index + 6]
                    index += 5
                else:
                    repaired += "\\\\"
            else:
                repaired += json.dumps(char)[1:-1] if ord(char) < 32 else char
            index += 1
        try:
            parsed = json.loads(repaired)
        except ValueError as exc:
            return {}, f"{exc}\n\nReceived arguments:\n{value}"
    if not isinstance(parsed, dict):
        return (
            {},
            f"Tool arguments must be a JSON object\n\nReceived arguments:\n{value}",
        )
    return parsed, None


def calculate_cost(config, usage):
    rates = model_metadata(config).get("cost") or {}
    tokens = usage["input"] + usage["cacheRead"] + usage["cacheWrite"]
    threshold = -1
    for tier in rates.get("tiers", []):
        if tokens > tier["inputTokensAbove"] > threshold:
            threshold, rates = tier["inputTokensAbove"], tier
    cost = {
        key: rates.get(key, 0) * usage[key] / 1000000
        for key in ("input", "output", "cacheRead", "cacheWrite")
    }
    cost["total"] = (
        cost["input"] + cost["output"] + cost["cacheRead"] + cost["cacheWrite"]
    )
    usage["cost"] = cost
    return usage


def normalize_usage(config, raw, api):
    # Framework/offline callers can already supply canonical Pi usage.
    if "input" in raw or "output" in raw:
        return dict(raw)
    details = (
        raw.get(
            "prompt_tokens_details"
            if api == "openai-completions"
            else "input_tokens_details"
        )
        or {}
    )
    cache_read = (
        details.get(
            "cached_tokens",
            raw.get("prompt_cache_hit_tokens", raw.get("cached_tokens", 0)),
        )
        or 0
    )
    cache_write = details.get("cache_write_tokens", 0) or 0
    output_details = (
        raw.get(
            "completion_tokens_details"
            if api == "openai-completions"
            else "output_tokens_details"
        )
        or {}
    )
    output = (
        raw.get(
            "completion_tokens" if api == "openai-completions" else "output_tokens", 0
        )
        or 0
    )
    input_tokens = (
        raw.get("prompt_tokens" if api == "openai-completions" else "input_tokens", 0)
        or 0
    )
    usage = {
        "input": max(0, input_tokens - cache_read - cache_write),
        "output": output,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "reasoning": output_details.get("reasoning_tokens", 0) or 0,
        "totalTokens": input_tokens + output
        if api == "openai-completions"
        else raw.get("total_tokens", 0) or 0,
    }
    return calculate_cost(config, usage)


def response_message(config, data, api, *, managed_effort=None, context=None):
    model = selected_model(config, api)
    grammar = grammar_properties(
        declared_tools(context or []), compat_options(model, api)
    )
    content = []
    result = {
        "role": "assistant",
        "api": api,
        "provider": model["provider"],
        "model": model["id"],
        "content": content,
        "usage": normalize_usage(config, data.get("usage") or {}, api),
    }
    if data.get("id"):
        result["responseId"] = data["id"]
    if api == "openai-completions":
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        signature = next(
            (
                field
                for field in ("reasoning_content", "reasoning", "reasoning_text")
                if message.get(field)
            ),
            None,
        )
        if signature:
            content.append(
                {
                    "type": "thinking",
                    "thinking": message[signature],
                    "thinkingSignature": "reasoning_content"
                    if model["provider"] == "opencode-go" and signature == "reasoning"
                    else signature,
                }
            )
        if message.get("reasoning_details"):
            if not content:
                content.append({"type": "thinking", "thinking": ""})
            content[0]["thinkingSignature"] = js_json(message["reasoning_details"])
        text = message.get("content")
        if text:
            content.append({"type": "text", "text": text})
        for call in message.get("tool_calls") or []:
            function = (
                call.get("custom" if call.get("type") == "custom" else "function") or {}
            )
            if call.get("type") == "custom":
                arguments = {
                    grammar.get(function.get("name"), "input"): function.get(
                        "input", ""
                    )
                }
                error = None
            else:
                arguments, error = parse_arguments(function.get("arguments"))
            content.append(
                {
                    "type": "toolCall",
                    "id": call.get("id", ""),
                    "name": function.get("name", ""),
                    "arguments": arguments,
                    **({"argumentsError": error} if error else {}),
                }
            )
        if data.get("model") and data["model"] != model["id"]:
            result["responseModel"] = data["model"]
        reason = choice.get("finish_reason")
        if reason:
            result["rawStopReason"] = reason
        result["stopReason"] = {
            None: "stop",
            "stop": "stop",
            "end": "stop",
            "length": "length",
            "function_call": "toolUse",
            "tool_calls": "toolUse",
        }.get(reason, "error")
        if not reason and compat_options(model, api).get("supportsFinishReason", True):
            result["stopReason"] = "error"
            result["errorMessage"] = "Stream ended without finish_reason"
        elif not reason:
            result["stopReason"] = (
                "toolUse"
                if any(block["type"] == "toolCall" for block in content)
                else "stop"
            )
        if result["stopReason"] == "error":
            result.setdefault("errorMessage", f"Provider finish_reason: {reason}")
    else:
        for item in data.get("output") or []:
            kind = item.get("type")
            if kind == "reasoning":
                content.append(
                    {
                        "type": "thinking",
                        "thinking": "\n\n".join(
                            part.get("text", "")
                            for part in (
                                item.get("summary") or item.get("content") or []
                            )
                        ),
                        "thinkingSignature": js_json(item),
                    }
                )
            elif kind == "message":
                signature = {"v": 1, "id": item.get("id", "")}
                if item.get("phase"):
                    signature["phase"] = item["phase"]
                text = "".join(
                    part.get("text", "")
                    if part.get("type") in {"output_text", "text"}
                    else part.get("refusal", "")
                    for part in item.get("content") or []
                )
                content.append(
                    {
                        "type": "text",
                        "text": text,
                        **(
                            {"textSignature": js_json(signature)}
                            if item.get("id")
                            else {}
                        ),
                    }
                )
            elif kind in {"function_call", "custom_tool_call"}:
                if kind == "custom_tool_call":
                    arguments = {
                        grammar.get(item.get("name"), "input"): item.get("input", "")
                    }
                    error = None
                else:
                    arguments, error = parse_arguments(item.get("arguments"))
                call_id = item.get("call_id", "") + (
                    "|" + item["id"] if item.get("id") else ""
                )
                content.append(
                    {
                        "type": "toolCall",
                        "id": call_id,
                        "name": item.get("name", ""),
                        "arguments": arguments,
                        **(
                            {"namespace": item["namespace"]}
                            if "namespace" in item
                            else {}
                        ),
                        **({"argumentsError": error} if error else {}),
                    }
                )
        status = data.get("status", "completed")
        reason = (data.get("incomplete_details") or {}).get("reason")
        result["rawStopReason"] = f"{status}.{reason}" if reason else status
        if status == "incomplete":
            result["stopReason"] = (
                "length" if reason == "max_output_tokens" else "error"
            )
            if result["stopReason"] == "error":
                result["errorMessage"] = (
                    f"Response incomplete: {reason}"
                    if reason
                    else "Response incomplete without a provider reason"
                )
        elif status in {"failed", "cancelled"}:
            result["stopReason"] = "error"
            if status == "failed":
                result["rawStopReason"] = "failed"
                result["usage"] = {
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "totalTokens": 0,
                    "cost": {
                        "input": 0,
                        "output": 0,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "total": 0,
                    },
                }
                error = data.get("error") or {}
                result["errorMessage"] = (
                    f"{error.get('code') or 'unknown'}: {error.get('message') or 'no message'}"
                    if error
                    else f"incomplete: {reason}"
                    if reason
                    else "Unknown error (no error details in response)"
                )
            else:
                result["errorMessage"] = "An unknown error occurred"
        elif status not in {None, "completed", "in_progress", "queued"}:
            result["stopReason"] = "error"
            result["errorMessage"] = f"Unhandled stop reason: {status}"
        else:
            result["stopReason"] = (
                "toolUse" if any(b["type"] == "toolCall" for b in content) else "stop"
            )
        if managed_effort:
            result["providerThinkingLevel"] = managed_effort
        if status != "failed":
            apply_service_tier_pricing(
                result["usage"], model["id"], data.get("service_tier")
            )
    return result


def sanitize(value: str) -> str:
    return value.encode("utf-16-le", errors="surrogatepass").decode(
        "utf-16-le", errors="ignore"
    )


def short_hash(value: str) -> str:
    h1, h2 = 0xDEADBEEF, 0x41C6CE57
    units = value.encode("utf-16-le", errors="surrogatepass")
    for index in range(0, len(units), 2):
        char = int.from_bytes(units[index : index + 2], "little")
        h1 = ((h1 ^ char) * 2654435761) & 0xFFFFFFFF
        h2 = ((h2 ^ char) * 1597334677) & 0xFFFFFFFF
    h1 = (
        ((h1 ^ (h1 >> 16)) * 2246822507) ^ ((h2 ^ (h2 >> 13)) * 3266489909)
    ) & 0xFFFFFFFF
    h2 = (
        ((h2 ^ (h2 >> 16)) * 2246822507) ^ ((h1 ^ (h1 >> 13)) * 3266489909)
    ) & 0xFFFFFFFF

    def base36(number):
        result = ""
        while number:
            number, rest = divmod(number, 36)
            result = "0123456789abcdefghijklmnopqrstuvwxyz"[rest] + result
        return result or "0"

    return base36(h2) + base36(h1)


def selected_model(config: Mapping[str, Any], api: str) -> dict[str, Any]:
    llm = config.get("llm", {})
    name = str(llm.get("model_name", "")).strip()
    provider, model = (
        name.split("/", 1) if "/" in name else (str(llm.get("provider_name", "")), name)
    )
    metadata = copy.deepcopy(model_metadata(config))
    return {
        "input": ["text", "image"],
        **metadata,
        "provider": provider.strip().lower(),
        "id": model.strip(),
        "api": api,
        "baseUrl": llm.get("base_url")
        or metadata.get("baseUrl")
        or "https://api.openai.com/v1",
    }


def compat_options(model: Mapping[str, Any], api: str) -> dict[str, Any]:
    provider, url, name = model["provider"], model["baseUrl"], model["id"]
    if api == "openai-responses":
        defaults = {
            "supportsDeveloperRole": True,
            "supportsMidConvoSystemMessages": False,
            "supportsLongCacheRetention": True,
            "supportsStrictMode": False,
            "supportsOpenAIGrammarTools": False,
            "supportsAdditionalTools": False,
            "supportsToolSearch": False,
            "supportsExplicitPromptCacheMode": False,
            "supportsMaxOutputTokens": True,
            "supportsMidConvoEffort": False,
            "sessionAffinityFormat": "openrouter"
            if provider == "openrouter" or "openrouter.ai" in url
            else "openai",
        }
    else:
        zai = provider in {"zai", "zai-coding-cn"} or any(
            s in url for s in ("api.z.ai", "open.bigmodel.cn")
        )
        together = provider == "together" or any(
            s in url for s in ("api.together.ai", "api.together.xyz")
        )
        moonshot = provider in {"moonshotai", "moonshotai-cn"} or "api.moonshot." in url
        router = provider == "openrouter" or "openrouter.ai" in url
        workers = provider == "cloudflare-workers-ai" or "api.cloudflare.com" in url
        gateway = (
            provider == "cloudflare-ai-gateway" or "gateway.ai.cloudflare.com" in url
        )
        nvidia = provider == "nvidia" or "integrate.api.nvidia.com" in url
        ant = provider == "ant-ling" or "api.ant-ling.com" in url
        cerebras = provider == "cerebras" or "cerebras.ai" in url
        deepseek = provider == "deepseek" or "deepseek.com" in url.lower()
        grok = provider == "xai" or "api.x.ai" in url
        nonstandard = (
            nvidia
            or cerebras
            or grok
            or together
            or "chutes.ai" in url
            or deepseek
            or zai
            or moonshot
            or provider == "opencode"
            or "opencode.ai" in url
            or workers
            or gateway
            or ant
        )
        legacy = (
            "chutes.ai" in url
            or deepseek
            or moonshot
            or gateway
            or together
            or nvidia
            or ant
            or zai
        )
        defaults = {
            "supportsStore": not nonstandard,
            "supportsDeveloperRole": (
                router and name.startswith(("anthropic/", "openai/"))
            )
            or (not nonstandard and not router),
            "supportsReasoningEffort": not (
                grok or zai or moonshot or together or gateway or nvidia or ant
            ),
            "maxTokensField": "max_tokens" if legacy else "max_completion_tokens",
            "thinkingFormat": "deepseek"
            if deepseek
            else "zai"
            if zai
            else "together"
            if together
            else "ant-ling"
            if ant
            else "openrouter"
            if router
            else "openai",
            "requiresToolResultName": False,
            "requiresAssistantAfterToolResult": False,
            "requiresThinkingAsText": False,
            "requiresReasoningContentOnAssistantMessages": deepseek,
            "supportsMidConvoSystemMessages": False,
            "supportsMidConvoToolAdditions": False,
            "supportsStrictMode": False,
            "supportsOpenAIGrammarTools": False,
            "sendSessionAffinityHeaders": router,
            "sessionAffinityFormat": "openrouter" if router else "openai",
            "supportsLongCacheRetention": not (
                together or workers or gateway or nvidia or ant
            ),
            "cacheControlFormat": "anthropic"
            if provider == "openrouter" and name.startswith("anthropic/")
            else None,
        }
    return {
        **defaults,
        **{
            key: value
            for key, value in (model.get("compat") or {}).items()
            if value is not None
        },
    }


def clamp_reasoning(model: Mapping[str, Any], reasoning: str | None) -> str | None:
    if not reasoning or not model.get("reasoning"):
        return None
    levels = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]
    mapping = model.get("thinkingLevelMap") or {}
    available = [
        level
        for level in levels
        if mapping.get(level, "unset") is not None
        and (level not in {"xhigh", "max"} or level in mapping)
    ]
    if reasoning in available:
        return None if reasoning == "off" else reasoning
    if reasoning not in levels:
        return None
    index = levels.index(reasoning)
    for level in levels[index:] + list(reversed(levels[:index])):
        if level in available:
            return None if level == "off" else level
    return None


def _render_system(message: Mapping[str, Any], initial: bool) -> str:
    if initial:
        return system_message_text(dict(message))
    parts = [content_text(message.get("content", []))]
    for name, value in (message.get("sections") or {}).items():
        parts.append(
            f'Removed system prompt section "{name}".'
            if value is None
            else f'Updated system prompt section "{name}":\n\n{value}'
        )
    return "\n\n".join(part for part in parts if part)


def canonical_messages(
    context: list[dict[str, Any]], model: Mapping[str, Any], *, mid_system=False
):
    context = copy.deepcopy(context)
    if not mid_system:
        system = current_system_message(context)
        context = ([system] if system else []) + [
            m for m in context if m.get("role") != "system"
        ]
    ids = {}
    for message in context:
        role = message.get("role")
        content = message.get("content") or []
        if (
            role in {"user", "toolResult"}
            and isinstance(content, list)
            and "image" not in model.get("input", [])
        ):
            placeholder = (
                "(image omitted: model does not support images)"
                if role == "user"
                else "(tool image omitted: model does not support images)"
            )
            replacement = []
            for block in content:
                if block.get("type") == "image":
                    if not replacement or replacement[-1].get("text") != placeholder:
                        replacement.append({"type": "text", "text": placeholder})
                else:
                    replacement.append(block)
            content = replacement
        if role == "assistant":
            same = all(
                message.get(k) == model[v]
                for k, v in (("api", "api"), ("provider", "provider"), ("model", "id"))
            )
            transformed = []
            for block in content:
                if block.get("type") == "thinking" and (
                    not same
                    or not (
                        block.get("thinkingSignature")
                        or block.get("redacted")
                        or block.get("thinking", "").strip()
                    )
                ):
                    continue
                if not same and block.get("type") == "text":
                    block = {"type": "text", "text": block.get("text", "")}
                if not same and block.get("type") == "toolCall":
                    block.pop("thoughtSignature", None)
                    original = block["id"]
                    if model["api"] == "openai-responses":
                        parts = original.split("|", 1)
                        normalized = re.sub(r"[^a-zA-Z0-9_-]", "_", parts[0])[
                            :64
                        ].rstrip("_")
                        if len(parts) > 1 and model["provider"] in {
                            "openai",
                            "openai-codex",
                            "opencode",
                        }:
                            foreign = (
                                message.get("provider") != model["provider"]
                                or message.get("api") != model["api"]
                            )
                            item_id = (
                                "fc_" + short_hash(parts[1])
                                if foreign
                                else re.sub(r"[^a-zA-Z0-9_-]", "_", parts[1])[
                                    :64
                                ].rstrip("_")
                            )
                            if not item_id.startswith("fc_"):
                                item_id = ("fc_" + item_id)[:64].rstrip("_")
                            normalized += "|" + item_id
                    else:
                        if "|" in original:
                            call_part, item_part = original.split("|", 1)
                            call_part = re.sub(r"[^a-zA-Z0-9_-]", "_", call_part)
                            item_part = re.sub(r"[^a-zA-Z0-9_-]", "_", item_part)
                            normalized = call_part + (
                                "_" + item_part if item_part else ""
                            )
                            if len(normalized) > 40:
                                hashed = short_hash(original)[:8]
                                normalized = (
                                    call_part[: max(1, 40 - len(hashed) - 1)]
                                    + "_"
                                    + hashed
                                )
                        else:
                            normalized = (
                                original[:40]
                                if model["provider"] == "openai"
                                else original
                            )
                    ids[original] = normalized
                    block["id"] = normalized
                transformed.append(block)
            content = transformed
        elif role == "toolResult":
            message["toolCallId"] = ids.get(
                message["toolCallId"], message["toolCallId"]
            )
        message["content"] = content
    result, pending, answered, held = [], [], set(), []

    def close():
        for call in pending:
            if call["id"] not in answered:
                result.append(
                    {
                        "role": "toolResult",
                        "toolCallId": call["id"],
                        "toolName": call["name"],
                        "content": [{"type": "text", "text": "No result provided"}],
                        "isError": True,
                        "timestamp": 0,
                    }
                )
        pending.clear()
        answered.clear()
        result.extend(held)
        held.clear()

    for message in context:
        role = message.get("role")
        if role == "assistant":
            close()
            if message.get("stopReason") in {"error", "aborted"}:
                continue
            pending.extend(b for b in message["content"] if b.get("type") == "toolCall")
        elif role == "user":
            close()
        elif role == "system" and pending:
            held.append(message)
            continue
        elif role == "toolResult":
            answered.add(message["toolCallId"])
        result.append(message)
    close()
    return result


def _tool_declarations(context):
    system = current_system_message(context)
    return (system or {}).get("toolsAdded", [])


def completion_messages(context, model, compat):
    messages = canonical_messages(
        context, model, mid_system=compat.get("supportsMidConvoSystemMessages", False)
    )
    _, folded = resolve_tools(messages, tool_support(compat, "openai-completions"))
    grammar = grammar_properties(declared_tools(context), compat)
    result, last_role, pending_images = [], None, []
    system_index = 0
    for index, message in enumerate(messages):
        role, content = message["role"], message["content"]
        if (
            compat.get("requiresAssistantAfterToolResult")
            and last_role == "toolResult"
            and role == "user"
        ):
            result.append(
                {"role": "assistant", "content": "I have processed the tool results."}
            )
        if role == "system":
            if system_index >= folded and message.get("toolsAdded"):
                result.append(
                    {
                        "role": "system",
                        "tools": convert_tools(
                            message["toolsAdded"], compat, "openai-completions"
                        ),
                    }
                )
            system_index += 1
            text = _render_system(message, index == 0)
            if text:
                result.append(
                    {
                        "role": "developer"
                        if model.get("reasoning")
                        and compat.get("supportsDeveloperRole")
                        else "system",
                        "content": sanitize(text),
                    }
                )
        elif role == "user":
            if isinstance(content, str):
                result.append({"role": "user", "content": sanitize(content)})
            else:
                blocks = [
                    {"type": "text", "text": sanitize(b["text"])}
                    if b.get("type") == "text"
                    else {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{b['mimeType']};base64,{b['data']}"
                        },
                    }
                    for b in content
                    if b.get("type") != "text" or b.get("text")
                ]
                if blocks:
                    result.append({"role": "user", "content": blocks})
        elif role == "assistant":
            value = {
                "role": "assistant",
                "content": content_text(content, "")
                or ("" if compat.get("requiresAssistantAfterToolResult") else None),
            }
            thinking = [b for b in content if b.get("type") == "thinking"]
            details = None
            for block in thinking:
                signature = block.get("thinkingSignature")
                if (
                    signature in {"reasoning", "reasoning_content", "reasoning_text"}
                    and block.get("thinking", "").strip()
                ):
                    value[
                        "reasoning_content"
                        if model["provider"] == "opencode-go"
                        and signature == "reasoning"
                        else signature
                    ] = "\n".join(b.get("thinking", "") for b in thinking)
                elif signature:
                    try:
                        parsed = json.loads(signature)
                        if isinstance(parsed, list) and parsed:
                            details = parsed
                    except (ValueError, TypeError):
                        pass
            if details:
                value["reasoning_details"] = details
            if compat.get("requiresThinkingAsText") and any(
                b.get("thinking", "").strip() for b in thinking
            ):
                value["content"] = [
                    {
                        "type": "text",
                        "text": sanitize(
                            "\n\n".join(b.get("thinking", "") for b in thinking)
                        ),
                    }
                ] + [
                    {"type": "text", "text": sanitize(b["text"])}
                    for b in content
                    if b.get("type") == "text" and b["text"].strip()
                ]
            if compat.get("requiresReasoningContentOnAssistantMessages") and model.get(
                "reasoning"
            ):
                value.setdefault("reasoning_content", "")
            calls = []
            for b in content:
                if b.get("type") != "toolCall":
                    continue
                if b["name"] in grammar:
                    calls.append(
                        {
                            "id": b["id"],
                            "type": "custom",
                            "custom": {
                                "name": b["name"],
                                "input": sanitize(
                                    grammar_input(
                                        b["name"],
                                        b.get("arguments", {}),
                                        grammar[b["name"]],
                                    )
                                ),
                            },
                        }
                    )
                    continue
                calls.append(
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {
                            "name": b["name"],
                            "arguments": js_json(b.get("arguments", {})),
                        },
                    }
                )
            if calls:
                value["tool_calls"] = calls
            if value["content"] or calls:
                result.append(value)
        elif role == "toolResult":
            text = content_text(content)
            has_images = any(b.get("type") == "image" for b in content)
            value = {
                "role": "tool",
                "tool_call_id": message["toolCallId"],
                "content": sanitize(
                    text
                    if text.strip()
                    else "(see attached image)"
                    if has_images
                    else "(no tool output)"
                ),
            }
            if compat.get("requiresToolResultName") and message.get("toolName"):
                value["name"] = message["toolName"]
            result.append(value)
            # Images follow all consecutive tool results, matching the provider's batch boundary.
            pending_images.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{b['mimeType']};base64,{b['data']}"},
                }
                for b in content
                if b.get("type") == "image"
            )
            if pending_images and (
                index + 1 == len(messages)
                or messages[index + 1]["role"] != "toolResult"
            ):
                if compat.get("requiresAssistantAfterToolResult"):
                    result.append(
                        {
                            "role": "assistant",
                            "content": "I have processed the tool results.",
                        }
                    )
                result.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Attached image(s) from tool result:",
                            }
                        ]
                        + pending_images,
                    }
                )
                pending_images = []
                last_role = "user"
                continue
        last_role = role
    return result


def responses_messages(context, model, compat, effort=None):
    messages = canonical_messages(
        context, model, mid_system=compat.get("supportsMidConvoSystemMessages", False)
    )
    result, count = [], 0
    support = tool_support(compat, "openai-responses")
    _, folded = resolve_tools(messages, support)
    grammar = grammar_properties(declared_tools(context), compat)
    system_index, declared_additional = 0, False
    unavailable = {}
    instruction_role = (
        "developer"
        if model.get("reasoning") and compat.get("supportsDeveloperRole", True)
        else "system"
    )
    for index, message in enumerate(messages):
        role, content = message["role"], message["content"]
        if role == "system":
            anchors = system_index >= folded
            system_index += 1
            added_tools = message.get("toolsAdded") or []
            if anchors:
                for tool in added_tools:
                    unavailable.pop(tool["name"], None)
                if added_tools and support == "changes":
                    if declared_additional:
                        notice = "This is an incremental tools update. Previously declared tools remain available unless explicitly marked unavailable. A tool declared again here is available again, and its latest definition replaces the earlier one."
                        if unavailable:
                            notice += (
                                "\nStill unavailable: " + ", ".join(unavailable) + "."
                            )
                        result.append({"role": instruction_role, "content": notice})
                    declared_additional = True
                    result.append(
                        {
                            "type": "additional_tools",
                            "role": "developer",
                            "tools": convert_tools(
                                added_tools, compat, "openai-responses"
                            ),
                        }
                    )
                elif added_tools and support == "additions":
                    names = [tool["name"] for tool in added_tools]
                    call_id = "pi_tool_load_" + short_hash(
                        f"system:{count}:" + ",".join(names)
                    )
                    result.extend(
                        [
                            {
                                "type": "tool_search_call",
                                "call_id": call_id,
                                "execution": "client",
                                "status": "completed",
                                "arguments": {
                                    "query": " ".join(names),
                                    "limit": len(names),
                                },
                            },
                            {
                                "type": "tool_search_output",
                                "call_id": call_id,
                                "execution": "client",
                                "status": "completed",
                                "tools": convert_tools(
                                    added_tools,
                                    compat,
                                    "openai-responses",
                                    tool_search_result=True,
                                ),
                            },
                        ]
                    )
            text = _render_system(message, index == 0)
            if anchors:
                added = {tool["name"] for tool in added_tools}
                removed = [
                    tool["name"]
                    for tool in message.get("toolsRemoved") or []
                    if tool["name"] not in added
                ]
                if removed:
                    notice = (
                        "The following tools are no longer available. Do not call them:\n"
                        + "\n".join("- " + name for name in removed)
                    )
                    text = "\n\n".join(part for part in (text, notice) if part)
                    unavailable.update(dict.fromkeys(removed))
            if text:
                result.append({"role": instruction_role, "content": sanitize(text)})
        elif role == "user":
            blocks = (
                [{"type": "input_text", "text": sanitize(content)}]
                if isinstance(content, str)
                else [
                    {"type": "input_text", "text": sanitize(b["text"])}
                    if b.get("type") == "text"
                    else {
                        "type": "input_image",
                        "detail": "auto",
                        "image_url": f"data:{b['mimeType']};base64,{b['data']}",
                    }
                    for b in content
                ]
            )
            if blocks:
                result.append({"role": "user", "content": blocks})
        elif role == "assistant":
            output, text_index = [], 0
            same = (
                message.get("provider") == model["provider"]
                and message.get("api") == model["api"]
                and message.get("model") == model["id"]
            )
            for block in content:
                kind = block.get("type")
                if kind == "thinking" and block.get("thinkingSignature"):
                    output.append(json.loads(block["thinkingSignature"]))
                elif kind == "text":
                    signature = block.get("textSignature")
                    try:
                        parsed = (
                            json.loads(signature)
                            if signature and signature.startswith("{")
                            else {"id": signature}
                            if signature
                            else {}
                        )
                    except ValueError:
                        parsed = {}
                    item_id = parsed.get("id") or f"msg_pi_{count}" + (
                        f"_{text_index}" if text_index else ""
                    )
                    if len(item_id) > 64:
                        item_id = "msg_" + short_hash(item_id)
                    value = {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": sanitize(block.get("text", "")),
                                "annotations": [],
                            }
                        ],
                        "status": "completed",
                        "id": item_id,
                    }
                    if parsed.get("phase") is not None:
                        value["phase"] = parsed["phase"]
                    output.append(value)
                    text_index += 1
                elif kind == "toolCall":
                    parts = block["id"].split("|", 1)
                    custom = grammar.get(block["name"])
                    value = {
                        "type": "custom_tool_call" if custom else "function_call",
                        "call_id": parts[0],
                        "name": block["name"],
                        **(
                            {
                                "input": sanitize(
                                    grammar_input(
                                        block["name"],
                                        block.get("arguments", {}),
                                        custom,
                                    )
                                )
                            }
                            if custom
                            else {"arguments": js_json(block.get("arguments", {}))}
                        ),
                    }
                    same_provider_api = (
                        message.get("provider") == model["provider"]
                        and message.get("api") == model["api"]
                    )
                    different_model = (
                        same_provider_api and message.get("model") != model["id"]
                    )
                    if (
                        len(parts) > 1
                        and parts[1].startswith("ctc_" if custom else "fc_")
                        and not different_model
                    ):
                        value["id"] = parts[1]
                    if same and "namespace" in block:
                        value["namespace"] = block["namespace"]
                    output.append(value)
            if (
                output
                and effort is not None
                and same
                and message.get("providerThinkingLevel") is not None
            ):
                result.append(
                    {
                        "type": "configuration_update",
                        "reasoning": {"effort": message["providerThinkingLevel"]},
                    }
                )
            result.extend(output)
        elif role == "toolResult":
            text = content_text(content)
            images = [b for b in content if b.get("type") == "image"]
            output = text
            if images:
                output = (
                    [{"type": "input_text", "text": sanitize(text)}] if text else []
                ) + [
                    {
                        "type": "input_image",
                        "image_url": f"data:{b['mimeType']};base64,{b['data']}",
                        "detail": "auto",
                    }
                    for b in images
                ]
            result.append(
                {
                    "type": "custom_tool_call_output"
                    if message.get("toolName") in grammar
                    else "function_call_output",
                    "call_id": message["toolCallId"].split("|", 1)[0],
                    "output": output,
                }
            )
        if index != 0 or role != "system":
            count += 1
    if effort is not None:
        result.append({"type": "configuration_update", "reasoning": {"effort": effort}})
    return result


def cache_retention(config):
    return config.get(
        "_cache_retention",
        config.get(
            "cache_retention", config.get("llm", {}).get("cache_retention", "short")
        ),
    )


def request_headers(config, api):
    model = selected_model(config, api)
    return session_headers(
        compat_options(model, api),
        api,
        None if cache_retention(config) == "none" else config.get("_session_id"),
    )


def build_payload(config, context, api, reasoning=None, fallback_tools=()):
    model = selected_model(config, api)
    compat = compat_options(model, api)
    llm = config.get("llm", {})
    level = clamp_reasoning(model, reasoning)
    mapping = model.get("thinkingLevelMap") or {}
    mapped = mapping.get(level, level) if level else mapping.get("off")
    context_window, model_max = model_limits(config)
    requested = config.get("max_tokens", llm.get("max_tokens", model_max))
    if requested is None:
        requested = model_max
    cap = clamp_max_tokens(
        context_window,
        context,
        int(requested),
    )
    tools, _ = resolve_tools(context, tool_support(compat, api))
    if not any(
        m.get("role") == "system" and ("toolsAdded" in m or "toolsRemoved" in m)
        for m in context
    ):
        tools = [t.get("function", t) for t in fallback_tools]
    payload = {"model": model["id"]}
    chatgpt = api == "openai-responses" and is_chatgpt_sign_in(
        model, llm.get("api_key")
    )
    if api == "openai-responses":
        effort = (
            mapped
            if level and compat.get("supportsMidConvoEffort") and not chatgpt
            else None
        )
        payload.update(
            input=responses_messages(context, model, compat, effort), store=False
        )
        if cap and compat.get("supportsMaxOutputTokens") and not chatgpt:
            payload["max_output_tokens"] = max(cap, 16)
        if model.get("reasoning"):
            if level:
                payload["reasoning"] = {
                    "effort": "medium" if effort is not None else mapped,
                    "summary": "auto",
                }
                payload["include"] = ["reasoning.encrypted_content"]
            elif (
                model["provider"] != "github-copilot"
                and mapping.get("off", "unset") is not None
            ):
                payload["reasoning"] = {"effort": mapping.get("off", "none")}
            if model["provider"] == "xai":
                payload["include"] = ["reasoning.encrypted_content"]
    else:
        effort = None
        payload["messages"] = completion_messages(context, model, compat)
        if cap:
            payload[compat["maxTokensField"]] = cap
        if compat.get("supportsStore"):
            payload["store"] = False
        payload.update(
            completion_options(
                model,
                compat,
                level,
                cap,
                config.get(
                    "thinking_budgets",
                    config.get("thinkingBudgets", llm.get("thinking_budgets")),
                ),
            )
        )
    temperature = config.get("temperature", llm.get("temperature"))
    if temperature is not None and not chatgpt:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = convert_tools(tools, compat, api)
        if api == "openai-completions" and compat.get("zaiToolStream"):
            payload["tool_stream"] = True
    elif (
        any(
            m.get("role") in {"toolResult"}
            or (
                m.get("role") == "assistant"
                and any(b.get("type") == "toolCall" for b in m.get("content", []))
            )
            for m in context
        )
        and api == "openai-completions"
    ):
        payload["tools"] = []
    retention = cache_retention(config)
    payload.update(
        prompt_cache_options(
            model,
            compat,
            api,
            retention,
            config.get("_session_id"),
            api_key=llm.get("api_key"),
        )
    )
    if api == "openai-completions":
        apply_compat_cache_control(payload, compat, retention)
    choice = config.get("tool_choice", llm.get("tool_choice"))
    if choice is not None:
        payload["tool_choice"] = choice
    sampling = {
        **(model.get("samplingParams") or {}),
        **(
            (model.get("samplingParamsByThinkingLevel") or {}).get(level or "off") or {}
        ),
        **(config.get("sampling_params", llm.get("sampling_params", {})) or {}),
    }
    payload.update(sampling)
    return payload, effort
