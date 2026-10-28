import asyncio
import json
import re

import pytest
from algorithm_helpers import MemoryBenchmark

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms.ace import ACE
from flashrsi.core import Agent, Trajectory


class Curator(Agent):
    name = "scripted_curator"

    def __init__(self, *, invalid=False):
        super().__init__({"type": "llm"})
        self.calls = 0
        self.invalid = invalid

    async def _run(self, prompt, working_dir=None):
        self.calls += 1
        if self.calls % 2:
            return Trajectory(output='{"key_insight": "Read carefully."}')
        return Trajectory(
            output=json.dumps(
                {
                    "operations": [
                        {
                            "type": "DELETE" if self.invalid else "ADD",
                            "content": f"rule-{self.calls // 2}",
                        }
                    ]
                }
            )
        )


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
@pytest.mark.parametrize(
    "scores,selected",
    [((1, 1, 1), 0), ((0, 1, 1), 1), ((1, 0, 0), 0), ((0, 0, 1), 2)],
)
def test_offline_retains_incumbent_on_dev_tie(monkeypatch, cls, scores, selected):
    evaluated = []

    async def run(self, prompt, working_dir=None):
        path = self.files_dir / self.instruction_file
        text = path.read_text() if path.exists() else ""
        version = 2 if "rule-2" in text else 1 if "rule-1" in text else 0
        evaluated.append(prompt)
        return Trajectory(output="right" if scores[version] else "wrong")

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline"}})
    initial = target.snapshot
    algorithm = ACE(
        {"max_steps": 2, "eval_steps": 1, "max_reflection_rounds": 1},
        target=target,
        worker=Curator(),
        benchmark=MemoryBenchmark(),
    )
    final = asyncio.run(algorithm.evolve())
    if selected == 0:
        assert final == initial
    else:
        assert final.id != initial.id
        text = final.files[target.instruction_file].content.decode()
        assert "rule-1" in text
        assert ("rule-2" in text) == (selected == 2)
    assert evaluated.count("dev-only") == 3
    assert "test-only" not in evaluated


def test_invalid_updates_cannot_win_a_tie(monkeypatch):
    async def run(self, prompt, working_dir=None):
        return Trajectory(output="right")

    monkeypatch.setattr(MiniAgent, "_run", run)
    target = MiniAgent({"llm": {"model_name": "offline"}})
    initial = target.snapshot
    algorithm = ACE(
        {"max_steps": 1, "eval_steps": 1, "max_reflection_rounds": 1},
        target=target,
        worker=Curator(invalid=True),
        benchmark=MemoryBenchmark(),
    )
    assert asyncio.run(algorithm.evolve()) == initial


@pytest.mark.parametrize("budget", [1, 3])
def test_curator_receives_budget_and_excess_additions_are_still_rejected(
    monkeypatch, budget
):
    seen = []

    async def run_target(self, prompt, working_dir=None):
        return Trajectory(output="right")

    async def run_curator(self, prompt, working_dir=None):
        if prompt.startswith("[ACE: reflect]"):
            return Trajectory(output='{"key_insight": "Read carefully."}')
        limit = re.search(r"at most (\d+) ADD operations", prompt)
        assert limit is not None
        seen.append(int(limit[1]))
        return Trajectory(
            output=json.dumps(
                {
                    "operations": [
                        {"type": "ADD", "content": f"rule-{i}"}
                        for i in range(int(limit[1]) + 1)
                    ]
                }
            )
        )

    monkeypatch.setattr(MiniAgent, "_run", run_target)
    monkeypatch.setattr(Curator, "_run", run_curator)
    target = MiniAgent({"llm": {"model_name": "offline"}})
    initial = target.snapshot
    algorithm = ACE(
        {
            "max_steps": 1,
            "eval_steps": 1,
            "max_reflection_rounds": 1,
            "edit_budget": budget,
        },
        target=target,
        worker=Curator(),
        benchmark=MemoryBenchmark(),
    )
    assert asyncio.run(algorithm.evolve()) == initial
    assert seen == [budget]
    assert f"budget={budget}" in algorithm._rejected[-1]["problem"]
