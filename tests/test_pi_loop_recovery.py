"""Real native HTTP boundaries for retries, long runs, cancellation and replay.

Fixed offline replies exercise production dispatch, session persistence and
built-in tools. Agent retry assertions follow original agent-session.ts
_prepareRetry/_finishCancelledRetry (3822/3806), message_end retry reset (1177),
and agent-loop.ts's natural completion loop. These integration checks do not
claim to execute the original AgentSession or compare model task accuracy.
"""

import asyncio
import json
import os
import shlex
import sys
import threading

import httpx
import pytest

from flashrsi.agents.pi_agent import Pi
from flashrsi.agents.pi_agent.runtime.pi_native import loop, provider_retry, tools
from flashrsi.agents.pi_agent.runtime.pi_native.resources import ResourceBundle
from flashrsi.agents.pi_agent.runtime.pi_native.session import Session


def config(session=None, **updates):
    value = {
        "llm": {
            "model_name": "openai/gpt-4.1",
            "model_api": "openai-completions",
            "api_key": "sk-offline-fixture",
            "base_url": "https://offline.invalid/v1",
            "max_retries": 0,
        },
        "tools": [],
        "compaction": False,
        "retry": {"enabled": True, "maxRetries": 2, "baseDelayMs": 0},
    }
    if session is not None:
        value["session_file"] = str(session)
    value.update(updates)
    return value


def completion(text="done", *, calls=(), usage=None):
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
            for call_id, name, arguments in calls
        ]
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": message, "finish_reason": "tool_calls" if calls else "stop"}
            ],
            "usage": usage or {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        loop.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        ),
    )


def resources(selected=()):
    return ResourceBundle(
        system_prompt="fixture system", tool_schemas=tools.tool_schemas(selected)
    )


async def native(tmp_path, cfg, **options):
    return await loop.run(
        cfg, "fixture task", tmp_path, tmp_path, resources(cfg["tools"]), **options
    )


def events(result, kind):
    return [event for event in result.events if event["type"] == kind]


def raw_entries(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def assert_aborted(result):
    assert result.status == "error"
    assert result.stop_reason == "aborted"
    assert result.events[-1] == {"type": "agent_settled", "aborted": True}
    assert events(result, "agent_end")
    assert events(result, "turn_end")[-1]["message"]["stopReason"] == "aborted"
    assert events(result, "message_end")[-1]["message"]["stopReason"] == "aborted"


def test_agent_retry_recovers_http_errors_and_keeps_raw_failed_attempts(
    tmp_path, monkeypatch
):
    session = tmp_path / "session.jsonl"
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) <= 2:
            return httpx.Response(503, text="server overloaded")
        return completion()

    transport(monkeypatch, handler)
    result = asyncio.run(native(tmp_path, config(session)))
    assert result.status == "finished"
    assert result.output == "done"
    assert len(requests) == 3
    assert [event["attempt"] for event in events(result, "auto_retry_start")] == [1, 2]
    assert events(result, "auto_retry_end") == [
        {"type": "auto_retry_end", "success": True, "attempt": 2}
    ]
    assert [event["willRetry"] for event in events(result, "agent_end")] == [
        True,
        True,
        False,
    ]
    entries = raw_entries(session)
    failures = [
        entry
        for entry in entries
        if entry.get("message", {}).get("stopReason") == "error"
    ]
    omissions = [entry for entry in entries if entry["type"] == "context_edit"]
    assert len(failures) == 2
    assert {entry["targetId"] for entry in omissions} == {
        entry["id"] for entry in failures
    }
    assert all(entry["replacement"] is None for entry in omissions)
    assert not any(
        message.get("stopReason") == "error"
        for message in Session(tmp_path, session).messages()
    )
    assert all(request["messages"] == requests[0]["messages"] for request in requests)


def test_agent_retry_quota_error_is_terminal(tmp_path, monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            429,
            json={
                "error": {"code": "insufficient_quota", "message": "Insufficient quota"}
            },
        )

    transport(monkeypatch, handler)
    result = asyncio.run(native(tmp_path, config()))
    assert result.status == "error"
    assert len(requests) == 1
    assert not events(result, "auto_retry_start")
    assert "quota" in result.error_message


def test_agent_retry_exhaustion_has_failure_end_and_preserves_last_error(
    tmp_path, monkeypatch
):
    session = tmp_path / "session.jsonl"
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, text="server overloaded")

    transport(monkeypatch, handler)
    result = asyncio.run(native(tmp_path, config(session)))
    assert result.status == "error"
    assert len(requests) == 3
    assert len(events(result, "auto_retry_start")) == 2
    end = events(result, "auto_retry_end")
    assert len(end) == 1 and end[0]["success"] is False and end[0]["attempt"] == 2
    assert "503" in end[0]["finalError"]
    assert events(result, "agent_end")[-1]["willRetry"] is False
    assert (
        len(
            [entry for entry in raw_entries(session) if entry["type"] == "context_edit"]
        )
        == 2
    )
    assert Session(tmp_path, session).messages()[-1]["stopReason"] == "error"


def test_provider_retry_succeeds_without_agent_retry_or_failed_session_messages(
    tmp_path, monkeypatch
):
    requests, delays = [], []

    def handler(request):
        requests.append(request)
        return (
            httpx.Response(503, text="server overloaded")
            if len(requests) == 1
            else completion()
        )

    async def sleep(delay):
        delays.append(delay)

    transport(monkeypatch, handler)
    monkeypatch.setattr(provider_retry.asyncio, "sleep", sleep)
    monkeypatch.setattr(provider_retry.random, "random", lambda: 0)
    cfg = config(tmp_path / "session.jsonl")
    cfg["llm"]["max_retries"] = 1
    result = asyncio.run(native(tmp_path, cfg))
    assert result.status == "finished"
    assert len(requests) == 2 and delays == [0.5]
    assert not events(result, "auto_retry_start")
    assert not events(result, "auto_retry_end")
    assert not any(
        entry.get("message", {}).get("stopReason") == "error"
        for entry in raw_entries(tmp_path / "session.jsonl")
    )


@pytest.mark.parametrize("limit", [None, 3])
def test_default_run_can_exceed_64_turns_and_explicit_limit_stops(
    tmp_path, monkeypatch, limit
):
    (tmp_path / "fixture.txt").write_text("harmless read")
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) <= 65:
            return completion(
                "", calls=[(f"read_{len(requests)}", "read", {"path": "fixture.txt"})]
            )
        return completion("finished after 65 tools")

    transport(monkeypatch, handler)
    cfg = config(tools=["read"])
    if limit is not None:
        cfg["max_turns"] = limit
    result = asyncio.run(native(tmp_path, cfg))
    if limit is None:
        assert result.status == "finished"
        assert result.output == "finished after 65 tools"
        assert len(requests) == 66
        assert len(events(result, "tool_execution_end")) == 65
    else:
        assert result.status == "error"
        assert "max_turns" in result.error_message
        assert len(requests) == limit


def test_cancel_during_http_wait_returns_aborted_lifecycle_and_session(
    tmp_path, monkeypatch
):
    requests = []
    session = tmp_path / "session.jsonl"

    async def scenario():
        started, never, abort = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def handler(request):
            requests.append(request)
            started.set()
            await never.wait()

        transport(monkeypatch, handler)
        pending = asyncio.create_task(
            native(tmp_path, config(session), cancel_event=abort)
        )
        await asyncio.wait_for(started.wait(), 3)
        abort.set()
        return await asyncio.wait_for(pending, 3)

    result = asyncio.run(scenario())
    assert_aborted(result)
    assert len(requests) == 1
    assert Session(tmp_path, session).messages()[-1]["stopReason"] == "aborted"


def test_cancel_during_agent_retry_sleep_finishes_retry_without_second_request(
    tmp_path, monkeypatch
):
    requests = []

    async def scenario():
        sleeping, never, abort = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def sleep(delay):
            assert delay == 60
            sleeping.set()
            await never.wait()

        def handler(request):
            requests.append(request)
            return httpx.Response(503, text="server overloaded")

        transport(monkeypatch, handler)
        monkeypatch.setattr(loop.asyncio, "sleep", sleep)
        cfg = config(retry={"enabled": True, "maxRetries": 2, "baseDelayMs": 60000})
        pending = asyncio.create_task(native(tmp_path, cfg, cancel_event=abort))
        await asyncio.wait_for(sleeping.wait(), 3)
        abort.set()
        return await asyncio.wait_for(pending, 3)

    result = asyncio.run(scenario())
    assert_aborted(result)
    assert len(requests) == 1
    assert events(result, "auto_retry_end") == [
        {
            "type": "auto_retry_end",
            "success": False,
            "attempt": 1,
            "finalError": "Retry cancelled",
        }
    ]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cancellation")
def test_cancel_bash_kills_descendant_and_prevents_late_side_effect(
    tmp_path, monkeypatch
):
    pid_path, late_path = tmp_path / "child.pid", tmp_path / "late.txt"
    child = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pid_path)!r}).write_text(str(os.getpid())); "
        f"time.sleep(0.4); Path({str(late_path)!r}).write_text('late side effect')"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(child)} & wait"
    requests = []

    def handler(request):
        requests.append(request)
        return completion("", calls=[("bash", "bash", {"command": command})])

    transport(monkeypatch, handler)

    async def scenario():
        abort = asyncio.Event()
        pending = asyncio.create_task(
            native(tmp_path, config(tools=["bash"]), cancel_event=abort)
        )
        try:

            async def ready():
                while not pid_path.exists():
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(ready(), 3)
            abort.set()
            result = await asyncio.wait_for(pending, 3)
            await asyncio.sleep(0.45)
            return result
        finally:
            abort.set()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    result = asyncio.run(scenario())
    assert_aborted(result)
    assert len(requests) == 1
    assert not late_path.exists()
    assert events(result, "tool_execution_end")[0]["isError"] is True


@pytest.mark.parametrize("max_turns", [None, 1])
def test_cancel_during_write_does_not_execute_queued_second_write(
    tmp_path, monkeypatch, max_turns
):
    started, release = threading.Event(), threading.Event()
    target = tmp_path / "note.txt"
    original = tools._write
    performed = []

    def controlled_write(arguments, cwd):
        performed.append(arguments["content"])
        if arguments["content"] == "first":
            started.set()
            assert release.wait(3), "test failed to release active write"
        return original(arguments, cwd)

    monkeypatch.setattr(tools, "_write", controlled_write)
    requests = []

    def handler(request):
        requests.append(request)
        return completion(
            "",
            calls=[
                ("one", "write", {"path": "note.txt", "content": "first"}),
                ("two", "write", {"path": "note.txt", "content": "second"}),
            ],
        )

    transport(monkeypatch, handler)

    async def scenario():
        abort = asyncio.Event()
        cfg = config(tools=["write"])
        if max_turns is not None:
            cfg["max_turns"] = max_turns
        pending = asyncio.create_task(native(tmp_path, cfg, cancel_event=abort))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            abort.set()
            await asyncio.sleep(0)
            release.set()
            return await asyncio.wait_for(pending, 3)
        finally:
            release.set()
            abort.set()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    result = asyncio.run(scenario())
    assert_aborted(result)
    assert len(requests) == 1
    assert performed == ["first"]
    assert target.read_text() == "first"
    assert len(events(result, "tool_execution_end")) == 2


def test_cancel_after_successful_agent_retry_does_not_finish_retry_twice(
    tmp_path, monkeypatch
):
    (tmp_path / "fixture.txt").write_text("read content")
    requests = []

    async def scenario():
        waiting, never, abort = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(503, text="server overloaded")
            if len(requests) == 2:
                return completion("", calls=[("read", "read", {"path": "fixture.txt"})])
            waiting.set()
            await never.wait()

        transport(monkeypatch, handler)
        pending = asyncio.create_task(
            native(tmp_path, config(tools=["read"]), cancel_event=abort)
        )
        await asyncio.wait_for(waiting.wait(), 3)
        abort.set()
        return await asyncio.wait_for(pending, 3)

    result = asyncio.run(scenario())
    assert_aborted(result)
    assert len(requests) == 3
    # Original _finishCancelledRetry returns immediately once the successful
    # assistant has reset _retryAttempt to zero (agent-session.ts:3807/1177).
    assert events(result, "auto_retry_end") == [
        {"type": "auto_retry_end", "success": True, "attempt": 1}
    ]


def test_cancel_during_provider_retry_sleep_has_no_agent_retry(tmp_path, monkeypatch):
    requests = []

    async def scenario():
        sleeping, never, abort = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def sleep(delay):
            assert delay == 10
            sleeping.set()
            await never.wait()

        def handler(request):
            requests.append(request)
            return httpx.Response(
                503, text="server overloaded", headers={"retry-after": "10"}
            )

        transport(monkeypatch, handler)
        monkeypatch.setattr(provider_retry.asyncio, "sleep", sleep)
        cfg = config()
        cfg["llm"]["max_retries"] = 2
        pending = asyncio.create_task(native(tmp_path, cfg, cancel_event=abort))
        await asyncio.wait_for(sleeping.wait(), 3)
        abort.set()
        return await asyncio.wait_for(pending, 3)

    result = asyncio.run(scenario())
    assert_aborted(result)
    assert len(requests) == 1
    assert not events(result, "auto_retry_start")
    assert not events(result, "auto_retry_end")


def test_adapter_timeout_retains_partial_tools_messages_and_usage(
    tmp_path, monkeypatch
):
    (tmp_path / "fixture.txt").write_text("read content")
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return completion(
                "reading",
                calls=[("read", "read", {"path": "fixture.txt"})],
                usage={"prompt_tokens": 12, "completion_tokens": 3},
            )
        await asyncio.Event().wait()

    transport(monkeypatch, handler)
    agent = Pi(config(tools=["read"], timeout=0.15))
    result = asyncio.run(agent.run("read the fixture", tmp_path))
    assert result.status == "error"
    assert "timed out" in result.error_message
    assert len(requests) == 2
    assert result.usage["input"] == 12
    assert result.usage["output"] == 3
    assert any(
        message.get("type") == "tool_execution_end" for message in result.messages
    )
    assert any(
        message.get("type") == "message_end"
        and message.get("message", {}).get("stopReason") == "aborted"
        for message in result.messages
    )


@pytest.mark.parametrize("api", ["openai-completions", "openai-responses"])
def test_native_cached_usage_subtracts_read_and_write_once(tmp_path, monkeypatch, api):
    def handler(request):
        if api == "openai-completions":
            return completion(
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 5,
                    "prompt_tokens_details": {
                        "cached_tokens": 30,
                        "cache_write_tokens": 10,
                    },
                }
            )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_done",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 5,
                    "total_tokens": 105,
                    "input_tokens_details": {
                        "cached_tokens": 30,
                        "cache_write_tokens": 10,
                    },
                },
            },
        )

    transport(monkeypatch, handler)
    cfg = config()
    cfg["llm"]["model_api"] = api
    result = asyncio.run(native(tmp_path, cfg))
    assert result.status == "finished"
    assert result.usage["input"] == 60
    assert result.usage["output"] == 5
    assert result.usage["cache_read_input_tokens"] == 30
    assert result.usage["cache_creation_input_tokens"] == 10
    assert result.usage["total_tokens"] == 105
    assistant = events(result, "message_end")[-1]["message"]
    assert {
        key: assistant["usage"][key]
        for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens")
    } == {
        "input": 60,
        "output": 5,
        "cacheRead": 30,
        "cacheWrite": 10,
        "totalTokens": 105,
    }


def test_native_responses_encrypted_thinking_and_call_item_ids_replay(
    tmp_path, monkeypatch
):
    (tmp_path / "fixture.txt").write_text("read content")
    session = tmp_path / "session.jsonl"
    requests = []
    reasoning = {
        "type": "reasoning",
        "id": "rs_fixture",
        "summary": [{"type": "summary_text", "text": "private summary"}],
        "encrypted_content": "encrypted-fixture",
    }

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "resp_first",
                    "status": "completed",
                    "output": [
                        reasoning,
                        {
                            "type": "message",
                            "id": "msg_before_tool",
                            "phase": "commentary",
                            "content": [{"type": "output_text", "text": "reading"}],
                        },
                        {
                            "type": "function_call",
                            "id": "fc_fixture",
                            "call_id": "call_fixture",
                            "name": "read",
                            "arguments": '{"path":"fixture.txt"}',
                        },
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "resp_final",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_done",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
            },
        )

    transport(monkeypatch, handler)
    cfg = config(session, tools=["read"], thinking="high")
    cfg["llm"].update(model_name="openai/gpt-5", model_api="openai-responses")
    result = asyncio.run(native(tmp_path, cfg))
    assert result.status == "finished"
    assert len(requests) == 2
    replay = requests[1]["input"]
    assert reasoning in replay
    replay_call = next(item for item in replay if item.get("type") == "function_call")
    assert (
        replay_call["id"] == "fc_fixture" and replay_call["call_id"] == "call_fixture"
    )
    replay_result = next(
        item for item in replay if item.get("type") == "function_call_output"
    )
    assert replay_result["call_id"] == "call_fixture"
    assert replay_result["output"] == "read content"
    replay_text = next(item for item in replay if item.get("id") == "msg_before_tool")
    assert replay_text["phase"] == "commentary"
    first = next(
        entry["message"]
        for entry in raw_entries(session)
        if entry.get("message", {}).get("responseId") == "resp_first"
    )
    assert json.loads(first["content"][0]["thinkingSignature"]) == reasoning
    assert first["content"][-1]["id"] == "call_fixture|fc_fixture"
    assert (
        events(result, "tool_execution_end")[0]["toolCallId"]
        == "call_fixture|fc_fixture"
    )
