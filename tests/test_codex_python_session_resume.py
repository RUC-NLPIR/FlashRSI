"""Source-directed cached-turn/steering cases using real localhost sessions.

The old-model compaction branches use controlled ModelInfo variants because
the pinned catalog has equal context windows; no native equivalence is claimed
for those synthetic variants. Ordering follows core/src/session/turn.rs.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from test_codex_core_parity import _events, _responses_server

from flashrsi.agents.codex.python_core import loop
from flashrsi.agents.codex.python_core.context import message
from flashrsi.agents.codex.python_core.models import Model
from flashrsi.agents.codex.python_core.subagents import NAMESPACE


def _request(tmp_path, replay, *, model="gpt-5", settings=None, **extra):
    home, task = tmp_path / "home", tmp_path / "task"
    home.mkdir(exist_ok=True)
    task.mkdir(exist_ok=True)
    if not (home / "python_core/resource_assets").exists():
        shutil.copytree(
            Path(loop.__file__).parent / "resource_assets",
            home / "python_core/resource_assets",
        )
    return {
        "home": str(home),
        "cwd": str(task),
        "environment": {},
        "prompt": "FIRST_USER_TASK",
        "settings": {
            "approval_policy": "never",
            "sandbox_mode": "danger-full-access",
            "project_doc_max_bytes": 0,
            "features": {"plugins": False, "unified_exec": False},
            **(settings or {}),
        },
        "llm": {
            "model_name": model,
            "api_key": "local-session-test-key",
            "base_url": replay.base_url,
        },
        **extra,
    }


def _text(items):
    return "\n".join(
        part.get("text", "") for item in items for part in item.get("content", [])
    )


def test_cached_model_effort_and_client_configuration_update(tmp_path):
    async def scenario(replay):
        cache = {}
        request = _request(tmp_path, replay, model="gpt-5.4", _session_cache=cache)
        first = await loop.run_session(request, lambda event: None)
        assert first["status"] == "finished", first["error_message"]
        resources, router, subagents = (
            cache[key] for key in ("resources", "router", "subagents")
        )
        base = replay.requests[0]["body"]["instructions"]
        second_events = []
        next_request = {
            **request,
            "prompt": "SECOND_USER_TASK",
            "llm": {
                **request["llm"],
                "model_name": "gpt-5.4-mini",
                "reasoning_effort": "high",
            },
        }
        second = await loop.run_session(next_request, second_events.append)
        assert second["status"] == "finished", second["error_message"]
        third = await loop.run_session(
            {
                **next_request,
                "prompt": "THIRD_USER_TASK",
                "llm": {**next_request["llm"], "reasoning_effort": "low"},
            },
            second_events.append,
        )
        assert third["status"] == "finished", third["error_message"]
        bodies = [request["body"] for request in replay.requests]
        assert [body["model"] for body in bodies] == [
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-mini",
        ]
        assert [body["reasoning"]["effort"] for body in bodies[1:]] == ["high", "low"]
        assert bodies[1]["instructions"] == bodies[2]["instructions"] == base
        switch = next(
            item for item in bodies[1]["input"] if "<model_switch>" in _text([item])
        )
        assert switch["role"] == "developer"
        assert Model("gpt-5.4-mini", request["settings"]).instructions in _text(
            [switch]
        )
        assert _text(bodies[2]["input"]).count("<model_switch>") == 1
        assert all("FIRST_USER_TASK" in _text(body["input"]) for body in bodies)
        assert (
            bodies[0]["prompt_cache_key"]
            == bodies[1]["prompt_cache_key"]
            == bodies[2]["prompt_cache_key"]
        )
        assert second["usage"]["input_tokens"] == third["usage"]["input_tokens"] == 20
        assert (
            cache["resources"] is resources
            and cache["router"] is router
            and cache["subagents"] is subagents
        )
        assert cache["history"].model is router.model is cache["client"].model
        assert resources.memories.settings is router.settings is subagents.settings
        assert any(
            event["type"] == "response.output_item.done" for event in second_events
        )
        await loop.close_session(cache)

    with _responses_server() as replay:
        replay.reset(
            [(200, _events(response_id=f"resp_{index}")) for index in range(3)]
        )
        asyncio.run(scenario(replay))
        assert not replay.steps and not replay.errors


@pytest.mark.parametrize("change", ["model", "resource"])
def test_cached_capability_changes_reject_before_sampling(tmp_path, change):
    async def scenario(replay):
        cache = {}
        request = _request(tmp_path, replay, model="gpt-5.4", _session_cache=cache)
        first = await loop.run_session(request, lambda event: None)
        assert first["status"] == "finished", first["error_message"]
        next_request = {**request, "prompt": "UNSUPPORTED_SECOND_TURN"}
        if change == "model":
            next_request["llm"] = {**request["llm"], "model_name": "gpt-5.6-sol"}
        else:
            next_request["settings"] = {
                **request["settings"],
                "memories": {"use_memories": True},
            }
        second = await loop.run_session(next_request, lambda event: None)
        assert second["status"] == "error"
        assert (
            "capabilities" in second["error_message"]
            or "resource configuration" in second["error_message"]
        )
        assert len(replay.requests) == 1
        assert "UNSUPPORTED_SECOND_TURN" not in _text(cache["history"].items)
        assert cache["client"].model.info["slug"] == "gpt-5.4"
        await loop.close_session(cache)

    with _responses_server() as replay:
        replay.reset([(200, _events())])
        asyncio.run(scenario(replay))
        assert not replay.steps and not replay.errors


@pytest.mark.parametrize("reason", ["comp_hash_changed", "model_downshift"])
@pytest.mark.parametrize("remote", [False, True])
def test_previous_model_compaction_uses_current_effort_and_preserves_base_prompt(
    tmp_path, monkeypatch, reason, remote
):
    class ControlledModel(Model):
        def __init__(self, name, settings):
            super().__init__(name, settings)
            self.instructions = (
                "BASE_A" if name == "model-a" else "MODEL_B_INSTRUCTIONS"
            )
            self.info.update(
                context_window=100000 if name == "model-a" else 50000,
                max_context_window=100000,
                comp_hash="a"
                if name == "model-a" or reason == "model_downshift"
                else "b",
                supported_reasoning_levels=[
                    {"effort": value} for value in ["low", "medium", "high"]
                ],
            )

    monkeypatch.setattr(loop, "Model", ControlledModel)

    async def scenario(replay):
        cache = {}
        settings = (
            {
                "model_provider": "openai",
                "features": {"plugins": False, "unified_exec": False},
            }
            if remote
            else {}
        )
        request = _request(
            tmp_path, replay, model="model-a", settings=settings, _session_cache=cache
        )
        first = await loop.run_session(request, lambda event: None)
        assert first["status"] == "finished", first["error_message"]
        if reason == "model_downshift":
            cache["history"].last_usage["total_tokens"] = 46000
        second = await loop.run_session(
            {
                **request,
                "prompt": "NEW_USER_MUST_FOLLOW_COMPACT",
                "llm": {
                    **request["llm"],
                    "model_name": "model-b",
                    "reasoning_effort": "ultra",
                },
            },
            lambda event: None,
        )
        assert second["status"] == "finished", second["error_message"]
        assert len(replay.requests) == 3
        compact, resumed = [request["body"] for request in replay.requests[1:]]
        assert compact["model"] == "model-a" and resumed["model"] == "model-b"
        assert compact["reasoning"]["effort"] == "medium"
        assert resumed["reasoning"]["effort"] == "max"
        assert compact["instructions"] == resumed["instructions"] == "BASE_A"
        assert "NEW_USER_MUST_FOLLOW_COMPACT" not in _text(compact["input"])
        assert "<model_switch>" not in _text(compact["input"])
        assert "NEW_USER_MUST_FOLLOW_COMPACT" in _text(resumed["input"])
        assert "MODEL_B_INSTRUCTIONS" in _text(resumed["input"])
        metadata = json.loads(compact["client_metadata"]["x-codex-turn-metadata"])
        assert metadata["compaction"]["phase"] == "pre_turn"
        assert metadata["compaction"]["reason"] == reason
        await loop.close_session(cache)

    checkpoint = (
        b'data: {"type":"response.output_item.done","item":{"type":"compaction","id":"cmp_test","encrypted_content":"opaque"}}\n\n'
        + _events()
    )
    with _responses_server() as replay:
        replay.reset(
            [
                (200, _events(response_id="resp_first")),
                (
                    200,
                    checkpoint
                    if remote
                    else _events(text="SUMMARY", response_id="resp_summary"),
                ),
                (200, _events(response_id="resp_next")),
            ]
        )
        asyncio.run(scenario(replay))
        assert not replay.steps and not replay.errors


def test_pending_steer_is_excluded_from_compaction_and_first_tool_continuation(
    tmp_path,
):
    async def scenario(replay):
        queue = asyncio.Queue()
        queue.put_nowait("PENDING_STEER")
        request = _request(
            tmp_path,
            replay,
            settings={"model_auto_compact_token_limit": 30000},
            _input_queue=queue,
        )
        result = await loop.run_session(request, lambda event: None)
        assert result["status"] == "finished", result["error_message"]
        assert result["output"] == "FINAL_AFTER_STEER"
        assert len(replay.requests) == 4
        texts = [_text(request["body"]["input"]) for request in replay.requests]
        assert all("PENDING_STEER" not in text for text in texts[:3])
        assert texts[3].count("PENDING_STEER") == 1
        assert all("FIRST_USER_TASK" in text for text in texts)
        assert (tmp_path / "task" / "counter").read_text() == "x"
        assert queue.empty()

    high_usage = (
        _events(
            call=("shell_command", {"command": "printf x >> counter"}),
            response_id="resp_tool",
        )
        .replace(b'"input_tokens": 20', b'"input_tokens": 32000')
        .replace(b'"total_tokens": 23', b'"total_tokens": 32003')
    )
    with _responses_server() as replay:
        replay.reset(
            [
                (200, high_usage),
                (200, _events(text="SUMMARY", response_id="resp_summary")),
                (200, _events(text="AFTER_TOOL", response_id="resp_after_tool")),
                (
                    200,
                    _events(text="FINAL_AFTER_STEER", response_id="resp_after_steer"),
                ),
            ]
        )
        asyncio.run(scenario(replay))
        assert not replay.steps and not replay.errors


def test_notify_injection_follows_tool_output_and_precedes_next_sample(
    tmp_path, monkeypatch
):
    from flashrsi.agents.codex.python_core.tools import ToolRouter

    execute = ToolRouter.execute

    async def notify(self, call):
        result = await execute(self, call)
        self.inject(message("user", "ASYNC_NOTIFY_RESULT"))
        return result

    monkeypatch.setattr(ToolRouter, "execute", notify)
    with _responses_server() as replay:
        replay.reset(
            [
                (
                    200,
                    _events(
                        call=("shell_command", {"command": "printf TOOL_RESULT"}),
                        response_id="resp_tool",
                    ),
                ),
                (200, _events()),
            ]
        )
        result = asyncio.run(
            loop.run_session(_request(tmp_path, replay), lambda event: None)
        )
        assert result["status"] == "finished", result["error_message"]
        history = replay.requests[1]["body"]["input"]
        output_index = next(
            index
            for index, item in enumerate(history)
            if item["type"] == "function_call_output"
        )
        assert "ASYNC_NOTIFY_RESULT" in _text([history[output_index + 1]])
        assert _text(history).count("ASYNC_NOTIFY_RESULT") == 1
        assert not replay.steps and not replay.errors


def test_cached_turn_fork_reads_current_history_provider(tmp_path, monkeypatch):
    real_session = loop.run_session

    async def scenario(replay):
        inherited, started, cache = [], asyncio.Event(), {}

        async def child(request, emit):
            inherited.extend(request["initial_history"])
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(loop, "run_session", child)
        request = _request(tmp_path, replay, _session_cache=cache)
        first = await real_session(request, lambda event: None)
        assert first["status"] == "finished", first["error_message"]
        second = await real_session(
            {**request, "prompt": "CURRENT_CACHED_TURN"}, lambda event: None
        )
        assert second["status"] == "finished", second["error_message"]
        await asyncio.wait_for(started.wait(), 2)
        assert "FIRST_USER_TASK" in _text(inherited)
        assert "FIRST_ASSISTANT_RESULT" in _text(inherited)
        assert "CURRENT_CACHED_TURN" in _text(inherited)
        assert all(item["type"] == "message" for item in inherited)
        await loop.close_session(cache)

    with _responses_server() as replay:
        replay.reset(
            [
                (
                    200,
                    _events(text="FIRST_ASSISTANT_RESULT").replace(
                        b'"role": "assistant"',
                        b'"role": "assistant", "phase": "final_answer"',
                    ),
                ),
                (
                    200,
                    _events(
                        call=(
                            f"{NAMESPACE}.spawn_agent",
                            {"message": "INHERIT_CURRENT_TASK", "fork_context": True},
                        ),
                        response_id="resp_spawn",
                    ),
                ),
                (200, _events(text="PARENT_CONTINUES")),
            ]
        )
        asyncio.run(scenario(replay))
        assert not replay.steps and not replay.errors


def test_failed_pre_turn_model_migration_retries_previous_model(tmp_path, monkeypatch):
    class ControlledModel(Model):
        def __init__(self, name, settings):
            super().__init__(name, settings)
            self.info["comp_hash"] = name

    monkeypatch.setattr(loop, "Model", ControlledModel)

    async def scenario(replay):
        cache = {}
        request = _request(
            tmp_path,
            replay,
            model="model-a",
            settings={
                "model_provider": "local",
                "model_providers": {"local": {"stream_max_retries": 0}},
            },
            _session_cache=cache,
        )
        first = await loop.run_session(request, lambda event: None)
        assert first["status"] == "finished", first["error_message"]
        next_request = {
            **request,
            "prompt": "MIGRATION_INPUT",
            "llm": {**request["llm"], "model_name": "model-b"},
        }
        failed = await loop.run_session(next_request, lambda event: None)
        assert failed["status"] == "error"
        assert cache["previous_model"].info["slug"] == "model-a"
        assert "MIGRATION_INPUT" not in _text(cache["history"].items)
        resumed = await loop.run_session(next_request, lambda event: None)
        assert resumed["status"] == "finished", resumed["error_message"]
        assert [request["body"]["model"] for request in replay.requests] == [
            "model-a",
            "model-a",
            "model-a",
            "model-b",
        ]
        assert cache["previous_model"].info["slug"] == "model-b"
        assert _text(cache["history"].items).count("MIGRATION_INPUT") == 1
        await loop.close_session(cache)

    with _responses_server() as replay:
        replay.reset(
            [
                (200, _events()),
                (
                    200,
                    b'data: {"type":"response.failed","response":{"error":{"code":"invalid_prompt","message":"reject migration"}}}\n\n',
                ),
                (200, _events(text="MIGRATION_SUMMARY")),
                (200, _events()),
            ]
        )
        asyncio.run(scenario(replay))
        assert not replay.steps and not replay.errors
