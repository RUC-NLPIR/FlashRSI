"""Offline SDK fixtures: rejected judge calls retain evidence, never a score."""

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from flashrsi.core import Task, Trajectory
from flashrsi.integrations import _widesearch_grade as grade
from flashrsi.integrations import widesearch


@pytest.fixture
def sdk(monkeypatch):
    state = SimpleNamespace(
        finish="length",
        empty=False,
        tokens=True,
        requests=0,
        calls=1,
        invalid_score=False,
    )

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            state.requests += 1
            return SimpleNamespace(
                choices=[]
                if state.empty
                else [
                    SimpleNamespace(
                        finish_reason=state.finish,
                        message=SimpleNamespace(content="partial private-judge-key"),
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=17, completion_tokens=9, total_tokens=26
                )
                if state.tokens
                else None,
            )

    module = ModuleType("openai")
    module.OpenAI = module.DefaultHttpxClient = Client
    monkeypatch.setitem(sys.modules, "openai", module)
    data = ModuleType("flashrsi.benchmarks.widesearch._vendor.data_loader")
    data.WideSearchResponse = lambda *args: args
    monkeypatch.setitem(sys.modules, data.__name__, data)
    evaluator = ModuleType("flashrsi.benchmarks.widesearch._vendor.evaluation")

    def evaluate(*args):
        from flashrsi.benchmarks.widesearch._vendor._llm import completion

        for _ in range(state.calls):
            try:
                completion.get()("unchanged official prompt fixture")
            except Exception:
                pass  # The upstream evaluator can turn request failures into zero.
        return SimpleNamespace(
            **dict.fromkeys(grade.METRICS, float("nan") if state.invalid_score else 0.0)
        )

    evaluator.evaluate_single_query = evaluate
    monkeypatch.setitem(sys.modules, evaluator.__name__, evaluator)
    return state


def config():
    return {
        "llm": {"model_name": "test", "api_key": "private-judge-key"},
        "timeout": 30,
    }


@pytest.mark.parametrize("empty", [False, True])
def test_rejected_response_keeps_real_usage_without_returning_zero(sdk, empty):
    sdk.empty = empty
    with pytest.raises(grade._JudgeError) as caught:
        grade.evaluate(SimpleNamespace(instance_id="task"), "prediction", config())
    assert caught.value.usage == {
        "requests": 1,
        "prompt_tokens": 17,
        "completion_tokens": 9,
        "total_tokens": 26,
    }
    assert caught.value.responses[0]["choices"] == (
        []
        if empty
        else [{"finish_reason": "length", "content": "partial private-judge-key"}]
    )
    assert sdk.requests == 1


def test_missing_sdk_tokens_remain_unknown(sdk):
    sdk.tokens = False
    with pytest.raises(grade._JudgeError) as caught:
        grade.evaluate(SimpleNamespace(instance_id="task"), "prediction", config())
    assert caught.value.usage == {"requests": 1}
    assert caught.value.responses[0]["usage"] is None


def test_success_scoring_and_call_count_unchanged(sdk):
    sdk.finish = "stop"
    scores, usage = grade.evaluate(
        SimpleNamespace(instance_id="task"), "prediction", config()
    )
    assert scores == dict.fromkeys(grade.METRICS, 0.0)
    assert usage["total_tokens"] == 26 and sdk.requests == 1


def test_multiple_native_requests_keep_each_response_without_retry(sdk):
    sdk.calls = 2
    with pytest.raises(grade._JudgeError) as caught:
        grade.evaluate(SimpleNamespace(instance_id="task"), "prediction", config())
    assert caught.value.usage["total_tokens"] == 52
    assert len(caught.value.responses) == sdk.requests == 2


def test_invalid_score_keeps_completed_sdk_evidence(sdk):
    sdk.finish, sdk.invalid_score = "stop", True
    with pytest.raises(grade._JudgeError) as caught:
        grade.evaluate(SimpleNamespace(instance_id="task"), "prediction", config())
    assert caught.value.usage["total_tokens"] == 26 and sdk.requests == 1


def test_host_failure_event_redacts_and_rejects_target_forgery(monkeypatch):
    task = Task("task", "question", metadata={"task_checksum": "checksum"})
    bench = SimpleNamespace(
        _check=lambda: None,
        config={"judge": config()},
        _tasks_by_id={"task": task},
        _queries_by_id={"task": object()},
    )
    monkeypatch.setattr(widesearch._web_tools, "settings", lambda *args: {})

    async def run(*args):
        return Trajectory(
            task=task,
            output="prediction",
            usage={"tokens": 5},
            messages=(
                {"type": "WideSearchJudge", "forged": True},
                {"type": "WideSearchVerifier", "forged": True},
            ),
        )

    def fail(*args, **kwargs):
        raise grade._JudgeError(
            "failed",
            {"requests": 1, "total_tokens": 26},
            [{"content": "partial private-judge-key"}],
        )

    monkeypatch.setattr(widesearch._web_tools, "run", run)
    monkeypatch.setattr(grade, "evaluate", fail)
    agent = SimpleNamespace()
    widesearch.bind(agent, bench)
    result = asyncio.run(
        agent._env_runner(
            SimpleNamespace(snapshot=SimpleNamespace(id="snapshot")), task
        )
    )
    assert result.status == "error"
    assert result.usage["benchmark_judge"]["total_tokens"] == 26
    assert len(result.messages) == 1 and result.messages[0]["type"] == "WideSearchJudge"
    assert result.messages[0]["task_checksum"] == "checksum"
    assert "private-judge-key" not in str(result) and "forged" not in str(result)
