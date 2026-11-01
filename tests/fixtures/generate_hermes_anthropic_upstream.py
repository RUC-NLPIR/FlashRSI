"""Execute original Hermes Anthropic conversion/transport offline, without SDK I/O."""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PIN = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"


def ns(value):
    if isinstance(value, dict):
        return SimpleNamespace(
            **{
                k: v if k in {"input", "model_extra"} else ns(v)
                for k, v in value.items()
            }
        )
    if isinstance(value, list):
        return [ns(v) for v in value]
    return value


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, SimpleNamespace):
        return plain(vars(value))
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def generate(source):
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        == PIN
    )
    sys.path.insert(0, str(source))

    def deny(*args, **kwargs):
        raise RuntimeError("offline Anthropic oracle prohibits network")

    socket.create_connection = deny
    socket.socket.connect = deny
    from agent import anthropic_adapter as adapter
    from agent.transports.anthropic import AnthropicTransport
    from agent.vision_message_prep import VisionMessagePrepMixin
    from hermes_constants import parse_reasoning_effort, resolve_reasoning_config
    from tools.registry import registry

    cases, responses, headers = [], [], []
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "Hermes Agent session_search memory tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"anyOf": [{"type": "string"}, {"type": "null"}]}
                    },
                },
            },
        }
        for name in ("read_file", "session_search", "memory", "mcp_linear_get_issue")
    ]
    for tool in tools:
        fn = tool["function"]
        registry.register(
            fn["name"], "fixture", fn, lambda **kwargs: "ok", override=True
        )

    def add(
        name,
        model="claude-opus-4.8",
        provider="anthropic",
        base="https://api.anthropic.com",
        effort=None,
        messages=None,
        **kwargs,
    ):
        route = {
            "model_name": model,
            "provider": provider,
            "base_url": base,
            "api_key": kwargs.pop("api_key", "sk-ant-api-fixture"),
        }
        route.update(kwargs.pop("route", {}))
        payload = {
            "model": model,
            "messages": copy.deepcopy(
                messages
                or [
                    {
                        "role": "system",
                        "content": "You are Hermes Agent from Nous Research. Use session_search, preserve tools/session_search.py and memory.",
                    },
                    {"role": "user", "content": "task"},
                ]
            ),
            "tools": copy.deepcopy(kwargs.pop("tools", tools)),
            "stream": False,
        }
        payload.update(kwargs.pop("payload", {}))
        settings = kwargs.pop("settings", {})
        if effort is not None:
            payload["reasoning_effort"] = effort
        cfg = (
            parse_reasoning_effort(effort)
            if effort is not None
            else resolve_reasoning_config(settings, model)
        )
        host = SimpleNamespace(provider=provider, base_url=base)
        expected = AnthropicTransport().build_kwargs(
            model,
            copy.deepcopy(payload["messages"]),
            copy.deepcopy(payload["tools"]),
            max_tokens=payload.get("max_tokens", payload.get("max_completion_tokens")),
            reasoning_config=cfg,
            is_oauth=adapter.anthropic_route_is_oauth(
                base, route["api_key"], provider=provider
            ),
            preserve_dots=route.get(
                "preserve_dots", VisionMessagePrepMixin._anthropic_preserve_dots(host)
            ),
            context_length=route.get("context_length", settings.get("context_length")),
            base_url=base,
            fast_mode=(route.get("request_overrides") or {}).get("speed") == "fast",
            drop_context_1m_beta=bool(route.get("drop_context_1m_beta")),
        )
        cases.append(
            dict(
                name=name,
                payload=payload,
                route=route,
                settings=settings,
                expected=plain(expected),
            )
        )

    for model in (
        "claude-3-haiku-20240307",
        "claude-3-7-sonnet-latest",
        "claude-opus-4.5",
        "claude-opus-4.6",
        "claude-opus-4.7",
        "claude-opus-4.8",
        "claude-opus-5.5",
        "claude-sonnet-5.5",
        "claude-haiku-5.5",
        "claude-fable",
        "claude-future",
    ):
        for effort in (None, "none", "high", "xhigh", "ultra"):
            add(model + "/" + str(effort), model=model, effort=effort)
    for provider, model, base in (
        ("minimax", "MiniMax-M2.7", "https://api.minimax.io/anthropic"),
        ("kimi", "kimi-k2.5", "https://api.kimi.com/coding"),
        ("alibaba", "qwen3.5-plus", "https://dashscope.aliyuncs.com/apps/anthropic"),
        ("opencode-go", "minimax-m2.5", "https://opencode.ai/zen/go/v1"),
        ("custom", "claude-opus-4.8", "https://proxy.example/anthropic"),
    ):
        for effort in (None, "none", "high"):
            add(
                provider + "/" + str(effort),
                model=model,
                provider=provider,
                base=base,
                effort=effort,
            )
    for cap in (0, -1, True, 1.9, 1000000):
        add(
            "cap/" + str(cap),
            payload={"max_tokens": cap},
            route={"context_length": 32768},
            effort="high",
        )
    add("oauth_aliases", api_key="sk-ant-oat-fixture", effort="high")
    add(
        "oauth_alias_collision",
        api_key="sk-ant-oat-fixture",
        tools=tools
        + [
            {
                "type": "function",
                "function": {"name": "chat_history_lookup", "parameters": {}},
            }
        ],
    )
    add("fast_native", route={"request_overrides": {"speed": "fast"}})
    add(
        "fast_compat_omitted",
        provider="custom",
        base="https://proxy.example/anthropic",
        route={"request_overrides": {"speed": "fast"}},
    )
    replay = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": "",
            "reasoning": "first",
            "reasoning_details": [
                {"type": "thinking", "thinking": "first", "signature": "s1"}
            ],
            "_anthropic_content_blocks": [
                {"type": "thinking", "thinking": "first", "signature": "s1"},
                {
                    "type": "tool_use",
                    "id": "c",
                    "name": "read_file",
                    "input": {"path": "note.txt"},
                },
                {"type": "thinking", "thinking": "second", "signature": "s2"},
            ],
            "tool_calls": [
                {
                    "id": "c",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"note.txt"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "c",
            "name": "read_file",
            "content": [
                {"type": "text", "text": "ok"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
                },
            ],
        },
        {"role": "user", "content": "continue"},
    ]
    for name, model, base in (
        ("native", "claude-opus-4.8", "https://api.anthropic.com"),
        ("legacy", "claude-3-7-sonnet-latest", "https://api.anthropic.com"),
        ("kimi", "kimi-k2.5", "https://api.kimi.com/coding"),
        ("compat", "claude-opus-4.8", "https://proxy.example/anthropic"),
    ):
        add("replay/" + name, model=model, base=base, messages=replay)
    add(
        "blank_and_schema",
        messages=[
            {"role": "system", "content": ""},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "text", "text": "actual", "citations": None},
                ],
            },
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "nullable",
                    "parameters": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {"n": {"type": ["string", "null"]}},
                            },
                            {"type": "null"},
                        ]
                    },
                },
            }
        ],
    )
    add(
        "unsupported_inline",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/bmp;base64,Ynl0ZXM="},
                    },
                    {"type": "text", "text": "read"},
                ],
            }
        ],
    )

    response_values = [
        (
            "text",
            {
                "content": [{"type": "text", "text": "answer"}],
                "stop_reason": "end_turn",
            },
        ),
        (
            "thinking_tool_order",
            {
                "content": [
                    {"type": "thinking", "thinking": "first", "signature": "s1"},
                    {
                        "type": "tool_use",
                        "name": "read_file",
                        "id": "c",
                        "input": {"path": "note.txt"},
                    },
                    {"type": "thinking", "thinking": "second", "signature": "s2"},
                ],
                "stop_reason": "tool_use",
            },
        ),
        (
            "oauth_aliases",
            {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "mcp__chat_history_lookup",
                        "id": "c",
                        "input": {},
                    }
                ],
                "stop_reason": "tool_use",
            },
        ),
        (
            "redacted",
            {
                "content": [
                    {"type": "redacted_thinking", "data": "encrypted"},
                    {"type": "text", "text": "answer", "citations": None},
                ],
                "stop_reason": "end_turn",
            },
        ),
        ("refusal", {"content": [], "stop_reason": "refusal"}),
        (
            "length",
            {
                "content": [{"type": "text", "text": "partial"}],
                "stop_reason": "max_tokens",
            },
        ),
        (
            "pause",
            {
                "content": [{"type": "text", "text": "partial"}],
                "stop_reason": "pause_turn",
            },
        ),
        ("context", {"content": [], "stop_reason": "model_context_window_exceeded"}),
        (
            "guardrail",
            {
                "content": [{"type": "text", "text": "blocked"}],
                "stop_reason": "end_turn",
                "model_extra": {"amazon-bedrock-guardrailAction": "INTERVENED"},
            },
        ),
        (
            "stop_details",
            {
                "content": [{"type": "text", "text": "partial"}],
                "stop_reason": "max_tokens",
                "stop_details": {"reason": "budget"},
            },
        ),
    ]
    for name, raw in response_values:
        raw.setdefault(
            "usage",
            {
                "input_tokens": 123,
                "output_tokens": 20,
                "cache_read_input_tokens": 40,
                "cache_creation_input_tokens": 10,
            },
        )
        transport = AnthropicTransport()
        value = ns(raw)
        valid = transport.validate_response(value)
        responses.append(
            dict(
                name=name,
                raw=raw,
                aliases={
                    "registered_tools": ["read_file", "session_search", "memory"],
                    "oauth": name == "oauth_aliases",
                },
                valid=valid,
                expected=plain(
                    transport.normalize_response(
                        value, strip_tool_prefix=name == "oauth_aliases"
                    )
                )
                if valid
                else None,
                cache=transport.extract_cache_stats(value),
            )
        )

    # The SDK client constructor is an I/O boundary; capture exactly what the
    # real client factory passed it, without importing/constructing an SDK.
    sdk = SimpleNamespace(Anthropic=lambda **kw: kw, Omit=lambda: "<OMIT>")
    with (
        patch.object(adapter, "_require_sdk", return_value=sdk),
        patch.object(adapter, "_get_claude_code_version", return_value="2.1.74"),
    ):
        for name, base, key in (
            ("native_api", "https://api.anthropic.com", "sk-ant-api-fixture"),
            ("native_oauth", "https://api.anthropic.com/v1", "sk-ant-oat-fixture"),
            ("minimax", "https://api.minimax.io/anthropic", "key"),
            ("kimi", "https://api.kimi.com/coding", "key"),
            ("proxy", "https://proxy.example/anthropic/v1", "key"),
            ("opencode", "https://opencode.ai/zen/go/v1", "key"),
            ("azure", "https://fixture.services.ai.azure.com/anthropic", "key"),
        ):
            client = adapter.build_anthropic_client(key, base)
            headers.append(
                dict(
                    name=name,
                    route={"base_url": base, "api_key": key},
                    expected={
                        k: v
                        for k, v in client["default_headers"].items()
                        if v != "<OMIT>"
                    },
                    credential_style="bearer" if "auth_token" in client else "api_key",
                    query=client.get("default_query"),
                )
            )
    return dict(
        commit=PIN,
        cases=cases,
        responses=responses,
        headers=headers,
        sources={
            p: hashlib.sha256((source / p).read_bytes()).hexdigest()
            for p in (
                "agent/anthropic_adapter.py",
                "agent/anthropic_message_convert.py",
                "agent/transports/anthropic.py",
            )
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("hermes_anthropic_upstream.json"),
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-anthropic-oracle-") as home:
        os.environ["HERMES_HOME"] = home
        args.output.write_text(
            json.dumps(generate(args.source), indent=2, ensure_ascii=False) + "\n"
        )
