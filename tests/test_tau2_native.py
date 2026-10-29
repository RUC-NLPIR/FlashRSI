"""Opt-in native-runtime tests: pinned tau2 installed and TAU2_DATA_DIR prepared.

Only model replies are scripted. The official orchestrator, user simulator,
tools, dual-control environment and reward evaluators run unchanged.
"""

import asyncio
import importlib.metadata
import json
import os
from pathlib import Path

import pytest

from flashrsi.agents import MiniAgent
from flashrsi.benchmarks import Tau2Benchmark, Tau3Banking
from flashrsi.core import Trajectory


@pytest.fixture
def native(monkeypatch):
    pytest.importorskip("tau2")
    if importlib.metadata.version("tau2") != "1.0.1":
        pytest.skip("Native tests require pinned tau2 v1.0.1")
    root = Path(os.environ.get("TAU2_DATA_DIR", "missing-tau2-data"))
    if not (root / "tau2/domains/telecom/tasks.json").is_file():
        pytest.skip("Set TAU2_DATA_DIR to pinned upstream data/")
    from flashrsi.integrations import tau2

    def no_network(*args, **kwargs):
        pytest.fail("Offline native validation must not call a model")

    monkeypatch.setattr("litellm.completion", no_network)
    return tau2, root / "tau2/domains"


def scripted_target(monkeypatch, outputs, prompts):
    responses = iter(outputs)

    async def reply(self, prompt, working_dir=None):
        prompts.append(prompt)
        return Trajectory(
            output=next(responses), usage={"input_tokens": 1, "output_tokens": 1}
        )

    monkeypatch.setattr(MiniAgent, "_run", reply)
    return MiniAgent(
        {
            "llm": {"model_name": "fixture-target", "api_key": "target-secret"},
            "max_steps": 20,
        }
    )


@pytest.mark.parametrize(
    "domain,counts",
    [("airline", (30, 20)), ("retail", (74, 40)), ("telecom", (74, 40))],
)
def test_native_data_policy_and_schema(native, domain, counts):
    bridge, root = native
    bench = Tau2Benchmark(
        {
            "domain": domain,
            "data_path": str(root / domain),
            "judge": {"llm": {"model_name": "fixture-judge"}},
        }
    )
    bench.load()
    assert (len(bench.train), len(bench.test)) == counts
    from tau2.data_model.tasks import Task as NativeTask
    from tau2.registry import registry

    with bridge._domain_paths(root / domain, domain):
        environment = registry.get_env_constructor(domain)()
        assert environment.get_policy() == bench.train[0].question
        assert bool(environment.user_tools) == (domain == "telecom")
    assert (
        bridge._native_task(root / domain, bench.train[0]).id == bench.train[0].task_id
    )
    selected = {t.task_id for t in (*bench.train, *bench.test)}
    rows = json.loads((root / domain / "tasks.json").read_text(encoding="utf-8"))
    assert sum(NativeTask.model_validate(row).id in selected for row in rows) == sum(
        counts
    )


@pytest.mark.parametrize("toggle,expected", [(True, 1.0), (False, 0.0)])
def test_native_dual_control_and_reward(native, monkeypatch, toggle, expected):
    bridge, root = native
    from tau2.data_model.message import AssistantMessage, ToolCall
    from tau2.user import user_simulator
    from tau2.user.user_simulator_base import STOP

    bench = Tau2Benchmark(
        {"domain": "telecom", "data_path": str(root / "telecom"), "seed": 42}
    )
    bench.load()
    task = next(
        t
        for t in (*bench.train, *bench.test)
        if t.task_id
        == "[mobile_data_issue]airplane_mode_on|user_abroad_roaming_enabled_off[PERSONA:None]"
    )
    responses = [
        AssistantMessage(
            role="assistant",
            content="I am abroad; my phone is 555-123-2002 and mobile data is not working.",
        )
    ]
    if toggle:
        responses.append(
            AssistantMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="user-airplane",
                        name="toggle_airplane_mode",
                        arguments={},
                        requestor="assistant",
                    ),
                    ToolCall(
                        id="user-roaming",
                        name="toggle_roaming",
                        arguments={},
                        requestor="assistant",
                    ),
                ],
            )
        )
    responses.append(AssistantMessage(role="assistant", content=STOP))
    user_outputs = iter(responses)
    user_calls = []

    def user_reply(**kwargs):
        user_calls.append(kwargs)
        return next(user_outputs)

    monkeypatch.setattr(user_simulator, "generate", user_reply)
    prompts = []
    agent = scripted_target(
        monkeypatch,
        [
            'TOOL: {"name":"get_customer_by_phone","arguments":{"phone_number":"555-123-2002"}}',
            "Please turn on data roaming on your phone.",
        ],
        prompts,
    )
    bridge.bind(
        agent,
        {
            "llm": {
                "model_name": "fixture-user",
                "api_key": "user-secret",
                "base_url": "https://user.invalid/v1",
                "temperature": 0.3,
            }
        },
    )
    trajectory = bench.grade(asyncio.run(agent.rollout((task,))))[0]
    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.metrics == {"reward": expected}
    event = trajectory.messages[-1]
    assert event["reward_info"]["reward"] == expected
    assert "C1001" in prompts[-1]  # Actual customer lookup result reaches the agent.
    assert "initialization_actions" not in prompts[0]
    assert "assert_internet_speed" not in prompts[0]
    assert all(
        call["model"] == "openai/fixture-user" and call["temperature"] == 0.3
        for call in user_calls
    )
    assert all(
        any(t.name == "toggle_roaming" for t in call["tools"]) for call in user_calls
    )
    assert "user-secret" not in str(trajectory.messages)
    assert "target-secret" not in str(trajectory.messages)


def test_native_airline_refusal_and_bank_path_restore(native, monkeypatch):
    bridge, root = native
    from tau2.data_model.message import AssistantMessage
    from tau2.domains.banking_knowledge import utils
    from tau2.user import user_simulator
    from tau2.user.user_simulator_base import STOP

    original = utils.KNOWLEDGE_DATA_DIR
    with bridge._domain_paths(root / "banking_knowledge"):
        assert utils.KNOWLEDGE_DATA_DIR == root / "banking_knowledge"
    assert utils.KNOWLEDGE_DATA_DIR == original
    bank = Tau3Banking(
        {
            "data_path": str(root / "banking_knowledge"),
            "split_counts": {"train": 1, "dev": 1, "test": 1},
        }
    )
    bank.load()
    assert (
        bridge._native_task(root / "banking_knowledge", bank.test[0]).id
        == bank.test[0].task_id
    )
    assert bank.metadata["variant"] == "alltools"
    bench = Tau2Benchmark({"domain": "airline", "data_path": str(root / "airline")})
    bench.load()
    task = next(t for t in (*bench.train, *bench.test) if t.task_id == "0")
    responses = iter(["Please cancel my booking.", STOP])
    monkeypatch.setattr(
        user_simulator,
        "generate",
        lambda **kwargs: AssistantMessage(role="assistant", content=next(responses)),
    )
    agent = scripted_target(
        monkeypatch, ["This booking cannot be cancelled with a refund."], []
    )
    bridge.bind(agent, {"llm": {"model_name": "fixture-user"}})
    trajectory = bench.grade(asyncio.run(agent.rollout((task,))))[0]
    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.metrics == {"reward": 1.0}


@pytest.mark.parametrize("accepted", [True, False])
def test_native_retail_episode_uses_own_judge(native, monkeypatch, accepted):
    bridge, root = native
    from tau2.data_model.message import AssistantMessage
    from tau2.evaluator import evaluator_nl_assertions as evaluator
    from tau2.user import user_simulator
    from tau2.user.user_simulator_base import STOP

    bench = Tau2Benchmark(
        {
            "domain": "retail",
            "data_path": str(root / "retail"),
            "judge": {"llm": {"model_name": "own-judge"}},
        }
    )
    bench.load()
    task = next(t for t in (*bench.train, *bench.test) if t.task_id == "24")
    responses = iter(["What are the materials of the two t-shirts?", STOP])
    monkeypatch.setattr(
        user_simulator,
        "generate",
        lambda **kwargs: AssistantMessage(role="assistant", content=next(responses)),
    )
    calls = []
    old_model = evaluator.DEFAULT_LLM_NL_ASSERTIONS

    def judge_reply(**kwargs):
        calls.append(kwargs)
        return AssistantMessage(
            role="assistant",
            content=json.dumps(
                {
                    "results": [
                        {
                            "expectedOutcome": "The two materials are polyester and cotton.",
                            "metExpectation": accepted,
                            "reasoning": "scripted judge result",
                        }
                    ]
                }
            ),
        )

    monkeypatch.setattr(evaluator, "generate", judge_reply)
    agent = scripted_target(
        monkeypatch, ["The materials are polyester and cotton."], []
    )
    bridge.bind(
        agent,
        {"llm": {"model_name": "fixture-user"}},
        judge={
            "llm": {
                "model_name": "own-judge",
                "base_url": "https://judge.invalid/v1",
                "api_key": "judge-secret",
            }
        },
    )
    trajectory = bench.grade(asyncio.run(agent.rollout((task,))))[0]
    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.metrics == {"reward": float(accepted)}
    assert len(calls) == 1
    assert calls[0]["model"] == "openai/own-judge"
    assert calls[0]["api_base"] == "https://judge.invalid/v1"
    assert calls[0]["api_key"] == "judge-secret"
    assert "polyester and cotton" in str(calls[0]["messages"])
    assert "judge-secret" not in str(trajectory.messages)
    assert evaluator.DEFAULT_LLM_NL_ASSERTIONS == old_model


def test_judge_routing_restoration_and_task_mutation(native, monkeypatch, tmp_path):
    bridge, root = native
    from tau2.data_model.message import AssistantMessage
    from tau2.data_model.tasks import Task as NativeTask
    from tau2.evaluator import evaluator_nl_assertions as evaluator

    old_model, old_args = (
        evaluator.DEFAULT_LLM_NL_ASSERTIONS,
        evaluator.DEFAULT_LLM_NL_ASSERTIONS_ARGS,
    )
    calls = []

    def judge_reply(**kwargs):
        calls.append(kwargs)
        return AssistantMessage(
            role="assistant",
            content=json.dumps(
                {
                    "results": [
                        {
                            "expectedOutcome": "criterion",
                            "metExpectation": False,
                            "reasoning": "fixture",
                        }
                    ]
                }
            ),
        )

    monkeypatch.setattr(evaluator, "generate", judge_reply)
    with (
        bridge._SIMULATION_LOCK,
        bridge._judge_settings(
            {
                "model_name": "own-judge",
                "base_url": "https://judge.invalid/v1",
                "api_key": "judge-secret",
                "temperature": 0.2,
            }
        ),
    ):
        row = next(
            r
            for r in json.loads(
                (root / "retail/tasks.json").read_text(encoding="utf-8")
            )
            if r["evaluation_criteria"].get("nl_assertions")
        )
        result = evaluator.NLAssertionsEvaluator.calculate_reward(
            NativeTask.model_validate(row), []
        )
        assert result.reward == 0
    assert (
        calls[0]["model"] == "openai/own-judge"
        and calls[0]["api_base"] == "https://judge.invalid/v1"
    )
    assert calls[0]["api_key"] == "judge-secret"
    assert evaluator.DEFAULT_LLM_NL_ASSERTIONS == old_model
    assert evaluator.DEFAULT_LLM_NL_ASSERTIONS_ARGS is old_args
    from dataclasses import replace

    bench = Tau2Benchmark({"domain": "airline", "data_path": str(root / "airline")})
    bench.load()
    (tmp_path / "tasks.json").write_text("[]")
    task = replace(bench.test[0], env=str(tmp_path))
    with pytest.raises(ValueError, match="changed after"):
        bridge._native_task(tmp_path, task)
