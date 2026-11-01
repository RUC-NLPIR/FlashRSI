"""Actual upstream compression fixtures plus the native HTTP integration seam.

Frozen fixtures execute the original pinned compressor and mixins. Comparisons
include every rewritten message and summarizer request/cap, using exact hashes
for long strings. They establish deterministic control-flow parity, not model
summary quality or durable session/database equivalence.
"""

import asyncio
import copy
import importlib.util
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from flashrsi.agents.hermes.runtime.hermes_native import loop as native_loop
from flashrsi.agents.hermes.runtime.hermes_native._vendor.todo import TodoStore
from flashrsi.agents.hermes.runtime.hermes_native.compression import ContextEngine
from flashrsi.agents.hermes.runtime.hermes_native.session import Session
from flashrsi.agents.hermes.runtime.hermes_native.upstream_compaction import (
    auxiliary_client,
    context_compressor,
    hermes_time,
)

FIXTURES = Path(__file__).parent / "fixtures"
ORACLE = json.loads((FIXTURES / "hermes_compression_upstream.json").read_text())
LOOP_ORACLE = json.loads(
    (FIXTURES / "hermes_compression_loop_upstream.json").read_text()
)
SPEC = importlib.util.spec_from_file_location(
    "hermes_compression_fixture_driver",
    FIXTURES / "generate_hermes_compression_upstream.py",
)
assert SPEC and SPEC.loader
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


@pytest.mark.parametrize("record", ORACLE["cases"], ids=lambda record: record["name"])
def test_native_compressor_matches_actual_upstream(record):
    actual = DRIVER.execute(
        context_compressor,
        record["input"],
        auxiliary_module=auxiliary_client,
        clock_module=hermes_time,
    )
    assert actual == record


def _messages(values, *, parse_arguments=True):
    fields = {
        "role",
        "content",
        "name",
        "tool_call_id",
        "tool_calls",
        "reasoning",
        "reasoning_content",
        "reasoning_details",
    }
    result = []
    for message in values:
        item = {
            key: copy.deepcopy(value) for key, value in message.items() if key in fields
        }
        for call in item.get("tool_calls", []):
            call.pop("call_id", None)
            call.pop("response_item_id", None)
            if parse_arguments:
                try:
                    call["function"]["arguments"] = json.loads(
                        call["function"]["arguments"]
                    )
                except (KeyError, ValueError, TypeError):
                    pass
        result.append(item)
    return result


def _main_request(request):
    fields = {
        "model",
        "max_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "reasoning_effort",
    }
    return DRIVER.canonical(
        {
            **{key: value for key, value in request.items() if key in fields},
            "messages": _messages(request["messages"], parse_arguments=False),
        }
    )


def _summary_request(request):
    # Original call_llm accepts routing/accounting kwargs; HTTP receives only the
    # serialized payload. Compare its effective model, prompts and output caps.
    fields = {"max_tokens", "max_completion_tokens", "temperature"}
    model = request.get("model") or request.get("main_runtime", {}).get("model")
    return DRIVER.canonical(
        {
            "model": model,
            "messages": request["messages"],
            **{key: value for key, value in request.items() if key in fields},
        }
    )


def replay_loop_native(record, cwd):
    case = record["input"]
    requests, summaries, tools_created = [], [], []
    declarations = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "read_file tool",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]

    class FixedTools:
        def __init__(self, workdir, snapshot_root, enabled_tools=None):
            self.cwd = workdir
            self.snapshot_root = snapshot_root
            self.schemas = copy.deepcopy(declarations)
            self.enabled = {"read_file"}
            self.todos = TodoStore()
            self.reset_calls = 0
            tools_created.append(self)

        def execute(self, tool, arguments):
            return json.dumps({"content": "src/calculation.py result 42\n" * 500})

        def reset_read_dedup(self):
            self.reset_calls += 1

        def close(self):
            pass

    def response(request):
        body = json.loads(request.content)
        first = body["messages"][0].get("content") or ""
        last = body["messages"][-1].get("content") or ""
        is_summary = (
            first == "You are a conversation summarization assistant."
            or last.startswith("You are a summarization agent")
        )
        if is_summary:
            summaries.append(body)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": DRIVER.SUMMARY},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 80,
                        "total_tokens": 180,
                    },
                },
            )
        requests.append(body)
        number = len(requests)
        assert number <= 16, "unexpected additional native request"
        if case.get("error_status") and number == 1:
            return httpx.Response(
                case["error_status"],
                json={
                    "error": {
                        "message": case["error_text"],
                        "code": "context_length_exceeded"
                        if case["error_status"] == 400
                        else "payload_too_large",
                    }
                },
            )
        tool_calls = None
        if number <= case.get("rounds", 0):
            tool_calls = [
                {
                    "id": f"read-{number}",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": f"file-{number}.txt"}),
                    },
                }
            ]
        content = (
            (
                f"Round {number} verified src/calculation.py and retained result 42.\n"
                * 150
            )
            if tool_calls
            else "Completed the requested check; the result is 42."
        )
        message = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": message,
                        "finish_reason": "tool_calls" if tool_calls else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": case.get("prompt_tokens", 120000)
                    if tool_calls
                    else 1000,
                    "completion_tokens": 128,
                    "total_tokens": case.get("prompt_tokens", 120000) + 128
                    if tool_calls
                    else 1128,
                },
            },
        )

    session_path = cwd / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "format": "hermes-native-v1",
                "messages": DRIVER.corpus(case.get("history_kind", "dialogue"))[1:-1]
                if case.get("history")
                else [],
                "last_activity": time.time() - case.get("idle", 0),
                "context_state": {},
                "todos": {"todos": case.get("todos", []), "revision": 0},
            }
        )
    )
    settings = {
        "llm": {
            "model_name": "oracle-main",
            "api_key": "synthetic-unused-key",
            "base_url": "http://oracle.invalid/v1",
            "provider": "custom",
            "max_tokens": 4096,
            "reasoning_effort": "medium",
        },
        "context_length": 131072,
        "model": {"default": "oracle-main", "context_length": 131072},
        "compression": {
            "enabled": True,
            "threshold_tokens": 90000,
            "idle_compact_after_seconds": 60 if case.get("idle") else 0,
            "micro_compact": bool(case.get("micro")),
            "proactive_prune_tokens": 1000 if case.get("prune") else 0,
            "proactive_prune_min_reclaim_tokens": 0 if case.get("prune") else 4096,
        },
        "session_file": str(session_path),
        "max_iterations": 20,
        "timeout": 10,
    }
    actual_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return actual_client(
            *args, **kwargs, transport=httpx.MockTransport(response), trust_env=False
        )

    with (
        patch.object(native_loop, "HermesTools", FixedTools),
        patch.object(
            native_loop,
            "load_resources",
            return_value=SimpleNamespace(
                system_prompt="You maintain a Python project. Obey the latest real user request.",
                enabled_tools=["read_file"],
                diagnostics=[],
                settings=settings,
            ),
        ),
        patch.object(httpx, "AsyncClient", client),
        patch.object(
            hermes_time,
            "now",
            return_value=DRIVER.datetime(2026, 11, 1, tzinfo=DRIVER.timezone.utc),
        ),
    ):
        result = asyncio.run(
            native_loop.run(
                settings,
                "Now finish the boundary check in src/calculation.py and report 42; do not restart completed work.",
                cwd,
                Path(native_loop.__file__).parents[2],
            )
        )
    settled = next(
        event for event in reversed(result.events) if event["type"] == "hermes_result"
    )
    return {
        "final_response": result.output,
        "completed": settled["completed"],
        "failed": settled["failed"],
        "error": result.error_message,
        "api_calls": settled["api_calls"],
        "messages": DRIVER.canonical(_messages(result.messages)),
        "requests": [_main_request(item) for item in requests],
        "summary_requests": [_summary_request(item) for item in summaries],
        "reset_calls": tools_created[0].reset_calls,
    }


@pytest.mark.parametrize(
    "record", LOOP_ORACLE["cases"], ids=lambda record: record["input"]["name"]
)
def test_native_loop_compression_matches_enabled_upstream(record, tmp_path):
    actual = replay_loop_native(record, tmp_path)
    expected = {
        key: record[key]
        for key in (
            "final_response",
            "completed",
            "failed",
            "error",
            "api_calls",
            "messages",
        )
    }
    expected["messages"] = DRIVER.canonical(_messages(record["messages"]))
    expected["requests"] = [_main_request(item) for item in record["requests"]]
    expected["summary_requests"] = [
        _summary_request(item) for item in record["summary_requests"]
    ]
    actual.pop("reset_calls")
    assert actual == expected


def _host(*, compression=None, auxiliary=None):
    tools = SimpleNamespace(
        enabled={"read_file", "session_search"},
        schemas=[],
        todos=TodoStore(),
        read_resets=0,
        skill_resets=0,
    )

    def reset_read():
        tools.read_resets += 1

    def reset_skill():
        tools.skill_resets += 1

    tools.reset_read_dedup = reset_read
    tools.reset_skill_dedup = reset_skill
    settings = {
        "context_length": 131072,
        "compression": {
            "enabled": True,
            "threshold_tokens": 90000,
            **(compression or {}),
        },
        "auxiliary": {"compression": auxiliary or {}},
    }
    llm = {
        "model_name": "oracle-main",
        "model": "oracle-main",
        "provider": "custom",
        "api_key": "MAIN_ONLY_SYNTHETIC_CREDENTIAL",
        "base_url": "http://main.invalid/v1",
        "max_tokens": 4096,
    }
    events = []
    return (
        ContextEngine(settings, llm, tools=tools, event_sink=events.append),
        tools,
        events,
    )


def _summary_response(content=DRIVER.SUMMARY, *, finish="stop"):
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 80},
    }


@pytest.mark.parametrize("mode", ["manual", "prune", "micro"])
def test_committed_context_rewrites_reset_read_skill_and_usage_anchor(mode):
    cfg = {
        "micro_compact": mode == "micro",
        "proactive_prune_tokens": 1000 if mode == "prune" else 0,
        "proactive_prune_min_reclaim_tokens": 0,
    }
    engine, tools, events = _host(compression=cfg)
    messages = DRIVER.corpus("tools" if mode == "prune" else "dialogue")[1:]
    before = copy.deepcopy(messages)
    engine.after_response({"prompt_tokens": 10000, "completion_tokens": 128}, messages)
    assert engine._anchor is not None
    calls = []

    async def send_summary(payload, route):
        calls.append(copy.deepcopy(payload))
        return _summary_response()

    async def run():
        if mode == "manual":
            return await engine.compact(
                messages, "Explicit system prompt.", send_summary
            )
        if mode == "micro":
            return await engine.finalise_turn(
                messages, "Explicit system prompt.", send_summary
            )
        return await engine.after_tools(
            messages, "Explicit system prompt.", send_summary
        )

    assert asyncio.run(run())
    assert messages != before
    assert engine._anchor is None
    assert tools.read_resets == tools.skill_resets == 1
    assert engine.search_archive("Task 0")["total_matches"] > 0
    assert any(event.get("committed") is True for event in events)
    if mode == "prune":
        assert not calls
    elif mode == "manual":
        assert len(calls) == 1 and "max_tokens" not in calls[0]
    else:
        assert len(calls) == 1 and calls[0]["max_tokens"] == 1500


def test_cancelled_summary_cannot_publish_late_history_or_state():
    engine, tools, events = _host()
    messages = DRIVER.corpus()[1:]
    original = copy.deepcopy(messages)
    original_compressor = engine.compressor
    finished_worker = threading.Event()
    actual_compress = context_compressor.ContextCompressor.compress

    def observe_compress(*args, **kwargs):
        try:
            return actual_compress(*args, **kwargs)
        finally:
            finished_worker.set()

    async def run():
        entered, release, finished_provider = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        async def late_summary(payload, route):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Model a provider coroutine that finishes after host cancellation.
                await release.wait()
            finally:
                finished_provider.set()
            return _summary_response()

        task = asyncio.create_task(engine.compact(messages, "System", late_summary))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert messages == original
        assert engine.compressor is original_compressor
        release.set()
        await asyncio.wait_for(finished_provider.wait(), 2)
        assert await asyncio.to_thread(finished_worker.wait, 2)
        await asyncio.sleep(0)

    with patch.object(
        context_compressor.ContextCompressor, "compress", observe_compress
    ):
        asyncio.run(run())
    assert messages == original
    assert engine.compressor is original_compressor
    assert engine.compressor.compression_count == 0
    assert engine.compressor._previous_summary is None
    assert tools.read_resets == tools.skill_resets == 0
    assert not engine.search_archive()["results"]
    assert not any(event.get("committed") for event in events)


def test_snapshot_restore_retains_micro_failure_progress_and_archive():
    engine, _, _ = _host(compression={"micro_compact": True})
    messages = DRIVER.corpus()[1:]

    async def empty(payload, route):
        return _summary_response("")

    async def healthy(payload, route):
        return _summary_response()

    assert not asyncio.run(engine.finalise_turn(messages, "System", empty))
    assert engine.compressor._micro_compact_consecutive_failures == 1
    state = json.loads(json.dumps(engine.snapshot_state()))
    restored, _, _ = _host(compression={"micro_compact": True})
    restored.restore_state(state)
    assert restored.compressor._micro_compact_consecutive_failures == 1
    assert (
        restored.compressor._micro_compact_last_failure_cursor
        == engine.compressor._micro_compact_last_failure_cursor
    )
    assert not asyncio.run(restored.finalise_turn(messages, "System", empty))
    assert restored.compressor._micro_compact_consecutive_failures == 2
    assert asyncio.run(restored.compact(messages, "System", healthy))
    state = json.loads(json.dumps(restored.snapshot_state()))
    newest, _, _ = _host(compression={"micro_compact": True})
    newest.restore_state(state)
    assert newest.search_archive("Task 0") == restored.search_archive("Task 0")
    assert newest.compressor._previous_summary == restored.compressor._previous_summary
    assert (
        newest.compressor.compression_count
        == restored.compressor.compression_count
        == 1
    )
    assert "MAIN_ONLY_SYNTHETIC_CREDENTIAL" not in json.dumps(state)


def test_snapshot_restore_preserves_terminal_summary_failure_during_cooldown():
    engine, _, _ = _host()
    messages = DRIVER.corpus()[1:]

    async def empty(payload, route):
        return _summary_response("")

    assert not asyncio.run(engine.compact(messages, "System", empty))
    assert engine.compressor._last_summary_empty_content_failure
    restored, _, _ = _host()
    restored.restore_state(json.loads(json.dumps(engine.snapshot_state())))
    assert restored.compressor.get_active_compression_failure_cooldown()
    original_history = DRIVER.corpus()
    # A cooldown skip has no new provider response to reassert terminal flags.
    # Resuming must retain the same lossless abort, never insert a placeholder.
    first = engine.compressor.compress(
        copy.deepcopy(original_history), current_tokens=120000
    )
    second = restored.compressor.compress(
        copy.deepcopy(original_history), current_tokens=120000
    )
    assert first == second == original_history


@pytest.mark.parametrize("with_aux_key", [True, False])
def test_auxiliary_auth_falls_back_without_crossing_credentials_or_output_caps(
    with_aux_key,
):
    auxiliary = {
        "model": "oracle-summary",
        "provider": "custom",
        "api_key": "AUX_ONLY_SYNTHETIC_CREDENTIAL",
        "base_url": "http://aux.invalid/v1",
    }
    if not with_aux_key:
        auxiliary.pop("api_key")
    engine, _, _ = _host(auxiliary=auxiliary)
    messages = DRIVER.corpus()[1:]
    messages[2]["content"] += "\nMAIN_ONLY_SYNTHETIC_CREDENTIAL"
    if with_aux_key:
        messages[2]["content"] += " AUX_ONLY_SYNTHETIC_CREDENTIAL"
    calls = []

    async def send_summary(payload, route):
        calls.append((copy.deepcopy(payload), copy.deepcopy(route)))
        assert "max_tokens" not in payload
        assert "MAIN_ONLY_SYNTHETIC_CREDENTIAL" not in json.dumps(payload)
        assert "AUX_ONLY_SYNTHETIC_CREDENTIAL" not in json.dumps(payload)
        if len(calls) == 1:
            request = httpx.Request("POST", route["base_url"])
            raise httpx.HTTPStatusError(
                "HTTP 401 Invalid token",
                request=request,
                response=httpx.Response(401, request=request),
            )
        return _summary_response()

    assert asyncio.run(engine.compact(messages, "System", send_summary))
    assert len(calls) == 2
    assert calls[0][0]["model"] == "oracle-summary"
    assert calls[0][1]["api_key"] == (
        "AUX_ONLY_SYNTHETIC_CREDENTIAL" if with_aux_key else ""
    )
    assert calls[0][1]["base_url"] == "http://aux.invalid/v1"
    assert calls[1][0]["model"] == "oracle-main"
    assert calls[1][1]["api_key"] == "MAIN_ONLY_SYNTHETIC_CREDENTIAL"
    assert calls[1][1]["base_url"] == "http://main.invalid/v1"


def test_threshold_and_overflow_share_budget_until_provider_confirms_recovery():
    engine, _, _ = _host(compression={"max_attempts": 1})
    messages = DRIVER.corpus()[1:]
    summary_calls = []

    async def send_summary(payload, route):
        summary_calls.append(copy.deepcopy(payload))
        return _summary_response()

    request = httpx.Request("POST", "http://main.invalid/v1/chat/completions")
    error = httpx.HTTPStatusError(
        "context_length_exceeded: prompt too long",
        request=request,
        response=httpx.Response(400, request=request),
    )

    async def run():
        engine.after_response(
            {"prompt_tokens": 120000, "completion_tokens": 128}, messages
        )
        assert await engine.after_tools(messages, "System", send_summary)
        assert engine.attempts == 1 and len(summary_calls) == 1
        messages.extend(DRIVER.corpus()[1:])
        grown = copy.deepcopy(messages)
        exhausted = await engine.recover(error, messages, "System", send_summary)
        assert not exhausted.retry
        assert exhausted.reason == "max_compression_attempts"
        assert messages == grown and len(summary_calls) == 1
        # Positive provider usage under the threshold proves the completed
        # rewrite worked. Rough shrinkage alone must not reset this budget.
        engine.after_response(
            {"prompt_tokens": 1000, "completion_tokens": 128}, messages
        )
        assert engine.attempts == 0
        recovered = await engine.recover(error, messages, "System", send_summary)
        assert recovered.retry
        assert messages != grown
        assert engine.attempts == 1 and len(summary_calls) == 2

    asyncio.run(run())


def test_disabled_automatic_maintenance_allows_explicit_manual_compaction():
    engine, tools, _ = _host(
        compression={
            "enabled": False,
            "micro_compact": True,
            "proactive_prune_tokens": 1,
        }
    )
    messages = DRIVER.corpus("tools")[1:]
    original = copy.deepcopy(messages)
    calls = []

    async def send_summary(payload, route):
        calls.append(payload)
        return _summary_response()

    async def run():
        engine.after_response(
            {"prompt_tokens": 120000, "completion_tokens": 128}, messages
        )
        assert not await engine.before_request(messages, "System", send_summary)
        assert not await engine.after_tools(messages, "System", send_summary)
        assert not await engine.finalise_turn(messages, "System", send_summary)
        assert messages == original and not calls
        assert await engine.compact(messages, "System", send_summary, force=True)

    asyncio.run(run())
    assert len(calls) == 1
    assert tools.read_resets == tools.skill_resets == 1


def test_checkpoint_required_keeps_history_without_capable_checkpoint_provider():
    engine, _, _ = _host(
        compression={"checkpoint_required": True, "micro_compact": True}
    )
    messages = DRIVER.corpus()[1:]
    original = copy.deepcopy(messages)
    calls = []

    async def send_summary(payload, route):
        calls.append(payload)
        return _summary_response()

    async def run():
        try:
            changed = await engine.compact(messages, "System", send_summary)
        except RuntimeError as error:
            assert "checkpoint" in str(error).lower()
            changed = False
        assert not changed
        assert not await engine.finalise_turn(messages, "System", send_summary)

    asyncio.run(run())
    assert not engine.compressor._micro_compact_enabled
    assert messages == original
    assert not calls


@pytest.mark.parametrize("failure", ["auth", "length", "empty"])
def test_native_manual_summary_failure_never_replaces_persisted_history(
    failure, tmp_path
):
    original = DRIVER.corpus()[1:]
    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "format": "hermes-native-v1",
                "messages": original,
                "context_state": {},
                "todos": {},
                "last_activity": time.time(),
            }
        )
    )
    config = {
        "llm": {
            "model_name": "oracle-main",
            "api_key": "synthetic-unused-key",
            "base_url": "http://manual.invalid/v1",
            "max_tokens": 4096,
        },
        "context_length": 131072,
        "enabled_tools": ["read_file"],
        "compression": {"enabled": True},
        "session_file": str(session_path),
    }
    requests = []

    def response(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "max_tokens" not in body
        if failure == "auth":
            return httpx.Response(401, json={"error": {"message": "Invalid token"}})
        return httpx.Response(
            200,
            json=_summary_response(
                "" if failure == "empty" else DRIVER.SUMMARY,
                finish="length" if failure == "length" else "stop",
            ),
        )

    actual_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return actual_client(
            *args, **kwargs, transport=httpx.MockTransport(response), trust_env=False
        )

    with (
        patch.object(httpx, "AsyncClient", client),
        patch.object(
            native_loop,
            "load_resources",
            return_value=SimpleNamespace(
                system_prompt="System",
                enabled_tools=["read_file"],
                diagnostics=[],
                settings=config,
            ),
        ),
    ):
        result = asyncio.run(
            native_loop.run(
                config,
                "/compress boundary check",
                tmp_path,
                Path(native_loop.__file__).parents[2],
            )
        )
    assert len(requests) == 1
    assert result.messages == original
    saved = json.loads(session_path.read_text())
    assert saved["messages"] == original
    assert not any(
        event.get("committed")
        for event in result.events
        if event["type"] == "compression"
    )


@pytest.mark.parametrize("async_checkpoint", [False, True])
def test_required_checkpoint_is_durable_before_summary_and_commit(
    async_checkpoint, tmp_path
):
    engine, tools, _ = _host(compression={"checkpoint_required": True})
    messages = DRIVER.corpus()[1:]
    original = copy.deepcopy(messages)
    session = Session(tmp_path / "session.json")

    async def checkpoint(values, state):
        return session.save_checkpoint(values, state)

    tools.checkpoint_context = (
        checkpoint if async_checkpoint else session.save_checkpoint
    )
    requests = []

    async def send_summary(payload, route):
        checkpoints = list(tmp_path.glob("session.json.checkpoints/*.json"))
        assert len(checkpoints) == 1
        retained = json.loads(checkpoints[0].read_text())
        assert retained["messages"] == original
        assert retained["context_state"]["version"] == 1
        requests.append(payload)
        return _summary_response()

    async def run():
        await session.open()
        try:
            assert await engine.compact(messages, "System", send_summary)
        finally:
            session.close()

    asyncio.run(run())
    assert len(requests) == 1 and messages != original
    checkpoint_file = next(tmp_path.glob("session.json.checkpoints/*.json"))
    assert json.loads(checkpoint_file.read_text())["messages"] == original
    assert engine.search_archive("Task 0")["total_matches"] > 0


def test_checkpoint_write_failure_keeps_history_and_never_sends_summary(tmp_path):
    engine, tools, events = _host(compression={"checkpoint_required": True})
    messages = DRIVER.corpus()[1:]
    original = copy.deepcopy(messages)
    session = Session(tmp_path / "session.json")
    tools.checkpoint_context = session.save_checkpoint
    requests = []

    async def send_summary(payload, route):
        requests.append(payload)
        return _summary_response()

    async def run():
        await session.open()
        try:
            with patch(
                "os.replace", side_effect=OSError("Synthetic disk write failure")
            ):
                assert not await engine.compact(messages, "System", send_summary)
        finally:
            session.close()

    asyncio.run(run())
    assert messages == original
    assert not requests
    assert not list(tmp_path.glob("session.json.checkpoints/*.json"))
    assert not list(tmp_path.glob("session.json.checkpoints/*.tmp"))
    assert not engine.search_archive()["results"]
    assert any(
        event.get("type") == "compression_checkpoint"
        and event.get("committed") is False
        for event in events
    )
