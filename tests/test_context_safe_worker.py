import asyncio
import json

from flashrsi.agents import LLM
from flashrsi.core import Trajectory
from scripts._context_safe_worker import ContextSafeLLM, strip_progress_events


def _prompt(kind="success"):
    progress = {
        "type": "SystemMessage",
        "subtype": "thinking_tokens",
        "data": {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 1},
    }
    thinking = {
        "type": "AssistantMessage",
        "content": [{"thinking": "Actual reasoning"}],
    }
    tool = {"type": "UserMessage", "content": [{"tool_use_result": "Skill content"}]}
    unusual = {**progress, "content": "Do not remove meaningful content"}
    item = {
        "task": {"question": "Q", "ground_truth": "A"},
        "output": "A",
        "metrics": {"hard": 1.0},
        "messages": [progress, thinking, tool, unusual],
    }
    value = (
        [item]
        if kind in ("success", "failure")
        else [{"previous": item, "current": item}]
    )
    marker = (
        "EVIDENCE (training tasks only):\n"
        if kind in ("success", "failure")
        else "COMPARISON: "
    )
    return f"[SkillOpt: {kind}]\n" + marker + json.dumps(value) + "\nUNTOUCHED SUFFIX"


def test_only_numeric_progress_events_removed_from_reflection_and_comparison():
    for kind in ("failure", "success", "meta", "slow"):
        original = _prompt(kind)
        cleaned, count = strip_progress_events(original)
        assert count == (1 if kind in ("failure", "success") else 2)
        assert "Actual reasoning" in cleaned and "Skill content" in cleaned
        assert "Do not remove meaningful content" in cleaned
        assert '"ground_truth": "A"' in cleaned and '"hard": 1.0' in cleaned
        assert cleaned.endswith("\nUNTOUCHED SUFFIX")
        assert strip_progress_events(cleaned) == (cleaned, 0)


def test_success_never_changes_or_reissues_prompt(monkeypatch):
    calls = []

    async def fake(self, prompt, working_dir=None):
        calls.append(prompt)
        return Trajectory(output="ok")

    monkeypatch.setattr(LLM, "_run", fake)
    worker = ContextSafeLLM({"llm": {"model_name": "offline"}})
    original = _prompt()
    assert asyncio.run(worker._run(original)).output == "ok"
    assert calls == [original]


def test_overflow_retries_once_and_records_actual_both_inputs(monkeypatch):
    calls = []

    async def fake(self, prompt, working_dir=None):
        calls.append(prompt)
        return Trajectory(
            status="error" if len(calls) == 1 else "finished",
            output="" if len(calls) == 1 else "patch",
            error_message="maximum context length exceeded"
            if len(calls) == 1
            else None,
            messages=({"type": "RunInput", "prompt": prompt},),
        )

    monkeypatch.setattr(LLM, "_run", fake)
    worker = ContextSafeLLM({"llm": {"model_name": "offline"}})
    original = _prompt()
    result = asyncio.run(worker._run(original))
    assert calls == [original, strip_progress_events(original)[0]]
    assert result.status == "finished" and result.error_message is None
    assert [m["type"] for m in result.messages] == [
        "RunInput",
        "ContextLengthRecovery",
        "RunInput",
    ]
    assert result.messages[1]["removed_events"] == 1


def test_other_errors_and_unknown_inputs_are_not_transformed(monkeypatch):
    calls = []

    async def fake(self, prompt, working_dir=None):
        calls.append(prompt)
        return Trajectory(status="error", error_message="HTTP 429")

    monkeypatch.setattr(LLM, "_run", fake)
    worker = ContextSafeLLM({"llm": {"model_name": "offline"}})
    original = _prompt()
    assert asyncio.run(worker._run(original)).status == "error"
    assert calls == [original]
    assert strip_progress_events("Unstructured text") == ("Unstructured text", 0)
