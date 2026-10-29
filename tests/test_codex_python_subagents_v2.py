"""V2 source-contract and offline native/Python lifecycle verification."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_python_resources import _hook_command, _resource, _text
from test_codex_python_resources import home as home
from test_codex_python_subagents import setup

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core.shell import ToolError
from flashrsi.agents.codex.python_core.subagents_v2 import (
    collaboration_spec_v2,
    resolve_path,
)


def v2_setup(tmp_path, session, **overrides):
    return setup(
        tmp_path,
        session,
        {
            "features": {
                "multi_agent_v2": {
                    "enabled": True,
                    "min_wait_timeout_ms": 0,
                    "default_wait_timeout_ms": 100,
                    **overrides,
                }
            }
        },
    )


def test_task_paths_match_pinned_validation():
    assert resolve_path("/root/one", "two/three") == "/root/one/two/three"
    assert resolve_path("/root/one", "/root/two") == "/root/two"
    assert resolve_path("/root", "/morpheus") == "/morpheus"
    for value, reason in [
        ("", "must not be empty"),
        ("../a", "reserved"),
        ("UPPER", "only lowercase"),
        ("/rooted/a", "must start"),
        ("a/", "must not end"),
        ("root", "reserved"),
    ]:
        with pytest.raises(ToolError, match=reason):
            resolve_path("/root", value)


def test_mailbox_queue_only_followup_history_and_plaintext_source(tmp_path):
    async def scenario():
        requests = []

        async def session(request, emit):
            requests.append(
                copy.deepcopy(
                    {key: request[key] for key in ("prompt", "_initial_input_items")}
                )
            )
            history = (
                request.get("initial_history", []) + request["_initial_input_items"]
            )
            request["_session_cache"].setdefault("marker", object())
            request["_history_sink"](history)
            return {
                "status": "finished",
                "history": history,
                "output": str(len(requests)),
            }

        manager, router, request, _ = v2_setup(tmp_path, session)
        child = await manager.spawn_agent(
            {"task_name": "worker", "message": "first", "fork_turns": "none"}
        )
        agent = manager._target(child["task_name"])
        await agent.task
        assert len(requests) == 1
        assert requests[0]["_initial_input_items"][0]["content"][-1] == {
            "type": "encrypted_content",
            "encrypted_content": "first",
        }
        assert (await manager.wait_agent({}))["message"] == "Wait completed."
        notice = request["_input_queue"].get_nowait()[0]
        assert (
            notice["content"][0]["text"]
            == "Message Type: FINAL_ANSWER\nTask name: /root\nSender: /root/worker\nPayload:\n1"
        )
        manager.input_drained()
        assert (await manager.wait_agent({"timeout_ms": 0}))["timed_out"]
        cache = agent.request["_session_cache"]
        assert (
            await manager.send_message({"target": "worker", "message": "queued"}) == ""
        )
        await asyncio.sleep(0)
        assert len(requests) == 1
        assert (
            await manager.followup_task(
                {"target": agent.id, "message": "next"},
                call={"namespace": "collaboration", "encrypted_function_args": []},
            )
            == ""
        )
        await agent.task
        assert agent.request["_session_cache"] is cache
        assert len(requests) == 2
        delivered = requests[1]["_initial_input_items"]
        assert len(delivered) == 2
        assert delivered[0]["content"][-1]["encrypted_content"] == "queued"
        assert delivered[1]["content"] == [
            {
                "type": "input_text",
                "text": "Message Type: NEW_TASK\nTask name: /root/worker\nSender: /root\nPayload:\nnext",
            }
        ]
        assert len(agent.history) == 3
        with pytest.raises(ToolError, match="can't target the root"):
            await manager.followup_task({"target": "/root", "message": "no"})
        await manager.close()
        await router.close()

    asyncio.run(scenario())


def test_interrupt_keeps_partial_history_and_followup_while_busy(tmp_path):
    async def scenario():
        entered = asyncio.Event()
        requests = []

        async def session(request, emit):
            requests.append(request)
            history = (
                request.get("initial_history", []) + request["_initial_input_items"]
            )
            request["_history_sink"](history)
            entered.set()
            if len(requests) == 1:
                await asyncio.Event().wait()
            return {"status": "finished", "history": history, "output": "done"}

        manager, router, request, _ = v2_setup(tmp_path, session)
        await manager.spawn_agent(
            {"task_name": "worker", "message": "start", "fork_turns": "none"}
        )
        agent = manager._target("worker")
        await entered.wait()
        interrupted = await manager.interrupt_agent({"target": "worker"})
        assert interrupted == {"previous_status": "running"}
        assert agent.status == "interrupted"
        assert request["_input_queue"].empty()
        await manager.followup_task({"target": "worker", "message": "resume"})
        await agent.task
        assert requests[1]["initial_history"] == requests[0]["_initial_input_items"]
        assert agent.status == {"completed": "done"}
        await manager.close()
        await router.close()

    asyncio.run(scenario())


def test_residency_unloads_idle_threads_and_reloads_path_and_history(tmp_path):
    async def scenario():
        async def session(request, emit):
            return {
                "status": "finished",
                "history": request.get("initial_history", [])
                + request["_initial_input_items"],
                "output": request["prompt"],
            }

        manager, router, _, _ = v2_setup(
            tmp_path, session, max_concurrent_threads_per_session=2
        )
        await manager.spawn_agent(
            {"task_name": "first", "message": "one", "fork_turns": "none"}
        )
        first = manager._target("first")
        await first.task
        saved = copy.deepcopy(first.history)
        await manager.spawn_agent(
            {"task_name": "second", "message": "two", "fork_turns": "none"}
        )
        second = manager._target("second")
        await second.task
        assert not first.loaded
        assert [
            entry["agent_name"] for entry in (await manager.list_agents({}))["agents"]
        ] == ["/root", "/root/second"]
        await manager.followup_task({"target": "first", "message": "again"})
        await first.task
        assert first.history[: len(saved)] == saved
        assert first.loaded and not second.loaded
        with pytest.raises(ToolError, match="already exists"):
            await manager.spawn_agent({"task_name": "first", "message": "duplicate"})
        await manager.close()
        await router.close()

    asyncio.run(scenario())


def test_v2_fork_filters_messages_and_supports_last_turns(tmp_path):
    async def scenario():
        async def session(request, emit):
            return {
                "status": "finished",
                "history": request.get("initial_history", []),
                "output": "done",
            }

        manager, router, request, _ = v2_setup(tmp_path, session)

        def user(text):
            return {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }

        request["_history_provider"] = lambda: [
            user("one"),
            {
                "type": "agent_message",
                "author": "/root/x",
                "recipient": "/root",
                "content": [],
            },
            user("two"),
        ]
        await manager.spawn_agent(
            {"task_name": "fork", "message": "task", "fork_turns": "1"}
        )
        agent = manager._target("fork")
        await agent.task
        assert agent.history == [user("two")]
        assert agent.request["settings"]["_forked_from_thread_id"] == "root"
        for arguments, error in [
            ({"fork_context": False}, "not supported"),
            ({"fork_turns": "0"}, "positive integer"),
            ({"fork_turns": "all", "agent_type": "default"}, "Full-history"),
        ]:
            with pytest.raises(ToolError, match=error):
                await manager.spawn_agent(
                    {"task_name": "bad", "message": "task", **arguments}
                )
        await manager.close()
        await router.close()

    asyncio.run(scenario())


def test_v2_schema_matches_installed_native(parity_source, upstream_codex, tmp_path):
    (parity_source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\nunified_exec=false\nmulti_agent_v2=true\n"
    )
    task = tmp_path / "task"
    task.mkdir()
    with _responses_server() as replay:
        replay.reset([(200, _events())])
        result = asyncio.run(
            Codex(
                {
                    "source_dir": parity_source,
                    "cli_path": upstream_codex,
                    "llm": {
                        "model_name": "gpt-5",
                        "api_key": "local-key",
                        "base_url": replay.base_url,
                    },
                    "timeout": 30,
                    "sandbox": "danger-full-access",
                }
            ).run("native schema", working_dir=task)
        )
        assert result.status == "finished", result.error_message
        assert not replay.errors
        native = next(
            tool
            for tool in replay.requests[0]["body"]["tools"]
            if tool.get("name") == "collaboration"
        )
        catalog = json.loads(
            (
                Path(__file__).parents[1]
                / "flashrsi/agents/codex/python_core/assets/models.json"
            ).read_text()
        )["models"]
        python = {
            "type": "namespace",
            "name": "collaboration",
            "description": "Tools for spawning and managing sub-agents.",
            "tools": collaboration_spec_v2(catalog, {}, {}, {}),
        }
        assert python == native


class _TaskSteps:
    """Route concurrent localhost requests by the actual agent input, not timing."""

    def __init__(
        self,
        replay,
        namespace="collaboration",
        encrypted_function_args=None,
        fork_mode="none",
    ):
        self.replay = replay
        self.child_requests = 0
        self.root_requests = 0
        self.stages = []
        self.namespace = namespace
        self.encrypted_function_args = encrypted_function_args
        self.fork_mode = fork_mode

    def namespaced(self, content, name):
        fields = {"name": name, "namespace": self.namespace}
        if self.encrypted_function_args is not None:
            fields["encrypted_function_args"] = self.encrypted_function_args
        return content.replace(
            json.dumps({"name": name})[1:-1].encode(), json.dumps(fields)[1:-1].encode()
        )

    def __bool__(self):
        return True

    def pop(self, index):
        body = self.replay.requests[-1]["body"]
        items = body["input"]
        child = any(
            item.get("type") == "agent_message"
            and item.get("recipient") == "/root/worker"
            for item in items
        )
        if child:
            self.child_requests += 1
            if self.child_requests == 1:
                self.stages.append("child-write")
                call = (
                    "shell_command",
                    {"command": "printf 'CHILD_PROOF\\n' > child-proof.txt"},
                )
                return 200, _events(call=call, response_id="child_write")
            assert self.child_requests == 2
            self.stages.append("child-finish")
            return 200, _events("CHILD_DONE", response_id="child_done")
        self.root_requests += 1
        if self.root_requests == 1:
            self.stages.append("spawn")
            content = _events(
                call=(
                    "spawn_agent",
                    {
                        "task_name": "worker",
                        "message": "Create the proof file then report completion.",
                        "fork_turns": self.fork_mode,
                    },
                ),
                response_id="spawn",
            )
            return 200, self.namespaced(content, "spawn_agent")
        verified = any(
            item.get("type") == "function_call" and item.get("call_id") == "call_verify"
            for item in items
        )
        if verified:
            self.stages.append("root-finish")
            return 200, _events("PARENT_VERIFIED_CHILD", response_id="root_done")
        complete = any(
            item.get("type") == "agent_message"
            and item.get("author") == "/root/worker"
            and "CHILD_DONE" in json.dumps(item)
            for item in items
        )
        if complete:
            self.stages.append("root-verify")
            return 200, _events(
                call=(
                    "shell_command",
                    {
                        "command": "test \"$(cat child-proof.txt)\" = CHILD_PROOF && printf 'VERIFIED\\n'"
                    },
                ),
                response_id="verify",
            )
        self.stages.append("wait")
        assert self.root_requests < 10, "child result was never delivered"
        content = _events(
            call=("wait_agent", {"timeout_ms": 1000}),
            response_id=f"wait_{self.root_requests}",
        )
        return 200, self.namespaced(content, "wait_agent")


@pytest.mark.parametrize(
    "namespace,encrypted_function_args,fork_mode",
    [
        ("collaboration", None, "none"),
        ("collaboration", [], "none"),
        ("collaboration", ["message"], "none"),
        ("team", [], "none"),
        ("collaboration", None, "all"),
        ("collaboration", None, "1"),
    ],
)
def test_v2_real_sessions_complete_task_like_installed_native(
    namespace,
    encrypted_function_args,
    fork_mode,
    parity_source,
    upstream_codex,
    tmp_path,
):
    (parity_source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\nunified_exec=false\ngoals=false\n"
        "[features.multi_agent_v2]\nenabled=true\nmin_wait_timeout_ms=0\n"
        + f'tool_namespace="{namespace}"\n'
    )
    task = tmp_path / "task"
    task.mkdir()
    observations = []
    if fork_mode != "none":
        # The framework's CLI adapter requests --ephemeral, which removes the
        # thread store required by native forks. Keep this oracle's isolated
        # temporary rollouts so we exercise the upstream fork implementation.
        wrapper = tmp_path / "native-with-rollouts"
        wrapper.write_text(
            f"#!{sys.executable}\nimport os,sys\nbinary={upstream_codex!r}\nos.execv(binary,[binary,*[arg for arg in sys.argv[1:] if arg!='--ephemeral']])\n"
        )
        wrapper.chmod(0o755)
        upstream_codex = str(wrapper)
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            proof = task / "child-proof.txt"
            proof.unlink(missing_ok=True)
            replay.reset([])
            steps = _TaskSteps(replay, namespace, encrypted_function_args, fork_mode)
            replay.steps = steps
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "local-key",
                    "base_url": replay.base_url,
                },
                "timeout": 30,
                "sandbox": "danger-full-access",
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Delegate proof creation and independently verify the result.",
                    working_dir=task,
                )
            )
            assert result.status == "finished", result.error_message
            assert result.output == "PARENT_VERIFIED_CHILD"
            assert not replay.errors, replay.errors
            assert steps.child_requests == 2
            assert proof.read_text() == "CHILD_PROOF\n"
            initial_child = next(
                request["body"]
                for request in replay.requests
                if any(
                    item.get("type") == "agent_message"
                    and item.get("recipient") == "/root/worker"
                    for item in request["body"]["input"]
                )
            )
            communication_item = next(
                item
                for item in initial_child["input"]
                if item.get("type") == "agent_message"
            )
            notice = next(
                item
                for request in replay.requests
                for item in request["body"]["input"]
                if item.get("type") == "agent_message"
                and item.get("author") == "/root/worker"
            )
            observations.append(
                _normalize(
                    {
                        "task_result": result.output,
                        "proof": proof.read_text(),
                        "child_input": {
                            key: communication_item[key]
                            for key in ("type", "author", "recipient", "content")
                        },
                        "completion": {
                            key: notice[key]
                            for key in ("type", "author", "recipient", "content")
                        },
                        "child_requests": steps.child_requests,
                        "initial_requests": [replay.requests[0]["body"], initial_child],
                        "stages": sorted(
                            stage for stage in steps.stages if stage != "wait"
                        ),
                    },
                    tmp_path,
                )
            )
            (tmp_path / ("v2-native.json" if binary else "v2-python.json")).write_text(
                json.dumps(replay.requests, indent=2)
            )
    assert observations[0] == observations[1]


def test_subagent_lifecycle_hooks_use_child_identity_and_parent_transcript(
    home, tmp_path
):
    log = tmp_path / "lifecycle.jsonl"
    command = _hook_command(
        home,
        "import json,sys\npayload=json.load(sys.stdin)\n"
        + f"with open({str(log)!r},'a') as file: file.write(json.dumps(payload)+'\\n')\n"
        + "if payload['hook_event_name']=='SubagentStart': print('SUBAGENT_START_CONTEXT')\nelif payload['hook_event_name']=='SubagentStop': print(json.dumps({} if payload['stop_hook_active'] else {'decision':'block','reason':'Verify child state.'}))\n",
    )
    hooks = {
        event: [
            {"matcher": "default", "hooks": [{"type": "command", "command": command}]}
        ]
        for event in ("SessionStart", "SubagentStart", "SubagentStop", "SessionEnd")
    }
    settings = {
        "_thread_id": "child-thread",
        "_session_id": "child-thread",
        "_turn_id": "child-turn",
        "_subagent_kind": "thread_spawn",
        "_agent_type": "default",
        "_transcript_path": "/child.jsonl",
        "_parent_transcript_path": "/parent.jsonl",
        "hooks": hooks,
    }
    resource, router, _ = _resource(home, tmp_path, settings)

    async def scenario():
        context = await resource.start(router)
        assert "SUBAGENT_START_CONTEXT" in _text(context)
        continuation = await resource.after_turn("first answer", "finished")
        assert "Verify child state." in _text(continuation)
        assert await resource.after_turn("verified answer", "finished") == []
        await resource.close()

    asyncio.run(scenario())
    payloads = [json.loads(line) for line in log.read_text().splitlines()]
    assert [payload["hook_event_name"] for payload in payloads] == [
        "SubagentStart",
        "SubagentStop",
        "SubagentStop",
    ]
    assert all(
        payload["agent_id"] == "child-thread" and payload["agent_type"] == "default"
        for payload in payloads
    )
    assert payloads[0]["transcript_path"] == "/child.jsonl"
    assert payloads[1]["transcript_path"] == "/parent.jsonl"
    assert payloads[1]["agent_transcript_path"] == "/child.jsonl"
    assert not payloads[1]["stop_hook_active"] and payloads[2]["stop_hook_active"]


def test_followup_queued_at_completion_starts_next_turn_without_interrupt(tmp_path):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def session(request, emit):
            calls.append(request)
            if len(calls) == 1:
                entered.set()
                await release.wait()
            return {
                "status": "finished",
                "output": "done",
                "history": request.get("initial_history", [])
                + request["_initial_input_items"],
            }

        manager, router, _, _ = v2_setup(tmp_path, session)
        await manager.spawn_agent(
            {"task_name": "worker", "message": "first", "fork_turns": "none"}
        )
        agent = manager._target("worker")
        await entered.wait()
        first_task = agent.task
        await manager.followup_task({"target": "worker", "message": "second"})
        assert agent.task is first_task and not first_task.cancelled()
        release.set()
        await first_task
        await agent.task
        assert len(calls) == 2
        assert "second" in json.dumps(calls[1]["_initial_input_items"])
        assert calls[1]["initial_history"] == calls[0]["_initial_input_items"]
        await manager.close()
        await router.close()

    asyncio.run(scenario())


class _LifecycleSteps(_TaskSteps):
    def __init__(self, replay, task):
        super().__init__(replay)
        self.task = task
        self.state = "spawn"
        self.worker_inputs = []
        self.list_observations = []

    def tool(self, name, arguments, tag):
        payload = _events(call=(name, arguments), response_id=tag)
        return 200, self.namespaced(payload, name)

    def pop(self, index):
        import shlex
        import sys
        import time

        body = self.replay.requests[-1]["body"]
        items = body["input"]
        child = any(
            item.get("type") == "agent_message"
            and item.get("recipient") == "/root/worker"
            for item in items
        )
        if child:
            self.child_requests += 1
            self.worker_inputs.append(copy.deepcopy(items))
            if self.child_requests == 1:
                code = "import pathlib,threading; pathlib.Path('child-started').write_text('running'); threading.Event().wait()"
                return 200, _events(
                    call=(
                        "shell_command",
                        {
                            "command": shlex.quote(sys.executable)
                            + " -c "
                            + shlex.quote(code),
                            "timeout_ms": 20000,
                        },
                    ),
                    response_id="block",
                )
            if self.child_requests == 2:
                latest = [item for item in items if item.get("type") == "agent_message"]
                assert (
                    latest[-2]["content"][-1]["encrypted_content"]
                    == "queued while interrupted"
                )
                assert latest[-1]["content"][-1]["encrypted_content"] == "resume now"
                return 200, _events(
                    call=(
                        "shell_command",
                        {"command": "printf 'RESUMED_PROOF\\n' > child-proof.txt"},
                    ),
                    response_id="resumed_write",
                )
            assert self.child_requests == 3
            return 200, _events("RESUMED_DONE", response_id="resumed_final")
        self.root_requests += 1
        assert self.root_requests <= 25, (self.state, items[-1])
        if self.state == "spawn":
            self.state = "started"
            return self.tool(
                "spawn_agent",
                {
                    "task_name": "worker",
                    "message": "Wait for new instructions.",
                    "fork_turns": "none",
                },
                "spawn",
            )
        if self.state == "started":
            self.state = "interrupt"
            return self.tool("list_agents", {}, "list_running")
        if self.state == "interrupt":
            deadline = time.monotonic() + 5
            while not (self.task / "child-started").exists():
                assert time.monotonic() < deadline, (
                    "child shell never entered its blocking task"
                )
                time.sleep(0.005)
            self.state = "interrupted"
            return self.tool("interrupt_agent", {"target": "worker"}, "interrupt")
        if self.state == "interrupted":
            self.state = "send"
            return self.tool("list_agents", {}, "list_interrupted")
        if self.state in {"send", "confirm_queue"}:
            output = next(
                item["output"]
                for item in reversed(items)
                if item.get("type") == "function_call_output"
            )
            listing = json.loads(output)
            status = next(
                entry["agent_status"]
                for entry in listing["agents"]
                if entry["agent_name"] == "/root/worker"
            )
            self.list_observations.append(status)
            if status != "interrupted":
                return self.tool("list_agents", {}, f"list_retry_{self.root_requests}")
            if self.state == "send":
                self.state = "list_queue"
                return self.tool(
                    "send_message",
                    {"target": "worker", "message": "queued while interrupted"},
                    "send",
                )
            self.state = "wait"
            return self.tool(
                "followup_task",
                {"target": "/root/worker", "message": "resume now"},
                "followup",
            )
        if self.state == "list_queue":
            self.state = "confirm_queue"
            return self.tool("list_agents", {}, "list_queue")
        if self.state == "wait":
            if any(
                item.get("type") == "agent_message"
                and "RESUMED_DONE" in json.dumps(item)
                for item in items
            ):
                self.state = "done"
                return 200, _events(
                    call=(
                        "shell_command",
                        {
                            "command": "test \"$(cat child-proof.txt)\" = RESUMED_PROOF && printf 'VERIFIED\\n'"
                        },
                    ),
                    response_id="verify_resumed",
                )
            return self.tool(
                "wait_agent", {"timeout_ms": 1000}, f"wait_{self.root_requests}"
            )
        assert self.state == "done"
        return 200, _events(
            "INTERRUPTED_QUEUED_RESUMED_VERIFIED", response_id="parent_done"
        )


def test_v2_real_native_interrupt_queue_followup_and_listing(
    parity_source, upstream_codex, tmp_path
):
    (parity_source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\nunified_exec=false\n[features.multi_agent_v2]\nenabled=true\nmin_wait_timeout_ms=0\n"
    )
    task = tmp_path / "task"
    task.mkdir()
    observations = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            for name in ("child-started", "child-proof.txt"):
                (task / name).unlink(missing_ok=True)
            replay.reset([])
            steps = _LifecycleSteps(replay, task)
            replay.steps = steps
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "local-key",
                    "base_url": replay.base_url,
                },
                "timeout": 30,
                "sandbox": "danger-full-access",
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Delegate, interrupt, queue a note, resume, and verify the child result.",
                    working_dir=task,
                )
            )
            assert result.status == "finished", result.error_message
            assert result.output == "INTERRUPTED_QUEUED_RESUMED_VERIFIED"
            assert not replay.errors, replay.errors
            assert steps.child_requests == 3
            assert steps.list_observations[-2:] == ["interrupted", "interrupted"]
            assert (task / "child-proof.txt").read_text() == "RESUMED_PROOF\n"
            observations.append(
                {
                    "output": result.output,
                    "proof": (task / "child-proof.txt").read_text(),
                    "messages": [
                        {
                            key: item[key]
                            for key in ("type", "author", "recipient", "content")
                        }
                        for item in steps.worker_inputs[1]
                        if item.get("type") == "agent_message"
                    ],
                    "statuses": steps.list_observations[-2:],
                }
            )
            (
                tmp_path
                / ("v2-lifecycle-native.json" if binary else "v2-lifecycle-python.json")
            ).write_text(json.dumps(replay.requests, indent=2))
    assert observations[0] == observations[1]
