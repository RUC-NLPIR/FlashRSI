"""SDK-free boundary around Hermes's original Anthropic Messages transport."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .chat_transport import _plain
from .upstream_anthropic import adapter
from .upstream_anthropic.boundaries import settings as request_settings
from .upstream_anthropic.credentials import anthropic_route_is_oauth
from .upstream_anthropic.dot_policy import _anthropic_preserve_dots
from .upstream_anthropic.endpoints import (
    _is_opencode_endpoint,
)
from .upstream_anthropic.transport import AnthropicTransport
from .upstream_chat.boundaries import request_settings as chat_settings
from .upstream_chat.configuration import resolve_request_settings
from .upstream_chat.profiles.nous import nous
from .upstream_chat.reasoning_config import (
    parse_reasoning_effort,
    resolve_reasoning_config,
)
from .upstream_compaction.responses_usage import normalize_usage


def anthropic_endpoint(route):
    base, options = adapter._base_client_kwargs(route.get("base_url"), None)
    parts = urlsplit(base or "https://api.anthropic.com")
    query = dict(parse_qsl(parts.query))
    query.update(options.get("default_query", {}))
    path = parts.path.rstrip("/")
    if not path.endswith("/messages"):
        path += "/v1/messages"
    return urlunsplit(
        (parts.scheme, parts.netloc, path, urlencode(query), parts.fragment)
    )


def anthropic_headers(route, settings=None):
    settings = settings or {}
    base = route.get("base_url")
    key = route.get("api_key") or ""
    normalized, _ = adapter._base_client_kwargs(base, None)
    style = adapter._auth_style(key, base, normalized)
    betas = adapter._common_betas_for_base_url(
        base, drop_context_1m_beta=bool(route.get("drop_context_1m_beta"))
    )
    if style == "oauth":
        betas += adapter._OAUTH_ONLY_BETAS
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        **adapter._beta_header(betas),
    }
    if key:
        headers["Authorization" if style in {"bearer", "oauth"} else "x-api-key"] = (
            f"Bearer {key}" if style in {"bearer", "oauth"} else key
        )
    if style == "kimi":
        headers.update(adapter._attribution_headers())
    elif style == "oauth":
        version = route.get("claude_code_version", "2.1.74")
        headers.update(
            {"user-agent": f"claude-code/{version} (external, cli)", "x-app": "cli"}
        )
    if _is_opencode_endpoint(base):
        for key, value in adapter._attribution_headers().items():
            headers.setdefault(key, value)
    for provider in settings.get("custom_providers", []):
        if str(provider.get("base_url", "")).rstrip("/") == str(base or "").rstrip("/"):
            headers.update(provider.get("extra_headers") or {})
    headers.update(route.get("default_headers") or {})
    headers.update(route.get("extra_headers") or {})
    # The original SDK explicitly omits the unused credential header. An
    # unrelated ambient environment variable is never read by this boundary.
    return headers


def prepare_anthropic(payload, route, settings):
    payload = copy.deepcopy(payload)
    model = payload.get("model") or route.get("model_name") or ""
    base = route.get("base_url")
    reasoning = route.get("reasoning_config", settings.get("reasoning_config"))
    effort = payload.get("reasoning_effort", route.get("reasoning_effort"))
    if effort is not None:
        reasoning = parse_reasoning_effort(effort)
    elif reasoning is None and not settings.get("_chat_auxiliary"):
        agent = dict(settings.get("agent") or {})
        for key in ("reasoning_effort", "reasoning_overrides"):
            if key in settings:
                agent[key] = settings[key]
        reasoning = resolve_reasoning_config({"agent": agent}, model)
    recovery = settings.get("_recovery_reasoning")
    if recovery is not None and not settings.get("_chat_auxiliary"):
        reasoning = recovery.reasoning_for_wire(
            reasoning, ephemeral_off=effort in ("none", "off", False)
        )
    oauth = anthropic_route_is_oauth(
        base, route.get("api_key"), provider=route.get("provider")
    )
    resolved = resolve_request_settings(settings, route, model)
    overrides = dict(resolved["request_overrides"])
    if recovery is not None and model in (
        getattr(recovery, "_fast_mode_unavailable_models", None) or ()
    ):
        overrides.pop("speed", None)
    token = request_settings.set({**settings, **route})
    chat_token = chat_settings.set({**settings, **route})
    try:
        result = AnthropicTransport().build_kwargs(
            model,
            payload.get("messages", []),
            payload.get("tools"),
            max_tokens=payload.get("max_tokens", payload.get("max_completion_tokens")),
            reasoning_config=reasoning,
            is_oauth=oauth,
            preserve_dots=route.get(
                "preserve_dots",
                _anthropic_preserve_dots(
                    SimpleNamespace(provider=route.get("provider"), base_url=base)
                ),
            ),
            context_length=route.get("context_length", settings.get("context_length")),
            base_url=base,
            fast_mode=overrides.get("speed") == "fast",
            drop_context_1m_beta=bool(route.get("drop_context_1m_beta")),
        )
        if route.get("provider") in {"nous", "nous-portal", "nousresearch"}:
            extra = nous.build_extra_body(session_id=settings.get("session_id"))
            result.setdefault("extra_body", {}).update(extra)
        result["stream"] = route.get("stream", True)
        adapter.sanitize_anthropic_kwargs(result)
        tools = payload.get("tools") or []
        result["_wire_aliases"] = {
            "registered_tools": [
                tool.get("function", {}).get("name") for tool in tools
            ],
            "oauth": oauth,
        }
        return result
    finally:
        request_settings.reset(token)
        chat_settings.reset(chat_token)


def ingest_anthropic(data, wire_aliases=None):
    transport = AnthropicTransport()

    def namespace(value):
        if isinstance(value, dict):
            return SimpleNamespace(
                **{
                    key: item if key in {"input", "model_extra"} else namespace(item)
                    for key, item in value.items()
                }
            )
        if isinstance(value, list):
            return [namespace(item) for item in value]
        return value

    response = namespace(data)
    if not transport.validate_response(response):
        raise ValueError("Hermes provider returned an invalid Anthropic message")
    aliases = wire_aliases or {}
    token = request_settings.set(aliases)
    try:
        normalized = transport.normalize_response(
            response, strip_tool_prefix=aliases.get("oauth", False)
        )
    finally:
        request_settings.reset(token)
    message = {"role": "assistant", "content": normalized.content}
    if normalized.reasoning is not None:
        message["reasoning"] = normalized.reasoning
    for key, value in (normalized.provider_data or {}).items():
        message[
            "_anthropic_content_blocks" if key == "anthropic_content_blocks" else key
        ] = _plain(value)
    if normalized.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in normalized.tool_calls
        ]
    usage = copy.deepcopy(data.get("usage") or {})
    canonical = normalize_usage(usage, api_mode="anthropic_messages")
    usage.update(
        prompt_tokens=canonical.prompt_tokens,
        completion_tokens=canonical.output_tokens,
        total_tokens=canonical.total_tokens,
        prompt_tokens_details={
            "cached_tokens": canonical.cache_read_tokens,
            "cache_write_tokens": canonical.cache_write_tokens,
        },
    )
    return {
        **data,
        "choices": [{"message": message, "finish_reason": normalized.finish_reason}],
        "usage": usage,
    }


def decode_anthropic(text):
    try:
        return json.loads(text)
    except ValueError:
        pass
    message = None
    blocks = {}
    partial_json = {}
    stopped = False
    for packet in text.replace("\r\n", "\n").split("\n\n"):
        lines = [
            line[5:].lstrip()
            for line in packet.splitlines()
            if line.startswith("data:")
        ]
        if not lines:
            continue
        event = json.loads("\n".join(lines))
        kind = event.get("type")
        index = event.get("index", 0)
        if kind == "error":
            return {"error": event.get("error")}
        if kind == "message_start":
            message = copy.deepcopy(event["message"])
            for i, block in enumerate(message.get("content") or []):
                blocks[i] = block
        elif kind == "content_block_start":
            blocks[index] = copy.deepcopy(event["content_block"])
        elif kind == "content_block_delta":
            block, delta = blocks[index], event.get("delta", {})
            if delta.get("type") == "input_json_delta":
                partial_json[index] = partial_json.get(index, "") + delta.get(
                    "partial_json", ""
                )
            elif delta.get("type") == "citations_delta":
                block.setdefault("citations", []).append(delta.get("citation"))
            else:
                field = {
                    "text_delta": "text",
                    "thinking_delta": "thinking",
                    "signature_delta": "signature",
                }.get(delta.get("type"))
                if field:
                    block[field] = block.get(field, "") + delta.get(field, "")
        elif kind == "content_block_stop" and index in partial_json:
            blocks[index]["input"] = json.loads(partial_json[index])
        elif kind == "message_delta" and message is not None:
            message.update(event.get("delta") or {})
            message.setdefault("usage", {}).update(event.get("usage") or {})
        elif kind == "message_stop":
            stopped = True
    if message is None or not stopped:
        raise ValueError("Anthropic stream ended before message_stop")
    message["content"] = [block for _, block in sorted(blocks.items())]
    return message
