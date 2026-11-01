"""Offline differential tests against the original Pi OpenAI providers."""

import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.openai_options import (
    adjust_max_tokens_for_thinking,
    apply_compat_cache_control,
    apply_service_tier_pricing,
    completion_options,
    prompt_cache_options,
    session_headers,
    thinking_budget_for_level,
)

_ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_openai_options_upstream.json").read_text()
)


@pytest.mark.parametrize("case", _ORACLE["bodyCases"], ids=lambda case: case["name"])
def test_openai_options_match_original_provider(case):
    before = copy.deepcopy(case)
    if case.get("kind") == "cache":
        actual = prompt_cache_options(
            case["model"],
            case["compat"],
            case["api"],
            case["retention"],
            case["session_id"],
            api_key=case["api_key"],
        )
    else:
        actual = completion_options(
            case["model"],
            {
                "supportsReasoningEffort": True,
                "thinkingFormat": "openai",
                **case["compat"],
            },
            case["level"],
            case["ceiling"],
            case["thinking_budgets"],
        )
    assert actual == case["expected"]
    assert case == before


@pytest.mark.parametrize("case", _ORACLE["headerCases"], ids=lambda case: case["name"])
def test_affinity_headers_match_original_provider(case):
    assert (
        session_headers(case["compat"], case["api"], case["session_id"])
        == case["expected"]
    )


@pytest.mark.parametrize("case", _ORACLE["costCases"], ids=lambda case: case["name"])
def test_response_service_tier_cost_matches_original_provider(case):
    usage = copy.deepcopy(case["base_usage"])
    assert apply_service_tier_pricing(usage, case["model_id"], case["tier"]) is usage
    expected = case["expected"]
    assert usage["cost"] == pytest.approx(expected["cost"])
    assert {key: value for key, value in usage.items() if key != "cost"} == {
        key: value for key, value in expected.items() if key != "cost"
    }


@pytest.mark.parametrize(
    "case", _ORACLE["cacheControlCases"], ids=lambda case: case["name"]
)
def test_compatible_anthropic_cache_boundaries_match_original(case):
    payload = copy.deepcopy(case["before"])
    apply_compat_cache_control(payload, case["compat"], case["retention"])
    assert payload == case["expected"]


@pytest.mark.parametrize("case", _ORACLE["budgetCases"], ids=lambda case: case["name"])
def test_thinking_budgets_and_nonadaptive_ceiling_match_original(case):
    assert (
        thinking_budget_for_level(case["level"], case["budgets"])
        == case["expected_budget"]
    )
    assert (
        adjust_max_tokens_for_thinking(
            case["base"], case["model_max"], case["level"], case["budgets"]
        )
        == case["expected_adjust"]
    )


def test_prompt_cache_key_counts_codepoints_like_javascript_array_from():
    model = {"baseUrl": "https://api.openai.com/v1"}
    compat = {"supportsLongCacheRetention": True}
    session_id = "a" * 63 + "\ud83d\ude00" + "tail"
    assert prompt_cache_options(
        model, compat, "openai-completions", "short", session_id
    ) == {"prompt_cache_key": "a" * 63 + "😀"}
    assert (
        prompt_cache_options(model, compat, "openai-completions", "short", None) == {}
    )


def test_compat_cache_control_skips_empty_instruction_but_stops_at_first_one():
    payload = {
        "messages": [
            {"role": "system", "content": ""},
            {"role": "developer", "content": "later"},
            {"role": "user", "content": [{"type": "text", "text": ""}]},
        ]
    }
    apply_compat_cache_control(
        payload,
        {"cacheControlFormat": "anthropic", "supportsLongCacheRetention": False},
        "long",
    )
    assert payload["messages"][1]["content"] == "later"
    assert payload["messages"][2]["content"][0]["cache_control"] == {
        "type": "ephemeral"
    }


def test_openai_options_oracle_did_not_use_network_or_a_model():
    assert _ORACLE["networkCalls"] == 0
    assert _ORACLE["fakeTransportCalls"] == 23
    assert _ORACLE["baseline"] == ("v1.4.0@4a080252f06caf63a525d7873c5d94d3c23887e0")
