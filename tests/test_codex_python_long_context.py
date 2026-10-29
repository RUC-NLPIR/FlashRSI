"""Pinned native long-task checkpoints through localhost scripted Responses.

Model decisions are fixed; both harnesses execute the real tools. Full model
requests, resulting files, output and usage are compared after ID/time/path
normalization. These traces do not measure real-model task success rates.
"""

from __future__ import annotations

import asyncio
import copy
import gzip
import json
import threading
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_codex_core_parity import _events, _normalize
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core.compact import estimate_item_tokens
from flashrsi.agents.codex.python_core.context import message
from flashrsi.agents.codex.python_core.context_budget import (
    advance_window,
    configure,
    observe_usage,
    record_budget_messages,
    token_status,
    window,
)
from flashrsi.agents.codex.python_core.history import History
from flashrsi.agents.codex.python_core.models import Model
from flashrsi.agents.codex.python_core.remote_compact import (
    TRUNCATED_OUTPUT,
    build_v2_history,
    trim_trailing_outputs,
    truncate_retained_messages,
)


@contextmanager
def _server():
    class Replay:
        requests = []
        steps = []
        errors = []

        def reset(self, steps):
            self.requests, self.errors, self.steps = [], [], copy.deepcopy(steps)

    replay = Replay()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                if self.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                replay.requests.append(
                    {
                        "path": self.path,
                        "body": json.loads(raw),
                        "turn_state": self.headers.get("x-codex-turn-state"),
                    }
                )
                assert replay.steps, "unscripted request"
                path, status, content = replay.steps.pop(0)
                assert self.path == path
                self.send(status, content)
            except Exception as error:
                replay.errors.append(error)
                self.send(400, b'{"error":{"message":"replay mismatch"}}')

        def send(self, status, content):
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "application/json"
                if self.path.endswith("/compact")
                else "text/event-stream",
            )
            self.send_header("Content-Length", str(len(content)))
            self.send_header("x-codex-turn-state", "sticky-long-task-route")
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(content)

        def do_GET(self):
            self.send(404, b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    replay.base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield replay
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _with_usage(stream, input_tokens, output_tokens=3):
    return (
        stream.replace(
            b'"input_tokens": 20', f'"input_tokens": {input_tokens}'.encode()
        )
        .replace(b'"output_tokens": 3', f'"output_tokens": {output_tokens}'.encode())
        .replace(
            b'"total_tokens": 23',
            f'"total_tokens": {input_tokens + output_tokens}'.encode(),
        )
    )


def _compaction_stream(*, count=1, partial=False):
    items = [
        {
            "type": "compaction",
            "id": f"cmp_server_{index}",
            "encrypted_content": "OPAQUE_COMPACTION_CHECKPOINT",
        }
        for index in range(count)
    ]
    # Extra assistant and tool output are accepted but never executed/installed.
    items.insert(
        0,
        {
            "type": "function_call",
            "id": "fc_do_not_run",
            "call_id": "do_not_run",
            "name": "shell_command",
            "arguments": json.dumps({"command": "touch COMPACTION_TOOL_EXECUTED"}),
        },
    )
    events = [{"type": "response.output_item.done", "item": item} for item in items]
    if not partial:
        completed = json.loads(_events().split(b"data: ")[-1].strip())
        events.append(completed)
    return b"".join(
        b"data: " + json.dumps(event).encode() + b"\n\n" for event in events
    )


def _run_pair(
    parity_source,
    upstream_codex,
    tmp_path,
    replay,
    steps,
    *,
    prompt="Persist evidence and finish the task after the checkpoint.",
    provider_name=None,
):
    task = tmp_path / "task"
    task.mkdir(exist_ok=True)
    traces = []
    for label, binary in (("native", upstream_codex), ("python", None)):
        for path in task.iterdir():
            if path.is_file():
                path.unlink()
        replay.reset(steps)
        config = {
            "source_dir": parity_source,
            "llm": {
                "model_name": "gpt-5",
                "api_key": "local-parity-key",
                "base_url": replay.base_url,
            },
            "sandbox": "danger-full-access",
            "timeout": 40,
        }
        if binary:
            config["cli_path"] = binary
        if provider_name:
            config["llm"]["provider_name"] = provider_name
        result = asyncio.run(Codex(config).run(prompt, working_dir=task))
        assert not replay.errors, (label, replay.errors, result.error_message)
        assert not replay.steps, (label, result.error_message, len(replay.steps))
        assert result.status == "finished", (label, result.error_message)
        assert result.output == "PARITY_ANSWER"
        assert not (task / "COMPACTION_TOOL_EXECUTED").exists()
        trace = _normalize(
            {
                "requests": replay.requests,
                "usage": dict(result.usage),
                "files": {
                    path.name: path.read_text()
                    for path in task.iterdir()
                    if path.is_file()
                },
            },
            tmp_path,
        )
        (tmp_path / (label + "-long-context.json")).write_text(
            json.dumps(trace, indent=2)
        )
        traces.append(trace)
    assert traces[0] == traces[1], f"Long context traces in {tmp_path}"
    return traces[0]


@pytest.mark.parametrize(
    "automatic,mode", [(False, "thread"), (True, "thread"), (False, "name")]
)
def test_native_token_budget_rollover_preserves_task_files(
    automatic, mode, parity_source, upstream_codex, tmp_path
):
    config = parity_source / "config.toml"
    config.write_text(
        ("model_auto_compact_token_limit = 100\n" if automatic else "")
        + config.read_text()
        + f'\n[features.token_budget]\nenabled = true\nmode = "{mode}"\nguidance_message = "Persist evidence before changing context windows."\n'
    )
    streams = [
        _events(
            call=(
                "shell_command",
                {"command": "printf SAVED_TASK_EVIDENCE > evidence.txt"},
            ),
            response_id="resp_save",
        )
    ]
    if automatic:
        streams[0] = _with_usage(streams[0], 32000)
    if not automatic:
        streams.append(_events(call=("new_context", {}), response_id="resp_reset"))
    streams += [
        _events(
            call=("shell_command", {"command": "cat evidence.txt"}),
            response_id="resp_read",
        ),
        _events(),
    ]
    with _server() as replay:
        trace = _run_pair(
            parity_source,
            upstream_codex,
            tmp_path,
            replay,
            [("/v1/responses", 200, stream) for stream in streams],
        )
    assert trace["files"] == {"evidence.txt": "SAVED_TASK_EVIDENCE"}
    reset_request = trace["requests"][1 if automatic else 2]["body"]
    assert "Previous context window id:" in json.dumps(reset_request)
    assert "Persist evidence and finish the task" not in json.dumps(
        reset_request["input"]
    )
    assert not any(
        item["type"] == "function_call_output" for item in reset_request["input"]
    )


def test_native_body_after_prefix_compacts_only_after_body_growth(
    parity_source, upstream_codex, tmp_path
):
    config = parity_source / "config.toml"
    config.write_text(
        'model_auto_compact_token_limit = 100\nmodel_auto_compact_token_limit_scope = "body_after_prefix"\n'
        + config.read_text()
    )
    streams = [
        _with_usage(
            _events(
                call=("shell_command", {"command": "printf PREFIX_EVIDENCE"}),
                response_id="resp_prefix",
            ),
            32000,
        ),
        _with_usage(
            _events(
                call=("shell_command", {"command": "printf BODY_EVIDENCE"}),
                response_id="resp_body",
            ),
            32100,
        ),
        _events(
            "Retain PREFIX_EVIDENCE and BODY_EVIDENCE.", response_id="resp_summary"
        ),
        _events(),
    ]
    with _server() as replay:
        trace = _run_pair(
            parity_source,
            upstream_codex,
            tmp_path,
            replay,
            [("/v1/responses", 200, stream) for stream in streams],
        )
    assert trace["requests"][1]["body"]["tools"]
    assert trace["requests"][2]["body"]["tools"] == []


def test_native_token_budget_fallback_runs_before_buffered_rollover(
    parity_source, upstream_codex, tmp_path
):
    config = parity_source / "config.toml"
    config.write_text(
        "model_auto_compact_token_limit = 100\n"
        + config.read_text()
        + "\n[features.token_budget]\nenabled = true\nreminder_threshold_tokens = 20\n"
        + 'reminder_message_template = "WINDOW_REMAINING={n_remaining}"\n'
        + 'auto_compact_fallback_prompt = "Persist notes before the context reset."\n'
        + "auto_compact_fallback_buffer_tokens = 200\n"
    )
    streams = [
        _with_usage(
            _events(
                call=(
                    "shell_command",
                    {"command": "printf SAVED_TASK_EVIDENCE > evidence.txt"},
                ),
                response_id="resp_save",
            ),
            200,
        ),
        _with_usage(
            _events(
                call=("shell_command", {"command": "printf saved > notes.txt"}),
                response_id="resp_note",
            ),
            300,
        ),
        _events(
            call=("shell_command", {"command": "cat evidence.txt notes.txt"}),
            response_id="resp_read",
        ),
        _events(),
    ]
    with _server() as replay:
        trace = _run_pair(
            parity_source,
            upstream_codex,
            tmp_path,
            replay,
            [("/v1/responses", 200, stream) for stream in streams],
        )
    before_reset = json.dumps(trace["requests"][1]["body"]["input"])
    assert before_reset.count("WINDOW_REMAINING=0") == 1
    assert before_reset.count("Persist notes before the context reset.") == 1
    assert "Previous context window id:" not in before_reset
    after_reset = json.dumps(trace["requests"][2]["body"]["input"])
    assert (
        "Previous context window id:" in after_reset
        and "WINDOW_REMAINING=" not in after_reset
    )
    assert trace["files"] == {
        "evidence.txt": "SAVED_TASK_EVIDENCE",
        "notes.txt": "saved",
    }


@pytest.mark.parametrize(
    "v2,retry", [(False, False), (True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize("provider_name", ["Azure", "OpenAI"])
def test_native_remote_checkpoint_continues_real_task(
    v2, retry, provider_name, parity_source, upstream_codex, tmp_path
):
    config = parity_source / "config.toml"
    config.write_text(
        "model_auto_compact_token_limit = 100\n"
        + config.read_text()
        + f"remote_compaction_v2 = {str(v2).lower()}\n"
    )
    first = _with_usage(
        _events(
            call=(
                "shell_command",
                {"command": "printf SAVED_TASK_EVIDENCE > evidence.txt"},
            ),
            response_id="resp_save",
        ),
        32000,
    )
    if v2:
        compact_step = ("/v1/responses", 200, _compaction_stream())
    else:
        compact_step = (
            "/v1/responses/compact",
            200,
            json.dumps(
                {
                    "output": [
                        message("developer", "DROP_STALE_CONTEXT"),
                        message(
                            "user",
                            "<environment_context>DROP_ENV</environment_context>",
                        ),
                        message("user", "Retain evidence.txt for the coding task."),
                        {
                            "type": "compaction",
                            "encrypted_content": "OPAQUE_COMPACTION_CHECKPOINT",
                        },
                    ]
                }
            ).encode(),
        )
    steps = [
        ("/v1/responses", 200, first),
        compact_step,
        (
            "/v1/responses",
            200,
            _events(
                call=("shell_command", {"command": "cat evidence.txt"}),
                response_id="resp_read",
            ),
        ),
        ("/v1/responses", 200, _events()),
    ]
    if retry:
        failed = (
            ("/v1/responses", 200, _compaction_stream(partial=True))
            if v2
            else (
                "/v1/responses/compact",
                503,
                b'{"error":{"message":"temporary compact failure"}}',
            )
        )
        steps.insert(1, failed)
    with _server() as replay:
        trace = _run_pair(
            parity_source,
            upstream_codex,
            tmp_path,
            replay,
            steps,
            provider_name=provider_name,
        )
    assert trace["files"] == {"evidence.txt": "SAVED_TASK_EVIDENCE"}
    sent = json.dumps(trace["requests"][3 if retry else 2]["body"]["input"])
    assert "OPAQUE_COMPACTION_CHECKPOINT" in sent and "DROP_" not in sent
    assert trace["requests"][1]["body"]["tools"]
    assert trace["requests"][0]["turn_state"] is None
    assert all(
        item["turn_state"] == "sticky-long-task-route" for item in trace["requests"][1:]
    )
    if retry:
        assert trace["requests"][1] == trace["requests"][2]


@pytest.mark.parametrize(
    "failure", ["missing_compaction", "duplicate_compaction", "retry_budget"]
)
def test_native_remote_v2_rejects_bad_checkpoints_without_replaying_tools(
    failure, parity_source, upstream_codex, tmp_path
):
    config = parity_source / "config.toml"
    config.write_text("model_auto_compact_token_limit = 100\n" + config.read_text())
    task = tmp_path / "task"
    task.mkdir()
    first = _with_usage(
        _events(
            call=("shell_command", {"command": "printf x >> executions.txt"}),
            response_id="resp_once",
        ),
        32000,
    )
    count = 0 if failure == "missing_compaction" else 2
    failures = (
        [_compaction_stream(partial=True)] * 3
        if failure == "retry_budget"
        else [_compaction_stream(count=count)]
    )
    steps = [("/v1/responses", 200, first)] + [
        ("/v1/responses", 200, stream) for stream in failures
    ]
    observed = []
    with _server() as replay:
        for label, binary in (("native", upstream_codex), ("python", None)):
            (task / "executions.txt").unlink(missing_ok=True)
            replay.reset(steps)
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "test",
                    "base_url": replay.base_url,
                    "provider_name": "Azure",
                },
                "sandbox": "danger-full-access",
                "timeout": 30,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Collect evidence once and use a valid checkpoint.",
                    working_dir=task,
                )
            )
            assert result.status == "error", (label, result.output)
            if failure != "retry_budget":
                assert (
                    f"expected exactly one compaction output item, got {count}"
                    in result.error_message
                )
            assert not replay.steps and not replay.errors, (label, result.error_message)
            assert len(replay.requests) == (4 if failure == "retry_budget" else 2)
            assert (task / "executions.txt").read_text() == "x"
            assert not (task / "COMPACTION_TOOL_EXECUTED").exists()
            observed.append(
                _normalize(
                    {"requests": replay.requests, "usage": dict(result.usage)}, tmp_path
                )
            )
    assert observed[0] == observed[1]


def test_window_prefill_observation_replaces_estimate_once():
    settings = {
        "model_auto_compact_token_limit_scope": "body_after_prefix",
        "model_auto_compact_token_limit": 100,
    }
    model = Model("gpt-5", settings)
    history = History(model)
    state = window(history, settings)
    state["prefill"] = 500
    observe_usage(history, {"input_tokens": 32000}, settings)
    observe_usage(history, {"input_tokens": 40000}, settings)
    assert state["prefill"] == 32000
    history.last_usage["total_tokens"] = 32060
    assert token_status(history, model, settings)["auto_compact_scope_tokens"] == 60
    advance_window(history, model, settings)
    assert state["prefill"] is None and not state["prefill_observed"]
    assert uuid_version(state["window_id"]) == 7


def uuid_version(value):
    import uuid

    return uuid.UUID(value).version


def test_budget_fallback_buffer_reminders_once_per_window():
    settings = {
        "features": {
            "token_budget": {
                "enabled": True,
                "reminder_threshold_tokens": 20,
                "reminder_message_template": "Remaining {n_remaining}",
                "auto_compact_fallback_prompt": "  Save notes now.  ",
                "auto_compact_fallback_buffer_tokens": 30,
            }
        },
        "model_auto_compact_token_limit": 100,
    }
    model, emitted = Model("gpt-5", settings), []
    configure(settings, model)
    history = History(model)
    history.last_usage["total_tokens"] = 100
    record_budget_messages(history, model, {"settings": settings}, emitted.append, True)
    record_budget_messages(history, model, {"settings": settings}, emitted.append, True)
    assert [item["content"][0]["text"] for item in emitted] == [
        "Remaining 0",
        "Save notes now.",
    ]
    assert not token_status(history, model, settings)["token_limit_reached"]
    history.last_usage["total_tokens"] = 130
    assert token_status(history, model, settings)["token_limit_reached"]


def test_model_budget_defaults_preserve_strings_and_explicit_user_settings():
    settings = {"features": {"token_budget": {"enabled": True, "mode": "name"}}}
    model = Model("gpt-5", settings)
    defaults = {
        "reminder_threshold_tokens": 10,
        "reminder_message_template": "Only {n_remaining}",
        "guidance_message": "guidance",
        "auto_compact_fallback_prompt": "  model-owned prompt  ",
        "auto_compact_fallback_buffer_tokens": 20,
    }
    model.info["model_messages"]["token_budget"] = defaults
    assert configure(settings, model) == {"mode": "name", **defaults}
    supplied = {
        "features": {
            "token_budget": {"enabled": True, "guidance_message": "user guidance"}
        }
    }
    resolved = configure(supplied, model)
    assert resolved["guidance_message"] == "user guidance"
    assert resolved["auto_compact_fallback_prompt"] is None
    model.info["model_messages"]["token_budget"]["reminder_threshold_tokens"] = 0
    assert configure(settings, model)["reminder_threshold_tokens"] is None


def test_remote_v2_preserves_user_images_and_bounded_agent_instructions():
    image = {"type": "input_image", "image_url": "data:image/png;base64,abc"}
    old = message("user", "old task")
    recent = message(
        "user",
        [
            {"type": "input_text", "text": "abcdef"},
            image,
            {"type": "output_text", "text": "uvwxyz"},
        ],
    )
    result = truncate_retained_messages([old, recent], 3)
    assert len(result) == 1 and result[0]["content"] == [
        {"type": "input_text", "text": "abcdef"},
        image,
        {"type": "output_text", "text": "uv…1 tokens truncated…yz"},
    ]
    agent = {
        "type": "agent_message",
        "author": "parent",
        "recipient": "child",
        "content": [{"type": "input_text", "text": "Do the assigned subtask."}],
    }
    completion = copy.deepcopy(agent)
    completion["content"][0]["text"] = "Message Type: FINAL_ANSWER\nfinished"
    huge = copy.deepcopy(agent)
    huge["content"][0]["text"] = "x" * 40000
    assert estimate_item_tokens(huge) > 10000
    output = {"type": "compaction", "encrypted_content": "encrypted"}
    kept = build_v2_history(
        [
            old,
            message("developer", "DROP"),
            agent,
            completion,
            huge,
            message("assistant", "discard answer"),
        ],
        output,
    )
    assert kept == [old, agent, output]


def test_remote_trim_only_rewrites_contiguous_trailing_outputs():
    model = Model("gpt-5", {"model_context_window": 1000, "base_instructions": ""})
    first = {"type": "function_call_output", "call_id": "old", "output": "x" * 10000}
    barrier = message("assistant", "keep boundary")
    last = {
        "type": "custom_tool_call_output",
        "id": "ctco_1",
        "call_id": "last",
        "output": "x" * 10000,
        "internal_chat_message_metadata_passthrough": {"turn_id": "parent"},
    }
    trimmed = trim_trailing_outputs([first, barrier, last], model)
    assert trimmed[:2] == [first, barrier]
    assert trimmed[-1] == {**last, "output": TRUNCATED_OUTPUT}
