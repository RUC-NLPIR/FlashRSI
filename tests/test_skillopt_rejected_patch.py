"""Invalid Worker proposals reject one update without swallowing runtime failures."""

import asyncio
import json

import pytest
from algorithm_helpers import MemoryBenchmark

from flashrsi.agents import MiniAgent
from flashrsi.algorithms.skillopt import SkillOpt
from flashrsi.core import Agent, Trajectory


class Proposer(Agent):
    name = "scripted_skill_proposer"

    def __init__(self, reply):
        super().__init__({"type": "llm"})
        self.reply = reply
        self.calls = 0

    async def _run(self, prompt, working_dir=None):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return Trajectory(output=self.reply, usage={"input_tokens": 2})


def setup(monkeypatch, tmp_path, reply):
    evaluated = []

    async def run(self, prompt, working_dir=None):
        evaluated.append(prompt)
        return Trajectory(output="right")

    monkeypatch.setattr(MiniAgent, "_run", run)
    target = MiniAgent({"llm": {"model_name": "offline"}})
    worker = Proposer(reply)
    algorithm = SkillOpt(
        {"num_epochs": 1, "use_slow_update": False, "use_meta_skill": False},
        target=target,
        worker=worker,
        benchmark=MemoryBenchmark(),
    )
    algorithm._run_dir = tmp_path
    for name in ("snapshots", "trajectories", "working"):
        (tmp_path / name).mkdir()
    return algorithm, worker, evaluated


@pytest.mark.parametrize(
    "reply",
    [
        "not JSON",
        json.dumps(
            {
                "edits": [
                    {
                        "op": "insert_after",
                        "path": "skills/probe.md",
                        "target": "anchor",
                        "content": "",
                    }
                ]
            }
        ),
        json.dumps(
            {
                "edits": [
                    {
                        "op": "replace",
                        "path": "skills/missing.md",
                        "target": "anchor",
                        "content": "new",
                    }
                ]
            }
        ),
    ],
)
def test_invalid_proposal_retains_incumbent_and_worker_evidence(
    monkeypatch, tmp_path, reply
):
    algorithm, worker, evaluated = setup(monkeypatch, tmp_path, reply)
    initial = algorithm.target.snapshot
    assert asyncio.run(algorithm.evolve()) == initial
    assert algorithm.target.snapshot == initial
    assert worker.calls == 1
    assert evaluated[0] == "dev-only"
    assert sorted(evaluated[1:]) == ["train-0", "train-1"]
    records = list((tmp_path / "trajectories").glob("*.json"))
    decision = json.loads(next(p for p in records if "decision" in p.name).read_text())
    assert decision["reason"] == "invalid_patch"
    assert decision["accepted"] is False
    assert decision["parent_id"] == initial.id
    evidence = json.loads(next(p for p in records if "worker" in p.name).read_text())
    assert evidence["trajectory"]["usage"]["input_tokens"] == 2
    assert not any("candidate_dev" in p.name for p in records)


def test_worker_runtime_failure_is_not_an_invalid_patch(monkeypatch, tmp_path):
    algorithm, worker, evaluated = setup(
        monkeypatch, tmp_path, RuntimeError("worker budget exhausted")
    )
    with pytest.raises(RuntimeError, match="worker budget exhausted"):
        asyncio.run(algorithm.evolve())
    assert worker.calls == 1
    assert not list((tmp_path / "trajectories").glob("*decision.json"))


def test_valid_candidate_still_requires_strict_dev_improvement(monkeypatch, tmp_path):
    reply = json.dumps(
        {"edits": [{"op": "append", "path": "skills/probe.md", "content": "new"}]}
    )
    algorithm, worker, evaluated = setup(monkeypatch, tmp_path, reply)
    initial = algorithm.target.snapshot
    assert asyncio.run(algorithm.evolve()) == initial
    assert worker.calls == 1
    assert evaluated.count("dev-only") == 2
    records = list((tmp_path / "trajectories").glob("*decision.json"))
    decision = json.loads(records[0].read_text())
    assert decision["accepted"] is False
    assert decision["candidate_id"] != initial.id
    assert decision["score"] == decision["baseline_score"]
