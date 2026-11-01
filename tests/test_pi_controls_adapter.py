"""Exercise call-local Pi controls through selected Snapshots and worker tools."""

import asyncio
import copy
import json
import threading

import httpx
import pytest

from flashrsi.agents.pi_agent import Pi
from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.controls import (
    EventLog,
    PendingMessageQueue,
)
from flashrsi.agents.pi_agent.runtime.pi_native.tools import ToolResult


def _config():
    return {
        "timeout": 10,
        "llm": {
            "model_name": "openai/gpt-5",
            "model_api": "openai-completions",
            "api_key": "sk-config-fixture",
            "base_url": "https://offline.invalid/v1",
            "max_retries": 0,
        },
        "tools": [],
        "compaction": False,
        "retry": {"enabled": False},
    }


def _completion(text):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


def _transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        loop.httpx,
        "AsyncClient",
        lambda *args, **kwargs: client(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        ),
    )


def _select_instrumented_snapshot(agent):
    """Execute an evolved Snapshot and audit its real serializable config."""
    seed = agent.snapshot
    with seed.check_out() as files:
        with (files / "runtime/pi_native/__init__.py").open("a") as stream:
            stream.write(
                "\n_seed_controls_run = run\n"
                "async def run(config, prompt, working_dir, files_dir, **controls):\n"
                "    import json\n"
                "    from pathlib import Path\n"
                "    forbidden = {'on_event', 'steering_queue', 'follow_up_queue', "
                "'hooks', 'cancel_event'}\n"
                "    assert not forbidden.intersection(config)\n"
                "    Path(working_dir, 'selected-native-config.json').write_text(\n"
                "        json.dumps(config), encoding='utf-8')\n"
                "    result = await _seed_controls_run(\n"
                "        config, prompt, working_dir, files_dir, **controls)\n"
                "    result.output = 'SELECTED_SNAPSHOT:' + result.output\n"
                "    return result\n"
            )
        selected = seed.commit(files)
    agent.update(selected)
    return selected


def _user_texts(body):
    values = []
    for message in body["messages"]:
        if message["role"] != "user":
            continue
        content = message["content"]
        values.append(
            content
            if isinstance(content, str)
            else "".join(block.get("text", "") for block in content)
        )
    return values


def test_selected_snapshot_receives_live_controls_without_serializing_them(
    tmp_path, monkeypatch
):
    requests, observed, hook_calls = [], [], []

    def handler(request):
        requests.append((json.loads(request.content), request.headers))
        return _completion("answer " + str(len(requests)))

    _transport(monkeypatch, handler)
    agent = Pi(_config())
    selected = _select_instrumented_snapshot(agent)
    snapshot_before = tmp_path / "before.json"
    selected.save(snapshot_before)
    config_before = json.dumps(agent.config, default=dict, sort_keys=True)

    async def scenario():
        cancel = asyncio.Event()
        steering, followup = PendingMessageQueue(), PendingMessageQueue()
        steering.enqueue("queued steering")
        followup.enqueue("queued followup")

        async def never_serialize_python_observer(event):
            await asyncio.sleep(0)
            observed.append(copy.deepcopy(event))

        async def prepare_request(request, signal):
            assert signal is cancel
            assert observed[-1]["type"] == "message_end"
            hook_calls.append(
                [
                    message["content"]
                    for message in request["context"]["messages"]
                    if message["role"] == "user"
                ]
            )

        def finish_turn(turn, signal):
            assert signal is cancel
            # The queued followup satisfies this continuation; no third
            # provider request should be added by the explicit decision.
            if len(hook_calls) == 1:
                return {"action": "continue"}

        result = await agent.run_with_controls(
            "controlled prompt",
            tmp_path,
            on_event=never_serialize_python_observer,
            hooks={
                "prepareRequest": prepare_request,
                "finish_turn": finish_turn,
                "getApiKey": lambda provider: "sk-hook-fixture",
            },
            steering_queue=steering,
            follow_up_queue=followup,
            cancel_event=cancel,
        )
        assert not cancel.is_set()
        assert not steering.has_items() and not followup.has_items()
        return result

    result = asyncio.run(scenario())
    assert result.status == "finished", result.error_message
    assert result.output == "SELECTED_SNAPSHOT:answer 2"
    assert result.messages[0]["snapshot_id"] == selected.id
    assert len(requests) == 2
    assert _user_texts(requests[0][0]) == ["controlled prompt", "queued steering"]
    assert _user_texts(requests[1][0]) == [
        "controlled prompt",
        "queued steering",
        "queued followup",
    ]
    assert all(
        headers["authorization"] == "Bearer sk-hook-fixture" for _, headers in requests
    )
    assert hook_calls == [
        ["controlled prompt", "queued steering"],
        ["controlled prompt", "queued steering", "queued followup"],
    ]
    assert observed == [
        dict(event) for event in result.messages if event["type"] != "RunConfig"
    ]
    native_config = json.loads((tmp_path / "selected-native-config.json").read_text())
    assert native_config == json.loads(config_before)
    assert json.dumps(agent.config, default=dict, sort_keys=True) == config_before
    snapshot_after = tmp_path / "after.json"
    agent.snapshot.save(snapshot_after)
    assert snapshot_before.read_bytes() == snapshot_after.read_bytes()


def test_concurrent_plain_run_does_not_inherit_another_invocations_controls(
    tmp_path, monkeypatch
):
    agent = Pi(_config())
    selected = _select_instrumented_snapshot(agent)
    controlled_dir, plain_dir, later_dir = (
        tmp_path / name for name in ("controlled", "plain", "later")
    )
    for directory in (controlled_dir, plain_dir, later_dir):
        directory.mkdir()
    observed, hook_prompts, requests = [], [], []

    async def scenario():
        both_started = asyncio.Event()
        started = set()
        queue = PendingMessageQueue()
        queue.enqueue("control-only steering")
        followup = PendingMessageQueue()
        followup.enqueue("control-only followup")

        async def handler(request):
            body = json.loads(request.content)
            label = _user_texts(body)[0]
            requests.append((label, body, request.headers))
            if label in {"controlled A", "plain B"}:
                started.add(label)
                if len(started) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), 3)
            return _completion(label + " done")

        _transport(monkeypatch, handler)

        async def observer(event):
            await asyncio.sleep(0)
            observed.append(copy.deepcopy(event))

        def prepare_request(request):
            users = [
                message["content"]
                for message in request["context"]["messages"]
                if message["role"] == "user"
            ]
            hook_prompts.append(users)
            return {"model": "openai/gpt-5-mini"}

        controlled, plain = await asyncio.gather(
            agent.run_with_controls(
                "controlled A",
                controlled_dir,
                on_event=observer,
                steering_queue=queue,
                follow_up_queue=followup,
                hooks={
                    "prepare_request": prepare_request,
                    "get_api_key": lambda provider: "sk-controlled-only",
                },
            ),
            agent.run("plain B", plain_dir),
        )
        # A later call in this same task also verifies the ContextVar token
        # was reset when the controlled invocation returned.
        observed_count, hook_count = len(observed), len(hook_prompts)
        later = await agent.run("plain C", later_dir)
        assert len(observed) == observed_count
        assert len(hook_prompts) == hook_count
        return controlled, plain, later

    controlled, plain, later = asyncio.run(scenario())
    for trajectory, label in (
        (controlled, "controlled A"),
        (plain, "plain B"),
        (later, "plain C"),
    ):
        assert trajectory.status == "finished", trajectory.error_message
        assert trajectory.output == "SELECTED_SNAPSHOT:" + label + " done"
        assert trajectory.messages[0]["snapshot_id"] == selected.id
    assert len(requests) == 4
    controlled_requests = [row for row in requests if row[0] == "controlled A"]
    assert len(controlled_requests) == 2
    assert len(hook_prompts) == 2
    assert all(users[0] == "controlled A" for users in hook_prompts)
    assert all(body["model"] == "gpt-5-mini" for _, body, _ in controlled_requests)
    for label, body, headers in requests:
        if label == "controlled A":
            assert headers["authorization"] == "Bearer sk-controlled-only"
            assert "control-only steering" in _user_texts(body)
        else:
            assert body["model"] == "gpt-5"
            assert headers["authorization"] == "Bearer sk-config-fixture"
            assert _user_texts(body) == [label]
    assert observed == [
        dict(event) for event in controlled.messages if event["type"] != "RunConfig"
    ]


def test_selected_snapshot_honors_supplied_cancel_event_during_http(
    tmp_path, monkeypatch
):
    agent = Pi(_config())
    selected = _select_instrumented_snapshot(agent)
    observed = []

    async def scenario():
        entered, cancel, never = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def handler(request):
            entered.set()
            await never.wait()

        _transport(monkeypatch, handler)

        def prepare_request(request, signal):
            assert signal is cancel

        pending = asyncio.create_task(
            agent.run_with_controls(
                "cancel this request",
                tmp_path,
                on_event=lambda event: observed.append(copy.deepcopy(event)),
                cancel_event=cancel,
                hooks={"prepareRequest": prepare_request},
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 3)
            cancel.set()
            return await asyncio.wait_for(pending, 3)
        finally:
            cancel.set()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    result = asyncio.run(scenario())
    assert result.status == "error"
    assert "abort" in result.error_message.lower()
    assert result.messages[0]["snapshot_id"] == selected.id
    assert observed[-1] == {"type": "agent_settled", "aborted": True}
    assert any(
        event["type"] == "message_end"
        and event["message"].get("stopReason") == "aborted"
        for event in observed
    )


def test_selected_snapshot_builtin_bash_forwards_live_updates(tmp_path, monkeypatch):
    requests, observed, after_inputs = [], [], []

    def handler(request):
        requests.append(json.loads(request.content))
        assert len(requests) == 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "run local printf",
                            "tool_calls": [
                                {
                                    "id": "bash-fixture",
                                    "type": "function",
                                    "function": {
                                        "name": "bash",
                                        "arguments": json.dumps(
                                            {"command": "printf 'controls fixture'"}
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    _transport(monkeypatch, handler)
    config = _config()
    config["tools"] = ["bash"]
    agent = Pi(config)
    _select_instrumented_snapshot(agent)

    async def observer(event):
        await asyncio.sleep(0)
        observed.append(copy.deepcopy(event))

    def after_tool_call(context):
        assert observed[-1]["type"] == "tool_execution_update"
        after_inputs.append(copy.deepcopy(context))
        return {"terminate": True}

    result = asyncio.run(
        agent.run_with_controls(
            "run the fixture printf",
            tmp_path,
            on_event=observer,
            hooks={"afterToolCall": after_tool_call},
        )
    )
    assert result.status == "finished", result.error_message
    assert result.output == "SELECTED_SNAPSHOT:run local printf"
    updates = [event for event in observed if event["type"] == "tool_execution_update"]
    assert len(updates) >= 2
    assert updates[0]["partialResult"]["content"] == []
    assert updates[-1]["partialResult"]["content"] == [
        {"type": "text", "text": "controls fixture"}
    ]
    assert after_inputs[0]["result"]["structuredContent"]["exit_code"] == 0
    assert (
        after_inputs[0]["result"]["structuredContent"]["output"] == "controls fixture"
    )
    end_index = next(
        index
        for index, event in enumerate(observed)
        if event["type"] == "tool_execution_end"
    )
    assert all(
        index < end_index
        for index, event in enumerate(observed)
        if event["type"] == "tool_execution_update"
    )


@pytest.mark.parametrize("replace_structured", [False, True])
def test_worker_tool_updates_reach_serial_async_observer_before_final_result(
    replace_structured, tmp_path, monkeypatch
):
    observed, observations, hook_inputs = [], [], []
    main_thread = threading.get_ident()
    state = {"active": 0, "max_active": 0}
    call = {"id": "read-1", "name": "read", "arguments": '{"path":"fixture.txt"}'}
    assistant = {
        "role": "assistant",
        "content": [
            {
                "type": "toolCall",
                "id": call["id"],
                "name": call["name"],
                "arguments": {"path": "fixture.txt"},
            }
        ],
        "stopReason": "toolUse",
    }
    context = {"messages": [assistant], "tools": []}

    def execute_tool(
        name,
        args,
        cwd,
        *,
        on_update,
        cancel_event,
        model,
        auto_resize_images,
    ):
        assert threading.get_ident() != main_thread
        assert name == "read" and args == {"path": "fixture.txt"}
        assert cwd == tmp_path
        assert model == {"id": "fixture-model"}
        assert auto_resize_images is False
        assert not cancel_event.is_set()
        for index in (1, 2):
            on_update(
                ToolResult(
                    f"partial {index}",
                    details={"step": index},
                    structured_content={"partial": index},
                    usage={"fixture": index},
                )
            )
        return ToolResult(
            "original final",
            details={"original": True},
            structured_content={"original": "structured"},
            usage={"fixture": 3},
        )

    monkeypatch.setattr(loop, "execute_tool", execute_tool)

    async def scenario():
        cancel = asyncio.Event()

        async def observer(event):
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            observations.append(("start", event["type"]))
            try:
                await asyncio.sleep(0)
                observed.append(copy.deepcopy(event))
            finally:
                observations.append(("end", event["type"]))
                state["active"] -= 1

        async def after_tool_call(tool, signal):
            assert signal is cancel
            assert [event["type"] for event in observed] == [
                "tool_execution_start",
                "tool_execution_update",
                "tool_execution_update",
            ]
            hook_inputs.append(copy.deepcopy(tool))
            override = {
                "content": [{"type": "text", "text": "overridden final"}],
                "usage": {"fixture": 9},
                "terminate": True,
            }
            if replace_structured:
                override["structuredContent"] = {"replacement": "structured"}
            return override

        events = EventLog(observer)
        results = await loop._execute_tool_batch(
            [call],
            selected=["read"],
            cwd=tmp_path,
            events=events,
            usage={"tool_calls": 0},
            stop_reason="toolUse",
            mode="sequential",
            cancel_event=cancel,
            model={"id": "fixture-model"},
            auto_resize_images=False,
            hooks={"afterToolCall": after_tool_call},
            assistant_message=assistant,
            context=context,
        )
        await events.flush()
        return events, results

    events, results = asyncio.run(scenario())
    assert state == {"active": 0, "max_active": 1}
    assert observed == list(events)
    assert observations == [
        observation
        for event in events
        for observation in (("start", event["type"]), ("end", event["type"]))
    ]
    assert [event["type"] for event in events] == [
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_update",
        "tool_execution_end",
        "message_start",
        "message_end",
    ]
    assert [event["partialResult"]["details"] for event in events[1:3]] == [
        {"step": 1},
        {"step": 2},
    ]
    assert hook_inputs[0]["result"]["structuredContent"] == {"original": "structured"}
    assert hook_inputs[0]["assistantMessage"] == assistant
    assert hook_inputs[0]["context"] == context
    final = events[3]["result"]
    assert final["content"] == [{"type": "text", "text": "overridden final"}]
    assert final["usage"] == results[0]["usage"] == {"fixture": 9}
    if replace_structured:
        assert final["structuredContent"] == {"replacement": "structured"}
    else:
        assert "structuredContent" not in final
    assert "structuredContent" not in results[0]
    assert results[0]["content"] == final["content"]
    assert results.terminate is True
    assert events[-1]["message"] == results[0]
