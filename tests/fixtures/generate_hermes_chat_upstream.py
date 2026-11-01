"""Execute the pinned original Chat transport and real bundled profiles offline.

Use the upstream-only venv and pass the pinned upstream checkout. No FlashRSI
imports, SDK client construction, semantic dependency mocks, or model requests.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

PIN = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"


def ns(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: ns(v) for k, v in value.items()})
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
    if isinstance(value, (list, tuple)):
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

    def deny(*a, **kw):
        raise RuntimeError("Offline original-source oracle prohibits network")

    socket.create_connection = deny
    socket.socket.connect = deny
    logging.disable(logging.CRITICAL)
    from agent.reasoning_carriers import shape_wire_carriers
    from agent.transports.chat_completions import (
        ChatCompletionsTransport,
        _rename_tool_search_bridge_for_xai,
    )
    from hermes_constants import parse_reasoning_effort, resolve_reasoning_config
    from providers import get_provider_profile
    from utils import (
        base_url_host_matches,
        base_url_hostname,
        model_forces_max_completion_tokens,
    )

    rows = []
    msg = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    tool = {
        "type": "function",
        "function": {
            "name": "read_file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    }

    def add(
        name,
        model="test",
        provider="",
        base="https://proxy.example/v1",
        effort=None,
        **kw,
    ):
        payload = {
            "model": model,
            "messages": copy.deepcopy(kw.pop("messages", msg)),
            "tools": copy.deepcopy(kw.pop("tools", [tool])),
            "stream": False,
        }
        route = {
            "provider": provider,
            "base_url": base,
            "model_name": model,
            **kw.pop("route", {}),
        }
        settings = kw.pop("settings", {})
        if effort is not None:
            payload["reasoning_effort"] = effort
        payload.update(kw.pop("payload", {}))
        profile = get_provider_profile(provider) if provider else None
        cfg = (
            parse_reasoning_effort(effort)
            if effort is not None
            else route.get("reasoning_config")
        )
        if cfg is None and not settings.get("_chat_auxiliary"):
            cfg = resolve_reasoning_config(settings, model)
        if (
            cfg is None
            and profile
            and not settings.get("_chat_auxiliary")
            and route.get("supports_reasoning") is not False
        ):
            cfg = profile.default_reasoning_config(model)
        completion = (
            base_url_hostname(base) == "api.openai.com"
            or base_url_host_matches(base, "openai.azure.com")
            or base_url_host_matches(base, "githubcopilot.com")
            or model_forces_max_completion_tokens(model)
        )
        params = {
            "base_url": base,
            "provider_name": provider,
            "provider_profile": profile,
            "model_lower": model.lower(),
            "reasoning_config": cfg,
            "supports_reasoning": route.get(
                "supports_reasoning",
                base_url_host_matches(base, "openrouter.ai")
                and model.startswith(
                    (
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
                ),
            ),
            "max_tokens_param_fn": lambda v: {
                "max_completion_tokens" if completion else "max_tokens": v
            },
            "max_tokens": payload.get(
                "max_completion_tokens", payload.get("max_tokens")
            ),
        }
        for key in (
            "session_id",
            "cache_scope_id",
            "provider_preferences",
            "openrouter_min_coding_score",
            "ollama_num_ctx",
            "supports_prompt_cache_key",
            "extra_body_additions",
        ):
            if key in route:
                params[key] = route[key]
        overrides = {
            k: copy.deepcopy(v)
            for k, v in payload.items()
            if k
            not in {
                "model",
                "messages",
                "tools",
                "max_tokens",
                "max_completion_tokens",
                "reasoning_effort",
            }
        }
        overrides.update(settings.get("request_overrides") or {})
        overrides.update(route.get("request_overrides") or {})
        params["request_overrides"] = overrides
        messages = shape_wire_carriers(
            copy.deepcopy(payload["messages"]), model=model, base_url=base
        )
        tools = copy.deepcopy(payload.get("tools"))
        aliases = {}
        if tools and (
            provider in {"xai", "xai-oauth"} or base_url_hostname(base) == "api.x.ai"
        ):
            tools, aliases = _rename_tool_search_bridge_for_xai(tools)
        transport = ChatCompletionsTransport()
        transport._last_wire_aliases = aliases
        result = transport.build_kwargs(model, messages, tools, **params)
        result["_wire_aliases"] = aliases
        rows.append(
            {
                "name": name,
                "payload": payload,
                "route": route,
                "settings": settings,
                "expected": plain(result),
            }
        )

    add("generic")
    add(
        "openai_cache_and_cap",
        model="gpt-4o",
        base="https://api.openai.com/v1",
        payload={"max_tokens": 128},
        route={"session_id": "session"},
    )
    add("developer_role", model="gpt-5-test", base="https://api.openai.com/v1")
    add("strict_endpoint_no_cache", base="https://api.openai.com.evil/v1")
    add(
        "explicit_cache_bound",
        route={"request_overrides": {"prompt_cache_key": "x" * 100}},
    )
    add("custom_default", provider="custom")
    add(
        "custom_non_reasoning_metadata",
        provider="custom",
        route={"supports_reasoning": False},
    )
    add("custom_auxiliary", provider="custom", settings={"_chat_auxiliary": True})
    for effort in ("none", "medium", "ultra"):
        add("custom_" + effort, provider="custom", effort=effort)
        add("kimi_" + effort, provider="kimi", model="kimi-k3", effort=effort)
        add(
            "deepseek_" + effort,
            provider="deepseek",
            model="deepseek-v4-pro",
            effort=effort,
        )
        add(
            "openrouter_" + effort,
            provider="openrouter",
            model="openai/gpt-5.4",
            base="https://openrouter.ai/api/v1",
            effort=effort,
            route={"session_id": "sess"},
        )
    add(
        "ollama_off",
        provider="custom",
        base="http://localhost:11434/v1",
        effort="none",
        route={"ollama_num_ctx": 32768},
    )
    add(
        "custom_groq_effort",
        provider="custom",
        base="https://api.groq.com/openai/v1",
        effort="high",
    )
    add("kimi_default_cap", provider="kimi", model="kimi-k2.5")
    add(
        "moonshot_schema",
        provider="kimi",
        model="kimi-k2.5",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "x",
                    "parameters": {
                        "properties": {"item": {"enum": ["a", "b"]}, "value": {}}
                    },
                },
            }
        ],
    )
    add(
        "openrouter_mandatory_anthropic",
        provider="openrouter",
        model="anthropic/claude-sonnet-4.6",
        base="https://openrouter.ai/api/v1",
        effort="high",
    )
    add(
        "openrouter_speed_and_routing",
        provider="openrouter",
        model="openai/gpt-6-astra-fast",
        base="https://openrouter.ai/api/v1",
        effort="high",
        route={"provider_preferences": {"sort": "price"}, "session_id": "s"},
    )
    add(
        "openrouter_grok_fork",
        provider="openrouter",
        model="x-ai/grok-4.6",
        base="https://openrouter.ai/api/v1",
        route={"session_id": "s", "cache_scope_id": "s::fork"},
    )
    add(
        "extra_body_merge",
        provider="custom",
        route={
            "extra_body_additions": {"a": 1, "b": 2},
            "request_overrides": {"extra_body": {"b": 3, "c": 4}, "seed": 4},
        },
    )
    replay = msg + [
        {
            "role": "assistant",
            "content": None,
            "message_uid": "private",
            "_private": 1,
            "reasoning_content": "think",
            "reasoning_details": [
                {"type": "hermes.native_assistant", "reasoning_opaque": "opaque"}
            ],
            "tool_calls": [
                {
                    "id": "call_0123456789",
                    "call_id": "c",
                    "response_item_id": "i",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                    "extra_content": {"google": {"thought_signature": "sig"}},
                }
            ],
        },
        {"role": "tool", "content": "ok", "tool_call_id": "c", "name": "read_file"},
    ]
    add("strict_replay_strip", messages=replay)
    add("mistral_replay_ids", model="mistral", messages=replay)
    add("gemini_signature_replay", model="google/gemini-3.8-flash", messages=replay)
    add(
        "xai_alias_collision",
        provider="xai",
        base="https://api.x.ai/v1",
        tools=[
            {"type": "function", "function": {"name": n, "parameters": {}}}
            for n in ("tool_search", "hermes_tool_search")
        ],
    )
    for effort in ("none", "medium", "ultra"):
        add(
            "gemini_compat_" + effort,
            provider="gemini",
            model="gemini-3.8-flash",
            base="https://generativelanguage.googleapis.com/v1beta/openai",
            effort=effort,
            payload={"max_tokens": 256},
        )
    for effort in ("none", "high", False, {"enabled": True, "effort": "bespoke"}):
        add(
            "snapshot_reasoning_" + str(effort),
            provider="custom",
            model="qwen3",
            settings={"agent": {"reasoning_effort": effort}},
        )
    add(
        "snapshot_model_reasoning_override",
        provider="custom",
        model="qwen3.6:27b",
        settings={
            "agent": {
                "reasoning_effort": "high",
                "reasoning_overrides": {"ollama-local/qwen3.6:27b": False},
            }
        },
    )
    # Actual bundled HTTP profiles, including their model-specific effort
    # vocabularies, message transforms, output caps and attribution headers.
    profile_models = {
        "actual": "fixture",
        "ai-gateway": "openai/gpt-5.4",
        "alibaba": "qwen3.6-plus",
        "alibaba-coding-plan": "qwen3.6-plus",
        "arcee": "trinity-large",
        "azure-foundry": "gpt-4o",
        "copilot": "fixture",
        "deepinfra": "deepseek-ai/DeepSeek-V4-Pro",
        "fireworks": "accounts/fireworks/models/kimi-k2.5",
        "gmi": "fixture",
        "huggingface": "fixture",
        "kilocode": "fixture",
        "lmstudio": "qwen3",
        "meta-ai": "muse-spark",
        "minimax": "MiniMax-M3",
        "nebius-token-factory": "deepseek-ai/DeepSeek-V3.2",
        "nous": "deepseek-v4-pro",
        "novita": "fixture",
        "nvidia": "nvidia/nemotron-3.5-super",
        "ollama-cloud": "qwen3.6:27b",
        "opencode-zen": "ox-alpha",
        "opencode-go": "deepseek-v4-pro",
        "qwen-oauth": "qwen3-coder-plus",
        "stepfun": "step-3.5-flash",
        "tencent-tokenhub": "hy3-preview",
        "upstage": "solar-pro3",
        "xiaomi": "mimo-v2.6-pro",
        "zai": "glm-5.2",
    }
    for provider, model in profile_models.items():
        profile = get_provider_profile(provider)
        for effort in (None, "none", "high", "ultra"):
            add(
                "profile/" + provider + "/" + str(effort),
                model=model,
                provider=provider,
                base="https://api.minimax.io/v1"
                if provider == "minimax"
                else (profile.base_url or "http://localhost:1234/v1"),
                effort=effort,
                route={"supports_reasoning": True, "session_id": "session"},
            )
    for model in ("glm-5.2", "kimi-k2.5", "deepseek-flash", "mimo-v2.5-pro"):
        add("opencode-go/" + model, model=model, provider="opencode-go", effort="ultra")
    add(
        "qwen_multipart",
        model="qwen-vl",
        provider="qwen-oauth",
        messages=[
            {"role": "system", "content": "system"},
            {
                "role": "user",
                "content": [
                    "literal",
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example/image.png"},
                    },
                    42,
                ],
            },
        ],
    )
    headers = [
        {
            "provider": name,
            "expected": dict(get_provider_profile(name).default_headers),
        }
        for name in (
            "custom",
            "kimi",
            "deepseek",
            "openrouter",
            "gemini",
            "xai",
            *profile_models,
        )
    ]
    responses = []
    for name, raw in [
        (
            "multipart_content",
            {
                "choices": [
                    {
                        "message": {
                            "content": [{"type": "text", "text": "multipart answer"}]
                        }
                    }
                ]
            },
        ),
        (
            "object_tool_arguments",
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": {"path": "note.txt"},
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        ),
        (
            "nullable_cache_details",
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens_details": None, "prompt_cache_hit_tokens": 25},
            },
        ),
        (
            "structured_refusal",
            {
                "choices": [
                    {
                        "finish_reason": "STOP",
                        "message": {"content": None, "refusal": "blocked"},
                    }
                ]
            },
        ),
        (
            "uppercase_length",
            {
                "choices": [
                    {"finish_reason": "MAX_TOKENS", "message": {"content": "partial"}}
                ]
            },
        ),
        (
            "cache_deepseek",
            {
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 2,
                    "prompt_cache_hit_tokens": 25,
                },
            },
        ),
        (
            "cache_openai",
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens_details": {
                        "cached_tokens": 10,
                        "cache_write_tokens": 7,
                    }
                },
            },
        ),
        (
            "reasoning_and_signatures",
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "reasoning_content": "thinking",
                            "reasoning_text": "readable",
                            "reasoning_opaque": "opaque",
                            "extra_content": {
                                "google": {"thought_signature": "msgsig"}
                            },
                            "tool_calls": [
                                {
                                    "id": "c",
                                    "function": {
                                        "name": "hermes_tool_search",
                                        "arguments": "{}",
                                        "thought_signature": "fnsig",
                                    },
                                    "extra_content": {
                                        "google": {"thought_signature": "callsig"}
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        ),
        (
            "router_timeout",
            {
                "choices": [
                    {"message": {"content": "Connect timeout, please try again later."}}
                ],
                "usage": {},
            },
        ),
        (
            "actual_timeout_text",
            {
                "choices": [
                    {"message": {"content": "Connect timeout, please try again later."}}
                ],
                "usage": {"completion_tokens": 4},
            },
        ),
    ]:
        transport = ChatCompletionsTransport()
        transport._last_wire_aliases = {"hermes_tool_search": "tool_search"}
        shaped = ns(raw)
        valid = transport.validate_response(shaped)
        responses.append(
            {
                "name": name,
                "input": raw,
                "aliases": transport._last_wire_aliases,
                "valid": valid,
                "normalized": plain(transport.normalize_response(shaped))
                if valid
                else None,
                "cache": transport.extract_cache_stats(shaped),
            }
        )
    return {
        "commit": PIN,
        "cases": rows,
        "headers": headers,
        "responses": responses,
        "source_sha256": hashlib.sha256(
            (source / "agent/transports/chat_completions.py").read_bytes()
        ).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("hermes_chat_upstream.json"),
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-chat-oracle-") as home:
        os.environ["HERMES_HOME"] = home
        args.output.write_text(
            json.dumps(generate(args.source), indent=2, ensure_ascii=False) + "\n"
        )
