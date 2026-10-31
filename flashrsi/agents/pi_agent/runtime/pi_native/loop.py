"""Pi's non-interactive agent loop implemented without Node or npm.

The loop follows Pi's JSON-mode lifecycle and provider-neutral message model.
It intentionally uses ``httpx`` directly so the selected Snapshot contains all
execution logic and never imports the host's Agent implementation.

The reference behavior is Pi v1.4.0 (upstream commit
``4a080252f06caf63a525d7873c5d94d3c23887e0``); this module ports the
headless Target/Worker path and keeps unsupported interactive/runtime features
outside the contract.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx

from .resources import (
    ResourceBundle,
    default_tools,
    expand_prompt_template,
    load_resources,
)
from .tools import ToolResult, _resolve, execute_tool


@dataclass
class NativePiResult:
    status: str
    output: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    error_message: str | None = None


@dataclass
class _ProviderReply:
    message: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    usage: dict[str, Any]
    stop_reason: str | None
    raw: dict[str, Any]


def _model(config: Mapping[str, Any]) -> tuple[str, str]:
    llm = config.get("llm", {})
    value = llm.get("model_name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Pi llm.model_name must be a non-empty string")
    value = value.strip()
    if "/" in value:
        provider, model = value.split("/", 1)
    else:
        provider, model = llm.get("provider_name"), value
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError(
            "Pi llm.model_name must use provider/model, or set llm.provider_name"
        )
    if not model.strip():
        raise ValueError("Pi llm.model_name must include a model id")
    return provider.strip().lower(), model.strip()


def _selected_tools(
    config: Mapping[str, Any], files_dir: Path | None = None
) -> list[str]:
    value = config.get("tools")
    if value is None:
        return (
            default_tools(files_dir)
            if files_dir is not None
            else ["read", "bash", "edit", "write"]
        )
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError("Pi tools must be a list of non-empty strings")
    available = {"read", "bash", "edit", "write", "grep", "find", "ls"}
    additive = any(item[:1] in {"+", "-"} for item in value)
    if additive and any(item[:1] not in {"+", "-"} for item in value):
        raise ValueError("Pi tools cannot mix plain names with +/- modifiers")
    configured_defaults = (
        default_tools(files_dir)
        if files_dir is not None
        else ["read", "bash", "edit", "write"]
    )
    selected: list[str] = list(configured_defaults) if additive else []
    for item in value:
        add = not item.startswith("-")
        name = item[1:] if item[:1] in {"+", "-"} else item
        if name not in available:
            raise ValueError(f"Pi unknown tool: {name}")
        if add and name not in selected:
            selected.append(name)
        elif not add and name in selected:
            selected.remove(name)
    if value and not additive:
        selected = list(dict.fromkeys(value))
    return selected


def _message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, Mapping) and isinstance(item.get("text"), str)
        )
    return ""


def _usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result = dict(value)
    aliases = {
        "input_tokens": "input",
        "prompt_tokens": "input",
        "output_tokens": "output",
        "completion_tokens": "output",
    }
    for source, target in aliases.items():
        if source in result and target not in result:
            result[target] = result[source]
    return result


def _max_retries(config: Mapping[str, Any], llm: Mapping[str, Any]) -> int:
    value = config.get(
        "max_retries",
        config.get(
            "llm_max_retries",
            llm.get("max_retries", llm.get("llm_max_retries", 2)),
        ),
    )
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 2


def _reasoning_effort(config: Mapping[str, Any], llm: Mapping[str, Any]) -> str | None:
    value = config.get(
        "thinking",
        config.get(
            "reasoning_effort",
            llm.get("thinking", llm.get("reasoning_effort", llm.get("effort"))),
        ),
    )
    if value in (None, "", "off", "none"):
        return None
    return str(value)


def _pi_usage(value: Any) -> dict[str, Any]:
    """Normalize provider usage to Pi's shared ``Usage`` shape.

    Providers use different names for the same counters.  Preserve their
    original fields for diagnostics while adding the fields Pi consumers use
    (`input`, `output`, `totalTokens`, and `cost`).
    """

    raw_value = dict(value) if isinstance(value, Mapping) else {}
    raw = _usage(raw_value)
    input_tokens = raw.get("input", 0)
    output_tokens = raw.get("output", 0)
    input_details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details")
    if not isinstance(input_details, Mapping):
        input_details = {}
    cache_read = raw.get(
        "cacheRead",
        raw.get(
            "cache_read_input_tokens",
            raw.get("cached_tokens", input_details.get("cached_tokens", 0)),
        ),
    )
    cache_write = raw.get(
        "cacheWrite",
        raw.get(
            "cache_creation_input_tokens",
            input_details.get("cache_creation_input_tokens", 0),
        ),
    )

    # OpenAI reports prompt/input tokens including the cached portion, while
    # Pi's ``Usage.input`` is the uncached count. Anthropic's
    # ``input_tokens`` is already uncached, so only subtract when the provider
    # exposes the OpenAI-style details or prompt counter.
    prompt_total = raw_value.get("prompt_tokens")
    input_total = raw_value.get("input_tokens")
    openai_cached = (
        isinstance(raw_value.get("prompt_tokens_details"), Mapping)
        or isinstance(raw_value.get("input_tokens_details"), Mapping)
        or "cached_tokens" in raw_value
    )

    def number(item: Any) -> int | float:
        return (
            item if isinstance(item, (int, float)) and not isinstance(item, bool) else 0
        )

    input_tokens = number(input_tokens)
    output_tokens = number(output_tokens)
    cache_read = number(cache_read)
    cache_write = number(cache_write)
    if isinstance(prompt_total, (int, float)) and not isinstance(prompt_total, bool):
        input_tokens = max(0, prompt_total - cache_read - cache_write)
    elif (
        isinstance(input_total, (int, float))
        and not isinstance(input_total, bool)
        and openai_cached
    ):
        input_tokens = max(0, input_total - cache_read - cache_write)
    result = dict(raw)
    result.update(
        {
            "input": input_tokens,
            "output": output_tokens,
            "cacheRead": cache_read,
            "cacheWrite": cache_write,
            "totalTokens": number(
                raw.get(
                    "totalTokens",
                    raw.get(
                        "total_tokens",
                        input_tokens + output_tokens + cache_read + cache_write,
                    ),
                )
            ),
            "cost": raw.get(
                "cost",
                {
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "total": 0,
                },
            ),
        }
    )
    return result


def _now_ms() -> int:
    return int(time.time() * 1000)


def _session_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _api_name(provider: str, config: Mapping[str, Any]) -> str:
    model_api = config.get("llm", {}).get("model_api")
    if isinstance(model_api, str) and model_api:
        return model_api
    if provider in {"anthropic", "anthropic-messages"}:
        return "anthropic-messages"
    return "openai-completions"


def _stop_reason(value: Any, *, has_tools: bool = False) -> str:
    """Map provider stop labels to Pi's AssistantMessage stopReason."""

    value = str(value or "")
    if value in {"length", "max_tokens", "max_output_tokens"}:
        return "length"
    if value in {"error", "failed", "incomplete", "content_filter"}:
        return "error"
    if value in {"aborted", "abort"}:
        return "aborted"
    # A provider may omit an explicit tool-call finish label while still
    # returning tool calls.  Preserve an explicit length label above: Pi
    # refuses to execute calls from a token-truncated assistant message.
    if value in {"tool_calls", "tool_use", "function_call"} or has_tools:
        return "toolUse"
    return "stop"


def _assistant_event_message(
    reply: _ProviderReply,
    *,
    provider: str,
    model: str,
    api: str,
    timestamp: int,
) -> dict[str, Any]:
    """Convert our provider-neutral reply to Pi's AssistantMessage shape."""

    content: list[dict[str, Any]] = []
    text = _message_text(reply.message)
    if text:
        content.append({"type": "text", "text": text})
    for call in reply.tool_calls:
        try:
            arguments = json.loads(call.get("arguments", "{}"))
        except (TypeError, json.JSONDecodeError):
            arguments = {}
        content.append(
            {
                "type": "toolCall",
                "id": call.get("id", ""),
                "name": call.get("name", ""),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    usage = _pi_usage(reply.usage)
    return {
        "role": "assistant",
        "content": content,
        "api": api,
        "provider": provider,
        "model": model,
        "usage": usage,
        "stopReason": _stop_reason(reply.stop_reason, has_tools=bool(reply.tool_calls)),
        "rawStopReason": reply.stop_reason,
        "timestamp": timestamp,
    }


async def _request_json(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    retries: int,
) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        response: Any = None
        try:
            response = await client.post(url, headers=dict(headers), json=dict(payload))
            if response.status_code >= 500 and attempt < retries:
                await asyncio.sleep(_retry_delay(response, attempt))
                continue
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("provider returned a non-object JSON response")
            return body
        except Exception as exc:
            last = exc
            status = getattr(response, "status_code", None)
            # Pi retries transient transport/server failures.  Client errors
            # and malformed successful responses are surfaced immediately so a
            # bad request cannot consume the whole retry budget.
            retryable = (
                not isinstance(status, int)
                or status in {408, 409, 429}
                or status >= 500
            )
            if not retryable:
                raise
            if attempt < retries:
                await asyncio.sleep(_retry_delay(response, attempt))
    raise RuntimeError(str(last) if last else "provider request failed")


def _retry_delay(response: Any, attempt: int) -> float:
    """Match Pi's bounded provider retry backoff for transient HTTP errors."""

    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("retry-after") if hasattr(headers, "get") else None
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0.0), 8.0)
        except (TypeError, ValueError):
            pass
    return min(0.5 * (2**attempt), 8.0)


def _openai_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


async def _openai_call(
    client: httpx.AsyncClient,
    config: Mapping[str, Any],
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> _ProviderReply:
    llm = config["llm"]
    base_url = str(llm.get("base_url") or "https://api.openai.com/v1")
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        payload.update({"tools": tools, "tool_choice": "auto"})
    max_tokens = config.get("max_tokens", llm.get("max_tokens"))
    if isinstance(max_tokens, int) and max_tokens > 0:
        payload["max_tokens"] = max_tokens
    temperature = config.get("temperature", llm.get("temperature"))
    if temperature is not None:
        payload["temperature"] = temperature
    thinking = _reasoning_effort(config, llm)
    if thinking:
        payload["reasoning_effort"] = thinking
    extra_body = llm.get("extra_body", config.get("extra_body"))
    if isinstance(extra_body, Mapping):
        payload.update(extra_body)
    data = await _request_json(
        client,
        _openai_url(base_url),
        {
            "Authorization": f"Bearer {llm['api_key']}",
            "Content-Type": "application/json",
        },
        payload,
        _max_retries(config, llm),
    )
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI-compatible response has no choices")
    choice = choices[0]
    message = dict(choice.get("message") or {})
    message.setdefault("role", "assistant")
    message.setdefault("content", "")
    calls: list[dict[str, Any]] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        calls.append(
            {
                "id": call.get("id") or uuid.uuid4().hex,
                "name": function.get("name", ""),
                "arguments": function.get("arguments", "{}"),
            }
        )
    return _ProviderReply(
        message,
        calls,
        _usage(data.get("usage")),
        choice.get("finish_reason"),
        data,
    )


def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "tool":
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id", ""),
                    "output": message.get("content", ""),
                }
            )
            continue
        if role == "assistant" and message.get("tool_calls"):
            if message.get("content"):
                result.append({"role": "assistant", "content": message["content"]})
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                result.append(
                    {
                        "type": "function_call",
                        "call_id": call.get("id", ""),
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments", "{}"),
                    }
                )
            continue
        result.append({"role": role, "content": message.get("content", "")})
    return result


async def _openai_responses_call(
    client: httpx.AsyncClient,
    config: Mapping[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> _ProviderReply:
    llm = config["llm"]
    base_url = str(llm.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    url = base_url if base_url.endswith("/responses") else base_url + "/responses"
    system = next(
        (item.get("content", "") for item in messages if item.get("role") == "system"),
        "",
    )
    payload: dict[str, Any] = {
        "model": model,
        "input": _responses_input(messages),
        "store": False,
    }
    if system:
        payload["instructions"] = system
    if tools:
        payload["tools"] = [
            {
                "type": "function",
                "name": item["function"]["name"],
                "description": item["function"].get("description", ""),
                "parameters": item["function"].get("parameters", {}),
            }
            for item in tools
        ]
    max_tokens = config.get("max_tokens", llm.get("max_tokens"))
    if isinstance(max_tokens, int) and max_tokens > 0:
        payload["max_output_tokens"] = max_tokens
    temperature = config.get("temperature", llm.get("temperature"))
    if temperature is not None:
        payload["temperature"] = temperature
    thinking = _reasoning_effort(config, llm)
    if thinking:
        payload["reasoning"] = {"effort": thinking}
    extra_body = llm.get("extra_body", config.get("extra_body"))
    if isinstance(extra_body, Mapping):
        payload.update(extra_body)
    data = await _request_json(
        client,
        url,
        {
            "Authorization": f"Bearer {llm['api_key']}",
            "Content-Type": "application/json",
        },
        payload,
        _max_retries(config, llm),
    )
    text = ""
    calls: list[dict[str, Any]] = []
    open_calls: list[dict[str, Any]] = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            text += "".join(
                content.get("text", "")
                for content in item.get("content") or []
                if content.get("type") in {"output_text", "text"}
            )
        elif item.get("type") == "function_call":
            call_id = item.get("call_id") or item.get("id") or uuid.uuid4().hex
            arguments = item.get("arguments", "{}")
            calls.append(
                {"id": call_id, "name": item.get("name", ""), "arguments": arguments}
            )
            open_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": arguments,
                    },
                }
            )
    status = data.get("status") or "completed"
    if status == "incomplete":
        reason = (data.get("incomplete_details") or {}).get("reason")
        if reason in {"max_output_tokens", "max_tokens"}:
            status = "length"
    return _ProviderReply(
        {"role": "assistant", "content": text, "tool_calls": open_calls},
        calls,
        _usage(data.get("usage")),
        status,
        data,
    )


def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id", ""),
                "content": message.get("content", ""),
            }
            if result and result[-1].get("role") == "user":
                content = result[-1].setdefault("content", [])
                if isinstance(content, list):
                    content.append(block)
            else:
                result.append({"role": "user", "content": [block]})
            continue
        if role == "assistant" and message.get("tool_calls"):
            content: list[dict[str, Any]] = []
            if message.get("content"):
                content.append({"type": "text", "text": message["content"]})
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments", "{}"))
                except (TypeError, json.JSONDecodeError):
                    arguments = {}
                content.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id", ""),
                        "name": function.get("name", ""),
                        "input": arguments,
                    }
                )
            result.append({"role": "assistant", "content": content})
        else:
            result.append({"role": role, "content": message.get("content", "")})
    return result


async def _anthropic_call(
    client: httpx.AsyncClient,
    config: Mapping[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> _ProviderReply:
    llm = config["llm"]
    base_url = str(llm.get("base_url") or "https://api.anthropic.com")
    url = base_url.rstrip("/")
    if not url.endswith("/messages"):
        url += "/messages" if url.endswith("/v1") else "/v1/messages"
    system = next(
        (item.get("content", "") for item in messages if item.get("role") == "system"),
        "",
    )
    max_tokens = config.get("max_tokens", llm.get("max_tokens", 4096))
    payload: dict[str, Any] = {
        "model": model,
        "messages": _anthropic_messages(messages),
        "max_tokens": int(max_tokens),
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [
            {
                "name": item["function"]["name"],
                "description": item["function"].get("description", ""),
                "input_schema": item["function"].get("parameters", {}),
            }
            for item in tools
        ]
    data = await _request_json(
        client,
        url,
        {
            "x-api-key": str(llm["api_key"]),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        payload,
        _max_retries(config, llm),
    )
    content = data.get("content") or []
    text = "".join(
        item.get("text", "") for item in content if item.get("type") == "text"
    )
    calls: list[dict[str, Any]] = []
    open_calls: list[dict[str, Any]] = []
    for item in content:
        if item.get("type") != "tool_use":
            continue
        call_id = item.get("id") or uuid.uuid4().hex
        arguments = json.dumps(item.get("input", {}), ensure_ascii=False)
        calls.append(
            {"id": call_id, "name": item.get("name", ""), "arguments": arguments}
        )
        open_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": item.get("name", ""), "arguments": arguments},
            }
        )
    return _ProviderReply(
        {"role": "assistant", "content": text, "tool_calls": open_calls},
        calls,
        _usage(data.get("usage")),
        data.get("stop_reason"),
        data,
    )


def _event(events: list[dict[str, Any]], value: dict[str, Any]) -> None:
    events.append(value)


async def _execute_tool_batch(
    calls: list[dict[str, Any]],
    *,
    selected: list[str],
    cwd: Path,
    events: list[dict[str, Any]],
    usage: dict[str, Any],
    stop_reason: str,
    mode: str,
) -> list[dict[str, Any]]:
    """Follow Pi's preparation, completion, and transcript ordering.

    Parallel batches emit starts in source order and ends in completion order;
    tool result messages always retain the model's source order. Mutations of
    the same file serialize, as in Pi's file-mutation queue.
    """

    mutation_locks: dict[Path, asyncio.Lock] = {}

    def prepare(
        call: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, ToolResult | None]:
        usage["tool_calls"] += 1
        try:
            arguments = json.loads(call.get("arguments", "{}"))
        except (TypeError, json.JSONDecodeError):
            arguments = None
        name = call.get("name", "")
        _event(
            events,
            {
                "type": "tool_execution_start",
                "toolCallId": call["id"],
                "toolName": name,
                "args": arguments if isinstance(arguments, dict) else {},
            },
        )
        if stop_reason == "length":
            return None, ToolResult(
                f'Tool call "{name}" was not executed: the response hit the '
                "output token limit, so its arguments may be truncated. "
                "Re-issue the tool call with complete arguments.",
                is_error=True,
            )
        if name not in selected:
            return None, ToolResult(f"Tool {name} not found", is_error=True)
        if not isinstance(arguments, dict):
            return None, ToolResult(
                "Tool arguments must be a valid JSON object.", is_error=True
            )
        return arguments, None

    def finish(
        call: dict[str, Any], result: ToolResult, duration_ms: int | None = None
    ) -> dict[str, Any]:
        tool_result: dict[str, Any] = {
            "role": "toolResult",
            "toolCallId": call["id"],
            "toolName": call.get("name", ""),
            "content": [{"type": "text", "text": result.content}],
            "details": result.details,
            "isError": result.is_error,
            "timestamp": _now_ms(),
        }
        end: dict[str, Any] = {
            "type": "tool_execution_end",
            "toolCallId": call["id"],
            "toolName": call.get("name", ""),
            "result": {"content": tool_result["content"], "details": result.details},
            "isError": result.is_error,
        }
        if duration_ms is not None:
            tool_result["durationMs"] = duration_ms
            end["durationMs"] = duration_ms
        _event(events, end)
        return tool_result

    async def execute(
        call: dict[str, Any], arguments: dict[str, Any]
    ) -> dict[str, Any]:
        started = time.monotonic()
        name = call.get("name", "")
        if name in {"write", "edit"}:
            try:
                path = _resolve(arguments.get("path"), cwd)
            except (OSError, RuntimeError, ValueError) as exc:
                return finish(
                    call,
                    ToolResult(
                        f"{name} failed: {type(exc).__name__}: {exc}", is_error=True
                    ),
                    round((time.monotonic() - started) * 1000),
                )
            lock = mutation_locks.setdefault(path, asyncio.Lock())
            async with lock:
                # Cancelling an await cannot stop filesystem work in a thread.
                # Keep the mutation lock until that work settles, matching
                # Pi's file-mutation queue and preventing writes after return.
                worker = asyncio.create_task(
                    asyncio.to_thread(execute_tool, name, arguments, cwd)
                )
                try:
                    result = await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await worker
                    raise
        else:
            result = await asyncio.to_thread(execute_tool, name, arguments, cwd)
        return finish(call, result, round((time.monotonic() - started) * 1000))

    def emit_result(message: dict[str, Any]) -> None:
        _event(events, {"type": "message_start", "message": message})
        _event(events, {"type": "message_end", "message": message})

    results: list[dict[str, Any]] = []
    if mode == "sequential" or stop_reason == "length":
        for call in calls:
            arguments, immediate = prepare(call)
            message = (
                finish(call, immediate)
                if immediate is not None
                else await execute(call, arguments)
            )
            results.append(message)
            emit_result(message)
    else:
        prepared = []
        for call in calls:
            arguments, immediate = prepare(call)
            prepared.append(
                (
                    call,
                    arguments,
                    finish(call, immediate) if immediate is not None else None,
                )
            )

        async def complete(call, arguments, immediate):
            return (
                immediate if immediate is not None else await execute(call, arguments)
            )

        results = await asyncio.gather(*(complete(*item) for item in prepared))
        for message in results:
            emit_result(message)
    return results


async def run(
    config: Mapping[str, Any],
    prompt: str,
    working_dir: Path,
    files_dir: Path,
    resources: ResourceBundle | None = None,
) -> NativePiResult:
    """Run a Pi-compatible task using only Python and the selected Snapshot."""
    provider, model = _model(config)
    llm = config.get("llm", {})
    api_key = llm.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("Pi requires the framework role's llm.api_key")
    selected = _selected_tools(config, files_dir)
    resources = resources or load_resources(
        files_dir,
        working_dir,
        selected_tools=selected,
        append_system_prompt=str(config.get("system_prompt", "")),
    )
    prompt = expand_prompt_template(prompt, resources.templates)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": resources.system_prompt},
        {"role": "user", "content": prompt},
    ]
    events: list[dict[str, Any]] = []
    session_id = str(uuid.uuid4())
    usage: dict[str, Any] = {
        "input": 0,
        "output": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "model_calls": 0,
        "tool_calls": 0,
    }
    _event(
        events,
        {
            "type": "session",
            "version": 3,
            "id": session_id,
            "timestamp": _session_timestamp(),
            "cwd": str(working_dir),
        },
    )
    _event(events, {"type": "agent_start"})
    max_turns = int(config.get("max_turns", 64))
    tool_execution = config.get(
        "tool_execution", config.get("toolExecution", "parallel")
    )
    if tool_execution not in {"parallel", "sequential"}:
        raise ValueError("Pi tool_execution must be parallel or sequential")
    timeout = float(config.get("request_timeout", config.get("timeout", 300)))
    tool_schemas = resources.tool_schemas
    api = _api_name(provider, config)
    # ``runAgentLoop`` reports the initial user prompt in the new-message list;
    # keep the same transcript shape for callers consuming ``agent_end``.
    generated_messages: list[dict[str, Any]] = []
    user_message = {"role": "user", "content": prompt, "timestamp": _now_ms()}
    user_emitted = False
    async with httpx.AsyncClient(timeout=timeout) as client:
        for _turn in range(1, max_turns + 1):
            _event(events, {"type": "turn_start"})
            if not user_emitted:
                _event(events, {"type": "message_start", "message": user_message})
                _event(events, {"type": "message_end", "message": user_message})
                generated_messages.append(user_message)
                user_emitted = True
            try:
                if (
                    provider in {"anthropic", "anthropic-messages"}
                    or llm.get("model_api") == "anthropic-messages"
                ):
                    reply = await _anthropic_call(
                        client, config, model, messages, tool_schemas
                    )
                elif llm.get("model_api") == "openai-responses":
                    reply = await _openai_responses_call(
                        client, config, model, messages, tool_schemas
                    )
                else:
                    reply = await _openai_call(
                        client, config, provider, model, messages, tool_schemas
                    )
            except Exception as exc:
                # Pi's stream contract represents transport/model failures as a
                # final assistant message with ``stopReason: error``.  Keep the
                # lifecycle complete so consumers can always wait for
                # ``turn_end`` before ``agent_end``/``agent_settled``.
                error_message = {
                    "role": "assistant",
                    "content": [],
                    "api": api,
                    "provider": provider,
                    "model": model,
                    "usage": _pi_usage({}),
                    "stopReason": "error",
                    "rawStopReason": "error",
                    "errorMessage": str(exc),
                    "timestamp": _now_ms(),
                }
                _event(
                    events,
                    {
                        "type": "message_start",
                        "message": {**error_message, "stopReason": "pending"},
                    },
                )
                _event(events, {"type": "message_end", "message": error_message})
                generated_messages.append(error_message)
                _event(
                    events,
                    {
                        "type": "turn_end",
                        "message": error_message,
                        "toolResults": [],
                    },
                )
                _event(
                    events,
                    {
                        "type": "agent_end",
                        "messages": generated_messages,
                        "willRetry": False,
                    },
                )
                _event(events, {"type": "agent_settled", "aborted": False})
                return NativePiResult(
                    "error",
                    events=events,
                    usage=usage,
                    stop_reason="error",
                    error_message=str(exc),
                )
            usage["model_calls"] += 1
            provider_usage = _pi_usage(reply.usage)
            for key in ("input", "output"):
                value = provider_usage.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage[key] += value
            usage["input_tokens"] = usage["input"]
            usage["output_tokens"] = usage["output"]
            usage["cache_read_input_tokens"] += provider_usage.get("cacheRead", 0)
            usage["cache_creation_input_tokens"] += provider_usage.get("cacheWrite", 0)
            usage["total_tokens"] = (
                usage["input"]
                + usage["output"]
                + usage["cache_read_input_tokens"]
                + usage["cache_creation_input_tokens"]
            )
            assistant = reply.message
            assistant_event_message = _assistant_event_message(
                reply,
                provider=provider,
                model=model,
                api=api,
                timestamp=_now_ms(),
            )
            _event(
                events,
                {
                    "type": "message_start",
                    "message": {
                        **assistant_event_message,
                        "content": [],
                        "usage": _pi_usage({}),
                        "stopReason": "pending",
                    },
                },
            )
            text = _message_text(assistant)
            if text:
                _event(
                    events,
                    {
                        "type": "message_update",
                        "usage": _pi_usage(reply.usage),
                        "message": assistant_event_message,
                        "assistantMessageEvent": {
                            "type": "text_delta",
                            "contentIndex": 0,
                            "delta": text,
                        },
                    },
                )
            for index, call in enumerate(reply.tool_calls, start=1 if text else 0):
                try:
                    arguments = json.loads(call.get("arguments", "{}"))
                except (TypeError, json.JSONDecodeError):
                    arguments = {}
                _event(
                    events,
                    {
                        "type": "message_update",
                        "usage": _pi_usage(reply.usage),
                        "message": assistant_event_message,
                        "assistantMessageEvent": {
                            "type": "toolcall_start",
                            "contentIndex": index,
                            "id": call.get("id", ""),
                            "toolName": call.get("name", ""),
                        },
                    },
                )
                _event(
                    events,
                    {
                        "type": "message_update",
                        "usage": _pi_usage(reply.usage),
                        "message": assistant_event_message,
                        "assistantMessageEvent": {
                            "type": "toolcall_end",
                            "contentIndex": index,
                            "toolCall": {
                                "type": "toolCall",
                                "id": call.get("id", ""),
                                "name": call.get("name", ""),
                                "arguments": arguments
                                if isinstance(arguments, dict)
                                else {},
                            },
                        },
                    },
                )
            _event(
                events,
                {
                    "type": "message_end",
                    "message": assistant_event_message,
                },
            )
            generated_messages.append(assistant_event_message)
            messages.append(assistant)
            reason = assistant_event_message["stopReason"]
            if not reply.tool_calls or reason in {"error", "aborted"}:
                _event(
                    events,
                    {
                        "type": "turn_end",
                        "message": assistant_event_message,
                        "toolResults": [],
                    },
                )
                _event(
                    events,
                    {
                        "type": "agent_end",
                        "messages": generated_messages,
                        "willRetry": False,
                    },
                )
                _event(
                    events, {"type": "agent_settled", "aborted": reason == "aborted"}
                )
                return NativePiResult(
                    "error" if reason in {"error", "aborted"} else "finished",
                    output=text,
                    events=events,
                    usage=usage,
                    stop_reason=reason,
                    error_message=(reply.raw.get("error") or f"Pi response {reason}")
                    if reason in {"error", "aborted"}
                    else None,
                )
            tool_results = await _execute_tool_batch(
                reply.tool_calls,
                selected=[schema["function"]["name"] for schema in tool_schemas],
                cwd=working_dir,
                events=events,
                usage=usage,
                stop_reason=assistant_event_message["stopReason"],
                mode=tool_execution,
            )
            for tool_result in tool_results:
                generated_messages.append(tool_result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_result["toolCallId"],
                        "content": _message_text(tool_result),
                    }
                )
            _event(
                events,
                {
                    "type": "turn_end",
                    "message": assistant_event_message,
                    "toolResults": tool_results,
                },
            )
    _event(
        events,
        {"type": "agent_end", "messages": generated_messages, "willRetry": False},
    )
    _event(events, {"type": "agent_settled", "aborted": False})
    return NativePiResult(
        "error",
        events=events,
        usage=usage,
        stop_reason="length",
        error_message="Pi reached max_turns",
    )


__all__ = ["NativePiResult", "run"]
