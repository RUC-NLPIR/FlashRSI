"""Replay traces captured by executing the pinned upstream Pi agent loop.

The oracle executes original read/write/edit implementations with fixed model
reply content. This verifies scheduling and tool semantics, not live model
quality, resource discovery, provider SDKs, or byte-for-byte streaming chunks.
"""

import asyncio
import base64
import copy
import json
import threading
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.resources import ResourceBundle
from flashrsi.agents.pi_agent.runtime.pi_native.tools import ToolResult, tool_schemas

_ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_trajectories_upstream.json").read_text()
)
_USAGE_FIELDS = ("input", "output", "cacheRead", "cacheWrite", "totalTokens")


def _semantic_messages(events):
    result = []
    for event in events:
        if event["type"] != "message_end":
            continue
        message = event["message"]
        role = message["role"]
        if role == "system":
            continue
        value = {"role": role, "content": message.get("content", [])}
        if role == "assistant":
            value.update(
                stopReason=message["stopReason"],
                usage={k: message.get("usage", {}).get(k, 0) for k in _USAGE_FIELDS},
            )
        if role == "toolResult":
            value.update(
                toolCallId=message["toolCallId"],
                toolName=message["toolName"],
                isError=message["isError"],
            )
        result.append(value)
    return result


def _control_events(events):
    result = []
    for event in events:
        kind = event["type"]
        role = event.get("message", {}).get("role", event.get("role"))
        if kind in {"session", "agent_settled", "message_update"} or role == "system":
            continue
        result.append(
            {
                "type": kind,
                **({"role": role} if role else {}),
                **{
                    k: event[k]
                    for k in ("toolCallId", "toolName", "isError")
                    if k in event
                },
            }
        )
    # Parallel execution ends follow completion order, which is not stable
    # across OS schedulers. Compare each contiguous completion group as a set;
    # starts and tool-result messages retain strict source ordering.
    grouped = []
    pending = []
    for event in result:
        if event["type"] == "tool_execution_end":
            pending.append(event)
        else:
            grouped.extend(sorted(pending, key=lambda item: item["toolCallId"]))
            pending.clear()
            grouped.append(event)
    grouped.extend(sorted(pending, key=lambda item: item["toolCallId"]))
    return grouped


@pytest.mark.parametrize(
    "case", _ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_pi_replays_original_upstream_trajectory(case, tmp_path, monkeypatch):
    case = copy.deepcopy(case)
    source, expected = case["input"], case["expected"]
    for name, text in source.get("files", {}).items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    responses = iter(source["replies"])
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        reply = next(responses)
        message = {
            "role": "assistant",
            "content": "".join(
                b["text"] for b in reply["content"] if b["type"] == "text"
            ),
        }
        calls = [
            {
                "id": b["id"],
                "type": "function",
                "function": {
                    "name": b["name"],
                    "arguments": json.dumps(b["arguments"], ensure_ascii=False),
                },
            }
            for b in reply["content"]
            if b["type"] == "toolCall"
        ]
        if calls:
            message["tool_calls"] = calls
        reason = {"toolUse": "tool_calls"}.get(reply["stopReason"], reply["stopReason"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message, "finish_reason": reason}],
                "usage": reply["usage"],
            },
        )

    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return original_client(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        )

    monkeypatch.setattr(loop.httpx, "AsyncClient", client)
    selected = source.get("tools", ["read", "write", "edit"])
    result = asyncio.run(
        loop.run(
            {
                "llm": {
                    "model_name": "openai/parity-fixture",
                    "api_key": "fixture-only",
                    "base_url": "http://reference.invalid/v1",
                    "max_retries": 0,
                },
                "tools": selected,
                "max_turns": 4,
            },
            source["prompt"],
            tmp_path,
            tmp_path,
            ResourceBundle(
                system_prompt=_ORACLE["system_prompt"],
                tool_schemas=tool_schemas(selected),
            ),
        )
    )

    assert _semantic_messages(result.events) == expected["messages"]
    assert _control_events(result.events) == _control_events(expected["control_events"])
    details = [
        event["message"].get("details") or {}
        for event in result.events
        if event["type"] == "message_end" and event["message"]["role"] == "toolResult"
    ]
    assert details == expected["tool_details"]
    files = {
        p.relative_to(tmp_path).as_posix(): base64.b64encode(p.read_bytes()).decode()
        for p in sorted(tmp_path.rglob("*"))
        if p.is_file()
    }
    assert files == expected["files"]
    assert result.status == expected["status"]
    assert len(requests) == len(expected["messages"]) - sum(
        m["role"] != "assistant" for m in expected["messages"]
    )
    if result.stop_reason == "aborted":
        assert result.events[-1] == {"type": "agent_settled", "aborted": True}


def test_pi_parallel_completions_emit_in_completion_order(tmp_path, monkeypatch):
    second_completed = threading.Event()
    original_event = loop._event

    def event(events, value):
        original_event(events, value)
        if value["type"] == "tool_execution_end" and value["toolCallId"] == "second":
            second_completed.set()

    def tool(name, args, cwd):
        if args["path"] == "first":
            assert second_completed.wait(3), "parallel second tool did not finish"
        return ToolResult(args["path"])

    monkeypatch.setattr(loop, "_event", event)
    monkeypatch.setattr(loop, "execute_tool", tool)
    calls = [
        {"id": name, "name": "read", "arguments": json.dumps({"path": name})}
        for name in ("first", "second")
    ]
    events = []
    results = asyncio.run(
        loop._execute_tool_batch(
            calls,
            selected=["read"],
            cwd=tmp_path,
            events=events,
            usage={"tool_calls": 0},
            stop_reason="toolUse",
            mode="parallel",
        )
    )
    starts = [e["toolCallId"] for e in events if e["type"] == "tool_execution_start"]
    ends = [e["toolCallId"] for e in events if e["type"] == "tool_execution_end"]
    assert starts == ["first", "second"]
    assert ends == ["second", "first"]
    assert [r["toolCallId"] for r in results] == ["first", "second"]


def test_pi_cancelled_mutation_settles_before_batch_returns(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    target = tmp_path / "note.txt"

    def write(name, args, cwd):
        started.set()
        assert release.wait(3), "test did not release pending filesystem operation"
        target.write_text("settled", encoding="utf-8")
        return ToolResult("done")

    monkeypatch.setattr(loop, "execute_tool", write)

    async def scenario():
        batch = asyncio.create_task(
            loop._execute_tool_batch(
                [
                    {
                        "id": "write",
                        "name": "write",
                        "arguments": '{"path":"note.txt","content":"settled"}',
                    }
                ],
                selected=["write"],
                cwd=tmp_path,
                events=[],
                usage={"tool_calls": 0},
                stop_reason="toolUse",
                mode="parallel",
            )
        )
        assert await asyncio.to_thread(started.wait, 3)
        batch.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not batch.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await batch
        assert target.read_text(encoding="utf-8") == "settled"

    asyncio.run(scenario())
