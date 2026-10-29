"""Local compaction requests and history replacements against native traces."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core.compact import (
    SUMMARY_PREFIX,
    _remove_first_with_pair,
    active_tokens,
    build_compacted_history,
    collect_user_messages,
    estimate_item_tokens,
    insert_initial_context,
    maybe_compact,
)
from flashrsi.agents.codex.python_core.context import message
from flashrsi.agents.codex.python_core.history import History, prepare_for_history
from flashrsi.agents.codex.python_core.models import Model


@pytest.mark.parametrize("token_limit,reported_tokens", [(1, 23), (32065, 32000)])
def test_native_local_midturn_compaction_parity(
    parity_source, upstream_codex, tmp_path, token_limit, reported_tokens
):
    # At 32,000 reported tokens the native tool result crosses 32,065 only
    # when its durable turn metadata participates in local token estimation.
    config_file = parity_source / "config.toml"
    config_file.write_text(
        f"model_auto_compact_token_limit = {token_limit}\n" + config_file.read_text()
    )
    task = tmp_path / "task"
    task.mkdir()
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset(
                [
                    (
                        200,
                        _events(
                            call=(
                                "shell_command",
                                {"command": "printf COMPACT_EVIDENCE"},
                            ),
                            response_id="resp_tool",
                        )
                        .replace(
                            b'"input_tokens": 20',
                            f'"input_tokens": {reported_tokens - 3}'.encode(),
                        )
                        .replace(
                            b'"total_tokens": 23',
                            f'"total_tokens": {reported_tokens}'.encode(),
                        ),
                    ),
                    (
                        200,
                        _events(
                            text="Retain COMPACT_EVIDENCE.", response_id="resp_compact"
                        ),
                    ),
                    (200, _events()),
                ]
            )
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "timeout": 30,
                "sandbox": "danger-full-access",
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run("Follow the compacted evidence.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert result.output == "PARITY_ANSWER", (
                "native" if binary else "python",
                len(replay.requests),
            )
            assert len(replay.requests) == 3 and not replay.errors and not replay.steps
            compact_request = replay.requests[1]["body"]
            assert compact_request["tools"] == []
            assert not compact_request["parallel_tool_calls"]
            metadata = json.loads(
                compact_request["client_metadata"]["x-codex-turn-metadata"]
            )
            assert metadata["request_kind"] == "compaction"
            assert metadata["compaction"]["phase"] == "mid_turn"
            assert "Retain COMPACT_EVIDENCE." in json.dumps(
                replay.requests[2]["body"]["input"]
            )
            observed.append(
                _normalize(
                    {"requests": replay.requests, "usage": dict(result.usage)}, tmp_path
                )
            )
    for label, trace in zip(("native", "python"), observed, strict=True):
        (tmp_path / (label + "-compact.json")).write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1], f"Compaction trace files in {tmp_path}"


def test_history_boundary_preserves_forked_turns_and_fills_missing_identity():
    inherited = message("user", "parent task")
    inherited["internal_chat_message_metadata_passthrough"] = {"turn_id": "parent"}
    prepared = prepare_for_history(inherited, "child")
    assert prepared == inherited
    new = {
        "type": "function_call_output",
        "id": "",
        "call_id": "call",
        "output": "proof",
        "internal_chat_message_metadata_passthrough": {"turn_id": ""},
    }
    prepared = prepare_for_history(new, "child")
    assert prepared["id"].startswith("fco_")
    assert prepared["internal_chat_message_metadata_passthrough"] == {
        "turn_id": "child"
    }
    assert new["id"] == "" and new["internal_chat_message_metadata_passthrough"] == {
        "turn_id": ""
    }
    additional = {"type": "additional_tools", "role": "developer", "tools": []}
    assert "internal_chat_message_metadata_passthrough" not in prepare_for_history(
        additional, "child"
    )


def test_context_exceeded_compacts_before_cached_continuation(parity_source, tmp_path):
    """Source-directed continuation check: turn.rs:1376, protocol.rs:2127."""
    from flashrsi.agents.codex.python_core.loop import close_session, run_session

    async def exercise(replay):
        cache = {}
        request = {
            "home": str(parity_source),
            "cwd": str(tmp_path),
            "prompt": "Collect evidence before solving.",
            "llm": {
                "model_name": "gpt-5",
                "base_url": replay.base_url,
                "api_key": "test",
            },
            "settings": {
                "model_context_window": 1000,
                "sandbox_mode": "danger-full-access",
                "features": {
                    "unified_exec": False,
                    "multi_agent": False,
                    "plugins": False,
                    "hooks": False,
                },
            },
            "_session_cache": cache,
        }
        failed = {
            "type": "response.failed",
            "response": {
                "error": {
                    "code": "context_length_exceeded",
                    "message": "context full",
                }
            },
        }
        replay.reset(
            [
                (
                    200,
                    _events(
                        call=("shell_command", {"command": "printf SAVED_EVIDENCE"}),
                        response_id="resp_tool",
                    ),
                ),
                (200, ("data: " + json.dumps(failed) + "\n\n").encode()),
            ]
        )
        try:
            first = await run_session(request, lambda event: None)
            assert (
                first["status"] == "error" and "context full" in first["error_message"]
            )
            assert len(replay.requests) == 2 and not replay.errors
            # Effective window = 95% of 1,000. Native fills aggregate usage and
            # sets last usage to the difference from the previous aggregate.
            history = cache["history"]
            assert history.usage["total_tokens"] == 950
            assert history.last_usage["total_tokens"] == 950 - 23
            assert not any(v for k, v in history.usage.items() if k != "total_tokens")
            replay.reset(
                [
                    (
                        200,
                        _events(text="Retain SAVED_EVIDENCE.", response_id="summary"),
                    ),
                    (200, _events()),
                ]
            )
            second = await run_session(
                {**request, "prompt": "Now finish using the evidence."},
                lambda event: None,
            )
            assert second["status"] == "finished", second
            assert len(replay.requests) == 2 and not replay.errors and not replay.steps
            compact_input = replay.requests[0]["body"]["input"]
            assert "SAVED_EVIDENCE" in json.dumps(compact_input)
            assert "Now finish" not in json.dumps(compact_input)
            metadata = json.loads(
                replay.requests[0]["body"]["client_metadata"]["x-codex-turn-metadata"]
            )
            assert metadata["compaction"]["phase"] == "pre_turn"
            final_input = replay.requests[1]["body"]["input"]
            assert not any(
                item["type"] == "function_call_output" for item in final_input
            )
            assert "Retain SAVED_EVIDENCE." in json.dumps(final_input)
            assert "Now finish using the evidence." in json.dumps(final_input)
        finally:
            await close_session(cache)

    with _responses_server() as replay:
        asyncio.run(exercise(replay))


def test_compaction_retains_real_users_and_preserves_content_concatenation():
    items = [
        message("user", "<environment_context>state</environment_context>"),
        message("user", '<hook_prompt hook_run_id="id">hook</hook_prompt>'),
        message(
            "user",
            '<codex_internal_context source="goal">hidden</codex_internal_context>',
        ),
        message("user", SUMMARY_PREFIX + "\nold summary"),
        message(
            "user",
            [
                {"type": "input_text", "text": "first"},
                {"type": "input_text", "text": "second"},
            ],
        ),
    ]
    assert collect_user_messages(items) == [{"text": "firstsecond", "metadata": None}]
    result = build_compacted_history(collect_user_messages(items), "summary", 1)
    assert result[-1]["content"][0]["text"] == "summary"
    assert "truncated" in result[0]["content"][0]["text"]


def test_compaction_insertion_prefers_agent_instruction_over_summary():
    context = [message("developer", "canonical")]
    instruction = {
        "type": "agent_message",
        "author": "parent",
        "recipient": "child",
        "content": [{"type": "input_text", "text": "work"}],
    }
    summary = message("user", SUMMARY_PREFIX + "\nsummary")
    items = [message("user", "old"), instruction, summary]
    assert insert_initial_context(items, context) == [
        items[0],
        *context,
        instruction,
        summary,
    ]
    final = copy.deepcopy(instruction)
    final["content"][0]["text"] = "Message Type: FINAL_ANSWER\ndone"
    assert insert_initial_context([final, summary], context) == [
        final,
        *context,
        summary,
    ]


def test_remove_first_output_removes_legacy_shell_counterpart():
    items = [
        {"type": "function_call_output", "call_id": "call", "output": "out"},
        {"type": "local_shell_call", "call_id": "call"},
        message("user", "keep"),
    ]
    _remove_first_with_pair(items)
    assert len(items) == 1 and items[0]["role"] == "user"


def test_reasoning_accounting_respects_server_header():
    history = History(Model("gpt-5", {}))
    reasoning = {"type": "reasoning", "encrypted_content": "a" * 1600, "summary": []}
    history.items = [
        reasoning,
        message("user", "follow-up"),
        message("assistant", "answer"),
        {"type": "function_call_output", "call_id": "x", "output": "local"},
    ]
    history.last_usage["total_tokens"] = 100
    expected = 100 + estimate_item_tokens(history.items[-1])
    assert active_tokens(history) == expected + estimate_item_tokens(reasoning)
    history.server_reasoning_included = True
    assert active_tokens(history) == expected


def test_pre_turn_compaction_omits_initial_context_until_caller_injects(tmp_path):
    model = Model("gpt-5", {"model_auto_compact_token_limit": 1})
    history = History(model)
    history.append(message("developer", "PRE_TURN_CONTEXT"))
    history.append(message("user", "old question"))
    history.append(message("assistant", "old answer"))
    history.last_usage["total_tokens"] = 10
    settings = {
        "_thread_id": "thread",
        "_turn_id": "turn",
        "_installation_id": "installation",
        "_started_at_unix_ms": 10,
        "sandbox_mode": "danger-full-access",
    }
    with _responses_server() as replay:
        replay.reset([(200, _events(text="PRE_TURN_SUMMARY"))])
        request = {
            "settings": settings,
            "llm": {"base_url": replay.base_url, "api_key": "test"},
            "_initial_context": history.items[:1],
            "_compaction_phase": "pre_turn",
        }
        assert asyncio.run(
            maybe_compact(
                history, model, request, SimpleNamespace(hooks=None), lambda event: None
            )
        )
        metadata = json.loads(
            replay.requests[0]["body"]["client_metadata"]["x-codex-turn-metadata"]
        )
        assert metadata["compaction"]["phase"] == "pre_turn"
        assert "PRE_TURN_CONTEXT" not in json.dumps(history.items)
        assert "PRE_TURN_SUMMARY" in json.dumps(history.items)
        assert history.window_number == 1 and settings["_window_number"] == 1


def test_precompact_hook_can_stop_before_request(tmp_path):
    from flashrsi.agents.codex.python_core.compact import compact
    from flashrsi.agents.codex.python_core.hooks import Hooks, HookStopped

    home = tmp_path / "home"
    home.mkdir()
    (home / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreCompact": [
                        {
                            "matcher": "auto",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'printf \'%s\' \'{"continue":false,"stopReason":"hold"}\'',
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )
    settings = {"_thread_id": "thread", "_turn_id": "turn", "model": "gpt-5"}
    events = []
    hooks = Hooks(home, tmp_path, settings, events.append, {})
    # Schemas live in the selected versioned resource home in production.
    import shutil
    from pathlib import Path

    from flashrsi.agents.codex.python_core import hooks as hooks_module

    shutil.copytree(
        Path(hooks_module.__file__).with_name("resource_assets") / "hook_schemas",
        home / "python_core/resource_assets/hook_schemas",
    )
    with _responses_server() as replay:
        request = {"settings": settings, "llm": {"base_url": replay.base_url}}
        with pytest.raises(HookStopped, match="hold"):
            asyncio.run(
                compact(
                    History(Model("gpt-5", {})),
                    Model("gpt-5", {}),
                    request,
                    SimpleNamespace(hooks=hooks),
                    events.append,
                )
            )
        assert not replay.requests
