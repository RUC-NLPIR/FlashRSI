"""Failed native extraction must retain its completed converter call evidence."""

import asyncio
import json
import sys
import tempfile
from types import ModuleType, SimpleNamespace

import pytest

from flashrsi.core import Task, Trajectory
from flashrsi.integrations import _travelplanner_postprocess as converter
from flashrsi.integrations import travelplanner


@pytest.fixture
def sdk(monkeypatch):
    state = SimpleNamespace(
        reply="unfenced reply",
        finish="stop",
        requests=[],
        usage_data={"prompt_tokens": 17, "completion_tokens": 9},
    )

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def create(self, **kwargs):
            state.requests.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=state.finish,
                        message=SimpleNamespace(content=state.reply),
                    )
                ],
                usage=(
                    SimpleNamespace(model_dump=lambda **kwargs: state.usage_data)
                    if state.usage_data is not None
                    else None
                ),
            )

    module = ModuleType("openai")
    module.AsyncOpenAI = Client
    monkeypatch.setitem(sys.modules, "openai", module)
    return state


def config():
    return {
        "llm": {"model_name": "test-model", "api_key": "private-converter-key"},
        "timeout": 30,
        "max_retries": 0,
    }


@pytest.mark.parametrize(
    "reply,finish",
    [
        ("unfenced reply", "stop"),
        ('```json\n[{"current_city": "City"}]\n```', "stop"),
        ("partial converter response", "length"),
    ],
)
def test_native_extraction_failure_keeps_response_and_usage(sdk, reply, finish):
    sdk.reply, sdk.finish = reply, finish
    with pytest.raises(converter._ConversionError) as caught:
        asyncio.run(converter.convert("solver output", config()))
    assert caught.value.reply == reply
    assert caught.value.usage == {
        "prompt_tokens": 17,
        "completion_tokens": 9,
        "requests": 1,
    }
    assert len(sdk.requests) == 1


def test_valid_plan_and_native_prompt_unchanged(sdk):
    plan = [
        dict.fromkeys(
            [
                "current_city",
                "transportation",
                "breakfast",
                "attraction",
                "lunch",
                "dinner",
                "accommodation",
            ],
            "-",
        )
    ]
    sdk.reply = "```json\n" + json.dumps(plan) + "\n```"
    parsed, usage = asyncio.run(converter.convert("solver output", config()))
    assert parsed == plan and usage["requests"] == 1
    assert sdk.requests[0]["messages"][1]["content"] == (
        converter.CONVERSION_PREFIX + "Text:\nsolver output\nJSON:\n"
    )
    # Only the Markdown wrapper differs; the plan and native prompt are equal.
    sdk.reply = json.dumps(plan)
    parsed_bare, _ = asyncio.run(converter.convert("solver output", config()))
    assert parsed_bare == parsed


@pytest.mark.parametrize(
    "reply",
    [
        "Here is the plan: []",
        "[] trailing explanation",
        "[] []",
        '{"plan": []}',
        '[{"current_city": "City"}]',
        "```python\n[]\n```",
        "[",
    ],
)
def test_json_compatibility_does_not_repair_or_extract_plans(sdk, reply):
    sdk.reply = reply
    with pytest.raises(converter._ConversionError) as caught:
        asyncio.run(converter.convert("solver output", config()))
    assert caught.value.reply == reply
    assert caught.value.usage["requests"] == 1


def test_complete_json_is_still_rejected_when_api_reports_truncation(sdk):
    sdk.reply, sdk.finish = "[]", "length"
    with pytest.raises(converter._ConversionError, match="Incomplete"):
        asyncio.run(converter.convert("solver output", config()))


def test_missing_sdk_tokens_are_not_invented(sdk):
    sdk.usage_data = None
    with pytest.raises(converter._ConversionError) as caught:
        asyncio.run(converter.convert("solver output", config()))
    assert caught.value.usage == {"requests": 1}


@pytest.mark.parametrize("failure_phase", ["conversion", "scoring"])
def test_binding_keeps_usage_and_redacts_failed_conversion(
    sdk, tmp_path, monkeypatch, failure_phase
):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(
        travelplanner.importlib.util, "find_spec", lambda name: object()
    )
    monkeypatch.setattr(
        travelplanner._travelplanner_grade, "check_database", lambda p: "db"
    )
    task = Task("task", "question", metadata={"task_checksum": "checksum"})
    benchmark = SimpleNamespace(
        config={"postprocess": config(), "database_path": str(tmp_path)},
        metadata={},
        _tasks_by_id={task.task_id: task},
        _rows_by_id={task.task_id: {}},
    )
    agent = SimpleNamespace()
    sdk.reply = "unfenced reply private-converter-key"
    if failure_phase == "scoring":
        sdk.reply = "```json\n[]\n```"

    async def evaluate(*args):
        assert failure_phase == "scoring", "Invalid extraction must not reach scoring"
        raise RuntimeError("private-converter-key")

    monkeypatch.setattr(travelplanner, "_evaluate", evaluate)

    async def run(*args, **kwargs):
        return Trajectory(
            task=task,
            output="solver output",
            usage={"prompt_tokens": 5},
            messages=({"type": "TravelPlannerConversion", "output": "forged"},),
        )

    target = SimpleNamespace(run=run)
    travelplanner.bind(agent, benchmark)
    result = asyncio.run(agent._env_runner(target, task))
    assert result.status == "error" and failure_phase in result.error_message
    assert result.usage["benchmark_postprocess"]["prompt_tokens"] == 17
    assert result.usage["benchmark_postprocess"]["requests"] == 1
    assert "private-converter-key" not in str(result)
    assert not any(m.get("output") == "forged" for m in result.messages)
    assert not any(m.get("type") == "TravelPlannerVerifier" for m in result.messages)
    if failure_phase == "conversion":
        assert result.messages[-1]["type"] == "TravelPlannerConversion"
        assert "unfenced reply" in result.messages[-1]["output"]
