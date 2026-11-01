"""Replay original Pi loop controls against the native Python HTTP boundary.

The checked-in oracle executes runAgentLoop, original queue code and (for SSE
cases) the actual upstream provider. Replies and tool bodies are deterministic.
This compares scheduling and observable hooks, not live-model task accuracy.
"""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.controls import PendingMessageQueue
from flashrsi.agents.pi_agent.runtime.pi_native.resources import ResourceBundle
from flashrsi.agents.pi_agent.runtime.pi_native.tools import ToolResult, tool_schemas

_ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_loop_controls_upstream.json").read_text()
)


def _user(content):
    return {"role": "user", "content": content, "timestamp": 1}


def _message(message):
    result = {"role": message["role"], "content": message.get("content", [])}
    if message["role"] == "assistant":
        result["stopReason"] = message["stopReason"]
        if "thinkingLevel" in message:
            result["thinkingLevel"] = message["thinkingLevel"]
    if message["role"] == "toolResult":
        for key in ("toolCallId", "toolName", "isError", "details", "usage"):
            if key in message:
                result[key] = message[key]
    return copy.deepcopy(result)


def _messages(messages):
    return [_message(message) for message in messages if message["role"] != "system"]


def _normalize(value):
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _normalize(item)
            for key, item in value.items()
            if key not in {"timestamp", "durationMs"}
        }
    return value


def _event(event, stream):
    if (
        event["type"] in {"agent_settled", "session"}
        or event.get("message", {}).get("role") == "system"
        or (not stream and event["type"] == "message_update")
    ):
        return None
    result = {"type": event["type"]}
    if "message" in event:
        result["message"] = _message(event["message"])
        if (
            not stream
            and event["type"] == "message_start"
            and event["message"]["role"] == "assistant"
        ):
            # These cases isolate scheduling with fixed fake source streams;
            # actual SSE cases compare provider partial metadata separately.
            result["message"].pop("stopReason", None)
            result["message"].pop("thinkingLevel", None)
    if "messages" in event:
        result["messages"] = _messages(event["messages"])
    if "toolResults" in event:
        result["toolResults"] = [_message(message) for message in event["toolResults"]]
    for key in (
        "toolCallId",
        "toolName",
        "args",
        "result",
        "isError",
        "partialResult",
    ):
        if key in event:
            result[key] = _normalize(event[key])
    if stream and "assistantMessageEvent" in event:
        result["assistantMessageEvent"] = _normalize(event["assistantMessageEvent"])
    return result


@pytest.mark.parametrize("case", _ORACLE["queueCases"], ids=lambda case: case["mode"])
def test_pending_queue_matches_extracted_original_class(case):
    queue = PendingMessageQueue(case["mode"])
    for step in case["steps"]:
        action, *args = step["action"]
        action = {"hasItems": "has_items"}.get(action, action)
        assert getattr(queue, action)(*args) == step["value"]
        assert queue.messages == step["messages"]


@pytest.mark.parametrize(
    "style", ["snake_sync_getters", "camel_async_getters", "camel_async_queues"]
)
@pytest.mark.parametrize(
    "case", _ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_original_loop_control_trace(case, style, tmp_path, monkeypatch):
    source = copy.deepcopy(case["input"])
    expected = case["expected"]
    selected = source.get("tools", [])
    steering = PendingMessageQueue(source.get("mode", "one-at-a-time"))
    followup = PendingMessageQueue(source.get("mode", "one-at-a-time"))
    for value in source.get("steering", []):
        steering.enqueue(_user(value))
    for value in source.get("followups", []):
        followup.enqueue(_user(value))
    state = {"request": 0, "turn": 0, "prepare": 0, "converted": []}
    timeline, events, requests = [], [], []

    def record(name, **value):
        timeline.append({"hook": name, **copy.deepcopy(value)})

    def on_event(event):
        event = _event(event, "wire" in source)
        if event is not None:
            events.append(event)
            timeline.append({"event": event})

    def update(spec):
        if spec is None:
            return None
        for value in spec.get("enqueue", []):
            steering.enqueue(_user(value))
        result = {}
        if "replace" in spec:
            result["context"] = {
                "messages": [_user(value) for value in spec["replace"]],
                "tools": tool_schemas(selected),
            }
        if "messages" in spec:
            result["messages"] = [_user(value) for value in spec["messages"]]
        if "model" in spec:
            result["model"] = {
                "id": spec["model"],
                "provider": "openai",
                "api": "openai-completions",
                "baseUrl": "https://offline.invalid/v1",
            }
        if "thinkingLevel" in spec:
            result["thinkingLevel"] = spec["thinkingLevel"]
        return result

    def indexed_update(name, index):
        values = source.get(name, [])
        return update(values[index] if index < len(values) else None)

    def prepare_request(request):
        record(
            "prepareRequest",
            messages=_messages(request["context"]["messages"]),
            model=request["model"]["id"],
            thinkingLevel=request["thinkingLevel"],
        )
        return indexed_update("prepareRequest", state["request"])

    def completed(name, turn):
        record(
            name,
            message=_message(turn["message"]),
            toolResults=[_message(message) for message in turn["toolResults"]],
            messages=_messages(turn["context"]["messages"]),
            newMessages=_messages(turn["newMessages"]),
        )

    def prepare_next_turn(turn):
        completed("prepareNextTurn", turn)
        index = state["prepare"]
        state["prepare"] += 1
        return indexed_update("prepareNext", index)

    def transform_context(messages):
        record("transformContext", messages=_messages(messages))
        return (
            [*messages, _user("transformed request")]
            if source.get("transform")
            else messages
        )

    def convert_to_llm(messages):
        record("convertToLlm", messages=_messages(messages))
        state["converted"] = _messages(messages)
        return messages

    def get_api_key(provider):
        record("getApiKey", provider=provider)
        return "sk-hook-fixture"

    def finish_turn(turn):
        completed("finishTurn", turn)
        if state["turn"] == 0:
            for value in source.get("enqueueOnFinish", []):
                steering.enqueue(_user(value))
        decisions = source.get("decisions", [])
        index = state["turn"]
        state["turn"] += 1
        return {"action": decisions[index]} if index < len(decisions) else None

    def before_tool_call(context):
        record(
            "beforeToolCall",
            toolCall=context["toolCall"],
            args=context["args"],
            messages=_messages(context["context"]["messages"]),
        )
        if "beforeThrow" in source:
            raise RuntimeError(source["beforeThrow"])
        return source.get("before")

    def after_tool_call(context):
        record(
            "afterToolCall",
            toolCall=context["toolCall"],
            args=context["args"],
            result=context["result"],
            isError=context["isError"],
            messages=_messages(context["context"]["messages"]),
        )
        if "afterThrow" in source:
            raise RuntimeError(source["afterThrow"])
        return source.get("afterById", {}).get(
            context["toolCall"]["id"], source.get("after")
        )

    def get_steering_messages():
        messages = steering.drain()
        record("getSteeringMessages", messages=_messages(messages))
        return messages

    def get_follow_up_messages():
        messages = followup.drain()
        record("getFollowUpMessages", messages=_messages(messages))
        return messages

    def execute_tool(name, args, cwd, **options):
        # A deterministic tool body isolates the source's hook and scheduling
        # logic. Built-in read/write/edit bodies have separate source oracles.
        call_id = next(
            item["event"]["toolCallId"]
            for item in reversed(timeline)
            if "event" in item and item["event"]["type"] == "tool_execution_start"
        )
        record("execute", id=call_id, args=args)
        base = copy.deepcopy(_ORACLE["toolBase"])
        return ToolResult(
            "",
            content_blocks=base["content"],
            details=base["details"],
            structured_content=base["structuredContent"],
            usage=base["usage"],
            terminate=base["terminate"],
        )

    hooks = {
        "prepare_request": prepare_request,
        "prepare_next_turn": prepare_next_turn,
        "transform_context": transform_context,
        "convert_to_llm": convert_to_llm,
        "get_api_key": get_api_key,
        "finish_turn": finish_turn,
        "before_tool_call": before_tool_call,
        "after_tool_call": after_tool_call,
    }
    direct_queues = style.endswith("queues")
    if not direct_queues:
        hooks.update(
            get_steering_messages=get_steering_messages,
            get_follow_up_messages=get_follow_up_messages,
        )

    def camel(name):
        first, *rest = name.split("_")
        return first + "".join(part.title() for part in rest)

    def asynchronous(callback):
        async def run(*args):
            # Controls can pass an optional trailing signal. These callbacks
            # deliberately omit it to verify native Python hook ergonomics.
            if len(args) > 1:
                args = args[:-1]
            return callback(*args)

        return run

    observer = on_event
    if "async" in style:
        hooks = {
            camel(name): asynchronous(callback) for name, callback in hooks.items()
        }
        observer = asynchronous(on_event)

    def request_record(body, headers):
        index = state["request"]
        requests.append(
            {
                "model": body["model"],
                "thinkingLevel": body.get("reasoning_effort", "off"),
                "apiKey": headers["authorization"].removeprefix("Bearer "),
                "messages": copy.deepcopy(state["converted"]),
            }
        )
        record("request", index=index)
        state["request"] += 1
        return index

    def handler(request):
        body = json.loads(request.content)
        index = request_record(body, request.headers)
        if "wire" in source:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="".join(
                    "data: " + json.dumps(item) + "\n\n" for item in source["wire"]
                )
                + "data: [DONE]\n\n",
            )
        assert index < len(source["replies"]), "unexpected extra native request"
        reply = source["replies"][index]
        message = {
            "role": "assistant",
            "content": "".join(
                block["text"] for block in reply["content"] if block["type"] == "text"
            ),
        }
        calls = [
            {
                "id": block["id"],
                "type": "function",
                "function": {
                    "name": block["name"],
                    "arguments": json.dumps(block["arguments"]),
                },
            }
            for block in reply["content"]
            if block["type"] == "toolCall"
        ]
        if calls:
            message["tool_calls"] = calls
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": message,
                        "finish_reason": {"toolUse": "tool_calls"}.get(
                            reply["stopReason"], reply["stopReason"]
                        ),
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        loop.httpx,
        "AsyncClient",
        lambda *args, **kwargs: client(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        ),
    )
    monkeypatch.setattr(loop, "execute_tool", execute_tool)
    if source.get("replies", [{}])[0].get("stopReason") in {"error", "aborted"}:
        # Those are agent-stream outcomes, not standard Chat Completions JSON
        # finish reasons. Replay them at the provider boundary only.
        async def failed_provider(*args, **kwargs):
            reply = source["replies"][state["request"]]
            record("request", index=state["request"])
            requests.append(
                {
                    "model": "gpt-5",
                    "thinkingLevel": "off",
                    "apiKey": "sk-hook-fixture",
                    "messages": copy.deepcopy(state["converted"]),
                }
            )
            state["request"] += 1
            return loop._ProviderReply(
                {"role": "assistant", "content": reply["content"][0]["text"]},
                [],
                {},
                reply["stopReason"],
                {
                    "_pi_content": reply["content"],
                    "errorMessage": reply["errorMessage"],
                },
            )

        monkeypatch.setattr(loop, "_provider_call", failed_provider)
    config = {
        "llm": {
            "model_name": "openai/gpt-5",
            "model_api": "openai-completions",
            "base_url": "https://offline.invalid/v1",
            "api_key": "sk-offline-fixture",
            "max_retries": 0,
        },
        "tools": selected,
        "thinking": source.get("thinking", "off"),
        "tool_execution": "sequential",
        "compaction": False,
        "retry": {"enabled": False},
        "max_turns": 8,
    }
    result = asyncio.run(
        loop.run(
            config,
            "fixture task",
            tmp_path,
            tmp_path,
            ResourceBundle(
                system_prompt="fixture system", tool_schemas=tool_schemas(selected)
            ),
            on_event=observer,
            hooks=hooks,
            steering_queue=steering,
            follow_up_queue=followup,
        )
    )
    expected_timeline = expected["timeline"]
    if direct_queues:
        expected_timeline = [
            item
            for item in expected_timeline
            if item.get("hook") not in {"getSteeringMessages", "getFollowUpMessages"}
        ]
    assert requests == expected["requests"]
    assert events == expected["events"]
    assert timeline == expected_timeline
    assert events == [
        value
        for event in result.events
        if (value := _event(event, "wire" in source)) is not None
    ], "on_event observers must see independent snapshots in stored event order"
    assert _messages(steering.messages) == expected["remainingSteering"]
    assert _messages(followup.messages) == expected["remainingFollowups"]


def test_controls_oracle_has_no_live_dependencies():
    assert _ORACLE["baseline"].endswith("4a080252f06caf63a525d7873c5d94d3c23887e0")
    assert _ORACLE["networkCalls"] == 0
    assert _ORACLE["fakeFetchCalls"] == 2
    assert len(_ORACLE["source_sha256"]) == 5
