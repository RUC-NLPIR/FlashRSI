from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path

import pytest
from codex_test_support import _events, _responses_server

from flashrsi.agents.codex.python_core.models import Model
from flashrsi.agents.codex.python_core.shell import ToolError
from flashrsi.agents.codex.python_core.subagents import Subagents, collaboration_spec
from flashrsi.agents.codex.python_core.tools import ToolRouter


def run(awaitable):
    return asyncio.run(awaitable)


def setup(tmp_path, session, settings=None):
    settings = {
        "sandbox_mode": "danger-full-access",
        "model": "gpt-5",
        "_thread_id": "root",
        **(settings or {}),
    }
    model = Model(settings["model"], settings)
    events = []
    router = ToolRouter(settings, tmp_path, model, events.append)
    request = {
        "home": str(tmp_path),
        "cwd": str(tmp_path),
        "settings": settings,
        "llm": {"model_name": settings["model"]},
        "environment": {},
        "_input_queue": asyncio.Queue(),
    }
    return Subagents(router, request, events.append, session), router, request, events


def test_v1_complete_schema_matches_local_native_oracle():
    root = Path(__file__).parents[1]
    path = root / ".cache/codex-python/gpt-5-request.json"
    if not path.exists():
        pytest.skip("explicit native oracle capture not present")
    body = json.loads(path.read_text())["body"]
    body = json.loads(body) if isinstance(body, str) else body
    native = next(tool for tool in body["tools"] if tool["type"] == "namespace")
    catalog = json.loads(
        (root / "flashrsi/agents/codex/python_core/assets/models.json").read_text()
    )["models"]
    assert collaboration_spec(catalog, {}, {}, {}) == native


def test_spawn_wait_followup_persistent_cache_and_close(tmp_path):
    async def scenario():
        requests = []
        closed = []

        async def session(request, emit):
            requests.append(request)
            cache = request["_session_cache"]
            cache.setdefault("mcp_session", object())
            emit({"type": "request"})
            await asyncio.sleep(0.01)
            history = request.get("initial_history", []) + [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": request["prompt"]}],
                }
            ]
            request["_history_sink"](history)
            return {
                "status": "success",
                "output": request["prompt"],
                "history": history,
                "usage": {"input_tokens": 4},
            }

        async def close_session(cache):
            closed.append(cache["mcp_session"])
            cache.clear()

        manager, router, request, events = setup(tmp_path, session)
        request["_close_session"] = close_session
        spawned = await manager.spawn_agent({"message": "first"})
        agent_id = spawned["agent_id"]
        assert uuid.UUID(agent_id)
        assert isinstance(spawned["nickname"], str) and spawned["nickname"]
        waited = await manager.wait_agent({"targets": [agent_id]})
        assert waited == {
            "status": {agent_id: {"completed": "first"}},
            "timed_out": False,
        }
        notice = request["_input_queue"].get_nowait()[0]["content"][0]["text"]
        assert (
            notice
            == '<subagent_notification>\n{"agent_path":"'
            + agent_id
            + '","status":{"completed":"first"}}\n</subagent_notification>'
        )
        submitted = await manager.send_input({"target": agent_id, "message": "second"})
        assert uuid.UUID(submitted["submission_id"])
        assert (await manager.wait_agent({"targets": [agent_id]}))["status"][
            agent_id
        ] == {"completed": "second"}
        assert requests[0]["_session_cache"] is requests[1]["_session_cache"]
        assert uuid.UUID(requests[1]["settings"]["_turn_id"])
        assert requests[1]["settings"]["_turn_id"] == submitted["submission_id"]
        assert len(requests[1]["initial_history"]) == 1
        assert manager.tree[agent_id].usage == {"input_tokens": 8}
        previous = await manager.close_agent({"target": agent_id})
        assert previous == {"previous_status": {"completed": "second"}}
        assert len(closed) == 1
        assert manager.tree[agent_id].status == "shutdown"
        assert (await manager.resume_agent({"id": agent_id}))[
            "status"
        ] == "pending_init"
        await manager.send_input({"target": agent_id, "message": "third"})
        await manager.wait_agent({"targets": [agent_id]})
        await manager.close()
        await router.close()
        assert len(closed) == 2
        assert any(
            event.get("agent_id") == agent_id and event["type"] == "request"
            for event in events
        )

    run(scenario())


def test_fork_history_role_overrides_and_depth(tmp_path):
    async def scenario():
        observed = []

        async def session(request, emit):
            observed.append(request)
            return {
                "status": "finished",
                "output": "done",
                "history": request.get("initial_history", []),
            }

        role = tmp_path / "researcher.toml"
        role.write_text(
            'model = "gpt-5.2"\nmodel_reasoning_effort = "high"\ndeveloper_instructions = "role instructions"\n'
        )
        manager, router, request, _ = setup(
            tmp_path,
            session,
            {
                "agents": {
                    "researcher": {
                        "description": "Research",
                        "config_file": str(role),
                        "nickname_candidates": ["Ada"],
                    }
                }
            },
        )
        inherited = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "parent"}],
            }
        ]
        request["_history_provider"] = lambda: inherited
        with pytest.raises(ToolError, match="Full-history forked agents"):
            await manager.spawn_agent(
                {"message": "fork", "fork_context": True, "agent_type": "researcher"}
            )
        fork = await manager.spawn_agent({"message": "fork", "fork_context": True})
        await manager.wait_agent({"targets": [fork["agent_id"]]})
        role_child = await manager.spawn_agent(
            {"message": "role", "agent_type": "researcher"}
        )
        await manager.wait_agent({"targets": [role_child["agent_id"]]})
        assert role_child["nickname"] == "Ada"
        assert observed[0]["initial_history"] == inherited
        inherited[0]["content"][0]["text"] = "mutated parent"
        assert observed[0]["initial_history"][0]["content"][0]["text"] == "parent"
        assert observed[1]["llm"]["model_name"] == "gpt-5.2"
        assert observed[1]["llm"]["reasoning_effort"] == "high"
        assert observed[1]["settings"]["developer_instructions"] == "role instructions"
        child_request = observed[1]
        child_router = ToolRouter(
            child_request["settings"],
            tmp_path,
            Model("gpt-5.2", child_request["settings"]),
            lambda event: None,
        )
        child_manager = Subagents(
            child_router, child_request, lambda event: None, session
        )
        assert not any(
            spec.get("name") == "multi_agent_v1" for spec in child_router.specs
        )
        with pytest.raises(ToolError, match="Agent depth limit reached"):
            await child_manager.spawn_agent({"message": "too deep"})
        await child_router.close()
        await manager.close()
        await router.close()

    run(scenario())


def test_concurrency_counts_completed_until_closed_and_unknown_targets(tmp_path):
    async def scenario():
        async def session(request, emit):
            return {"status": "completed", "output": "done", "history": []}

        manager, router, _, _ = setup(
            tmp_path, session, {"agents": {"max_concurrent_threads_per_session": 1}}
        )
        child = await manager.spawn_agent({"message": "one"})
        await manager.wait_agent({"targets": [child["agent_id"]]})
        with pytest.raises(ToolError, match="agent thread limit reached"):
            await manager.spawn_agent({"message": "two"})
        await manager.close_agent({"target": child["agent_id"]})
        second = await manager.spawn_agent({"message": "two"})
        missing = str(uuid.uuid4())
        assert await manager.wait_agent({"targets": [missing]}) == {
            "status": {missing: "not_found"},
            "timed_out": False,
        }
        with pytest.raises(ToolError, match="invalid agent id"):
            await manager.send_input({"target": "bad", "message": "x"})
        with pytest.raises(ToolError, match="timeout_ms must be greater"):
            await manager.wait_agent({"targets": [second["agent_id"]], "timeout_ms": 0})
        await manager.close()
        await router.close()

    run(scenario())


@pytest.mark.parametrize("maximum", [0, -1, 1.5, True])
def test_invalid_native_thread_limit_is_rejected_before_execution(tmp_path, maximum):
    async def session(request, emit):
        pytest.fail("invalid thread configuration must not start an agent")

    with pytest.raises(ValueError, match="agents.max_concurrent_threads_per_session"):
        setup(
            tmp_path,
            session,
            {"agents": {"max_concurrent_threads_per_session": maximum}},
        )


@pytest.mark.parametrize("agents", [{}, {"max_concurrent_threads_per_session": None}])
def test_default_six_threads_and_resume_capacity_follow_native_config(tmp_path, agents):
    async def scenario():
        async def session(request, emit):
            return {"status": "finished", "output": "done", "history": []}

        manager, router, _, _ = setup(tmp_path, session, {"agents": agents})
        children = []
        for index in range(6):
            child = await manager.spawn_agent({"message": str(index)})
            await manager.wait_agent({"targets": [child["agent_id"]]})
            children.append(child["agent_id"])
        with pytest.raises(ToolError, match="agent thread limit reached"):
            await manager.spawn_agent({"message": "seventh"})
        await manager.close_agent({"target": children[0]})
        await manager.spawn_agent({"message": "replacement"})
        with pytest.raises(ToolError, match="agent thread limit reached"):
            await manager.resume_agent({"id": children[0]})
        await manager.close()
        await router.close()

    run(scenario())


def test_send_input_queue_and_interrupt_preserve_partial_history(tmp_path):
    async def scenario():
        entered = asyncio.Event()
        requests = []

        async def session(request, emit):
            requests.append(request)
            request["_history_sink"](
                [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "partial"}],
                    }
                ]
            )
            request["_session_cache"]["alive"] = True
            entered.set()
            if request["prompt"] == "first":
                await asyncio.Event().wait()
            return {
                "status": "finished",
                "output": request["prompt"],
                "history": request.get("initial_history", []),
            }

        async def close_session(cache):
            cache.clear()

        manager, router, request, _ = setup(tmp_path, session)
        request["_close_session"] = close_session
        child = await manager.spawn_agent({"message": "first"})
        await entered.wait()
        await manager.send_input({"target": child["agent_id"], "message": "queued"})
        assert manager.tree[child["agent_id"]].queue.qsize() == 1
        await manager.send_input(
            {"target": child["agent_id"], "message": "redirected", "interrupt": True}
        )
        result = await manager.wait_agent({"targets": [child["agent_id"]]})
        assert requests[1]["initial_history"][0]["content"][0]["text"] == "partial"
        assert requests[0]["_session_cache"] is requests[1]["_session_cache"]
        assert result["status"][child["agent_id"]] == {"completed": "queued"}
        await manager.close()
        await router.close()

    run(scenario())


def test_structured_input_validation(tmp_path):
    async def session(request, emit):
        return {"status": "completed", "history": []}

    async def scenario():
        manager, router, _, _ = setup(tmp_path, session)
        for arguments, expected in [
            ({}, "Provide one of"),
            ({"message": "", "items": []}, "but not both"),
            ({"message": " "}, "Empty message"),
            ({"items": []}, "Items can't"),
            ({"items": [{"type": "audio", "audio_url": "data:"}]}, "capability"),
        ]:
            with pytest.raises(ToolError, match=expected):
                await manager.spawn_agent(arguments)
        with pytest.raises(ToolError, match="Unknown model"):
            await manager.spawn_agent({"message": "x", "model": "not-in-catalog"})
        await manager.close()
        await router.close()

    run(scenario())


def test_custom_roles_reject_unported_provider_and_relative_path_reload(tmp_path):
    async def scenario():
        observed = []

        async def session(request, emit):
            observed.append(request)
            return {"status": "finished", "history": []}

        for index, body in enumerate(
            [
                'model_provider = "other"\n',
                '[mcp_servers.probe]\ncommand = "python"\ncwd = "relative"\n',
                '[sandbox_workspace_write]\nwritable_roots = ["relative"]\n',
            ]
        ):
            path = tmp_path / f"role-{index}.toml"
            path.write_text(body)
            manager, router, _, _ = setup(
                tmp_path, session, {"agents": {"custom": {"config_file": str(path)}}}
            )
            with pytest.raises(ToolError, match="do not support"):
                await manager.spawn_agent({"message": "work", "agent_type": "custom"})
            assert not manager.tree
            await manager.close()
            await router.close()
        assert not observed

    run(scenario())


def test_real_python_child_loop_uses_localhost_and_continues_history(tmp_path):
    from flashrsi.agents.codex.python_core.loop import run_session

    shutil.copytree(
        Path(__file__).parents[1] / "flashrsi/agents/codex/python_core/resource_assets",
        tmp_path / "python_core/resource_assets",
    )

    with _responses_server() as replay:
        replay.reset(
            [
                (200, _events(text="CHILD_ONE", response_id="child_one")),
                (200, _events(text="CHILD_TWO", response_id="child_two")),
            ]
        )

        async def scenario():
            manager, router, request, _ = setup(
                tmp_path,
                run_session,
                {"features": {"plugins": False, "unified_exec": False}},
            )
            request["llm"].update(api_key="local-test-key", base_url=replay.base_url)
            child = await manager.spawn_agent({"message": "child first turn"})
            first = await manager.wait_agent({"targets": [child["agent_id"]]})
            assert first["status"][child["agent_id"]] == {"completed": "CHILD_ONE"}
            await manager.send_input(
                {"target": child["agent_id"], "message": "child followup"}
            )
            second = await manager.wait_agent({"targets": [child["agent_id"]]})
            assert second["status"][child["agent_id"]] == {"completed": "CHILD_TWO"}
            await manager.close()
            await router.close()

        run(scenario())
        assert len(replay.requests) == 2
        first, second = (request["body"] for request in replay.requests)
        assert "child first turn" in json.dumps(first["input"])
        assert "CHILD_ONE" in json.dumps(second["input"])
        assert "child followup" in json.dumps(second["input"])
        assert not any(spec.get("name") == "multi_agent_v1" for spec in first["tools"])
        assert not replay.errors and not replay.steps


def test_cleanup_closes_siblings_concurrently_and_keeps_errors(tmp_path):
    async def scenario():
        async def session(request, emit):
            request["_session_cache"]["resource"] = request["prompt"]
            return {"status": "finished", "output": "ready", "history": []}

        manager, router, request, _ = setup(tmp_path, session)
        entered = []
        all_entered = asyncio.Event()

        async def close_session(cache):
            entered.append(cache["resource"])
            if len(entered) == 3:
                all_entered.set()
            await all_entered.wait()
            if cache["resource"] == "bad":
                raise RuntimeError("cleanup fixture failure")
            cache.clear()

        request["_close_session"] = close_session
        for label in ["one", "bad", "three"]:
            child = await manager.spawn_agent({"message": label})
            await manager.wait_agent({"targets": [child["agent_id"]]})
        with pytest.raises(ExceptionGroup, match="sub-agent cleanup failed"):
            await asyncio.wait_for(manager.close(), 1)
        assert sorted(entered) == ["bad", "one", "three"]
        assert all(
            agent.closed and agent.status == "shutdown"
            for agent in manager.tree.values()
        )
        await router.close()

    run(scenario())
