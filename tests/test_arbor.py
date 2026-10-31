"""Hypothesis ancestry, trunk adoption, propagation and sealed-test boundaries."""

import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.algorithms import Arbor
from flashrsi.config import load_config
from flashrsi.core import Agent, Benchmark, Task, Trajectory


class Tasks(Benchmark):
    name = "arbor-fixture"
    primary_metric = "accuracy"
    metadata = {}

    def load(self):
        if self._splits is None:
            self._splits = {
                "train": (Task("train", "train"),),
                "dev": (Task("dev", "dev"),),
                "test": (Task("sealed", "DO-NOT-EXPOSE-TEST"),),
            }
        return self._splits

    def grade(self, rows):
        return tuple(
            replace(row, metrics={"accuracy": float(row.output or 0)}) for row in rows
        )


class Coordinator(Agent):
    name = "offline-arbor-worker"

    def __init__(self, actions, edits, *, relocate=False):
        super().__init__(
            {
                "type": "agent",
                "name": "offline-worker",
                "llm": {"model_name": "offline", "api_key": "worker-secret"},
            }
        )
        self.actions = iter(actions)
        self.edits = iter(edits)
        self.relocate = relocate
        self.prompts = []
        self.bases = []

    async def _run(self, prompt, working_dir=None):
        self.prompts.append(prompt)
        assert "DO-NOT-EXPOSE-TEST" not in prompt
        assert "target-secret" not in prompt and "worker-secret" not in prompt
        assert '"type": "RunConfig"' not in prompt
        if prompt.startswith("[Arbor: coordinate]"):
            return Trajectory(
                output="<ARBOR>" + json.dumps(next(self.actions)) + "</ARBOR>"
            )
        if prompt.startswith("[Arbor: execute]"):
            with TemporaryDirectory() as temporary:
                directory = (
                    Path(temporary) / "relocated" if self.relocate else working_dir
                )
                if self.relocate:
                    shutil.copytree(working_dir, directory)
                self.bases.append(
                    (directory / "skills/main.md").read_text(encoding="utf-8")
                )
                edit = next(self.edits)
                if edit is not None:
                    (directory / "skills/main.md").write_text(edit, encoding="utf-8")
                if self.relocate:
                    shutil.copytree(directory, working_dir, dirs_exist_ok=True)
            return Trajectory(output="Implemented one reusable mechanism.")
        if prompt.startswith("[Arbor: reflect]"):
            return Trajectory(
                output="Experiment lesson: retain evidence and compare alternatives."
            )
        assert prompt.startswith("[Arbor: synthesize]")
        assert "Experiment lesson" in prompt or "Synthesized lesson" in prompt
        return Trajectory(
            output="Synthesized lesson: measure reusable mechanisms before adopting."
        )


def expand(node, *hypotheses):
    return {"action": "expand", "node_id": node, "hypotheses": list(hypotheses)}


def run(node):
    return {"action": "run", "node_id": node}


def setup(
    monkeypatch, tmp_path, actions, edits, *, cls=MiniAgent, relocate=False, **options
):
    source = tmp_path / "source"
    (source / "skills").mkdir(parents=True)
    (source / "skills/main.md").write_text("SEED", encoding="utf-8")
    (source / "components.yaml").write_text("skill: ['skills/**']", encoding="utf-8")
    calls = []
    outcomes = {
        "SEED": (0.5, 0.5),
        "GOOD": (0.8, 0.7),
        "TIED": (0.9, 0.7),
        "BEST": (1.0, 0.9),
        "WORSE": (0.4, 1.0),
    }

    async def solve(self, prompt, working_dir=None):
        marker = (self.files_dir / "skills/main.md").read_text(encoding="utf-8")
        calls.append((marker, prompt))
        score = outcomes[marker][0 if prompt == "train" else 1]
        return Trajectory(
            output=str(score),
            messages=({"type": "Trace", "text": "Observed evidence: 检查"},),
        )

    monkeypatch.setattr(cls, "_run", solve)
    target = cls(
        {
            "name": cls.name,
            "source_dir": str(source),
            "llm": {"model_name": "offline", "api_key": "target-secret"},
        }
    )
    worker = Coordinator(actions, edits, relocate=relocate)
    algorithm = Arbor(
        {"name": "arbor", "worker": worker.config, "max_cycles": 4, **options},
        target=target,
        worker=worker,
        benchmark=Tasks(),
    )
    algorithm._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algorithm._run_dir / name).mkdir(parents=True)
    return algorithm, calls


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
@pytest.mark.parametrize("relocate", [False, True])
def test_tree_ancestry_is_independent_of_code_trunk_and_ties_keep_earlier_best(
    monkeypatch, tmp_path, cls, relocate
):
    actions = [
        expand("ROOT", "Direction one", "Direction two"),
        expand("1", "First mechanism", "Sibling"),
        run("1.1"),
        run("1.2"),
        expand("1.1", "Refine measured result"),
        run("1.1.1"),
        {"action": "prune", "node_id": "1.2", "reason": "No dev gain"},
        {"action": "stop", "reason": "Budget sufficient"},
    ]
    algo, calls = setup(
        monkeypatch,
        tmp_path,
        actions,
        ["GOOD", "TIED", "BEST"],
        cls=cls,
        relocate=relocate,
    )
    final = asyncio.run(algo.evolve())
    assert final.files["skills/main.md"].content == b"BEST"
    assert algo.worker.bases == ["SEED", "GOOD", "GOOD"]
    assert len(calls) == 8 and {prompt for _, prompt in calls} == {"train", "dev"}
    records = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((algo._run_dir / "trajectories").glob("*-decision.json"))
    ]
    tree = {node["id"]: node for node in records[-1]["tree"]}
    assert tree["1.2"]["parent_id"] == "1"
    assert tree["1.2"]["base_snapshot_id"] == tree["1.1"]["snapshot_id"]
    assert tree["1.1.1"]["base_snapshot_id"] == tree["1.1"]["snapshot_id"]
    assert tree["1.2"]["dev_score"] == 0.7 and tree["1.2"]["status"] == "pruned"
    assert tree["ROOT"]["insight"].startswith("Synthesized lesson")
    assert any(
        "Synthesized lesson" in prompt
        for prompt in algo.worker.prompts
        if prompt.startswith("[Arbor: coordinate]")
    )
    assert not list((algo._run_dir / "working").iterdir())
    saved = "".join(
        p.read_text(encoding="utf-8")
        for p in (algo._run_dir / "trajectories").glob("*.json")
    )
    assert "target-secret" not in saved and "worker-secret" not in saved


def test_train_regression_is_recorded_without_dev_admission(monkeypatch, tmp_path):
    algo, calls = setup(
        monkeypatch,
        tmp_path,
        [expand("ROOT", "Direction"), expand("1", "Try"), run("1.1")],
        ["WORSE"],
        max_cycles=1,
    )
    seed = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == seed.id
    assert calls == [("SEED", "train"), ("SEED", "dev"), ("WORSE", "train")]
    trees = list((algo._run_dir / "trajectories").glob("*-arbor-tree.json"))
    node = json.loads(trees[0].read_text(encoding="utf-8"))["nodes"][-1]
    assert node["train_score"] == 0.4 and node["dev_score"] is None
    assert node["insight"] and node["status"] == "done"


@pytest.mark.parametrize("edit", [None, "target-secret"])
def test_invalid_edits_consume_an_attempt_and_propagate_failure_insights(
    monkeypatch, tmp_path, edit
):
    algo, calls = setup(
        monkeypatch,
        tmp_path,
        [expand("ROOT", "Direction"), expand("1", "Try"), run("1.1")],
        [edit],
        max_cycles=1,
    )
    seed = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == seed.id
    assert len(calls) == 2
    node = json.loads(
        next((algo._run_dir / "trajectories").glob("*-arbor-tree.json")).read_text(
            encoding="utf-8"
        )
    )["nodes"][-1]
    assert node["status"] == "needs_retry" and node["train_score"] is None
    assert not list((algo._run_dir / "working").iterdir())


def test_invalid_planning_and_pruned_descendants_cannot_dispatch(monkeypatch, tmp_path):
    actions = [
        expand("ROOT", "Direction"),
        expand("1", "Mechanism"),
        {"action": "prune", "node_id": "1", "reason": "Abandon"},
        run("1.1"),
        {"action": "stop"},
    ]
    algo, calls = setup(monkeypatch, tmp_path, actions, [])
    assert asyncio.run(algo.evolve()).files["skills/main.md"].content == b"SEED"
    assert len(calls) == 2
    assert list((algo._run_dir / "trajectories").glob("*-arbor-plan-rejected.json"))


def test_planning_actions_are_bounded_without_experiments(monkeypatch, tmp_path):
    algo, _ = setup(monkeypatch, tmp_path, [run("missing")] * 12, [])
    with pytest.raises(ValueError, match="12 planning actions"):
        asyncio.run(algo.evolve())


@pytest.mark.parametrize("value", [0, True, 1.5])
def test_invalid_cycle_budget_is_rejected(monkeypatch, tmp_path, value):
    with pytest.raises(ValueError, match="max_cycles"):
        setup(monkeypatch, tmp_path, [], [], max_cycles=value)


def test_text_worker_and_empty_dev_are_rejected(monkeypatch, tmp_path):
    algo, calls = setup(monkeypatch, tmp_path, [], [])
    with pytest.raises(ValueError, match="file-editing"):
        Arbor({}, target=algo.target, worker=LLM(), benchmark=Tasks())
    benchmark = Tasks()
    benchmark.load()["dev"] = ()
    with pytest.raises(ValueError, match="non-empty"):
        Arbor({}, target=algo.target, worker=algo.worker, benchmark=benchmark)
    assert not calls


def test_runner_registration_and_final_test_after_selection(monkeypatch, tmp_path):
    from flashrsi import runner

    assert runner._ALGORITHMS["arbor"] is Arbor
    algo, calls = setup(
        monkeypatch,
        tmp_path,
        [expand("ROOT", "Direction"), expand("1", "Try"), run("1.1")],
        ["GOOD"],
        max_cycles=1,
    )

    async def prepare(config):
        return algo

    monkeypatch.setattr(runner, "_prepare", prepare)
    # Keep the framework's long Snapshot filenames below legacy MAX_PATH on
    # Windows; pytest's nested source-checkout directory can already be deep.
    with TemporaryDirectory(prefix="arbor-run-") as output:
        config = load_config(
            overrides={
                "run": {"output_dir": output},
                "benchmark": {"name": "arbor-fixture"},
                "agent": algo.target.config,
                "algorithm": algo.config,
            }
        )
        directory, result = asyncio.run(runner._run(config))
        assert result["status"] == "finished" and result["test_tasks"] == 1
        assert result["test_score"] == 0.7
        assert calls[-1] == ("GOOD", "DO-NOT-EXPOSE-TEST")
        assert sum(question == "DO-NOT-EXPOSE-TEST" for _, question in calls) == 1
        assert (directory / "result.json").is_file()
        assert (directory / "end-summary.json").is_file()


@pytest.mark.parametrize("split", ["train", "dev"])
def test_failed_candidate_evaluations_do_not_move_trunk(monkeypatch, tmp_path, split):
    algo, _ = setup(
        monkeypatch,
        tmp_path,
        [expand("ROOT", "Direction"), expand("1", "Try"), run("1.1")],
        ["GOOD"],
        max_cycles=1,
    )
    original = algo.target._run

    async def fail(prompt, working_dir=None):
        marker = (algo.target.files_dir / "skills/main.md").read_text(encoding="utf-8")
        if marker == "GOOD" and prompt == split:
            return Trajectory(status="error", error_message="fixture provider failure")
        return await original(prompt, working_dir)

    monkeypatch.setattr(algo.target, "_run", fail)
    seed = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == seed.id
    node = json.loads(
        next((algo._run_dir / "trajectories").glob("*-arbor-tree.json")).read_text(
            encoding="utf-8"
        )
    )["nodes"][-1]
    assert node["status"] == "needs_retry"


def test_worker_error_is_recorded_and_checkout_is_cleaned(monkeypatch, tmp_path):
    algo, _ = setup(
        monkeypatch,
        tmp_path,
        [expand("ROOT", "Direction"), expand("1", "Try"), run("1.1")],
        [],
    )
    original = algo.worker._run

    async def fail(prompt, working_dir=None):
        if prompt.startswith("[Arbor: execute]"):
            return Trajectory(status="error", error_message="fixture Worker failed")
        return await original(prompt, working_dir)

    monkeypatch.setattr(algo.worker, "_run", fail)
    with pytest.raises(RuntimeError, match="fixture Worker failed"):
        asyncio.run(algo.evolve())
    assert not list((algo._run_dir / "working").iterdir())
    records = list((algo._run_dir / "trajectories").glob("*-worker.json"))
    assert (
        json.loads(sorted(records)[-1].read_text(encoding="utf-8"))["trajectory"][
            "status"
        ]
        == "error"
    )


def test_overlapping_split_ids_are_rejected(monkeypatch, tmp_path):
    algo, _ = setup(monkeypatch, tmp_path, [], [])
    benchmark = Tasks()
    splits = benchmark.load()
    splits["dev"] = splits["train"]
    with pytest.raises(ValueError, match="disjoint"):
        Arbor({}, target=algo.target, worker=algo.worker, benchmark=benchmark)
