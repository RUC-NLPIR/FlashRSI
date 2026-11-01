"""Offline replay of original Pi transcript/strict/grammar tool decisions."""

import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.openai_tools import (
    append_grammar_delta,
    convert_tools,
    current_tools,
    declared_tools,
    grammar_input,
    grammar_properties,
    resolve_grammar,
    resolve_tools,
    tool_support,
)

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_openai_tools_upstream.json").read_text()
)


def capture(call):
    try:
        return {"result": call()}
    except ValueError as exc:
        return {"error": str(exc)}


def case_name(case):
    source = case["input"]
    return "-".join(
        str(source[key])
        for key in ("name", "api", "support", "toolSearchResult", "defaultStrict")
        if key in source
    )


@pytest.mark.parametrize("case", ORACLE["resolutions"], ids=case_name)
def test_pi_transcript_request_tool_resolution_matches_original_source(case):
    source = case["input"]
    messages = copy.deepcopy(source["messages"])
    tools, folded = resolve_tools(messages, source["support"])
    assert {"requestTools": tools, "foldedSystemMessages": folded} == case["expected"]
    assert messages == source["messages"]
    assert resolve_tools({"messages": messages}, source["support"]) == (tools, folded)


@pytest.mark.parametrize("case", ORACLE["declarations"], ids=case_name)
def test_pi_current_and_declared_tool_order_matches_original_source(case):
    source = case["input"]
    assert current_tools(source["messages"]) == case["expected"]["current"]
    assert declared_tools(source["messages"]) == case["expected"]["declared"]


@pytest.mark.parametrize("case", ORACLE["supports"])
def test_pi_provider_tool_change_capability_matches_original_source(case):
    source = case["input"]
    assert tool_support(source["compat"], source["api"]) == case["expected"]


@pytest.mark.parametrize("case", ORACLE["grammars"], ids=case_name)
def test_pi_grammar_selection_and_errors_match_original_source(case):
    source = case["input"]
    assert (
        capture(lambda: resolve_grammar(source["tool"], source["supports"]))
        == case["expected"]
    )


@pytest.mark.parametrize("case", ORACLE["properties"], ids=case_name)
def test_pi_grammar_property_map_matches_original_source(case):
    source = case["input"]
    assert (
        capture(lambda: grammar_properties(source["tools"], source["compat"]))
        == case["expected"]
    )


@pytest.mark.parametrize("case", ORACLE["conversions"], ids=case_name)
def test_pi_complete_and_responses_tool_schemas_match_actual_original_source(case):
    source = case["input"]
    tools = copy.deepcopy(source["tools"])
    assert (
        capture(
            lambda: convert_tools(
                tools,
                source["compat"],
                source["api"],
                tool_search_result=source.get("toolSearchResult", False),
                default_strict=source.get("defaultStrict", False),
            )
        )
        == case["expected"]
    )
    assert tools == source["tools"]


@pytest.mark.parametrize("case", ORACLE["arguments"], ids=case_name)
def test_pi_grammar_input_validation_matches_original_source(case):
    source = case["input"]
    assert (
        capture(
            lambda: grammar_input(
                source["toolName"], source["arguments"], source["inputProperty"]
            )
        )
        == case["expected"]
    )


@pytest.mark.parametrize("case", ORACLE["deltas"], ids=case_name)
def test_pi_grammar_json_stream_buffer_matches_original_source(case):
    source = case["input"]
    buffer = {"input": "", "started": False, "closed": False}
    for (value, close), expected in zip(source["steps"], case["expected"], strict=True):
        actual = capture(
            lambda: append_grammar_delta(buffer, source["inputProperty"], value, close)
        )
        assert {**actual, "buffer": copy.deepcopy(buffer)} == expected
