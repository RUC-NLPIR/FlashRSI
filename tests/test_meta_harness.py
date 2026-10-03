"""Meta-Harness retrieves native versions and uncompressed framework records."""

import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.algorithms import MetaHarness
from flashrsi.core import Agent, Benchmark, Task, Trajectory


class SearchTasks(Benchmark):
    name = "meta-search"
    description = "Disjoint offline tasks."
    primary_metric = "accuracy"
    metadata = {}

    def load(self):
        if self._splits is None:
            self._splits = {
                "train": (Task("train-only", "train-only"),),
                "dev": tuple(Task(f"dev-{i}", f"dev-{i}") for i in range(2)),
                "test": (Task("test-only", "test-only"),),
            }
        return self._splits

    def grade(self, results):
        return tuple(
            replace(item, metrics={"accuracy": float(item.output)}) for item in results
        )


class EditingWorker(Agent):
    name = "editing"
    description = "Offline file-editing Worker."

    def __init__(self, edit, *, relocate=False):
        super().__init__({"type": "agent", "llm": {"api_key": "worker-private-secret"}})
        self.apply_edit = edit
        self.relocate = relocate
        self.prompts = []
        self.directories = []

    async def _run(self, prompt, working_dir=None):
        self.prompts.append(prompt)
        self.directories.append(working_dir)
        if self.relocate:
            # Only working_dir travels, as it would for an isolated Worker.
            with TemporaryDirectory() as temporary:
                relocated = Path(temporary) / "workspace"
                shutil.copytree(working_dir, relocated)
                result = self.apply_edit(prompt, relocated)
                shutil.copytree(relocated, working_dir, dirs_exist_ok=True)
        else:
            result = self.apply_edit(prompt, working_dir)
        return result or Trajectory(output="Inspected history and edited the harness.")


def history(prompt, directory):
    line = next(line for line in prompt.splitlines() if line.startswith("- `"))
    index_path = directory / line.split("`")[1]
    return index_path.parent, json.loads(index_path.read_text())


def setup(monkeypatch, tmp_path, edit, *, cls=MiniAgent, relocate=False, **options):
    source = tmp_path / "source"
    (source / "skills").mkdir(parents=True)
    (source / "tools").mkdir()
    (source / "skills/main.md").write_text("SEED")
    (source / "tools/binary").write_bytes(b"\x00\xff\x01")
    (source / "tools/binary").chmod(0o755)
    (source / "components.yaml").write_text("skill: ['skills/**']\ntool: ['tools/**']")
    calls = []

    async def run(self, prompt, working_dir=None):
        marker = (self.files_dir / "skills/main.md").read_text()
        passing = (
            {"dev-0"}
            if marker.startswith("GOOD")
            else {"dev-0", "dev-1"}
            if marker == "GREAT"
            else set()
        )
        calls.append((self.snapshot.id, prompt))
        return Trajectory(
            output=str(float(prompt in passing)),
            messages=(
                {
                    "type": "Trace",
                    "text": "evidence " * 5000 + "TAIL_EVIDENCE target-private-secret",
                },
            ),
        )

    monkeypatch.setattr(cls, "_run", run)
    target = cls(
        {
            "source_dir": str(source),
            "llm": {"model_name": "offline", "api_key": "target-private-secret"},
        }
    )
    worker = EditingWorker(edit, relocate=relocate)
    algo = MetaHarness(
        {"max_steps": 1, **options},
        target=target,
        worker=worker,
        benchmark=SearchTasks(),
    )
    return algo, calls


def attach_run(algo, tmp_path):
    algo._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algo._run_dir / name).mkdir(parents=True)
    return algo._run_dir


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
@pytest.mark.parametrize("relocate", [False, True])
def test_full_history_includes_regressions_and_survives_workspace_relocation(
    monkeypatch, tmp_path, cls, relocate
):
    seen = []

    def edit(prompt, directory):
        folder, index = history(prompt, directory)
        markers = [
            (folder / row["directory"] / "skills/main.md").read_text() for row in index
        ]
        seen.append(markers)
        assert markers == ["SEED", "GOOD", "WORSE"][: len(seen)]
        assert all(
            (folder / row["directory"] / "tools/binary").read_bytes() == b"\x00\xff\x01"
            and (folder / row["directory"] / "tools/binary").stat().st_mode & 0o111
            for row in index
        )
        records = [
            json.loads(path.read_text())
            for path in (folder / "trajectories").glob("*.json")
        ]
        evaluations = [row for row in records if "trajectories" in row]
        assert len(evaluations) == len(seen)
        assert {row["snapshot_id"] for row in evaluations} == {
            row["snapshot_id"] for row in index
        }
        text = json.dumps(records)
        assert "TAIL_EVIDENCE" in text  # Full traces, including beyond prompt budgets.
        assert "target-private-secret" not in text
        assert "worker-private-secret" not in text
        assert "test-only" not in text and "train-only" not in text
        if len(seen) == 3:
            assert "Inspected history" in text  # Prior proposer reasoning is readable.
            assert any(row.get("score") == 0.5 for row in records)
            # The Worker may base a proposal on a worse historical version.
            shutil.copyfile(
                folder / index[-1]["directory"] / "skills/main.md",
                directory / "skills/main.md",
            )
        (directory / "skills/main.md").write_text(
            ["GOOD", "WORSE", "GREAT"][len(seen) - 1]
        )

    algo, calls = setup(
        monkeypatch, tmp_path, edit, cls=cls, relocate=relocate, max_steps=3
    )
    run_dir = attach_run(algo, tmp_path)
    seed = algo.target.snapshot
    updates = []
    update = algo.target.update

    def promote(snapshot):
        updates.append((len(algo.worker.prompts), snapshot.id))
        update(snapshot)

    monkeypatch.setattr(algo.target, "update", promote)
    final = asyncio.run(algo.evolve())

    assert final.files["skills/main.md"].content == b"GREAT"
    assert final.parent_id == seed.id  # Physical checkout provenance stays native.
    assert final.files["tools/binary"] == seed.files["tools/binary"]
    assert updates == [(3, final.id)]
    assert len(calls) == 8 and {task for _, task in calls} == {"dev-0", "dev-1"}
    assert not any(path.startswith("history-") for path in final.files)
    assert not list((run_dir / "working").iterdir())
    assert len(list((run_dir / "trajectories").glob("*-worker.json"))) == 3


def test_ties_keep_the_earlier_best_after_later_regressions(monkeypatch, tmp_path):
    markers = iter(["GOOD", "GOOD-TIED", "WORSE"])

    def edit(prompt, directory):
        (directory / "skills/main.md").write_text(next(markers))

    algo, _ = setup(monkeypatch, tmp_path, edit, max_steps=3)
    run_dir = attach_run(algo, tmp_path)
    final = asyncio.run(algo.evolve())
    records = [
        json.loads(path.read_text())
        for path in sorted((run_dir / "trajectories").glob("*-decision.json"))
    ]
    assert [row["improved_best"] for row in records[:-1]] == [True, False, False]
    assert records[-1]["candidate_id"] == records[0]["candidate_id"] == final.id
    assert records[1]["candidate_id"] != final.id
    assert len(records[-1]["candidate_ids"]) == 4


@pytest.mark.parametrize(
    "problem", ["unchanged", "unclassified", "credential", "rules"]
)
def test_invalid_edits_consume_one_attempt_and_next_round_reads_the_rejection(
    monkeypatch, tmp_path, problem
):
    count = 0

    def edit(prompt, directory):
        nonlocal count
        count += 1
        if count == 1:
            if problem == "unclassified":
                (directory / "unknown.txt").write_text("invalid")
            elif problem == "credential":
                (directory / "skills/main.md").write_text("target-private-secret")
            elif problem == "rules":
                (directory / "components.yaml").write_text("tool: ['**']")
        else:
            folder, index = history(prompt, directory)
            assert len(index) == 1
            records = [
                json.loads(p.read_text())
                for p in (folder / "trajectories").glob("*.json")
            ]
            assert any(row.get("kind") == "decline" for row in records)
            (directory / "skills/main.md").write_text("GOOD")

    algo, calls = setup(monkeypatch, tmp_path, edit, max_steps=2)
    directory = attach_run(algo, tmp_path)
    final = asyncio.run(algo.evolve())
    assert final.files["skills/main.md"].content == b"GOOD"
    assert len(calls) == 4
    assert not list((directory / "working").iterdir())


def test_history_changes_are_discarded_and_rebuilt_from_native_records(
    monkeypatch, tmp_path
):
    count = 0

    def edit(prompt, directory):
        nonlocal count
        count += 1
        folder, index = history(prompt, directory)
        seed_source = folder / index[0]["directory"] / "skills/main.md"
        assert seed_source.read_text() == "SEED"
        seed_source.write_text("corrupted reference")
        (directory / "skills/main.md").write_text("GOOD")
        (directory / "skills/__pycache__").mkdir()
        (directory / "skills/__pycache__/generated.pyc").write_bytes(b"cache")

    algo, _ = setup(monkeypatch, tmp_path, edit, max_steps=2)
    final = asyncio.run(algo.evolve())
    assert count == 2 and final.files["skills/main.md"].content == b"GOOD"
    assert not any("__pycache__" in path for path in final.files)


@pytest.mark.parametrize("persistent", [False, True])
def test_worker_failure_aborts_and_cleans_all_checkouts(
    monkeypatch, tmp_path, persistent
):
    def fail(prompt, directory):
        folder, index = history(prompt, directory)
        assert len(index) == 1 and folder.is_dir()
        return Trajectory(status="error", error_message="provider failed")

    algo, _ = setup(monkeypatch, tmp_path, fail)
    run_dir = attach_run(algo, tmp_path) if persistent else None
    seed = algo.target.snapshot
    with pytest.raises(RuntimeError, match="provider failed"):
        asyncio.run(algo.evolve())
    assert algo._run_dir == run_dir
    assert algo.target.snapshot.id == seed.id
    assert all(not path.exists() for path in algo.worker.directories)
    if persistent:
        assert list((run_dir / "trajectories").glob("*-worker.json"))
        assert not list((run_dir / "working").iterdir())


def test_direct_python_use_provides_full_history_and_restores_recording_state(
    monkeypatch, tmp_path
):
    def edit(prompt, directory):
        folder, index = history(prompt, directory)
        assert len(index) == 1 and list(
            (folder / "trajectories").glob("*-baseline.json")
        )
        (directory / "skills/main.md").write_text("GOOD")

    algo, _ = setup(monkeypatch, tmp_path, edit)
    final = asyncio.run(algo.evolve())
    assert final.files["skills/main.md"].content == b"GOOD"
    assert algo._run_dir is None
    assert all(not path.exists() for path in algo.worker.directories)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
def test_invalid_budget_is_rejected_before_execution(monkeypatch, tmp_path, value):
    with pytest.raises(ValueError, match="max_steps"):
        setup(monkeypatch, tmp_path, lambda *args: None, max_steps=value)


def test_text_only_worker_and_empty_search_split_are_rejected(monkeypatch, tmp_path):
    algo, calls = setup(monkeypatch, tmp_path, lambda *args: None)
    with pytest.raises(ValueError, match="worker.type: agent"):
        MetaHarness({}, target=algo.target, worker=LLM(), benchmark=SearchTasks())
    benchmark = SearchTasks()
    benchmark.load()["dev"] = ()
    with pytest.raises(ValueError, match="non-empty dev"):
        MetaHarness({}, target=algo.target, worker=algo.worker, benchmark=benchmark)
    assert not calls
