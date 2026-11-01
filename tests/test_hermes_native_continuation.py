"""Stateful Responses recovery against executed pinned upstream helpers."""

import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from flashrsi.agents.hermes.runtime.hermes_native.native_continuation import (
    ContinuationState,
)
from flashrsi.agents.hermes.runtime.hermes_native.upstream_compaction import (
    message_metadata,
)

EVIDENCE = json.loads(
    (
        Path(__file__).parent / "fixtures/hermes_native_continuation_upstream.json"
    ).read_text()
)


@pytest.mark.parametrize("case", EVIDENCE["cases"], ids=lambda case: case["name"])
def test_stateful_continuation_matches_original_complete_trace(case, monkeypatch):
    monkeypatch.setattr(
        message_metadata, "wall_time", lambda: EVIDENCE["fixed_wall_time"]
    )
    state = ContinuationState(**case["initial_state"])
    messages = copy.deepcopy(case["initial_messages"])
    original_inputs = copy.deepcopy(case["steps"])
    for index, (request, expected) in enumerate(zip(case["steps"], case["trace"]), 1):
        verdict = state.step(
            messages,
            request["assistant"],
            configured_cap=case["configured_cap"],
            usage=request["usage"],
            response_status=request["response_status"],
            incomplete_reason=request["incomplete_reason"],
            api_call_count=index,
        )
        assert {
            **asdict(verdict),
            "messages": messages,
            "state": asdict(state),
        } == expected
    assert case["steps"] == original_inputs


def test_reset_starts_a_new_turn_without_spent_streak():
    state = ContinuationState(incomplete_retries=2, reasoning_only_streak=2)
    state.reset()
    messages = [{"role": "user", "content": "A new turn"}]
    verdict = state.step(messages, {"content": "Working on the new request."})
    assert verdict.continue_turn
    assert state.incomplete_retries == 1
    assert state.reasoning_only_streak == 0
    assert messages[-1]["role"] == "assistant"


def test_budget_overrides_do_not_survive_next_nonbudget_attempt():
    state = ContinuationState()
    messages = [{"role": "user", "content": "Finish"}]
    assistant = {"content": "", "reasoning": "Private reasoning"}
    exhausted = state.step(
        messages,
        assistant,
        configured_cap=2000,
        response_status="incomplete",
        incomplete_reason="max_output_tokens",
        usage={"output_tokens": 2000},
    )
    assert exhausted.reasoning_off and exhausted.max_output_tokens == 4000
    next_attempt = state.step(messages, assistant, configured_cap=2000)
    assert next_attempt.continue_turn
    assert not next_attempt.reasoning_off
    assert next_attempt.max_output_tokens is None
