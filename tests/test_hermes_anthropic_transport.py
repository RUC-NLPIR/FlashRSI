"""Actual original Hermes Anthropic conversion/normalization differential."""

import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.hermes.runtime.hermes_native.anthropic_transport import (
    anthropic_endpoint,
    anthropic_headers,
    decode_anthropic,
    ingest_anthropic,
    prepare_anthropic,
)

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures/hermes_anthropic_upstream.json").read_text()
)


@pytest.mark.parametrize("case", REFERENCE["cases"], ids=lambda case: case["name"])
def test_request_matches_actual_original_anthropic_transport(case):
    original = copy.deepcopy(case["payload"])
    result = prepare_anthropic(case["payload"], case["route"], case["settings"])
    result.pop("_wire_aliases")
    assert result.pop("stream") is True
    assert result == case["expected"]
    assert case["payload"] == original


@pytest.mark.parametrize("case", REFERENCE["headers"], ids=lambda case: case["name"])
def test_native_http_headers_match_original_client_factory(case):
    result = anthropic_headers(case["route"])
    for key, value in case["expected"].items():
        assert result[key] == value
    if case["credential_style"] == "bearer":
        assert result["Authorization"] == "Bearer " + case["route"]["api_key"]
        assert "x-api-key" not in result
    else:
        assert result["x-api-key"] == case["route"]["api_key"]
        assert "Authorization" not in result
    endpoint = anthropic_endpoint(case["route"])
    assert "/v1/messages" in endpoint
    if case["query"]:
        assert "api-version=2025-04-15" in endpoint


@pytest.mark.parametrize("case", REFERENCE["responses"], ids=lambda case: case["name"])
def test_response_matches_actual_original_normalization(case):
    if not case["valid"]:
        with pytest.raises(ValueError, match="invalid Anthropic"):
            ingest_anthropic(case["raw"], case["aliases"])
        return
    result = ingest_anthropic(case["raw"], case["aliases"])
    choice = result["choices"][0]
    message = choice["message"]
    expected = case["expected"]
    assert choice["finish_reason"] == expected["finish_reason"]
    assert message["content"] == expected["content"]
    assert message.get("reasoning") == expected["reasoning"]
    for key, value in (expected["provider_data"] or {}).items():
        assert (
            message[
                "_anthropic_content_blocks"
                if key == "anthropic_content_blocks"
                else key
            ]
            == value
        )
    for call, expected_call in zip(
        message.get("tool_calls") or [], expected["tool_calls"] or [], strict=True
    ):
        assert call["id"] == expected_call["id"]
        assert call["function"] == {
            "name": expected_call["name"],
            "arguments": expected_call["arguments"],
        }
    stats = case["cache"] or {}
    assert result["usage"]["prompt_tokens_details"] == {
        "cached_tokens": stats.get("cached_tokens", 0),
        "cache_write_tokens": stats.get("creation_tokens", 0),
    }


def sse(*events):
    return "".join(
        "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
        for event in events
    )


def test_sse_decoder_preserves_interleaved_tool_thinking_and_usage():
    raw = decode_anthropic(
        sse(
            {
                "type": "message_start",
                "message": {
                    "id": "m",
                    "role": "assistant",
                    "content": [],
                    "usage": {"input_tokens": 123, "output_tokens": 0},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "first"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "c",
                    "name": "read_file",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '"note.txt"}'},
            },
            {"type": "content_block_stop", "index": 1},
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": "tool_use",
                    "stop_details": {"reason": "tool"},
                },
                "usage": {"output_tokens": 20},
            },
            {"type": "message_stop"},
        )
    )
    result = ingest_anthropic(raw)
    message = result["choices"][0]["message"]
    assert message["tool_calls"][0]["function"]["arguments"] == '{"path": "note.txt"}'
    assert [block["type"] for block in message["_anthropic_content_blocks"]] == [
        "thinking",
        "tool_use",
    ]
    assert message["stop_details"] == {"reason": "tool"}
    assert result["usage"]["prompt_tokens"] == 123
    assert result["usage"]["completion_tokens"] == 20


def test_sse_decoder_rejects_dropped_or_malformed_tool_stream():
    with pytest.raises(ValueError, match="before message_stop"):
        decode_anthropic(sse({"type": "message_start", "message": {"content": []}}))
    with pytest.raises(ValueError):
        decode_anthropic(
            sse(
                {"type": "message_start", "message": {"content": []}},
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "c",
                        "name": "read_file",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": "{bad}"},
                },
                {"type": "content_block_stop", "index": 0},
                {"type": "message_stop"},
            )
        )
