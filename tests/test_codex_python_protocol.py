"""Protocol tests for the Python port, using scripted local HTTP and native oracle."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.codex.python_core.client import ResponseError, ResponsesClient
from flashrsi.agents.codex.python_core.history import History, truncate_text
from flashrsi.agents.codex.python_core.models import Model


def _sse(*events):
    return "".join(
        "data: " + json.dumps(event, ensure_ascii=False) + "\r\n\r\n"
        for event in events
    ).encode()


def _completed(response_id="resp_1"):
    return {
        "type": "response.completed",
        "response": {
            "id": response_id,
            "usage": {
                "input_tokens": 11,
                "output_tokens": 5,
                "total_tokens": 16,
                "input_tokens_details": {"cached_tokens": 3, "cache_write_tokens": 2},
                "output_tokens_details": {"reasoning_tokens": 4},
            },
        },
    }


def _message(text="hello"):
    return {
        "type": "message",
        "id": "msg_answer",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


@contextmanager
def _server(steps):
    requests = []
    script = list(steps)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
                    "body": request,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                }
            )
            status, body = script.pop(0) if script else (500, b"unexpected request")
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "text/event-stream" if status == 200 else "application/json",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests, script
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _call(steps, *, settings=None, model="gpt-5"):
    events = []
    with _server(steps) as (url, requests, script):

        async def run():
            async with ResponsesClient(
                {"base_url": url, "api_key": "local-key"},
                Model(model, settings or {}),
                settings or {},
                "thread",
                events.append,
            ) as client:
                return await client.response([], [])

        result = asyncio.run(run())
        assert not script
        return result, requests, events


def test_assets_are_upstream_bytes_and_model_catalog_is_used():
    assets = Path(__file__).parents[1] / "flashrsi/agents/codex/python_core/assets"
    provenance = json.loads((assets / "PROVENANCE.json").read_text())
    for entry in provenance["files"]:
        assert (
            hashlib.sha256((assets / entry["path"]).read_bytes()).hexdigest()
            == entry["sha256"]
        )
    fallback = Model("gpt-5", {})
    assert fallback.instructions == (assets / "prompt.md").read_text()
    assert fallback.info["used_fallback_model_metadata"]
    known = Model("provider/gpt-5.4-2026", {})
    assert known.info["slug"] == "provider/gpt-5.4-2026"
    assert not known.info["used_fallback_model_metadata"]
    assert known.info["default_reasoning_level"] == "medium"
    assert known.info["truncation_policy"] == {"mode": "tokens", "limit": 10000}
    assert Model("a/b/gpt-5.4", {}).info["used_fallback_model_metadata"]


def test_model_config_overrides_and_literal_personality():
    settings = {
        "model_context_window": 2000000,
        "model_auto_compact_token_limit": 1200000,
        "tool_output_token_limit": 40,
        "personality": "none",
    }
    model = Model("gpt-5.4", settings)
    assert model.info["context_window"] == 1000000
    assert model.auto_compact_token_limit == 900000
    assert model.info["truncation_policy"]["limit"] == 40
    assert "# Personality\n" not in model.instructions
    literal = "Literal {{ personality }} stays when no variables exist."
    assert Model("gpt-5.4", {"base_instructions": literal}).instructions == literal
    assert (
        Model("gpt-5", {"tool_output_token_limit": 40}).info["truncation_policy"][
            "limit"
        ]
        == 160
    )


def test_sse_framing_item_done_and_exact_token_usage():
    item = _message("你好")
    # Event labels, comments, malformed JSON and [DONE] never fabricate history.
    body = b": keepalive\r\n\r\ndata: invalid\r\n\r\n" + _sse(
        {"type": "response.output_text.delta", "delta": "ignored for history"},
        {"type": "response.output_item.done", "item": item},
        _completed(),
    )
    result, requests, events = _call([(200, body)])
    assert result["items"] == [item]
    assert result["response_id"] == "resp_1"
    assert result["usage"] == {
        "input_tokens": 11,
        "output_tokens": 5,
        "total_tokens": 16,
        "cached_input_tokens": 3,
        "cache_write_input_tokens": 2,
        "reasoning_output_tokens": 4,
    }
    assert len(events) == 3
    assert requests[0]["path"] == "/v1/responses"
    assert requests[0]["headers"]["authorization"] == "Bearer local-key"


def test_http_5xx_retries_but_429_does_not(monkeypatch):
    monkeypatch.setattr(
        "flashrsi.agents.codex.python_core.client._backoff", lambda attempt: 0
    )
    result, requests, events = _call(
        [(503, b'{"error":{"message":"retry"}}'), (200, _sse(_completed()))]
    )
    assert result["response_id"] == "resp_1"
    assert len(requests) == 2
    assert not any(event.get("will_retry") for event in events)
    with _server([(429, b'{"error":{"message":"limited"}}')]) as (
        url,
        requests,
        script,
    ):

        async def run():
            async with ResponsesClient(
                {"base_url": url}, Model("gpt-5", {}), {}, "thread", lambda event: None
            ) as client:
                return await client.response([], [])

        with pytest.raises(ResponseError, match="HTTP 429") as caught:
            asyncio.run(run())
        assert not caught.value.retryable
        assert len(requests) == 1


def test_stream_error_reconnects_without_completed_items(monkeypatch):
    monkeypatch.setattr(
        "flashrsi.agents.codex.python_core.client._backoff", lambda attempt: 0
    )
    result, requests, events = _call(
        [
            (
                200,
                _sse(
                    {
                        "type": "response.incomplete",
                        "response": {
                            "incomplete_details": {"reason": "max_output_tokens"}
                        },
                    }
                ),
            ),
            (200, _sse(_completed())),
        ]
    )
    assert result["response_id"] == "resp_1"
    assert len(requests) == 2
    assert any(event.get("will_retry") for event in events)


def test_completed_items_in_failed_stream_are_returned_to_loop_without_replay():
    item = {
        "type": "function_call",
        "id": "fc_1",
        "name": "shell_command",
        "arguments": "{}",
        "call_id": "call_1",
    }
    with _server(
        [(200, _sse({"type": "response.output_item.done", "item": item}))]
    ) as (url, requests, script):
        events = []

        async def run():
            async with ResponsesClient(
                {"base_url": url}, Model("gpt-5", {}), {}, "thread", events.append
            ) as client:
                return await client.response([], [])

        with pytest.raises(ResponseError, match="before response.completed") as caught:
            asyncio.run(run())
        assert caught.value.partial_items == [item]
        assert caught.value.retryable
        assert events == [{"type": "response.output_item.done", "item": item}]
        assert len(requests) == 1


@pytest.mark.parametrize(
    "code",
    [
        "context_length_exceeded",
        "insufficient_quota",
        "invalid_prompt",
        "server_is_overloaded",
        "cyber_policy",
    ],
)
def test_fatal_stream_failure_is_not_retried(code):
    with _server(
        [
            (
                200,
                _sse(
                    {
                        "type": "response.failed",
                        "response": {"error": {"code": code, "message": "failure"}},
                    }
                ),
            )
        ]
    ) as (url, requests, script):

        async def run():
            async with ResponsesClient(
                {"base_url": url}, Model("gpt-5", {}), {}, "thread", lambda event: None
            ) as client:
                return await client.response([], [])

        with pytest.raises(ResponseError, match="failure") as caught:
            asyncio.run(run())
        assert caught.value.code == code
        assert not caught.value.retryable
        assert len(requests) == 1


def test_history_normalizes_call_pairs_without_mutating_durable_items():
    history = History(Model("gpt-5", {}))
    history.append(
        {
            "type": "function_call",
            "id": "fc_a",
            "call_id": "call_a",
            "name": "shell_command",
            "arguments": "{}",
            "status": "completed",
        }
    )
    history.append(
        {"type": "function_call_output", "call_id": "orphan", "output": "drop"}
    )
    history.append({"type": "message", "role": "system", "content": []})
    first, second = history.input_items(), history.input_items()
    assert first == second
    assert "status" not in first[0]
    assert first[1]["output"] == "aborted"
    assert first[1]["id"] == "fco_7c0944c5-f336-503b-9f81-554a58cb1562"
    assert len(first) == 2
    assert history.items[1]["call_id"] == "orphan"


def test_history_preserves_encrypted_reasoning_strips_wire_extras_and_counts_usage():
    history = History(Model("gpt-5.4", {}))
    history.append(
        {
            "type": "reasoning",
            "id": "rs_a",
            "summary": [],
            "encrypted_content": "opaque",
            "status": "completed",
        }
    )
    history.append(
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "answer", "annotations": []}],
            "status": "completed",
        }
    )
    items = history.input_items()
    assert items[0]["encrypted_content"] == "opaque"
    assert "status" not in items[0]
    assert items[1]["content"] == [{"type": "output_text", "text": "answer"}]
    history.add_usage({"input_tokens": 11, "output_tokens": 5, "total_tokens": 16})
    history.add_usage({"input_tokens": 13, "output_tokens": 7, "total_tokens": 20})
    assert history.usage["total_tokens"] == 36
    assert history.last_usage["input_tokens"] == 13


def test_history_tool_output_truncation_keeps_utf8_head_tail_and_serialization_budget():
    assert truncate_text("abcdefghij", "bytes", 4) == "ab…6 chars truncated…ij"
    assert truncate_text("你好世界", "bytes", 6) == "你…2 chars truncated…界"
    assert truncate_text("abcdefghij", "tokens", 1) == "ab…2 tokens truncated…ij"
    history = History(Model("gpt-5", {"tool_output_token_limit": 1}))
    history.append(
        {"type": "function_call_output", "call_id": "c", "output": "abcdefghij"}
    )
    assert history.items[0]["output"] == "ab…5 chars truncated…hij"


def test_responses_lite_formats_input_and_header():
    client = ResponsesClient(
        {}, Model("gpt-5.6-sol", {}), {}, "thread", lambda event: None
    )
    body = client.request([], [])
    assert "tools" not in body and "instructions" not in body
    assert body["reasoning"]["context"] == "all_turns"
    assert body["parallel_tool_calls"] is False
    assert body["input"][0] == {
        "type": "additional_tools",
        "role": "developer",
        "tools": [],
    }
    assert body["input"][1]["content"][0]["text"] == client.model.instructions
    assert client._headers({})["x-openai-internal-codex-responses-lite"] == "true"


def test_sse_multiline_data_bom_and_one_byte_utf8_chunks():
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            # Exercise decoding, line framing and UTF-8 boundaries independently
            # of OS packet buffering, including a split multibyte character.
            for value in body:
                yield bytes([value])

    item = _message("你好")
    event = json.dumps(
        {"type": "response.output_item.done", "item": item}, ensure_ascii=False
    )
    left, right = event.split('"item":', 1)
    body = (
        "\ufeff: comment\r\nevent: ignored_label\r\ndata: "
        + left
        + '"item":\r\ndata: '
        + right
        + "\r\n\r\n"
    ).encode() + _sse(_completed())
    events = []
    client = ResponsesClient({}, Model("gpt-5", {}), {}, "thread", events.append)

    async def run():
        response = httpx.Response(
            200,
            stream=Bytes(),
            request=httpx.Request("POST", "http://localhost/responses"),
        )
        try:
            return await client._reduce(response)
        finally:
            await response.aclose()

    result = asyncio.run(run())
    assert result["items"] == [item]
    assert len(events) == 2


def test_failed_event_is_deferred_until_eof_and_completion_wins():
    failed = {
        "type": "response.failed",
        "response": {"error": {"code": "invalid_prompt", "message": "deferred"}},
    }
    result, requests, events = _call([(200, _sse(failed, _completed()))])
    assert result["response_id"] == "resp_1"
    assert len(requests) == 1


def test_request_projects_provider_metadata_and_schema_controls():
    settings = {
        "model_reasoning_effort": "ultra",
        "model_reasoning_summary": "concise",
        "model_verbosity": "high",
        "service_tier": "priority",
        "output_schema": {"type": "object", "properties": {}},
    }
    client = ResponsesClient(
        {}, Model("gpt-5.4", settings), settings, "thread", lambda event: None
    )
    item = {
        "type": "function_call",
        "id": "legacy",
        "call_id": "call",
        "name": "x",
        "arguments": "{}",
        "encrypted_function_args": ["secret"],
        "internal_chat_message_metadata_passthrough": {"secret": "private"},
    }
    request = client.request([item], [])
    assert request["reasoning"] == {"effort": "max", "summary": "concise"}
    assert request["service_tier"] == "priority"
    assert request["text"] == {
        "verbosity": "high",
        "format": {
            "type": "json_schema",
            "strict": True,
            "schema": settings["output_schema"],
            "name": "codex_output_schema",
        },
    }
    assert request["input"] == [
        {"type": "function_call", "call_id": "call", "name": "x", "arguments": "{}"}
    ]
    assert item["id"] == "legacy"
