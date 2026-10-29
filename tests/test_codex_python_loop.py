"""Exercise the selected Python core's continuation and scheduling boundaries."""

import asyncio
import json
import re

import pytest
from codex_test_support import _events, _responses_server
from codex_test_support import parity_source as parity_source

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core.loop import ToolSchedule


def _config(source, replay, **extra):
    return {
        "source_dir": source,
        "llm": {
            "model_name": "gpt-5",
            "api_key": "local-parity-test-key",
            "base_url": replay.base_url,
        },
        "timeout": 20,
        "sandbox": "danger-full-access",
        **extra,
    }


def test_partial_failed_stream_executes_completed_tool_once(parity_source, tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    # The stream fails after a completed call. Replaying the original request
    # would execute this side effect twice; native continuation uses history.
    partial = _events(
        call=("shell_command", {"command": "printf x >> counter"}),
        response_id="resp_partial",
    )
    partial = partial.split(b"event: response.completed", 1)[0]
    partial += b'data: {"type":"response.failed","response":{"error":{"code":"server_error","message":"transient"}}}\n\n'
    with _responses_server() as replay:
        replay.reset([(200, partial), (200, _events())])
        result = asyncio.run(
            Codex(_config(parity_source, replay)).run(
                "Follow the responses.", working_dir=task
            )
        )
        assert result.status == "finished", result.error_message
        assert result.output == "PARITY_ANSWER"
        assert (task / "counter").read_text() == "x"
        assert len(replay.requests) == 2
        history = replay.requests[1]["body"]["input"]
        assert sum(i["type"] == "function_call" for i in history) == 1
        assert sum(i["type"] == "function_call_output" for i in history) == 1
        assert not replay.errors and not replay.steps


def test_end_turn_false_continues_and_uses_last_response_message(parity_source):
    first = _events(text="INTERIM", response_id="resp_first").decode()
    first = first.replace('"usage": {', '"end_turn": false, "usage": {')
    with _responses_server() as replay:
        replay.reset([(200, first.encode()), (200, _events())])
        result = asyncio.run(
            Codex(_config(parity_source, replay)).run("Continue when required.")
        )
        assert result.status == "finished", result.error_message
        assert result.output == "PARITY_ANSWER"
        assert result.usage["prompt_tokens"] == 40
        assert "INTERIM" in json.dumps(replay.requests[1]["body"]["input"])
        assert not replay.steps and not replay.errors


def test_unsupported_enabled_feature_fails_before_model_request(parity_source):
    (parity_source / "config.toml").write_text("[features]\nrollout_budget = true\n")
    with _responses_server() as replay:
        result = asyncio.run(
            Codex(_config(parity_source, replay)).run("Do not call a model.")
        )
        assert result.status == "error"
        assert "rollout_budget" in result.error_message
        assert not replay.requests


def test_parallel_tools_overlap_and_exclusive_calls_form_barriers():
    async def exercise():
        started, finished, outputs = [], [], []
        both_parallel = asyncio.Event()

        class Router:
            def supports_parallel(self, call):
                return call["name"] != "serial"

            async def execute(self, call):
                name = call["name"]
                started.append(name)
                if name in {"a", "b"}:
                    if {"a", "b"} <= set(started):
                        both_parallel.set()
                    await asyncio.wait_for(both_parallel.wait(), 2)
                if name == "serial":
                    assert {"a", "b"} <= set(finished)
                if name == "c":
                    assert "serial" in finished
                finished.append(name)
                return {"type": "function_call_output", "call_id": name, "output": name}

        schedule = ToolSchedule(Router())
        for name in ("a", "b", "serial", "c"):
            schedule.submit({"name": name})
        await schedule.drain(outputs.append)
        assert [i["call_id"] for i in outputs] == ["a", "b", "serial", "c"]
        await schedule.close()

    asyncio.run(exercise())


def test_interrupted_partial_drain_retains_outputs_once_in_call_order():
    async def exercise():
        first_recorded, later_finished = asyncio.Event(), asyncio.Event()
        outputs = []

        class Router:
            def supports_parallel(self, call):
                return True

            async def execute(self, call):
                name = call["name"]
                if name == "shell_command":
                    await asyncio.Event().wait()
                if name == "last":
                    later_finished.set()
                return {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": name,
                }

        def append(item):
            outputs.append(item)
            if item["call_id"] == "first":
                first_recorded.set()

        schedule = ToolSchedule(Router())
        for name, call_id in [
            ("first", "first"),
            ("shell_command", "pending"),
            ("last", "last"),
        ]:
            schedule.submit({"type": "function_call", "name": name, "call_id": call_id})
        draining = asyncio.create_task(schedule.drain(append))
        await asyncio.wait_for(first_recorded.wait(), 2)
        await asyncio.wait_for(later_finished.wait(), 2)
        draining.cancel()
        with pytest.raises(asyncio.CancelledError):
            await draining
        await schedule.close(append)
        await schedule.close(append)
        assert [item["call_id"] for item in outputs] == ["first", "pending", "last"]
        assert re.fullmatch(
            r"Wall time: \d+\.\d seconds\naborted by user", outputs[1]["output"]
        )
        assert outputs[0]["output"] == "first" and outputs[2]["output"] == "last"
        assert not schedule.tasks and not schedule.calls

    asyncio.run(exercise())


def test_native_abort_payloads_and_minimum_duration(monkeypatch):
    from types import SimpleNamespace

    from flashrsi.agents.codex.python_core import loop

    monkeypatch.setattr(loop, "time", SimpleNamespace(monotonic=lambda: 100.01))
    shell = ToolSchedule._aborted(
        {"type": "function_call", "name": "shell_command", "call_id": "shell"}, 100.0
    )
    assert shell == {
        "type": "function_call_output",
        "call_id": "shell",
        "output": "Wall time: 0.1 seconds\naborted by user",
    }
    custom = ToolSchedule._aborted(
        {"type": "custom_tool_call", "name": "apply_patch", "call_id": "patch"}, 100.0
    )
    assert custom == {
        "type": "custom_tool_call_output",
        "call_id": "patch",
        "output": "aborted by user after 0.1s",
    }
    search = ToolSchedule._aborted(
        {"type": "tool_search_call", "call_id": "search"}, 100.0
    )
    assert search == {
        "type": "tool_search_output",
        "call_id": "search",
        "status": "completed",
        "execution": "client",
        "tools": [],
    }


def test_abort_duration_excludes_process_teardown(monkeypatch):
    from types import SimpleNamespace

    from flashrsi.agents.codex.python_core import loop

    async def exercise():
        clock, entered, outputs = [100.0], asyncio.Event(), []
        monkeypatch.setattr(loop, "time", SimpleNamespace(monotonic=lambda: clock[0]))

        class Router:
            def supports_parallel(self, call):
                return True

            async def execute(self, call):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    clock[0] = 150.0
                    raise

        schedule = ToolSchedule(Router())
        schedule.submit(
            {"type": "function_call", "name": "shell_command", "call_id": "pending"}
        )
        await entered.wait()
        clock[0] = 100.01
        await schedule.close(outputs.append)
        assert outputs[0]["output"] == "Wall time: 0.1 seconds\naborted by user"

    asyncio.run(exercise())


def test_fatal_dispatch_error_logs_and_releases_serial_gate():
    async def exercise():
        outputs, events, executed = [], [], []

        class Router:
            emit = events.append

            def supports_parallel(self, call):
                return call["name"] != "serial"

            async def execute(self, call):
                executed.append(call["name"])
                if call["name"] == "fatal":
                    raise RuntimeError("native dispatch failure")
                return {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": call["name"],
                }

        schedule = ToolSchedule(Router())
        for name in ("fatal", "serial", "last"):
            schedule.submit({"type": "function_call", "name": name, "call_id": name})
        await schedule.drain(outputs.append)
        await schedule.close(outputs.append)
        assert executed == ["fatal", "serial", "last"]
        assert [item["call_id"] for item in outputs] == ["serial", "last"]
        assert events == [
            {
                "type": "error",
                "message": "in-flight tool future failed during drain: native dispatch failure",
            }
        ]

    asyncio.run(exercise())


def test_explicit_unsupported_dispatch_rejects_after_other_results_are_recorded():
    async def exercise():
        outputs = []

        class Router:
            def supports_parallel(self, call):
                return True

            async def execute(self, call):
                if call["call_id"] == "unsupported":
                    raise ValueError(
                        "Codex Python core has not implemented this capability"
                    )
                return {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": "retained",
                }

        schedule = ToolSchedule(Router())
        for name in ("unsupported", "success"):
            schedule.submit({"type": "function_call", "name": name, "call_id": name})
        with pytest.raises(ValueError, match="has not implemented"):
            await schedule.drain(outputs.append)
        await schedule.close(outputs.append)
        assert outputs == [
            {"type": "function_call_output", "call_id": "success", "output": "retained"}
        ]

    asyncio.run(exercise())


def test_hook_stop_cancels_parallel_peers_and_preserves_settled_results():
    from flashrsi.agents.codex.python_core.hooks import HookStopped

    async def exercise():
        outputs, pending_started = [], asyncio.Event()

        class Router:
            def supports_parallel(self, call):
                return True

            async def execute(self, call):
                if call["call_id"] == "pending":
                    pending_started.set()
                    await asyncio.Event().wait()
                if call["call_id"] == "stop":
                    await pending_started.wait()
                    raise HookStopped("PreToolUse", "stop now")
                return {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": "completed",
                }

        schedule = ToolSchedule(Router())
        for name in ("completed", "pending", "stop"):
            schedule.submit({"type": "function_call", "name": name, "call_id": name})
        with pytest.raises(HookStopped, match="stop now"):
            await asyncio.wait_for(schedule.drain(outputs.append), 2)
        await schedule.close(outputs.append)
        assert [item["call_id"] for item in outputs] == ["completed", "pending", "stop"]
        assert outputs[0]["output"] == "completed"
        assert all("aborted by user after " in item["output"] for item in outputs[1:])

    asyncio.run(exercise())


def test_interrupted_cached_turn_records_abort_with_id_before_reuse(
    parity_source, tmp_path, monkeypatch
):
    from flashrsi.agents.codex.python_core.loop import close_session, run_session
    from flashrsi.agents.codex.python_core.tools import ToolRouter

    async def exercise(replay):
        cache, pending = {}, asyncio.Event()

        async def execute(self, call):
            if json.loads(call["arguments"])["command"] == "pending":
                pending.set()
                await asyncio.Event().wait()
            return {
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": "completed tool result",
            }

        monkeypatch.setattr(ToolRouter, "execute", execute)
        calls = [
            {
                "type": "function_call",
                "id": "fc_" + name,
                "call_id": name,
                "name": "shell_command",
                "arguments": json.dumps({"command": name}),
            }
            for name in ("complete", "pending")
        ]
        events = [{"type": "response.created", "response": {"id": "resp_tools"}}]
        events += [
            {"type": "response.output_item.done", "item": item} for item in calls
        ]
        events += [
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_tools",
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 3,
                        "total_tokens": 23,
                    },
                },
            }
        ]
        stream = "".join(
            "data: " + json.dumps(event) + "\n\n" for event in events
        ).encode()
        replay.reset([(200, stream)])
        request = {
            "home": str(parity_source),
            "cwd": str(tmp_path),
            "prompt": "Start tools.",
            "llm": {
                "model_name": "gpt-5",
                "base_url": replay.base_url,
                "api_key": "test",
            },
            "settings": {
                "_thread_id": "00000000-0000-0000-0000-000000000001",
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
        task = asyncio.create_task(run_session(request, lambda event: None))
        try:
            await asyncio.wait_for(pending.wait(), 2)
            task.cancel()
            interrupted = await task
            assert interrupted["status"] == "interrupted", interrupted
            outputs = [
                item
                for item in cache["history"].items
                if item["type"] == "function_call_output"
            ]
            assert [item["call_id"] for item in outputs] == ["complete", "pending"]
            assert outputs[0]["output"] == "completed tool result"
            assert "aborted by user" in outputs[1]["output"]
            assert all(item["id"].startswith("fco_") for item in outputs)
            assert all(
                item["internal_chat_message_metadata_passthrough"]["turn_id"]
                for item in outputs
            )
            replay.reset([(200, _events())])
            completed = await run_session(
                {**request, "prompt": "Continue after interruption."},
                lambda event: None,
            )
            assert completed["status"] == "finished", completed
            sent_outputs = [
                item
                for item in replay.requests[0]["body"]["input"]
                if item["type"] == "function_call_output"
            ]
            assert sent_outputs == [
                {
                    key: value
                    for key, value in item.items()
                    if key != "internal_chat_message_metadata_passthrough"
                }
                for item in outputs
            ]
            assert len({item["call_id"] for item in sent_outputs}) == 2
        finally:
            if not task.done():
                task.cancel()
                await task
            await close_session(cache)

    with _responses_server() as replay:
        asyncio.run(exercise(replay))


def test_scheduler_cleanup_error_still_resets_cached_actors(
    parity_source, tmp_path, monkeypatch
):
    from flashrsi.agents.codex.python_core.loop import close_session, run_session
    from flashrsi.agents.codex.python_core.tools import ToolRouter

    async def exercise(replay):
        cache, pending = {}, asyncio.Event()

        async def execute(self, call):
            pending.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise ValueError("explicit unsupported cleanup branch") from None

        monkeypatch.setattr(ToolRouter, "execute", execute)
        replay.reset(
            [
                (
                    200,
                    _events(
                        call=("shell_command", {"command": "pending"}),
                        response_id="resp_pending",
                    ),
                )
            ]
        )
        request = {
            "home": str(parity_source),
            "cwd": str(tmp_path),
            "prompt": "Start a pending call.",
            "llm": {
                "model_name": "gpt-5",
                "base_url": replay.base_url,
                "api_key": "test",
            },
            "settings": {
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
        task = asyncio.create_task(run_session(request, lambda event: None))
        try:
            await asyncio.wait_for(pending.wait(), 2)
            previous_shell = cache["router"].shell
            task.cancel()
            result = await task
            assert result["status"] == "error"
            assert "explicit unsupported cleanup branch" in result["error_message"]
            assert not previous_shell.sessions
            assert cache["router"].shell.snapshot is previous_shell.snapshot
            assert not cache["router"].shell.closed
        finally:
            if not task.done():
                task.cancel()
                await task
            await close_session(cache)

    with _responses_server() as replay:
        asyncio.run(exercise(replay))
