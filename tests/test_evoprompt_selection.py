import asyncio
import re

import pytest
from algorithm_helpers import MemoryBenchmark

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms import EvoPrompt
from flashrsi.core import Agent, Trajectory


class Proposer(Agent):
    name = "scripted_proposer"

    def __init__(self):
        super().__init__({"type": "llm"})
        self.calls = 0

    async def _run(self, prompt, working_dir=None):
        self.calls += 1
        return Trajectory(output=f"<prompt>proposal-{self.calls}</prompt>")


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
@pytest.mark.parametrize(
    "scores,selected",
    [
        ((1, 1, 1, 1, 1, 1), 0),
        ((0, 1, 1, 1, 1, 1), 1),
        ((0, 0, 1, 1, 1, 0), 2),
        ((1, 0, 0, 0, 0, 0), 0),
        ((0, 0, 0, 0, 1, 1), 4),
    ],
)
def test_standard_generations_retain_earliest_global_dev_best(
    monkeypatch, cls, scores, selected
):
    evaluated = []

    async def run(self, prompt, working_dir=None):
        path = self.files_dir / self.instruction_file
        text = path.read_text() if path.exists() else ""
        match = re.search(r"proposal-(\d+)", text)
        version = int(match[1]) if match else 0
        evaluated.append((prompt, version))
        return Trajectory(output="right" if scores[version] else "wrong")

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline"}})
    initial = target.snapshot
    algorithm = EvoPrompt(
        {
            "variant": "ga",
            "population_size": 2,
            "max_steps": 2,
            "selection": "tournament",
            "survivor_selection": "standard",
        },
        target=target,
        worker=Proposer(),
        benchmark=MemoryBenchmark(),
    )
    final = asyncio.run(algorithm.evolve())

    # Standard still replaces the population, even when children are worse.
    assert [member.text.strip() for member in algorithm._population] == [
        "proposal-4",
        "proposal-5",
    ]
    if selected == 0:
        assert final == initial
    else:
        assert final.files[target.instruction_file].content.decode().strip() == (
            f"proposal-{selected}"
        )
    assert evaluated == [("dev-only", version) for version in range(6)]
