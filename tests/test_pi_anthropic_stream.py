"""Check every incremental Anthropic snapshot against original pinned Pi."""

import copy
import json
import math
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.anthropic_messages import (
    build_anthropic_payload,
)
from flashrsi.agents.pi_agent.runtime.pi_native.anthropic_stream import AnthropicStream
from flashrsi.agents.pi_agent.runtime.pi_native.compaction import js_json
from flashrsi.agents.pi_agent.runtime.pi_native.stream_json import (
    parse_streaming_json,
    parse_tool_arguments,
    repair_json,
)

ORACLE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "pi_anthropic_stream_upstream.json"
    ).read_text()
)


def initial_diagnostics(source):
    if not source.get("strictRejection"):
        return None
    error = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": source["strictRejection"],
        },
    }
    return [
        {
            "type": "anthropic_strict_tools_fallback",
            "timestamp": 0,
            "error": {"message": f"400 {js_json(error)}"},
            "details": {"reason": "strict_tool_limits_exceeded"},
        }
    ]


def replay(source):
    _, _, managed = build_anthropic_payload(
        source["config"], source["context"], source.get("reasoning")
    )
    stream = AnthropicStream(
        source["config"],
        source["context"],
        managed,
        diagnostics=initial_diagnostics(source),
    )
    events = stream.start()
    for index, event in enumerate(source["rawEvents"]):
        events.extend(stream.feed(copy.deepcopy(event)))
        if index == source.get("abortAfter"):
            events.extend(stream.abort("Request was aborted"))
            break
    canonical = stream.finish()
    events.extend(stream.drain())
    return stream, events, canonical


@pytest.mark.parametrize(
    "case", ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_pi_anthropic_incremental_events_match_original_synchronous_snapshots(case):
    _, actual, _ = replay(case["input"])
    assert actual == case["expected"]["events"]


@pytest.mark.parametrize(
    "case", ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_pi_anthropic_stream_canonical_reply_matches_original_source(case):
    stream, _, canonical = replay(case["input"])
    assert canonical == case["expected"]["reply"]
    assert stream.finish() == canonical
    assert stream.drain() == []
    assert stream.feed({"type": "message_stop"}) == []
    assert stream.abort() == []
    assert stream.fail("late error") == []


def as_json(value):
    # JSON.stringify maps the non-finite numeric values supported by partial-json
    # to null. Ordinary Pi snapshots are compared without any transformation.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [as_json(item) for item in value]
    if isinstance(value, dict):
        return {key: as_json(item) for key, item in value.items()}
    return value


@pytest.mark.parametrize(
    "case", ORACLE["jsonCases"], ids=lambda case: repr(case["input"])
)
def test_pi_stream_json_repair_partial_and_final_errors_match_original_source(case):
    value = case["input"]
    assert repair_json(value) == case["repaired"]
    assert as_json(parse_streaming_json(value)) == case["partial"]
    assert parse_tool_arguments(value) == case["final"]


def test_pi_anthropic_stream_stores_independent_partial_snapshots():
    case = ORACLE["cases"][0]
    stream, events, _ = replay(case["input"])
    assert events == stream.events
    assert events[0]["partial"]["content"] == []
    text_delta = next(event for event in events if event["type"] == "text_delta")
    assert text_delta["partial"]["content"][0]["text"] == "Hello "
    stream.message["content"][0]["text"] = "changed by consumer"
    assert text_delta["partial"]["content"][0]["text"] == "Hello "


def test_pi_anthropic_stream_oracle_pins_source_and_partial_json_dependency():
    assert ORACLE["baseline"] == "v1.4.0@4a080252f06caf63a525d7873c5d94d3c23887e0"
    assert ORACLE["partial_json"]["version"] == "0.1.7"
    assert "synchronous snapshots" in ORACLE["method"]
    assert all(case["expected"]["fetchCalls"] <= 2 for case in ORACLE["cases"])
