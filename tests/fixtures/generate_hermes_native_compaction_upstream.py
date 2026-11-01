"""Execute original Hermes native Responses helpers without FlashRSI or HTTP.

Reproduce with the upstream-only dependency environment:
  /tmp/hermes-loop-oracle-venv/bin/python tests/fixtures/generate_hermes_native_compaction_upstream.py /tmp/hermes-agent-v0.22.5-source

Imports and executes the pinned original modules. Only HERMES_HOME is isolated
and socket connections are prohibited; no helper or semantic dependency is mocked.
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
CODEX = "https://chatgpt.com/backend-api/codex"
OPENAI = "https://api.openai.com/v1"


def namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [namespace(item) for item in value]
    return value


def plain(value):
    if isinstance(value, SimpleNamespace):
        return {key: plain(item) for key, item in vars(value).items()}
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def generate(source):
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if actual != PIN:
        raise RuntimeError(f"Wrong upstream commit: {actual}")
    sys.path.insert(0, str(source))

    def deny_network(*args, **kwargs):
        raise RuntimeError("The pure-helper oracle prohibits network connections")

    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    logging.disable(logging.CRITICAL)
    from agent import codex_responses_adapter as adapter
    from agent import context_compressor, usage_pricing
    from agent import native_compaction as native
    from agent.transports.codex import ResponsesApiTransport

    functions = []

    def record(label, name, *args, **kwargs):
        result = getattr(native, name)(*copy.deepcopy(args), **copy.deepcopy(kwargs))
        functions.append(
            {
                "label": label,
                "name": name,
                "args": args,
                "kwargs": kwargs,
                "result": result,
            }
        )

    for model, provider, url in [
        ("gpt-5.6", None, None),
        ("GPT-5.6-mini-2026-07-15", None, None),
        ("vendor/gpt-5.6-sol", "custom", "https://proxy.example/v1"),
        ("gpt-5.3-codex", "openai-codex", CODEX),
        ("gpt-6-astra", "openai-codex", CODEX),
        ("vendor/gpt-6-astra-900k", "openai-codex", CODEX + "/"),
        ("gpt-6-astra", "openai", OPENAI),
        ("gpt-6-astra", "openai-codex", "https://proxy.example/codex"),
        (None, None, None),
    ]:
        record(
            str(model) + ":" + str(provider),
            "is_native_compaction_model",
            model,
            provider=provider,
            base_url=url,
        )
    for url, codex in [
        (OPENAI, False),
        (CODEX, True),
        (CODEX, False),
        ("https://api.openai.com.evil.example/v1", False),
        ("https://api.openai.com/v1", True),
        (None, False),
        ("https://[broken", False),
    ]:
        record(
            str(url) + ":" + str(codex),
            "is_direct_openai_route",
            url,
            is_codex_backend=codex,
        )
    for configured, local in [
        (None, None),
        (None, 765000),
        (200000, 100000),
        (200000, 765000),
        (None, 8192),
        (None, 4000),
        (None, 100),
        (1, 100000),
        (10, None),
        (True, 765000),
        (123.4, 765000),
        ("120000", 765000),
        ("12.5", 765000),
        (0, 765000),
        (-1, 765000),
        (None, "4000"),
    ]:
        record(
            f"configured={configured!r},local={local!r}",
            "resolve_compact_threshold",
            configured,
            local,
        )
    for params in [
        {"model": "gpt-5.6", "provider": "openai", "base_url": None},
        {"model": "gpt-5.6", "provider": "custom", "base_url": None},
        {"model": "gpt-5.6", "provider": "custom", "base_url": OPENAI},
        {
            "model": "gpt-6-astra",
            "provider": "openai-codex",
            "base_url": CODEX,
            "is_codex_backend": True,
        },
        {"model": "gpt-6-astra", "provider": "openai", "base_url": OPENAI},
    ]:
        record(
            json.dumps(params, sort_keys=True),
            "resolve_native_compaction_capabilities",
            **params,
        )
    for error, status in [
        ("unsupported field context_management", 400),
        ("unsupported field context_management", 500),
        ("unsupported field compact_threshold", 429),
        ("context_management appeared in request", 400),
        ("invalid compact_threshold", None),
        ("invalid compact_threshold", "not-a-number"),
        ("connection timed out", None),
    ]:
        record(f"{error}:{status}", "is_native_compaction_rejection", error, status)

    cp = {"type": "compaction", "encrypted_content": "checkpoint-new"}
    old_cp = {"type": "compaction", "encrypted_content": "checkpoint-old"}

    def user(content):
        return {"type": "message", "role": "user", "content": content}

    summary = {
        "type": "message",
        "role": "assistant",
        "content": "Canonical handoff summary",
        context_compressor.COMPRESSED_SUMMARY_METADATA_KEY: True,
    }
    for label, items, kwargs in [
        (
            "without_checkpoint_unchanged",
            [user("keep full"), {"role": "assistant", "content": "answer"}],
            {},
        ),
        (
            "newest_contiguous_checkpoint_run",
            [
                user("first ask"),
                old_cp,
                {"role": "assistant", "content": "discard ordinary history"},
                user("latest ask"),
                cp,
                {**cp, "encrypted_content": "checkpoint-new-part-2"},
                user("after checkpoint"),
            ],
            {},
        ),
        (
            "ascii_boundary_head",
            [user("older ask"), user("abcdefghijklmnop"), cp],
            {"retained_user_token_budget": 2},
        ),
        (
            "cjk_boundary_head",
            [user("old ask"), user("癌症治疗与检查方案"), cp],
            {"retained_user_token_budget": 3},
        ),
        (
            "cyrillic_boundary_head",
            [user("Привет мир привет"), cp],
            {"retained_user_token_budget": 3},
        ),
        (
            "typed_parts_keep_metadata",
            [
                user(
                    [
                        {"type": "input_text", "text": "abcd", "tag": "keep"},
                        {"type": "input_text", "text": "efghijkl", "tag": "truncate"},
                    ]
                ),
                cp,
            ],
            {"retained_user_token_budget": 2},
        ),
        (
            "image_only_one_token",
            [
                user(
                    [{"type": "input_image", "image_url": "data:image/png;base64,AA=="}]
                ),
                cp,
            ],
            {"retained_user_token_budget": 1},
        ),
        (
            "oversize_mixed_stops_older_asks",
            [
                user("old"),
                user(
                    [
                        {"type": "input_text", "text": "oversized ask"},
                        {
                            "type": "input_image",
                            "image_url": "https://example.invalid/image.png",
                        },
                    ]
                ),
                cp,
            ],
            {"retained_user_token_budget": 1},
        ),
        ("summary_kept_once_whole", [summary, user("ask"), summary, cp], {}),
        ("summary_never_sliced", [summary, cp], {"retained_summary_token_budget": 1}),
        (
            "summary_retention_disabled",
            [summary, user("ask"), cp],
            {"enable_summary_retention": False},
        ),
        (
            "source_summary_survives_lossy_tool_conversion",
            [
                {
                    "type": "function_call_output",
                    "call_id": "call_a",
                    "output": "stale",
                },
                cp,
            ],
            {"item_sources": [summary, None]},
        ),
    ]:
        record(label, "prune_pre_checkpoint_items", items, **kwargs)
    for label, items in [
        ("valid", [cp]),
        ("blank", [{"type": "compaction", "encrypted_content": " "}]),
        ("wrong_type", [{"type": "reasoning", "encrypted_content": "blob"}]),
        ("none", None),
    ]:
        record(label, "has_compaction_checkpoint", items)
    for label, prior, new in [
        (
            "carry_prior_checkpoint",
            [old_cp, {"type": "reasoning", "encrypted_content": "old-reason"}],
            [{"type": "reasoning", "encrypted_content": "new-reason"}],
        ),
        ("new_checkpoint_wins", [old_cp], [cp]),
        (
            "blank_new_checkpoint_keeps_prior",
            [old_cp],
            [{"type": "compaction", "encrypted_content": ""}],
        ),
        ("missing_new_keeps_checkpoint", [old_cp], None),
    ]:
        record(label, "merge_interim_reasoning_items", prior, new)

    agent_defaults = {
        "model": "gpt-5.6",
        "provider": "openai",
        "base_url": OPENAI,
        "codex_responses_native_compaction": True,
        "compression_enabled": True,
        "codex_responses_compact_threshold": None,
        "context_compressor": {"threshold_tokens": 100000},
        "capabilities": {},
    }
    context_cases = []
    for name, overrides, route in [
        ("eligible_auto_threshold", {}, {}),
        ("session_kill_switch", {"codex_responses_native_compaction": False}, {}),
        ("compression_disabled", {"compression_enabled": False}, {}),
        ("checkpoint_required_true", {"compression_checkpoint_required": True}, {}),
        (
            "checkpoint_required_integer_not_explicit_true",
            {"compression_checkpoint_required": 1},
            {},
        ),
        (
            "resolved_false_survives",
            {"runtime_capabilities": {"native_compaction": False}},
            {},
        ),
        ("resolved_empty_dict_is_false", {"runtime_capabilities": {}}, {}),
        ("xai_suppressed", {}, {"is_xai_responses": True}),
        ("github_suppressed", {}, {"is_github_responses": True}),
        ("untrusted_proxy_suppressed", {"base_url": "https://proxy.example/v1"}, {}),
        (
            "trusted_proxy_enabled",
            {
                "base_url": "https://proxy.example/v1",
                "capabilities": {"openai_native_compaction": True},
            },
            {},
        ),
        (
            "wrong_model_even_trusted_proxy",
            {
                "model": "gpt-5.3-codex",
                "capabilities": {"openai_native_compaction": True},
            },
            {},
        ),
        (
            "astra_official_codex",
            {
                "model": "gpt-6-astra-900k",
                "provider": "openai-codex",
                "base_url": CODEX,
            },
            {"is_codex_backend": True},
        ),
        ("astra_direct_api_suppressed", {"model": "gpt-6-astra"}, {}),
    ]:
        fields = {**copy.deepcopy(agent_defaults), **overrides}
        agent = SimpleNamespace(**fields)
        agent.context_compressor = namespace(fields["context_compressor"])
        flags = {"is_codex_backend": False, **route}
        result = native.native_compaction_context_management(agent, **flags)
        context_cases.append(
            {"name": name, "agent": fields, "route": flags, "result": result}
        )

    stamp = "other:" + OPENAI
    captured = {**cp, "_issuer_kind": stamp, "_issuer_model": "gpt-5.6"}
    history = [
        {"role": "system", "content": "system supplied separately"},
        {"role": "user", "content": "retain the plaintext user ask"},
        {"role": "assistant", "content": "before native boundary"},
        {
            "role": "assistant",
            "content": "checkpoint answer",
            "codex_reasoning_items": [captured],
        },
        {"role": "user", "content": "continue"},
    ]
    conversion_cases = []
    for name, overrides in [
        ("eligible_checkpoint_replay_prunes_old_assistant", {}),
        (
            "disabled_preserves_full_plaintext_history",
            {"native_compaction_eligible": False},
        ),
        ("foreign_issuer_omits_checkpoint", {"current_issuer_kind": "codex_backend"}),
        ("foreign_model_omits_checkpoint", {"current_issuer_model": "gpt-4.1"}),
        (
            "api_same_family_accepts_sibling_blob",
            {"current_issuer_model": "gpt-5.6-mini"},
        ),
        ("replay_session_kill_switch", {"replay_encrypted_reasoning": False}),
    ]:
        kwargs = {
            "current_issuer_kind": stamp,
            "current_issuer_model": "gpt-5.6",
            "native_compaction_eligible": True,
            **overrides,
        }
        result = adapter._chat_messages_to_responses_input(
            copy.deepcopy(history), **kwargs
        )
        conversion_cases.append(
            {"name": name, "messages": history, "kwargs": kwargs, "result": result}
        )
    capture_cases = []
    for kind, encrypted in [
        ("compaction", "opaque-checkpoint"),
        ("compaction", ""),
        ("reasoning", "opaque-reasoning"),
    ]:
        item = {
            "type": kind,
            "encrypted_content": encrypted,
            "id": "cp_a" if kind == "compaction" else "rs_a",
            "summary": [{"type": "summary_text", "text": "visible summary"}],
        }
        result = adapter._capture_encrypted_item(
            namespace(item), kind, stamp, "gpt-5.6"
        )
        capture_cases.append(
            {
                "name": kind + ("_empty" if not encrypted else "_nonempty"),
                "item": item,
                "issuer_kind": stamp,
                "issuer_model": "gpt-5.6",
                "result": result,
            }
        )
    usage_cases = []
    for name, raw in [
        (
            "responses_inclusive_cache_and_reasoning",
            {
                "input_tokens": 1000,
                "output_tokens": 100,
                "input_tokens_details": {
                    "cached_tokens": 400,
                    "cache_write_tokens": 100,
                    "cache_creation_tokens": 300,
                },
                "output_tokens_details": {"reasoning_tokens": 60},
            },
        ),
        (
            "legacy_cache_creation_fallback",
            {
                "input_tokens": 500,
                "output_tokens": 20,
                "input_tokens_details": {
                    "cached_tokens": 100,
                    "cache_creation_tokens": 50,
                },
            },
        ),
        (
            "cache_totals_cannot_make_negative_uncached",
            {
                "input_tokens": 10,
                "output_tokens": 3,
                "input_tokens_details": {"cached_tokens": 100},
            },
        ),
        ("missing_usage", None),
    ]:
        kwargs = {"provider": "openai", "api_mode": "codex_responses"}
        usage = usage_pricing.normalize_usage(copy.deepcopy(raw), **kwargs)
        result = {
            **dataclasses.asdict(usage),
            "prompt_tokens": usage.prompt_tokens,
            "total_tokens": usage.total_tokens,
        }
        usage_cases.append(
            {"name": name, "usage": raw, "kwargs": kwargs, "result": result}
        )
    tool_schemas = [
        {
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read text",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
    ]
    cm = [{"type": "compaction", "compact_threshold": 91808}]
    system = {
        "role": "system",
        "content": "Maintain this Python project. Complete the latest real user request.",
    }
    cp_history = [system, *history[1:]]
    codex_tool_history = [
        system,
        {"role": "user", "content": "Read note.txt then report."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_original_1",
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "arguments": '{"command":"cat note.txt"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_original_1", "content": "note body\n"},
    ]
    summary_history = [
        system,
        {"role": "user", "content": "Keep the latest request"},
        {
            "role": "assistant",
            "content": "[CONTEXT SUMMARY]:\nPrior completed steps and pending check.",
            context_compressor.COMPRESSED_SUMMARY_METADATA_KEY: True,
        },
        {"role": "user", "content": "Continue the pending check."},
    ]
    request_cases = []
    for name, model, messages, tools, overrides in [
        (
            "openai_gpt56_native_tools",
            "gpt-5.6",
            [system, {"role": "user", "content": "Inspect the failing test."}],
            tool_schemas,
            {"context_management": cm},
        ),
        (
            "codex_typed_text_and_tool_ids",
            "gpt-5.6",
            codex_tool_history,
            tool_schemas,
            {
                "provider": "openai-codex",
                "base_url": CODEX,
                "is_codex_backend": True,
                "context_management": cm,
            },
        ),
        ("summary_without_context_management", "gpt-5.6", summary_history, None, {}),
        (
            "explicit_reasoning_none",
            "gpt-5.6",
            [system, {"role": "user", "content": "Reply briefly."}],
            None,
            {"reasoning_config": {"enabled": False, "effort": "none"}},
        ),
        (
            "astra_900k_alias_sampling_sanitized",
            "gpt-6-astra-900k",
            [system, {"role": "user", "content": "Verify the proof."}],
            None,
            {
                "reasoning_config": {"enabled": True, "effort": "none"},
                "request_overrides": {
                    "temperature": 0.5,
                    "top_p": 0.9,
                    "logprobs": True,
                    "prompt_cache_retention": "24h",
                },
            },
        ),
        ("checkpoint_native_disabled_full_history", "gpt-5.6", cp_history, None, {}),
        (
            "checkpoint_native_enabled_wire_pruned",
            "gpt-5.6",
            cp_history,
            None,
            {"context_management": cm},
        ),
    ]:
        params = {
            "provider": "openai",
            "base_url": OPENAI,
            "session_id": "hermes-native-parity-session",
            "cache_scope_id": "hermes-native-parity-scope",
            "max_tokens": 1024,
            "timeout": 30,
            "reasoning_config": {"enabled": True, "effort": "high"},
            **copy.deepcopy(overrides),
        }
        transport = ResponsesApiTransport()
        result = transport.build_kwargs(
            model,
            copy.deepcopy(messages),
            copy.deepcopy(tools),
            **copy.deepcopy(params),
        )
        preflight = adapter._preflight_codex_api_kwargs(copy.deepcopy(result))
        request_cases.append(
            {
                "name": name,
                "model": model,
                "messages": messages,
                "tools": tools,
                "params": params,
                "result": result,
                "preflight": preflight,
                "transport_state": {
                    key: plain(getattr(transport, key))
                    for key in (
                        "_last_issuer_kind",
                        "_last_issuer_model",
                        "_last_wire_aliases",
                        "_last_sent_all_turns",
                    )
                },
            }
        )

    def message_item(text, *, phase="final_answer", status="completed"):
        return {
            "type": "message",
            "id": "msg_parity_answer",
            "role": "assistant",
            "status": status,
            "phase": phase,
            "content": [{"type": "output_text", "text": text}],
        }

    reasoning_item = {
        "type": "reasoning",
        "id": "rs_parity_reasoning",
        "encrypted_content": "opaque-reasoning",
        "summary": [{"type": "summary_text", "text": "Inspecting the next boundary."}],
    }
    normalize_cases = []
    for name, response, overrides in [
        (
            "completed_final_answer",
            {"status": "completed", "output": [message_item("All checks pass.")]},
            {},
        ),
        (
            "structured_function_call",
            {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "status": "completed",
                        "id": "fc_parity_terminal",
                        "call_id": "call_parity_terminal",
                        "name": "terminal",
                        "arguments": '{"command":"pwd"}',
                    }
                ],
            },
            {},
        ),
        (
            "compaction_with_final_answer",
            {
                "status": "completed",
                "output": [
                    {
                        "type": "compaction",
                        "id": "cp_not_replayed",
                        "encrypted_content": "opaque-cumulative-checkpoint",
                    },
                    message_item("Checkpoint saved; continue."),
                ],
            },
            {},
        ),
        (
            "codex_reasoning_only_requires_continuation",
            {"status": "completed", "output": [reasoning_item]},
            {"issuer_kind": "codex_backend"},
        ),
        (
            "openai_reasoning_only_trusted_completed",
            {"status": "completed", "output": [reasoning_item]},
            {},
        ),
        (
            "commentary_phase_is_not_final",
            {
                "status": "completed",
                "output": [
                    message_item("I will inspect the failing test.", phase="commentary")
                ],
            },
            {},
        ),
        (
            "incomplete_output_is_not_final",
            {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [message_item("partial answer", status="in_progress")],
            },
            {},
        ),
        (
            "leaked_harmony_tool_call_is_reelicited",
            {
                "status": "completed",
                "output": [message_item('to=functions.terminal {"command":"pwd"}')],
            },
            {},
        ),
        (
            "output_text_stream_fallback",
            {
                "status": "completed",
                "output": [],
                "output_text": "Streamed final answer.",
            },
            {},
        ),
    ]:
        kwargs = {"issuer_kind": stamp, "issuer_model": "gpt-5.6", **overrides}
        message, finish_reason = adapter._normalize_codex_response(
            namespace(copy.deepcopy(response)), **kwargs
        )
        normalize_cases.append(
            {
                "name": name,
                "response": response,
                "kwargs": kwargs,
                "result": {"message": plain(message), "finish_reason": finish_reason},
            }
        )
    paths = [
        "agent/native_compaction.py",
        "agent/codex_responses_adapter.py",
        "agent/usage_pricing.py",
        "agent/context_compressor.py",
        "agent/model_metadata.py",
        "agent/message_content.py",
        "agent/codex_headers.py",
        "agent/reasoning_effort.py",
        "agent/transports/codex.py",
    ]
    return {
        "upstream_repository": "https://github.com/NousResearch/hermes-agent",
        "upstream_commit": PIN,
        "generation": "Actual pinned upstream module imports and function execution; isolated HERMES_HOME and prohibited network; no FlashRSI modules or helper substitutes.",
        "source_sha256": {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in paths
        },
        "manual_compact_endpoint": "Pinned source has automatic context_management compaction; no /responses/compact endpoint invocation. CLI /compact uses Hermes compressor or Codex app-server thread/compact/start.",
        "functions": functions,
        "context_management": context_cases,
        "responses_input": conversion_cases,
        "capture": capture_cases,
        "usage": usage_cases,
        "request_build": request_cases,
        "normalize": normalize_cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("hermes_native_compaction_upstream.json"),
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-native-helpers-") as home:
        os.environ["HERMES_HOME"] = home
        os.environ["HERMES_SKIP_DOTENV"] = "1"
        evidence = generate(args.checkout.resolve())
        args.output.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n"
        )
    print(args.output)
