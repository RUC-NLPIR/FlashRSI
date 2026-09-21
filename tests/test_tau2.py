"""Check the tau2 simulator boundary without remote model calls."""

import asyncio
import dataclasses
import hashlib
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("tau2")

from tau2.data_model.message import (  # noqa: E402
    AssistantMessage,
    ToolMessage,
    UserMessage,
)

from flashrsi.benchmarks import Tau3Banking  # noqa: E402
from flashrsi.core import Trajectory  # noqa: E402
from flashrsi.integrations import tau2  # noqa: E402


class _Agent:
    """A stand-in Agent that records prompts and replays scripted replies."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.config = {"max_steps": 7}
        self.snapshot = SimpleNamespace(id="snapshot-1")

    async def run(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Trajectory):
            return reply
        return Trajectory(status="finished", output=reply)


def _domain(root):
    domain = root / "data" / "tau2" / "domains" / "banking_knowledge"
    (domain / "tasks").mkdir(parents=True)
    (domain / "db.json").write_text("{}")
    (domain / "tasks" / "task_001.json").write_text(
        json.dumps({"id": "task_001", "user_scenario": {"instructions": "Ask."}})
    )
    return domain


def _task(domain):
    path = domain / "tasks" / "task_001.json"
    return SimpleNamespace(
        task_id="task_001",
        env=str(domain),
        metadata={
            "task_checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
            "task_path": "tasks/task_001.json",
            "variant": "grep_only",
        },
    )


def _tool(name="grep"):
    return SimpleNamespace(name=name, to_str=lambda: f"def {name}(pattern: str) -> str")


def _bridge(agent, tools=(), policy="POLICY"):
    """Build the bridge with a live loop, as _simulate does."""
    loop = asyncio.new_event_loop()
    thread = __import__("threading").Thread(target=loop.run_forever, daemon=True)
    thread.start()
    bridge = tau2._AgentBridge(list(tools), policy, agent=agent, loop=loop)
    return bridge, (loop, thread)


def _close(handle):
    loop, thread = handle
    loop.call_soon_threadsafe(loop.stop)
    thread.join()
    loop.close()


def test_prompt_carries_the_policy_tools_protocol_and_conversation():
    agent = _Agent("Hello, how can I help?")
    bridge, handle = _bridge(agent, tools=[_tool(), _tool("get_current_time")])
    try:
        reply, state = bridge.generate_next_message(
            UserMessage(role="user", content="My card was declined."), []
        )
    finally:
        _close(handle)

    (prompt,) = agent.prompts
    assert prompt.startswith("POLICY")
    assert "def grep(pattern: str) -> str" in prompt
    assert "def get_current_time" in prompt
    assert tau2._PREFIX in prompt
    assert "user: My card was declined." in prompt
    # The reply is spoken, and both turns are kept for the next call.
    assert reply.content == "Hello, how can I help?"
    assert reply.tool_calls is None
    assert len(state) == 2


def test_a_tool_line_becomes_a_tau2_tool_call():
    agent = _Agent('TOOL: {"name": "grep", "arguments": {"pattern": "fees"}}')
    bridge, handle = _bridge(agent, tools=[_tool()])
    try:
        reply, _ = bridge.generate_next_message(
            UserMessage(role="user", content="?"), []
        )
    finally:
        _close(handle)

    (call,) = reply.tool_calls
    assert call.name == "grep"
    assert call.arguments == {"pattern": "fees"}
    assert call.requestor == "assistant"
    assert reply.content is None


def test_a_malformed_tool_line_is_reported_rather_than_spoken_silently():
    agent = _Agent("TOOL: {not json")
    bridge, handle = _bridge(agent)
    try:
        reply, _ = bridge.generate_next_message(
            UserMessage(role="user", content="?"), []
        )
    finally:
        _close(handle)

    assert reply.tool_calls is None
    assert "unparsable tool call" in reply.content
    assert "{not json" in reply.content


def test_tool_results_and_prior_calls_reach_the_next_prompt():
    agent = _Agent('TOOL: {"name": "grep", "arguments": {"pattern": "x"}}', "Found it.")
    bridge, handle = _bridge(agent, tools=[_tool()])
    try:
        first, state = bridge.generate_next_message(
            UserMessage(role="user", content="Search."), []
        )
        bridge.generate_next_message(
            ToolMessage(
                id=first.tool_calls[0].id,
                role="tool",
                content="matched line",
                requestor="assistant",
            ),
            state,
        )
    finally:
        _close(handle)

    second = agent.prompts[1]
    assert "matched line" in second
    # The agent sees its own earlier call, so it does not repeat it blindly.
    assert '"name": "grep"' in second


def test_a_failed_agent_run_stops_the_simulation():
    agent = _Agent(
        Trajectory(status="error", output="", error_message="backend unavailable")
    )
    bridge, handle = _bridge(agent)
    try:
        with pytest.raises(RuntimeError, match="backend unavailable"):
            bridge.generate_next_message(UserMessage(role="user", content="?"), [])
    finally:
        _close(handle)


def test_reward_becomes_a_graded_trajectory(tmp_path, monkeypatch):
    domain = _domain(tmp_path)
    task = _task(domain)
    seen = {}

    def simulate(config, native):
        seen["config"] = config
        seen["data_dir"] = __import__("os").environ["TAU2_DATA_DIR"]
        return SimpleNamespace(
            reward_info=SimpleNamespace(reward=1.0),
            termination_reason="user_stop",
            messages=[
                UserMessage(role="user", content="My card was declined."),
                AssistantMessage(role="assistant", content="Thanks."),
            ],
            agent_cost=0.01,
            user_cost=0.02,
        )

    monkeypatch.setattr(tau2, "run_single_task", simulate)
    monkeypatch.setattr(tau2, "_native_task", lambda domain, task: None)

    agent = _Agent()
    tau2.bind(agent, {"llm": {"model_name": "sim-model", "api_key": "sim-key"}})
    trajectory = asyncio.run(agent._env_runner(agent, task))

    assert trajectory.status == "finished"
    assert trajectory.output == "Thanks."
    assert trajectory.usage == {"agent_cost": 0.01, "user_cost": 0.02}
    event = trajectory.messages[-1]
    assert event["type"] == "Tau2Simulator"
    assert event["task_id"] == "task_001"
    assert event["task_checksum"] == task.metadata["task_checksum"]
    assert event["reward"] == 1.0
    assert event["termination_reason"] == "user_stop"
    # The simulator gets its own model; the variant selects its tools.
    assert seen["config"].llm_user == "sim-model"
    assert seen["config"].retrieval_config == "grep_only"
    assert seen["config"].max_steps == 7
    assert seen["data_dir"] == str(domain.parents[2])
    # The simulator key never leaks into the recorded trajectory.
    assert "sim-key" not in json.dumps(trajectory.messages, default=str)


def test_a_run_without_a_reward_is_an_error(tmp_path, monkeypatch):
    task = _task(_domain(tmp_path))
    monkeypatch.setattr(
        tau2,
        "run_single_task",
        lambda config, native: SimpleNamespace(reward_info=None),
    )
    monkeypatch.setattr(tau2, "_native_task", lambda domain, task: None)

    agent = _Agent()
    tau2.bind(agent, {"llm": {"model_name": "sim-model"}})
    trajectory = asyncio.run(agent._env_runner(agent, task))

    assert trajectory.status == "error"
    assert "without a reward" in trajectory.error_message
    assert trajectory.messages[-1]["error"] == trajectory.error_message


def test_the_event_satisfies_the_benchmark_grader(tmp_path, monkeypatch):
    """The integration's event must be exactly what Tau3Banking.grade accepts."""
    domain = tmp_path / "banking_knowledge"
    (domain / "tasks").mkdir(parents=True)
    (domain / "documents").mkdir()
    (domain / "prompts" / "components").mkdir(parents=True)
    (domain / "db.json").write_text("{}")
    (domain / "prompts" / "components" / "policy_header.md").write_text("# Policy\n")
    (domain / "prompts" / "grep_only.md").write_text("{{component:policy_header}}\n")
    (domain / "tasks" / "task_001.json").write_text(
        json.dumps({"id": "task_001", "user_scenario": {"instructions": "Ask."}})
    )
    benchmark = Tau3Banking(
        {
            "data_path": domain,
            "variant": "grep_only",
            "split": {"train": 1, "dev": 0, "test": 0},
        }
    )
    (task,) = benchmark.load()["train"]

    monkeypatch.setattr(
        tau2,
        "run_single_task",
        lambda config, native: SimpleNamespace(
            reward_info=SimpleNamespace(reward=0.5),
            termination_reason="agent_stop",
            messages=[],
            agent_cost=None,
            user_cost=None,
        ),
    )
    monkeypatch.setattr(tau2, "_native_task", lambda domain, task: None)
    agent = _Agent()
    tau2.bind(agent, {"llm": {"model_name": "sim-model"}})

    trajectory = asyncio.run(agent._env_runner(agent, task))
    # rollout attaches the Task; grade needs the one the benchmark produced.
    (graded,) = benchmark.grade((dataclasses.replace(trajectory, task=task),))

    assert graded.metrics["reward"] == 0.5


def test_bind_requires_a_dedicated_user_simulator_model():
    agent = _Agent()
    for value in (None, {}, {"llm": {}}, {"llm": {"model_name": "  "}}):
        with pytest.raises(ValueError, match="user simulator model"):
            tau2.bind(agent, value)
    assert not hasattr(agent, "_env_runner")


def test_a_task_without_its_domain_is_rejected(tmp_path):
    task = _task(_domain(tmp_path))
    task.env = str(tmp_path / "missing")
    agent = _Agent()
    tau2.bind(agent, {"llm": {"model_name": "sim-model"}})

    trajectory = asyncio.run(agent._env_runner(agent, task))

    assert trajectory.status == "error"
    assert "no domain directory" in trajectory.error_message
