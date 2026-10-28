import asyncio

import pytest
from algorithm_helpers import MemoryBenchmark

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms import GEPA
from flashrsi.core import Agent, Trajectory


class Proposer(Agent):
    name = "scripted_proposer"

    def __init__(self):
        super().__init__({"type": "llm"})
        self.calls = 0

    async def _run(self, prompt, working_dir=None):
        self.calls += 1
        return Trajectory(output=f"```\nproposal-{self.calls}\n```")


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
@pytest.mark.parametrize(
    "scores,selected",
    [((1, 1, 1), 0), ((0, 1, 1), 1), ((1, 0, 0), 0), ((0, 0, 1), 2)],
)
def test_final_dev_ties_keep_earlier_best(monkeypatch, cls, scores, selected):
    evaluated = []

    async def run(self, prompt, working_dir=None):
        path = self.files_dir / self.instruction_file
        text = path.read_text() if path.exists() else ""
        version = 2 if "proposal-2" in text else 1 if "proposal-1" in text else 0
        evaluated.append(prompt)
        correct = scores[version] if prompt == "dev-only" else True
        return Trajectory(output="right" if correct else "wrong")

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline"}})
    initial = target.snapshot
    algorithm = GEPA(
        {
            "max_metric_calls": 7,
            "reflection_minibatch_size": 1,
            "skip_perfect_score": False,
            "acceptance_criterion": "improvement_or_equal",
        },
        target=target,
        worker=Proposer(),
        benchmark=MemoryBenchmark(),
    )
    final = asyncio.run(algorithm.evolve())
    # Both candidates pass the training screen; the final choice depends on dev.
    assert len(algorithm._population) == 3
    if selected == 0:
        assert final == initial
    else:
        assert final.files[target.instruction_file].content.decode().strip() == (
            f"proposal-{selected}"
        )
    assert evaluated.count("dev-only") == 3
    assert "test-only" not in evaluated
