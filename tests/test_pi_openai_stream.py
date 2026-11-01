"""Original emitted SSE lifecycle and replay data against the Python parser."""

import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.compaction import _model_catalog
from flashrsi.agents.pi_agent.runtime.pi_native.openai_stream import OpenAIStream

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_openai_stream_upstream.json").read_text()
)


@pytest.mark.parametrize(
    "case", ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_openai_incremental_events_and_final_message_match_original_source(
    case, monkeypatch
):
    source = case["input"]
    cfg = copy.deepcopy(source["config"])
    monkeypatch.setitem(_model_catalog(), cfg["llm"]["model_name"], source["model"])
    parser = OpenAIStream(
        cfg, source["api"], source["context"], source.get("managed_effort")
    )
    events = parser.start()
    for event in source["wire"]:
        events.extend(parser.feed(copy.deepcopy(event)))
    if source.get("abort"):
        events.extend(parser.abort(case["expected"]["message"]["errorMessage"]))
    elif source.get("fail"):
        events.extend(parser.fail(source["fail"]))
    message = parser.finish()
    events.extend(parser.drain())
    assert events == case["expected"]["events"]
    assert message == case["expected"]["message"]
    assert parser.events == events
    assert parser.feed({}) == []
    assert parser.finish() == message
    assert parser.drain() == []


def test_openai_stream_event_snapshots_are_independent_of_future_mutation():
    cfg = {"llm": {"model_name": "openai/gpt-5", "api_key": "sk-offline-fixture"}}
    parser = OpenAIStream(cfg, "openai-completions", [])
    events = parser.feed({"choices": [{"delta": {"content": "first"}}]})
    assert events[1]["partial"]["content"] == [{"type": "text", "text": ""}]
    parser.feed(
        {"choices": [{"delta": {"content": " second"}, "finish_reason": "stop"}]}
    )
    parser.finish()
    assert events[-1]["partial"]["content"] == [{"type": "text", "text": "first"}]


def test_openai_stream_oracle_never_used_network_or_a_model():
    assert ORACLE["networkCalls"] == 0
    assert ORACLE["fakeFetchCalls"] == len(ORACLE["cases"])
    assert ORACLE["baseline"] == "v1.4.0@4a080252f06caf63a525d7873c5d94d3c23887e0"
