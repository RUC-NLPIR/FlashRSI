"""Malformed server items follow the pinned serde boundary before task execution."""

import asyncio
import json

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_python_long_context import _server, _with_usage

import flashrsi.agents.codex as adapter
from flashrsi.agents import Codex


def _with_item(item, response):
    event = {"type": "response.output_item.done", "item": item}
    return ("data: " + json.dumps(event) + "\n\n").encode() + response


def _config(source, replay, binary):
    config = {
        "source_dir": source,
        "sandbox": "danger-full-access",
        "timeout": 30,
        "llm": {
            "model_name": "gpt-5.4",
            "api_key": "local-validation-test-key",
            "base_url": replay.base_url,
        },
    }
    if binary:
        config["cli_path"] = binary
    return config


@pytest.mark.parametrize("encrypted", ["missing", None, 42])
def test_native_and_python_reject_malformed_checkpoint_before_replacing_task_history(
    encrypted, parity_source, upstream_codex, tmp_path, monkeypatch
):
    config_file = parity_source / "config.toml"
    config_file.write_text(
        "model_auto_compact_token_limit=100\n"
        + config_file.read_text()
        + "shell_snapshot=false\n"
    )
    original_settings = adapter._settings

    def settings(*args, **kwargs):
        overrides, environment, native = original_settings(*args, **kwargs)
        overrides["model_providers.flashrsi.name"] = "Azure"
        return overrides, environment, native

    monkeypatch.setattr(adapter, "_settings", settings)
    task = tmp_path / "task"
    task.mkdir()
    first = _events(
        call=("shell_command", {"command": "printf x >> attempts"}),
        response_id="resp_save",
    ).replace(b'"input_tokens": 20', b'"input_tokens": 32000')
    first = first.replace(b'"total_tokens": 23', b'"total_tokens": 32003')
    checkpoint = {"type": "compaction", "id": "cmp_invalid"}
    if encrypted != "missing":
        checkpoint["encrypted_content"] = encrypted
    malformed = _with_item(
        checkpoint, _events(text="ignored", response_id="resp_compact")
    )
    observed = []
    with _responses_server() as replay:
        for label, binary in (("native", upstream_codex), ("python", None)):
            (task / "attempts").unlink(missing_ok=True)
            replay.reset(
                [
                    (200, first),
                    (200, malformed),
                    (200, _events("MUST_NOT_CONTINUE_AFTER_INVALID_CHECKPOINT")),
                ]
            )
            result = asyncio.run(
                Codex(_config(parity_source, replay, binary)).run(
                    "Write evidence then finish after compaction.", working_dir=task
                )
            )
            assert result.status == "error", result.error_message
            assert (
                "expected exactly one compaction output item, got 0 from 1 output items"
                in result.error_message
            )
            assert len(replay.requests) == 2 and len(replay.steps) == 1
            assert not replay.errors and (task / "attempts").read_text() == "x"
            trace = _normalize(
                {
                    "requests": replay.requests,
                    "status": result.status,
                    "output": result.output,
                    "usage": dict(result.usage),
                    "file": (task / "attempts").read_text(),
                },
                tmp_path,
            )
            (tmp_path / f"{label}-checkpoint-validation.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2)
            )
            observed.append(trace)
    assert observed[0] == observed[1], f"Full malformed-checkpoint traces in {tmp_path}"


@pytest.mark.parametrize(
    "malformed",
    [
        {"type": "message", "id": "bad", "role": "assistant"},
        {
            "type": "message",
            "id": "bad",
            "role": "assistant",
            "content": [{"type": "output_text", "text": 42}],
        },
        {
            "type": "message",
            "id": 42,
            "role": "assistant",
            "content": [],
        },
        {"type": "reasoning", "id": "bad", "encrypted_content": "secret"},
        {
            "type": "function_call",
            "id": "bad",
            "call_id": "bad_call",
            "name": "shell_command",
            "arguments": {"command": "touch invalid-call-ran"},
        },
        {
            "type": "custom_tool_call",
            "id": "bad",
            "call_id": "bad_call",
            "name": "apply_patch",
            "input": None,
        },
        {"type": "additional_tools", "role": "developer", "tools": {}},
        {"type": "agent_message", "author": "agent", "recipient": 42, "content": []},
        {"type": "function_call_output", "call_id": "orphan", "output": 42},
        {
            "type": "custom_tool_call_output",
            "call_id": "orphan",
            "output": [{"type": "input_text", "text": False}],
        },
        {
            "type": "local_shell_call",
            "call_id": "bad_call",
            "status": "wrong",
            "action": {"type": "exec", "command": ["touch", "invalid-call-ran"]},
        },
        {"type": "tool_search_call", "execution": 42, "arguments": {}},
        {
            "type": "tool_search_output",
            "status": "completed",
            "execution": "client",
            "tools": {},
        },
        {"type": "web_search_call", "action": {"type": "search", "queries": [42]}},
        {"type": "image_generation_call", "status": "completed"},
        {
            "type": "message",
            "role": "assistant",
            "content": [],
            "internal_chat_message_metadata_passthrough": {"turn_id": 42},
        },
    ],
    ids=[
        "content-required",
        "text-string",
        "id-string",
        "summary-required",
        "args-string",
        "input-string",
        "additional-tools-array",
        "agent-recipient-string",
        "function-output-body",
        "custom-output-text",
        "shell-status-enum",
        "search-execution-string",
        "search-output-array",
        "web-query-string",
        "image-result-required",
        "metadata-turn-id-string",
    ],
)
def test_native_and_python_discard_malformed_items_and_complete_the_same_task(
    malformed, parity_source, upstream_codex, tmp_path
):
    config_file = parity_source / "config.toml"
    config_file.write_text(config_file.read_text() + "shell_snapshot=false\n")
    task = tmp_path / "task"
    task.mkdir()
    first = _with_item(
        malformed,
        _events(
            call=(
                "shell_command",
                {"command": "printf VALID_TOOL_EVIDENCE > evidence"},
            ),
            response_id="resp_valid_call",
        ),
    )
    observed = []
    with _responses_server() as replay:
        for label, binary in (("native", upstream_codex), ("python", None)):
            (task / "evidence").unlink(missing_ok=True)
            replay.reset([(200, first), (200, _events("VALID_TASK_COMPLETED"))])
            result = asyncio.run(
                Codex(_config(parity_source, replay, binary)).run(
                    "Write the supplied evidence and finish.", working_dir=task
                )
            )
            assert result.status == "finished", result.error_message
            assert result.output == "VALID_TASK_COMPLETED"
            assert not replay.errors and not replay.steps and len(replay.requests) == 2
            assert (task / "evidence").read_text() == "VALID_TOOL_EVIDENCE"
            assert not (task / "invalid-call-ran").exists()
            trace = _normalize(
                {
                    "requests": replay.requests,
                    "status": result.status,
                    "output": result.output,
                    "usage": dict(result.usage),
                    "file": (task / "evidence").read_text(),
                },
                tmp_path,
            )
            (tmp_path / f"{label}-response-validation.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2)
            )
            observed.append(trace)
    assert observed[0] == observed[1], f"Full item-validation task traces in {tmp_path}"


@pytest.mark.parametrize(
    "output",
    [
        [{"type": "compaction", "id": "cmp_missing"}],
        [{"type": "function_call_output", "call_id": "orphan", "output": 42}],
    ],
    ids=["checkpoint-required-payload", "tool-output-body"],
)
def test_native_and_python_reject_malformed_unary_compaction_history(
    output, parity_source, upstream_codex, tmp_path
):
    config_file = parity_source / "config.toml"
    config_file.write_text(
        "model_auto_compact_token_limit=100\n"
        + config_file.read_text()
        + "remote_compaction_v2=false\nshell_snapshot=false\n"
    )
    task = tmp_path / "task"
    task.mkdir()
    first = _with_usage(
        _events(
            call=("shell_command", {"command": "printf x > evidence"}),
            response_id="resp_save",
        ),
        32000,
    )
    observed = []
    with _server() as replay:
        for label, binary in (("native", upstream_codex), ("python", None)):
            (task / "evidence").unlink(missing_ok=True)
            replay.reset(
                [
                    ("/v1/responses", 200, first),
                    (
                        "/v1/responses/compact",
                        200,
                        json.dumps({"output": output}).encode(),
                    ),
                ]
            )
            config = _config(parity_source, replay, binary)
            config["llm"]["provider_name"] = "Azure"
            result = asyncio.run(
                Codex(config).run(
                    "Write evidence, compact and finish.", working_dir=task
                )
            )
            assert result.status == "error", result.error_message
            assert len(replay.requests) == 2 and not replay.steps and not replay.errors
            assert (task / "evidence").read_text() == "x"
            trace = _normalize(
                {
                    "requests": replay.requests,
                    "status": result.status,
                    "output": result.output,
                    "usage": dict(result.usage),
                    "file": (task / "evidence").read_text(),
                },
                tmp_path,
            )
            (tmp_path / f"{label}-unary-validation.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2)
            )
            observed.append(trace)
    assert observed[0] == observed[1], f"Full unary-validation traces in {tmp_path}"
