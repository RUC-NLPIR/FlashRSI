"""Exercise the Hermes adapter with real HTTP serialization and native tools."""

import asyncio
import json
import threading
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.hermes import Hermes
from flashrsi.agents.hermes.runtime.hermes_native import loop as native_loop
from flashrsi.agents.hermes.runtime.hermes_native.policy import (
    MAX_ITERATIONS_SUMMARY_REQUEST,
)


def _completion(content="", *, calls=None, finish="stop", usage=None):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return {
        "choices": [{"message": message, "finish_reason": finish}],
        "usage": usage or {"prompt_tokens": 4, "completion_tokens": 2},
    }


def _call(identifier, name, arguments):
    return {
        "id": identifier,
        "type": "function",
        "function": {
            "name": name,
            "arguments": (
                arguments if isinstance(arguments, str) else json.dumps(arguments)
            ),
        },
    }


def _agent(**overrides):
    llm = {
        "model_name": "hermes-test-model",
        "api_key": "hermes-test-credential",
        "base_url": "http://provider.invalid/v1",
        **overrides.pop("llm", {}),
    }
    return Hermes({"timeout": 10, "llm": llm, **overrides})


@pytest.fixture
def provider(monkeypatch):
    class Provider:
        replies = []
        requests = []

        def respond(self, request):
            self.requests.append(
                {
                    "url": str(request.url),
                    "body": json.loads(request.content),
                    "authorization": request.headers.get("Authorization"),
                }
            )
            assert self.replies, "unexpected additional provider request"
            reply = self.replies.pop(0)
            if callable(reply):
                reply = reply(self.requests[-1])
            return (
                reply
                if isinstance(reply, httpx.Response)
                else httpx.Response(200, json=reply)
            )

    value = Provider()
    original = httpx.AsyncClient

    def client(*args, **kwargs):
        return original(
            *args,
            **kwargs,
            transport=httpx.MockTransport(value.respond),
            trust_env=False,
        )

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return value


def _events(trajectory, kind):
    return [event for event in trajectory.messages if event["type"] == kind]


def _response_output(*items, status="completed", usage=None):
    return {
        "status": status,
        "output": list(items),
        "usage": usage or {"input_tokens": 4, "output_tokens": 2},
    }


def _response_text(text):
    return {
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text}],
    }


def test_fallback_changes_protocol_endpoint_and_credentials(provider, tmp_path):
    provider.replies = [
        httpx.Response(401, json={"error": {"message": "invalid API key"}}),
        _completion("backup completed"),
    ]
    agent = _agent(
        max_iterations=1,
        api_max_retries=1,
        llm={"model_api": "responses", "provider": "openai"},
        fallback_providers=[
            {
                "provider": "custom",
                "model": "backup-model",
                "base_url": "http://backup.invalid/v1",
                "api_key": "backup-key",
                "model_api": "chat_completions",
            }
        ],
    )
    result = asyncio.run(agent.run("finish", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "backup completed"
    assert [request["url"] for request in provider.requests] == [
        "http://provider.invalid/v1/responses",
        "http://backup.invalid/v1/chat/completions",
    ]
    assert [request["authorization"] for request in provider.requests] == [
        "Bearer hermes-test-credential",
        "Bearer backup-key",
    ]
    assert "input" in provider.requests[0]["body"]
    assert "messages" in provider.requests[1]["body"]
    assert _events(result, "hermes_result")[-1]["api_calls"] == 1


@pytest.mark.parametrize(
    "llm",
    [
        {"model_api": "bedrock_converse"},
        {"model_api": "gemini"},
        {"base_url": "https://generativelanguage.googleapis.com/v1beta"},
        {"provider": "copilot-acp"},
    ],
)
def test_unsupported_protocol_or_profile_fails_before_session_or_http(
    provider, tmp_path, llm
):
    result = asyncio.run(
        _agent(llm=llm, session_file="state.json").run("finish", tmp_path)
    )
    assert result.status == "error"
    assert provider.requests == []
    assert not (tmp_path / "state.json").exists()


def test_runtime_timestamp_is_stable_across_session_resume(provider, tmp_path):
    provider.replies = [_completion("first"), _completion("second")]
    agent = _agent(session_file="state.json")
    assert asyncio.run(agent.run("first", tmp_path)).status == "finished"
    started = json.loads((tmp_path / "state.json").read_text())["runtime_started_at"]
    assert started
    assert asyncio.run(agent.run("second", tmp_path)).status == "finished"
    assert (
        json.loads((tmp_path / "state.json").read_text())["runtime_started_at"]
        == started
    )


def test_responses_checkpoint_and_tool_ids_survive_real_loop_and_resume(
    provider, tmp_path
):
    state = tmp_path / "responses.json"
    provider.replies = [
        _response_output(
            {"type": "compaction", "encrypted_content": "opaque-checkpoint"},
            {
                "type": "function_call",
                "id": "fc_item",
                "call_id": "call_read",
                "name": "read_file",
                "arguments": '{"path":"note.txt"}',
            },
            usage={
                "input_tokens": 120000,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 40000},
            },
        ),
        _response_output(_response_text("read complete")),
        _response_output(_response_text("resumed")),
    ]
    (tmp_path / "note.txt").write_text("checkpoint file")
    agent = _agent(
        session_file=str(state),
        context_length=200000,
        compression={"codex_responses_native": True},
        llm={
            "model_name": "gpt-5.6",
            "model_api": "responses",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
        },
    )
    first = asyncio.run(agent.run("read the file", tmp_path))
    assert first.status == "finished", first.error_message
    assert first.output == "read complete"
    assert first.usage["input"] == 120004
    assert first.usage["cache_read_input_tokens"] == 40000
    body = provider.requests[1]["body"]
    assert provider.requests[0]["url"] == "https://api.openai.com/v1/responses"
    assert body["context_management"][0]["type"] == "compaction"
    assert "messages" not in body
    assert any(
        item.get("type") == "compaction"
        and item["encrypted_content"] == "opaque-checkpoint"
        for item in body["input"]
    )
    assert any(
        item.get("type") == "function_call_output"
        and item["call_id"] == "call_read"
        and "checkpoint file" in item["output"]
        for item in body["input"]
    )
    saved = json.loads(state.read_text())
    call = next(row for row in saved["messages"] if row.get("tool_calls"))[
        "tool_calls"
    ][0]
    assert call["call_id"] == "call_read"
    assert call["response_item_id"] == "fc_item"
    assert saved["context_state"]["anchor"] is not None
    second = asyncio.run(agent.run("continue", tmp_path))
    assert second.status == "finished", second.error_message
    assert second.output == "resumed"
    assert any(
        item.get("type") == "compaction"
        for item in provider.requests[-1]["body"]["input"]
    )


def test_responses_native_rejection_retries_once_and_persists_disabled_state(
    provider, tmp_path
):
    provider.replies = [
        httpx.Response(
            400, json={"error": {"message": "unknown field context_management"}}
        ),
        _response_output(_response_text("done")),
        _response_output(_response_text("next")),
    ]
    agent = _agent(
        max_iterations=1,
        session_file="state.json",
        compression={"codex_responses_native": True},
        llm={
            "model_name": "gpt-5.6",
            "api_mode": "responses",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
        },
    )
    first = asyncio.run(agent.run("hello", tmp_path))
    assert first.status == "finished", first.error_message
    assert "context_management" in provider.requests[0]["body"]
    assert "context_management" not in provider.requests[1]["body"]
    assert (tmp_path / "state.json").is_file()
    assert _events(first, "hermes_result")[-1]["api_calls"] == 1
    second = asyncio.run(agent.run("hello again", tmp_path))
    assert second.status == "finished", second.error_message
    assert "context_management" not in provider.requests[2]["body"]


def test_official_codex_sse_runs_without_sdk(provider, tmp_path):
    raw = _response_output(_response_text("SSE done"))
    provider.replies = [
        httpx.Response(
            200,
            text="event: response.completed\ndata: "
            + json.dumps({"type": "response.completed", "response": raw})
            + "\n\n",
            headers={"Content-Type": "text/event-stream"},
        )
    ]
    result = asyncio.run(
        _agent(
            llm={
                "model_name": "gpt-5.6",
                "model_api": "codex_responses",
                "provider": "openai-codex",
                "base_url": "https://chatgpt.com/backend-api/codex",
            }
        ).run("hi", tmp_path)
    )
    assert result.status == "finished", result.error_message
    assert result.output == "SSE done"
    assert provider.requests[0]["body"]["stream"] is True
    assert "extra_headers" not in provider.requests[0]["body"]
    assert "timeout" not in provider.requests[0]["body"]


def test_responses_incomplete_replays_checkpoint_and_escalates_once(provider, tmp_path):
    incomplete = _response_output(
        {"type": "compaction", "encrypted_content": "incomplete-checkpoint"},
        {
            "type": "reasoning",
            "id": "rs_1",
            "encrypted_content": "thinking",
            "summary": [{"type": "summary_text", "text": "work in progress"}],
        },
        status="incomplete",
        usage={"input_tokens": 4000, "output_tokens": 1000},
    )
    incomplete["incomplete_details"] = {"reason": "max_output_tokens"}
    provider.replies = [
        incomplete,
        _response_output(_response_text("answer")),
        _response_output(_response_text("new answer")),
    ]
    agent = _agent(
        session_file=str(tmp_path / "state.json"),
        compression={"codex_responses_native": True},
        llm={
            "model_name": "gpt-5.6",
            "model_api": "responses",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "max_tokens": 1000,
            "reasoning_effort": "high",
        },
    )
    result = asyncio.run(agent.run("solve", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "answer"
    second = provider.requests[1]["body"]
    assert second["max_output_tokens"] == 2000
    assert second["reasoning"]["effort"] == "none"
    assert any(item.get("type") == "compaction" for item in second["input"])
    result2 = asyncio.run(agent.run("solve again", tmp_path))
    assert result2.status == "finished", result2.error_message
    assert provider.requests[2]["body"]["max_output_tokens"] == 1000
    assert provider.requests[2]["body"]["reasoning"]["effort"] == "high"


def test_responses_truncated_tool_is_not_executed_and_ids_stay_paired(
    provider, tmp_path
):
    truncated = _response_output(
        {
            "type": "function_call",
            "id": "fc_bad",
            "call_id": "reused",
            "name": "write_file",
            "arguments": '{"path":"unsafe"',
        },
        status="incomplete",
    )
    truncated["incomplete_details"] = {"reason": "max_output_tokens"}

    def read_response(item):
        return _response_output(
            {
                "type": "function_call",
                "id": item,
                "call_id": "reused",
                "name": "read_file",
                "arguments": '{"path":"note.txt"}',
            }
        )

    provider.replies = [
        truncated,
        read_response("fc_first"),
        read_response("fc_second"),
        _response_output(_response_text("done")),
    ]
    (tmp_path / "note.txt").write_text("read me")
    result = asyncio.run(
        _agent(
            llm={"model_name": "gpt-5.6", "model_api": "responses", "max_tokens": 1000}
        ).run("read twice", tmp_path)
    )
    assert result.status == "finished", result.error_message
    assert not (tmp_path / "unsafe").exists()
    assert provider.requests[1]["body"]["max_output_tokens"] == 2000
    body = provider.requests[-1]["body"]
    calls = [
        item["call_id"] for item in body["input"] if item.get("type") == "function_call"
    ]
    results = [
        item["call_id"]
        for item in body["input"]
        if item.get("type") == "function_call_output"
    ]
    assert calls == results == ["reused", "reused_d2"]
    assert len(_events(result, "tool_execution_end")) == 2


def test_responses_summary_canonical_text_survives_stale_sidecar_and_checkpoint(
    provider, tmp_path
):
    state = tmp_path / "state.json"
    history = [
        {
            "role": "assistant",
            "content": "CANONICAL_HANDOFF",
            "_compressed_summary": True,
            "_compressed_summary_has_user_turn": True,
            "codex_message_items": [_response_text("STALE_VISIBLE_SIDECAR")],
        },
        {
            "role": "assistant",
            "content": "",
            "codex_reasoning_items": [
                {
                    "type": "compaction",
                    "encrypted_content": "checkpoint",
                    "_issuer_kind": "other:https://api.openai.com/v1",
                    "_issuer_model": "gpt-5.6",
                }
            ],
        },
    ]
    state.write_text(json.dumps({"format": "hermes-native-v1", "messages": history}))
    provider.replies = [_response_output(_response_text("done"))]
    result = asyncio.run(
        _agent(
            session_file=str(state),
            compression={"codex_responses_native": True},
            llm={
                "model_name": "gpt-5.6",
                "model_api": "responses",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
            },
        ).run("continue", tmp_path)
    )
    assert result.status == "finished", result.error_message
    serialized = json.dumps(provider.requests[0]["body"])
    assert any(
        item.get("type") == "compaction"
        for item in provider.requests[0]["body"]["input"]
    )
    assert "CANONICAL_HANDOFF" in serialized
    assert "STALE_VISIBLE_SIDECAR" not in serialized
    assert "_compressed_summary" not in serialized


def test_responses_manual_summary_honors_auxiliary_chat_protocol_and_key(
    provider, tmp_path
):
    state = tmp_path / "state.json"
    history = [
        {"role": role, "content": f"turn {index}: " + "detail " * 600}
        for index in range(20)
        for role in ("user", "assistant")
    ]
    state.write_text(json.dumps({"format": "hermes-native-v1", "messages": history}))
    provider.replies = [
        _completion("Prior progress, constraints, and next steps retained.")
    ]
    agent = _agent(
        session_file=str(state),
        auxiliary={
            "compression": {
                "api_mode": "chat_completions",
                "model": "summary-model",
                "provider": "custom",
                "base_url": "http://summary.invalid/v1",
                "api_key": "summary-key",
            }
        },
        llm={"model_name": "gpt-5.6", "model_api": "responses"},
    )
    result = asyncio.run(agent.run("/compress", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "Context compressed."
    sent = provider.requests[0]
    assert sent["url"] == "http://summary.invalid/v1/chat/completions"
    assert sent["authorization"] == "Bearer summary-key"
    assert sent["body"]["model"] == "summary-model"
    assert "input" not in sent["body"]


def test_explicit_session_restores_messages_and_active_todos(provider, tmp_path):
    state = tmp_path / "state.json"
    provider.replies = [
        _completion(
            calls=[
                _call(
                    "todo-1",
                    "todo_list",
                    {
                        "todos": [
                            {
                                "id": "task",
                                "content": "Retain this task",
                                "status": "in_progress",
                            }
                        ],
                    },
                )
            ],
            finish="tool_calls",
        ),
        _completion("First turn finished."),
        _completion(calls=[_call("todo-2", "todo_list", {})], finish="tool_calls"),
        _completion("Second turn finished."),
    ]
    agent = _agent(session_file=str(state))
    first = asyncio.run(agent.run("Create my task.", tmp_path))
    assert first.status == "finished", first.error_message
    persisted = json.loads(state.read_text())
    assert persisted["todos"]["todos"][0]["status"] == "in_progress"
    assert "hermes-test-credential" not in state.read_text()
    second = asyncio.run(agent.run("Continue the task.", tmp_path))
    assert second.status == "finished", second.error_message
    next_turn = provider.requests[2]["body"]["messages"]
    assert any(row.get("content") == "Create my task." for row in next_turn)
    assert any(row.get("content") == "First turn finished." for row in next_turn)
    restored = _events(second, "tool_execution_end")[0]
    assert json.loads(restored["result"])["todos"][0]["content"] == "Retain this task"


def test_corrupt_session_is_preserved_and_does_not_send_request(provider, tmp_path):
    state = tmp_path / "bad.json"
    state.write_text("{incomplete")
    result = asyncio.run(_agent(session_file=str(state)).run("work", tmp_path))
    assert result.status == "error"
    assert not provider.requests
    assert state.read_text() == "{incomplete"


def test_required_checkpoint_is_real_and_retains_original_history(provider, tmp_path):
    state = tmp_path / "checkpointed.json"
    history = [
        {"role": role, "content": f"{role} turn {index}: " + "detail " * 600}
        for index in range(20)
        for role in ("user", "assistant")
    ]
    state.write_text(json.dumps({"format": "hermes-native-v1", "messages": history}))
    provider.replies = [
        _completion(
            "The prior work and user constraints are preserved; continue the active task."
        )
    ]
    result = asyncio.run(
        _agent(
            session_file=str(state),
            compression={"checkpoint_required": True},
        ).run("/compress", tmp_path)
    )
    assert result.status == "finished", result.error_message
    assert result.output == "Context compressed."
    checkpoints = list((tmp_path / "checkpointed.json.checkpoints").glob("*.json"))
    assert len(checkpoints) == 1
    checkpoint = json.loads(checkpoints[0].read_text())
    assert checkpoint["messages"] == history
    assert checkpoints[0].stat().st_mode & 0o777 == 0o600
    assert "hermes-test-credential" not in checkpoints[0].read_text()
    assert len(json.loads(state.read_text())["messages"]) < len(history)


def test_hermes_snapshot_contains_native_runtime_and_identity():
    agent = _agent()
    assert agent.instruction_file == "SOUL.md"
    assert {
        "SOUL.md",
        "skills/autonomous-ai-agents/hermes-agent/SKILL.md",
        "runtime/hermes_native/loop.py",
        "runtime/hermes_native/policy.py",
        "runtime/hermes_native/tools.py",
        "runtime/hermes_native/resources.py",
        "runtime/hermes_native/_vendor/schemas.json",
    } <= set(agent.snapshot.files)
    assert not any(
        path.endswith((".js", ".ts")) or "node_modules/" in path
        for path in agent.snapshot.files
    )


def test_hermes_plain_reply_and_usage(provider, tmp_path):
    provider.replies = [
        _completion(
            "<think>internal</think>Native answer",
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 4},
            },
        )
    ]
    agent = _agent(max_iterations=1)
    result = asyncio.run(agent.run("hello", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "Native answer"
    assert result.usage["input"] == 10
    assert result.usage["output"] == 3
    assert result.usage["total_tokens"] == 13
    assert result.usage["cache_read_input_tokens"] == 4
    assert _events(result, "hermes_result")[-1]["completed"] is True
    assert provider.requests[0]["url"].endswith("/v1/chat/completions")
    assert provider.requests[0]["body"]["messages"][-1] == {
        "role": "user",
        "content": "hello",
    }


def test_hermes_multiround_tools_feed_real_results_back_to_model(provider, tmp_path):
    provider.replies = [
        _completion(
            calls=[
                _call(
                    "write", "write_file", {"path": "note.txt", "content": "native\n"}
                )
            ],
            finish="tool_calls",
        ),
        _completion(
            calls=[_call("read", "read_file", {"path": "note.txt"})],
            finish="tool_calls",
        ),
        _completion("The note now says native."),
    ]
    result = asyncio.run(_agent().run("write and verify", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "The note now says native."
    assert (tmp_path / "note.txt").read_text() == "native\n"
    assert [event["name"] for event in _events(result, "tool_execution_start")] == [
        "write_file",
        "read_file",
    ]
    tool_messages = [
        message
        for message in provider.requests[-1]["body"]["messages"]
        if message["role"] == "tool"
    ]
    assert [message["tool_call_id"] for message in tool_messages] == ["write", "read"]
    assert "native" in tool_messages[-1]["content"]
    assert "error" not in json.loads(tool_messages[0]["content"])
    assert result.usage["input"] == 12
    assert result.usage["output"] == 6


def test_hermes_tool_results_conform_to_strict_chat_message_schema(provider, tmp_path):
    def strict_followup(request):
        tool_messages = [
            message
            for message in request["body"]["messages"]
            if message["role"] == "tool"
        ]
        if any(
            set(message) - {"role", "content", "tool_call_id"}
            for message in tool_messages
        ):
            return httpx.Response(400, json={"error": "Unknown tool-message key"})
        return _completion("accepted by strict provider")

    provider.replies = [
        _completion(
            calls=[
                _call("write", "write_file", {"path": "note.txt", "content": "native"})
            ],
            finish="tool_calls",
        ),
        strict_followup,
    ]
    result = asyncio.run(_agent().run("write", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "accepted by strict provider"
    assert _events(result, "tool_execution_start")[0]["name"] == "write_file"


@pytest.mark.parametrize("same_batch", [False, True])
def test_hermes_planner_respects_terminal_cwd(
    provider, tmp_path, monkeypatch, same_batch
):
    directory = tmp_path / "subdir"
    directory.mkdir()
    note = directory / "note.txt"
    note.write_text("before\n")
    cd = _call("cd", "terminal", {"command": "cd subdir"})
    file_calls = [
        _call("read", "read_file", {"path": "note.txt"}),
        _call("write", "write_file", {"path": str(note), "content": "after\n"}),
    ]
    provider.replies = (
        [_completion(calls=[cd, *file_calls], finish="tool_calls")]
        if same_batch
        else [
            _completion(calls=[cd], finish="tool_calls"),
            _completion(calls=file_calls, finish="tool_calls"),
        ]
    ) + [_completion("done")]
    original_execute = native_loop.HermesTools.execute
    reading = threading.Event()
    writing = threading.Event()
    overlapped = []

    def execute(tools, name, arguments):
        if name == "read_file":
            reading.set()
            try:
                # A conflicting writer must wait for this read. Give an
                # incorrectly concurrent writer a deterministic chance to run.
                writing.wait(timeout=0.2)
                return original_execute(tools, name, arguments)
            finally:
                reading.clear()
        if name == "write_file":
            reading.wait(timeout=0.5)
            overlapped.append(reading.is_set())
            writing.set()
        return original_execute(tools, name, arguments)

    monkeypatch.setattr(native_loop.HermesTools, "execute", execute)
    result = asyncio.run(
        native_loop.run(
            {
                "timeout": 10,
                "llm": {
                    "model_name": "cwd-test",
                    "api_key": "test-key",
                    "base_url": "http://provider.invalid/v1",
                },
            },
            "change directory, then read before writing",
            tmp_path,
            Path(__file__).parents[1] / "flashrsi/agents/hermes",
        )
    )
    assert result.status == "finished", result.error_message
    assert overlapped == [False]
    read_result = next(
        message for message in result.messages if message.get("tool_call_id") == "read"
    )
    assert "before" in read_result["content"]
    assert note.read_text() == "after\n"


def test_hermes_v4a_move_finishes_before_reading_destination(
    provider, tmp_path, monkeypatch
):
    (tmp_path / "old.txt").write_text("moved content\n")
    patch = "*** Begin Patch\n*** Move File: old.txt -> renamed.txt\n*** End Patch"
    provider.replies = [
        _completion(
            calls=[
                _call("move", "patch", {"mode": "patch", "patch": patch}),
                _call("read", "read_file", {"path": "renamed.txt"}),
            ],
            finish="tool_calls",
        ),
        _completion("The moved file was read successfully."),
    ]
    original = native_loop.HermesTools.execute
    moving, reading = threading.Event(), threading.Event()
    overlapped = []

    def execute(tools, name, arguments):
        if name == "patch":
            moving.set()
            try:
                reading.wait(timeout=0.2)
                return original(tools, name, arguments)
            finally:
                moving.clear()
        if name == "read_file":
            overlapped.append(moving.is_set())
            reading.set()
        return original(tools, name, arguments)

    monkeypatch.setattr(native_loop.HermesTools, "execute", execute)
    result = asyncio.run(
        native_loop.run(
            {
                "llm": {
                    "model_name": "gpt-5-mini",
                    "api_key": "test-key",
                    "base_url": "http://provider.invalid/v1",
                },
                "enabled_toolsets": ["file"],
            },
            "Move the file and read it.",
            tmp_path,
            Path(__file__).parents[1] / "flashrsi/agents/hermes",
        )
    )
    assert result.status == "finished", result.error_message
    assert overlapped == [False]
    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "renamed.txt").read_text() == "moved content\n"
    tool_messages = provider.requests[-1]["body"]["messages"]
    read_result = next(
        row for row in tool_messages if row.get("tool_call_id") == "read"
    )
    assert json.loads(read_result["content"])["content"] == "1|moved content"


def test_hermes_duplicate_calls_execute_once_and_keep_first_call_id(provider, tmp_path):
    command = "printf x >> counter.txt"
    provider.replies = [
        _completion(
            calls=[
                _call("first", "terminal", {"command": command, "timeout": 5}),
                _call(
                    "duplicate",
                    "terminal",
                    json.dumps({"timeout": 5, "command": command}),
                ),
            ],
            finish="tool_calls",
        ),
        _completion("done"),
    ]
    result = asyncio.run(
        _agent(enabled_tools=["terminal"]).run("append once", tmp_path)
    )
    assert result.status == "finished", result.error_message
    assert (tmp_path / "counter.txt").read_text() == "x"
    assert len(_events(result, "tool_execution_start")) == 1
    messages = provider.requests[-1]["body"]["messages"]
    assistant = next(message for message in messages if message.get("tool_calls"))
    assert [call["id"] for call in assistant["tool_calls"]] == ["first"]
    assert [
        message["tool_call_id"] for message in messages if message["role"] == "tool"
    ] == ["first"]


def test_hermes_iteration_limit_requests_summary_without_executing_summary_tools(
    provider, tmp_path
):
    provider.replies = [
        _completion(
            calls=[
                _call("work", "write_file", {"path": "done.txt", "content": "done"})
            ],
            finish="tool_calls",
        ),
        _completion(
            "Partial summary",
            calls=[
                _call(
                    "summary-action",
                    "write_file",
                    {"path": "unexpected.txt", "content": "bad"},
                )
            ],
            finish="tool_calls",
        ),
    ]
    result = asyncio.run(_agent(max_iterations=1).run("work", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "Partial summary"
    assert (tmp_path / "done.txt").read_text() == "done"
    assert not (tmp_path / "unexpected.txt").exists()
    assert len(_events(result, "tool_execution_start")) == 1
    assert _events(result, "hermes_result")[-1]["completed"] is False
    assert (
        provider.requests[-1]["body"]["messages"][-1]["content"]
        == MAX_ITERATIONS_SUMMARY_REQUEST
    )
    # Current upstream retains tools to preserve the provider's cached prefix;
    # its final-summary path ignores emitted tool calls.
    assert (
        provider.requests[-1]["body"]["tools"] == provider.requests[0]["body"]["tools"]
    )
    assert len(provider.requests) == 2


@pytest.mark.parametrize("tool_name", ["terminal", "unknown_tool"])
def test_hermes_unknown_or_disabled_tools_never_execute(provider, tmp_path, tool_name):
    provider.replies = [
        _completion(
            calls=[_call("rejected", tool_name, {"command": "touch unexpected.txt"})],
            finish="tool_calls",
        ),
        _completion("recovered"),
    ]
    result = asyncio.run(_agent(enabled_tools=["read_file"]).run("read only", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "recovered"
    assert not (tmp_path / "unexpected.txt").exists()
    assert not _events(result, "tool_execution_start")
    followup = provider.requests[-1]["body"]
    assert [schema["function"]["name"] for schema in followup["tools"]] == ["read_file"]
    error = next(
        message for message in followup["messages"] if message["role"] == "tool"
    )
    assert error["tool_call_id"] == "rejected"
    assert "does not exist" in error["content"]


def test_hermes_mixed_unknown_and_valid_batch_runs_only_valid_call(provider, tmp_path):
    provider.replies = [
        _completion(
            calls=[
                _call("unknown", "unknown_tool", {}),
                _call("valid", "write_file", {"path": "valid.txt", "content": "yes"}),
            ],
            finish="tool_calls",
        ),
        _completion("done"),
    ]
    result = asyncio.run(_agent().run("work", tmp_path))
    assert result.status == "finished", result.error_message
    assert (tmp_path / "valid.txt").read_text() == "yes"
    assert [event["id"] for event in _events(result, "tool_execution_start")] == [
        "valid"
    ]
    messages = provider.requests[-1]["body"]["messages"]
    assistant = next(message for message in messages if message.get("tool_calls"))
    assert [call["id"] for call in assistant["tool_calls"]] == ["unknown", "valid"]
    assert {
        message["tool_call_id"] for message in messages if message["role"] == "tool"
    } == {"unknown", "valid"}


def test_hermes_length_tool_call_is_retried_without_side_effects(provider, tmp_path):
    provider.replies = [
        _completion(
            calls=[
                _call(
                    "truncated",
                    "write_file",
                    {"path": "unexpected.txt", "content": "bad"},
                )
            ],
            finish="length",
        ),
        _completion("recovered"),
    ]
    result = asyncio.run(_agent(max_iterations=1).run("work", tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "recovered"
    assert not (tmp_path / "unexpected.txt").exists()
    assert not _events(result, "tool_execution_start")
    assert len(provider.requests) == 2
    first, second = (request["body"].copy() for request in provider.requests)
    assert "max_tokens" not in first
    assert second.pop("max_tokens") == 8192
    assert first == second


def test_hermes_incomplete_json_call_is_rejected_before_execution(provider, tmp_path):
    provider.replies = [
        _completion(
            calls=[
                _call("truncated", "write_file", '{"path":"unexpected.txt","content":')
            ],
            finish="tool_calls",
        )
    ]
    result = asyncio.run(_agent().run("work", tmp_path))
    assert result.status == "error"
    assert "Truncated tool arguments" in result.error_message
    assert not (tmp_path / "unexpected.txt").exists()
    assert not _events(result, "tool_execution_start")
    assert len(provider.requests) == 1


def test_hermes_adapter_timeout_stops_terminal_before_returning(provider, tmp_path):
    provider.replies = [
        _completion(
            calls=[
                _call(
                    "long-command",
                    "terminal",
                    {
                        "command": "printf started > started.txt; sleep 0.4; printf late > late.txt"
                    },
                )
            ],
            finish="tool_calls",
        )
    ]

    async def exercise():
        result = await _agent(timeout=0.2, enabled_tools=["terminal"]).run(
            "work", tmp_path
        )
        assert (tmp_path / "started.txt").exists()
        assert not (tmp_path / "late.txt").exists()
        await asyncio.sleep(0.45)
        assert not (tmp_path / "late.txt").exists()
        return result

    result = asyncio.run(exercise())
    assert result.status == "error"
    assert "timed out" in result.error_message
    assert len(provider.requests) == 1


@pytest.mark.parametrize("http_failure", [False, True])
def test_hermes_provider_errors_return_redacted_trajectory(
    provider, tmp_path, http_failure
):
    credential = "hermes-sensitive-provider-credential"
    provider.replies = [
        httpx.Response(401, text=credential)
        if http_failure
        else {"error": {"message": f"rejected {credential}"}}
    ]
    result = asyncio.run(
        _agent(
            api_max_retries=1,
            llm={
                "api_key": credential,
                "base_url": f"http://provider.invalid/{credential}/v1",
            },
        ).run("work", tmp_path)
    )
    assert result.status == "error"
    assert result.error_message
    assert credential not in json.dumps(
        {
            "error": result.error_message,
            "messages": [dict(message) for message in result.messages],
        }
    )
    assert _events(result, "hermes_result")[-1]["failed"] is True
    assert len(provider.requests) == 1


def test_hermes_target_and_worker_use_independent_provider_parameters(
    provider, tmp_path
):
    provider.replies = [_completion("target"), _completion("worker")]
    agents = [
        _agent(
            llm={
                "model_name": "target-model",
                "api_key": "target-key",
                "base_url": "http://target.invalid/v1",
                "temperature": 0.2,
                "max_tokens": 31,
            }
        ),
        _agent(
            llm={
                "model_name": "worker-model",
                "api_key": "worker-key",
                "base_url": "http://worker.invalid/v1",
                "temperature": 0.7,
                "max_tokens": 63,
            }
        ),
    ]
    for agent in agents:
        result = asyncio.run(agent.run("hello", tmp_path))
        assert result.status == "finished", result.error_message
    for request, role, temperature, maximum in zip(
        provider.requests, ["target", "worker"], [0.2, 0.7], [31, 63]
    ):
        assert request["url"] == f"http://{role}.invalid/v1/chat/completions"
        assert request["authorization"] == f"Bearer {role}-key"
        assert request["body"]["model"] == f"{role}-model"
        assert request["body"]["temperature"] == temperature
        assert request["body"]["max_tokens"] == maximum
    missing = _agent(llm={"model_name": "worker-model", "api_key": ""})
    result = asyncio.run(missing.run("hello", tmp_path))
    assert result.status == "error"
    assert "api_key is required for this role" in result.error_message
    assert len(provider.requests) == 2


def test_hermes_selected_snapshot_executes_changed_runtime_and_soul(provider, tmp_path):
    credential = "snapshot-redaction-credential"
    provider.replies = [
        _completion("before"),
        _completion(f"after {credential}"),
        _completion("restored"),
    ]
    agent = _agent(llm={"api_key": credential})
    seed = agent.snapshot
    with seed.check_out() as files:
        with (files / "runtime/hermes_native/__init__.py").open("a") as stream:
            stream.write(
                "\n_seed_run = run\n"
                "async def run(*args, **kwargs):\n"
                "    result = await _seed_run(*args, **kwargs)\n"
                "    result.output = 'SELECTED_RUNTIME:' + result.output\n"
                "    return result\n"
            )
        with (files / "SOUL.md").open("a") as stream:
            stream.write("\nSELECTED_HERMES_SOUL\n")
        selected = seed.commit(files)
    before = asyncio.run(agent.run("hello", tmp_path))
    agent.update(selected)
    after = asyncio.run(agent.run("hello", tmp_path))
    agent.update(seed)
    restored = asyncio.run(agent.run("hello", tmp_path))
    assert before.output == "before"
    assert after.status == "finished", after.error_message
    assert after.output == "SELECTED_RUNTIME:after [REDACTED]"
    assert restored.output == "restored"
    assert after.messages[0]["snapshot_id"] == selected.id
    assert selected.id != seed.id
    assert "SELECTED_HERMES_SOUL" not in json.dumps(provider.requests[0]["body"])
    assert "SELECTED_HERMES_SOUL" in json.dumps(provider.requests[1]["body"])
    assert "SELECTED_HERMES_SOUL" not in json.dumps(provider.requests[2]["body"])
    assert credential not in json.dumps([dict(message) for message in after.messages])
