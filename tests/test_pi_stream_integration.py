"""Native agent -> incremental HTTP bytes -> source-verified provider events."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop, tools
from flashrsi.agents.pi_agent.runtime.pi_native.compaction import _model_catalog
from flashrsi.agents.pi_agent.runtime.pi_native.resources import ResourceBundle


def fixture(filename):
    return json.loads((Path(__file__).parent / "fixtures" / filename).read_text())[
        "cases"
    ]


OPENAI = fixture("pi_openai_stream_upstream.json")
ANTHROPIC = fixture("pi_anthropic_stream_upstream.json")


def source_case(name):
    return next(case for case in OPENAI + ANTHROPIC if case["input"]["name"] == name)


TEXT_CASES = [
    source_case("chat_text"),
    source_case("responses_text_slots"),
    source_case("text_multiple_deltas"),
]
ABORT_CASES = [
    source_case("chat_abort_content"),
    source_case("responses_abort_text"),
    source_case("abort_partial_text"),
]
TOOL_ABORT_CASES = [
    source_case("chat_abort_tool_calls"),
    source_case("responses_abort_tool"),
    source_case("abort_partial_tool"),
]
TOOL_CASES = [
    source_case("chat_id_only_correlates"),
    source_case("responses_function_argument_done_suffix"),
    source_case("oauth_tool_canonical_name"),
]
ERROR_CASES = [
    source_case("chat_raw_error"),
    source_case("responses_event_error"),
    source_case("provider_error_retains_partial"),
]


def wire(case):
    return case["input"].get("wire", case["input"].get("rawEvents"))


def expected(case):
    return case["expected"].get("message", case["expected"].get("reply"))


def api(case):
    return case["input"]["config"]["llm"]["model_api"]


def config(case, session, monkeypatch, *, selected=(), retries=0):
    source = case["input"]
    value = copy.deepcopy(source["config"])
    value["llm"]["max_retries"] = retries
    value.update(
        tools=list(selected),
        session_file=str(session),
        compaction=False,
        retry={"enabled": False},
    )
    if source.get("reasoning"):
        value["thinking"] = source["reasoning"]
    monkeypatch.setitem(_model_catalog(), value["llm"]["model_name"], source["model"])
    return value


def sse_bytes(events, newline="\n", *, multiline=False, omit_type=False):
    chunks = []
    for event in events:
        body = copy.deepcopy(event)
        kind = body.get("type", "message")
        if omit_type:
            body.pop("type", None)
        raw = json.dumps(
            body,
            ensure_ascii=False,
            indent=2 if multiline else None,
            separators=None if multiline else (",", ":"),
        )
        lines = [": keepalive", "id: ignored", "retry: 100", f"event: {kind}"]
        lines.extend(f"data: {line}" for line in raw.splitlines())
        chunks.append((newline.join(lines) + newline * 2).encode())
    return b"".join(chunks)


class FragmentedStream(httpx.AsyncByteStream):
    """Yield split UTF-8 and SSE lines, with an actual scheduling boundary."""

    def __init__(self, body, *, block_at_eof=False, failure=None):
        self.body = body
        self.block_at_eof = block_at_eof
        self.failure = failure
        self.yielded = 0
        self.closed = False
        self.release = asyncio.Event()

    async def __aiter__(self):
        widths = (1, 2, 7, 3, 11)
        part = 0
        while self.yielded < len(self.body):
            following = min(len(self.body), self.yielded + widths[part % len(widths)])
            chunk = self.body[self.yielded : following]
            self.yielded = following
            part += 1
            yield chunk
            await asyncio.sleep(0)
        if self.failure:
            raise httpx.ReadError(self.failure)
        if self.block_at_eof:
            await self.release.wait()

    async def aclose(self):
        self.closed = True


def response(stream):
    return httpx.Response(
        200, headers={"content-type": "text/event-stream; charset=utf-8"}, stream=stream
    )


def install_transport(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        loop.httpx,
        "AsyncClient",
        lambda *args, **kwargs: client_type(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        ),
    )


async def native(tmp_path, cfg, **options):
    resources = ResourceBundle(
        system_prompt="offline stream fixture",
        tool_schemas=tools.tool_schemas(cfg["tools"]),
    )
    return await asyncio.wait_for(
        loop.run(cfg, "fixture task", tmp_path, tmp_path, resources, **options),
        timeout=5,
    )


def assistant_ends(result):
    return [
        event["message"]
        for event in result.events
        if event["type"] == "message_end" and event["message"]["role"] == "assistant"
    ]


def saved_assistants(session):
    return [
        entry["message"]
        for line in session.read_text().splitlines()
        if (entry := json.loads(line)).get("type") == "message"
        and entry["message"]["role"] == "assistant"
    ]


def semantic(value):
    if isinstance(value, list):
        return [semantic(item) for item in value]
    if isinstance(value, dict):
        return {
            key: semantic(item)
            for key, item in value.items()
            if key not in {"timestamp", "durationMs", "thinkingLevel"}
        }
    return value


def provider_events(events):
    result = []
    for event in events:
        message = event.get("message", {})
        if message.get("role") != "assistant":
            continue
        kind = event["type"]
        if kind == "message_start":
            # The provider parser records synchronous push snapshots. The
            # agent loop consumes those events after the decoded SSE frame,
            # when the shared partial has advanced; parser and agent snapshots
            # are checked separately by their source oracles.
            result.append({"type": "start"})
        elif kind == "message_update":
            result.append(
                {
                    key: value
                    for key, value in event["assistantMessageEvent"].items()
                    if key != "partial"
                }
            )
        elif kind == "message_end":
            failed = message["stopReason"] in {"error", "aborted"}
            result.append({"type": "error" if failed else "done", "reason": message["stopReason"]})
    return semantic(result)


def expected_agent_provider_events(events):
    """Normalize provider push fixtures to the agent's consumed event shape."""
    result = []
    for event in events:
        if event["type"] in {"start", "done", "error"}:
            result.append(
                {
                    key: event[key]
                    for key in ("type", "reason")
                    if key in event
                }
            )
        else:
            result.append(
                {
                    key: value
                    for key, value in event.items()
                    if key != "partial"
                }
            )
    return semantic(result)


@pytest.mark.parametrize("case", TEXT_CASES, ids=api)
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["LF", "CRLF", "CR"])
def test_native_stream_forwards_original_events_before_body_closes(
    case, newline, tmp_path, monkeypatch
):
    session = tmp_path / "session.jsonl"
    cfg = config(case, session, monkeypatch)
    stream = FragmentedStream(
        sse_bytes(wire(case), newline, multiline=True, omit_type=True)
    )
    requests, observed = [], []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(stream)

    async def on_event(event):
        observed.append(copy.deepcopy(event))
        update = event.get("assistantMessageEvent", {})
        if update.get("type") == "text_delta":
            assert not stream.closed
            assert stream.yielded < len(stream.body)
        await asyncio.sleep(0)

    install_transport(monkeypatch, handler)
    result = asyncio.run(native(tmp_path, cfg, on_event=on_event))
    assert result.status == "finished"
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    if api(case) == "openai-completions":
        assert requests[0]["stream_options"] == {"include_usage": True}
    assert observed == result.events
    assert stream.closed
    assert provider_events(observed) == expected_agent_provider_events(
        case["expected"]["events"]
    )
    assert semantic(assistant_ends(result)[-1]) == semantic(expected(case))
    assert saved_assistants(session) == assistant_ends(result)
    assert result.usage["input"] == expected(case)["usage"]["input"]
    assert result.usage["output"] == expected(case)["usage"]["output"]
    assert result.usage["model_calls"] == 1


@pytest.mark.parametrize(
    "case", ABORT_CASES + TOOL_ABORT_CASES, ids=lambda case: case["input"]["name"]
)
def test_native_stream_abort_retains_partial_message_usage_and_session(
    case, tmp_path, monkeypatch
):
    session = tmp_path / "session.jsonl"
    cfg = config(case, session, monkeypatch, selected=["read"])
    raw = wire(case)
    if case["input"].get("abortAfter") is not None:
        raw = raw[: case["input"]["abortAfter"] + 1]
    stream = FragmentedStream(sse_bytes(raw), block_at_eof=True)
    observed, requests = [], []

    def handler(request):
        requests.append(request)
        return response(stream)

    async def exercise():
        cancel = asyncio.Event()
        active = 0

        async def on_event(event):
            nonlocal active
            active += 1
            try:
                assert active == 1
                observed.append(copy.deepcopy(event))
                if event.get("assistantMessageEvent", {}).get("type") in {
                    "text_delta",
                    "toolcall_delta",
                }:
                    cancel.set()
                await asyncio.sleep(0)
            finally:
                active -= 1

        result = await native(tmp_path, cfg, cancel_event=cancel, on_event=on_event)
        assert active == 0
        return result

    install_transport(monkeypatch, handler)
    result = asyncio.run(exercise())
    assert result.status == "error"
    assert result.stop_reason == "aborted"
    assert len(requests) == 1
    assert stream.closed
    messages = assistant_ends(result)
    assert len(messages) == 1
    actual = semantic(messages[0])
    original = semantic(expected(case))
    assert actual == original
    assert saved_assistants(session) == messages
    assert observed == result.events
    assert provider_events(observed) == expected_agent_provider_events(
        case["expected"]["events"]
    )
    assert result.events[-1] == {"type": "agent_settled", "aborted": True}
    assert result.usage["input"] == original["usage"]["input"]
    assert result.usage["output"] == original["usage"]["output"]
    assert not any(event["type"] == "tool_execution_start" for event in result.events)


@pytest.mark.parametrize("case", ABORT_CASES, ids=api)
def test_native_stream_external_task_cancellation_propagates_cancelled_error(
    case, tmp_path, monkeypatch
):
    cfg = config(case, tmp_path / "session.jsonl", monkeypatch)
    raw = wire(case)
    if case["input"].get("abortAfter") is not None:
        raw = raw[: case["input"]["abortAfter"] + 1]
    stream = FragmentedStream(sse_bytes(raw), block_at_eof=True)
    install_transport(monkeypatch, lambda request: response(stream))
    observed = []

    async def exercise():
        received = asyncio.Event()

        async def on_event(event):
            observed.append(copy.deepcopy(event))
            if event.get("assistantMessageEvent", {}).get("type") == "text_delta":
                received.set()
            await asyncio.sleep(0)

        operation = asyncio.create_task(native(tmp_path, cfg, on_event=on_event))
        await asyncio.wait_for(received.wait(), timeout=0.5)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation

    asyncio.run(exercise())
    assert stream.closed
    assert not any(
        event.get("message", {}).get("stopReason") == "aborted" for event in observed
    )


@pytest.mark.parametrize("case", TEXT_CASES, ids=api)
@pytest.mark.parametrize("failure", ["http_status", "connection"])
def test_native_stream_retries_opening_failures_once_before_any_provider_event(
    case, failure, tmp_path, monkeypatch
):
    cfg = config(case, tmp_path / "session.jsonl", monkeypatch, retries=1)
    cfg["_provider_retry_delay"] = 0
    stream = FragmentedStream(sse_bytes(wire(case)))
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            if failure == "connection":
                raise httpx.ConnectError("offline opening failure", request=request)
            return httpx.Response(
                503,
                text="offline opening failure",
                headers={"retry-after-ms": "0"},
            )
        return response(stream)

    install_transport(monkeypatch, handler)
    result = asyncio.run(native(tmp_path, cfg))
    assert result.status == "finished"
    assert len(requests) == 2
    assert len(assistant_ends(result)) == 1
    assert len(provider_events(result.events)) == len(case["expected"]["events"])
    assert result.usage["model_calls"] == 1
    assert not any(event["type"] == "auto_retry_start" for event in result.events)


@pytest.mark.parametrize("case", ABORT_CASES, ids=api)
def test_native_stream_connection_break_after_partial_response_is_never_retried(
    case, tmp_path, monkeypatch
):
    session = tmp_path / "session.jsonl"
    cfg = config(case, session, monkeypatch, retries=3)
    raw = wire(case)
    if case["input"].get("abortAfter") is not None:
        raw = raw[: case["input"]["abortAfter"] + 1]
    stream = FragmentedStream(sse_bytes(raw), failure="offline stream broke")
    requests = []

    def handler(request):
        requests.append(request)
        return response(stream)

    install_transport(monkeypatch, handler)
    result = asyncio.run(native(tmp_path, cfg))
    assert result.status == "error"
    assert result.stop_reason == "error"
    assert len(requests) == 1
    assert stream.closed
    messages = assistant_ends(result)
    assert len(messages) == 1
    assert messages[0]["content"] == expected(case)["content"]
    assert messages[0]["usage"] == expected(case)["usage"]
    assert messages[0]["errorMessage"] == "offline stream broke"
    assert saved_assistants(session) == messages
    assert result.usage["model_calls"] == 1


@pytest.mark.parametrize("case", ERROR_CASES, ids=api)
def test_native_provider_error_settles_without_waiting_for_http_body_eof(
    case, tmp_path, monkeypatch
):
    session = tmp_path / "session.jsonl"
    cfg = config(case, session, monkeypatch, retries=3)
    stream = FragmentedStream(sse_bytes(wire(case)), block_at_eof=True)
    requests = []

    def handler(request):
        requests.append(request)
        return response(stream)

    async def exercise():
        return await asyncio.wait_for(native(tmp_path, cfg), timeout=0.5)

    install_transport(monkeypatch, handler)
    result = asyncio.run(exercise())
    assert result.status == "error"
    assert result.stop_reason == "error"
    assert len(requests) == 1
    assert stream.closed
    messages = assistant_ends(result)
    assert len(messages) == 1
    assert semantic(messages[0]) == semantic(expected(case))
    assert saved_assistants(session) == messages


@pytest.mark.parametrize("case", TOOL_CASES, ids=api)
def test_native_stream_tool_deltas_execute_and_replay_the_completed_call(
    case, tmp_path, monkeypatch
):
    cfg = config(case, tmp_path / "session.jsonl", monkeypatch, selected=["read"])
    call = expected(case)["content"][0]
    (tmp_path / call["arguments"]["path"]).write_text("streamed tool file\n")
    final = next(candidate for candidate in TEXT_CASES if api(candidate) == api(case))
    streams = [
        FragmentedStream(sse_bytes(wire(case))),
        FragmentedStream(sse_bytes(wire(final))),
    ]
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(streams[len(requests) - 1])

    install_transport(monkeypatch, handler)
    result = asyncio.run(native(tmp_path, cfg))
    assert result.status == "finished"
    assert len(requests) == 2
    assert all(stream.closed for stream in streams)
    assert assistant_ends(result)[0]["content"] == expected(case)["content"]
    updates = [
        event["assistantMessageEvent"]["type"]
        for event in result.events
        if event["type"] == "message_update"
    ]
    assert "toolcall_delta" in updates
    assert updates.index("toolcall_start") < updates.index("toolcall_end")
    executed = [
        event for event in result.events if event["type"] == "tool_execution_end"
    ]
    assert len(executed) == 1
    assert executed[0]["isError"] is False
    assert executed[0]["toolCallId"] == call["id"]
    assert "streamed tool file" in json.dumps(requests[1])
    assert result.usage["tool_calls"] == 1
