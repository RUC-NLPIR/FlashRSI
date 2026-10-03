"""Measured population behavior with offline directory edits and noisy trials."""

import asyncio
import json
import shutil
from collections import Counter
from dataclasses import replace

import pytest
from test_opro import PATHS, MemoryBenchmark

from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.algorithms import DarwinX
from flashrsi.core import Agent, Snapshot, Task, Trajectory


class Scores(MemoryBenchmark):
    def load(self):
        if self._splits is None:
            self._splits = {
                "train": tuple(Task(f"t{i}", f"t{i}") for i in range(3)),
                "dev": (Task("dev-only", "dev-only"),),
                "test": (Task("test-only", "test-only"),),
            }
        return self._splits

    def grade(self, results):
        return tuple(replace(r, metrics={"accuracy": float(r.output)}) for r in results)


class Worker(Agent):
    name = "offline_editor"
    description = "Edits real checkouts and distills scripted lessons."

    def __init__(self, edits, path):
        super().__init__({"type": "agent", "llm": {"model_name": "offline-worker"}})
        self.edits = iter(edits)
        self.path = path
        self.prompts, self.lessons, self.checkouts = [], [], []
        self.references = []

    async def _run(self, prompt, working_dir=None):
        if working_dir is None:
            self.lessons.append(prompt)
            return Trajectory(output="<LEARNINGS>Inspect shared fallbacks.</LEARNINGS>")
        self.prompts.append(prompt)
        if prompt.startswith("[DarwinX: recombine]"):
            refs = json.loads(
                prompt.split("RECOMBINATION INPUT (empty for mutation):\n")[1].split(
                    "\nFor recombination"
                )[0]
            )
            self.references.append(
                {
                    r["role"]: {
                        "snapshot_id": r["snapshot_id"],
                        "text": (working_dir / r["directory"] / self.path).read_text(),
                        "files": {
                            str(
                                p.relative_to(working_dir / r["directory"])
                            ): p.read_bytes()
                            for p in (working_dir / r["directory"]).rglob("*")
                            if p.is_file()
                        },
                    }
                    for r in refs
                }
            )
        file = working_dir / self.path
        self.checkouts.append(file.read_text() if file.exists() else "")
        changes = next(self.edits)
        if isinstance(changes, str):
            changes = {self.path: changes}
        for name, content in changes.items():
            destination = working_dir / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                destination.unlink()
            else:
                destination.write_text(content)
        return Trajectory(output=f"<DESIGN>edit {len(self.prompts)}</DESIGN>")


def setup(monkeypatch, edits, scores, *, cls=MiniAgent, benchmark=None, **config):
    counts, calls = Counter(), []

    async def run(self, prompt, working_dir=None):
        entry = self.snapshot.files.get(PATHS[cls])
        text = entry.content.decode() if entry else ""
        marker = text if text in scores else "SEED"
        values = scores.get(marker, {}).get(prompt, 0.0)
        if isinstance(values, list):
            value = values[counts[marker, prompt] % len(values)]
        else:
            value = values
        counts[marker, prompt] += 1
        calls.append((marker, prompt, self.snapshot.id))
        return Trajectory(
            output=str(value), messages=({"type": "Trace", "marker": marker},)
        )

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline-target"}})
    worker = Worker(edits, PATHS[cls])
    algorithm = DarwinX(
        {
            "max_steps": len(edits) or 1,
            "screen_size": 3,
            "confirm_samples": 2,
            "exploration_probability": 0.0,
            "merge_every": 0,
            **config,
        },
        target=target,
        worker=worker,
        benchmark=benchmark or Scores(),
    )
    return algorithm, calls


def attach(algo, path):
    algo._run_dir = path
    for name in ("snapshots", "trajectories", "working"):
        (path / name).mkdir(exist_ok=True)


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_confirmed_extension_promoted_on_both_harnesses(monkeypatch, tmp_path, cls):
    algo, calls = setup(monkeypatch, ["GOOD"], {"GOOD": {"t0": 1}}, cls=cls)
    attach(algo, tmp_path)
    original = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    assert final.id != original.id
    assert final.files[PATHS[cls]].content == b"GOOD"
    assert algo._archive[1]["accepted"]
    assert algo._archive[1]["score"] == 1 / 3
    assert len(calls) == 24  # seed 6 + screen 6 + matched confirmation 12
    assert {task for _, task, _ in calls} == {"t0", "t1", "t2"}
    assert all(
        "test-only" not in p and "dev-only" not in p for p in algo.worker.prompts
    )
    assert "RunConfig" not in algo.worker.prompts[0]
    assert not list((tmp_path / "working").iterdir())
    records = [
        json.loads(p.read_text())
        for p in sorted((tmp_path / "trajectories").glob("*-decision.json"))
    ]
    assert records[0]["accepted"] and records[0]["gain"] == 1
    assert records[-1]["archive"][1]["fidelity"] == "confirmation"


def test_improved_mean_with_a_lost_capability_is_rejected(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        ["TRADE"],
        {
            "SEED": {"t0": 1},
            "TRADE": {"t1": 1, "t2": 1},
        },
    )
    original = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    stats = algo._archive[1]
    assert final.id == original.id
    assert stats["score"] == 2 / 3
    assert stats["fidelity"] == "confirmation" and not stats["accepted"]
    assert len(algo.worker.lessons) == 1
    assert '"regression_mass": 1.0' in algo.worker.lessons[0]
    assert '"lost_invariant": ["t0"]' in algo.worker.lessons[0]


def test_avg_k_and_fresh_confirmation_prevent_lucky_parent(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        ["LUCKY", "NEXT"],
        {
            "LUCKY": {"t0": [1, 0, 0]},
            "NEXT": {"t1": 1},
        },
    )
    asyncio.run(algo.evolve())
    assert algo._archive[1]["per_task"]["t0"] == 0
    assert not algo._archive[1]["accepted"]
    assert algo._archive[2]["parent_id"] == algo._archive[0]["snapshot_id"]
    assert '"fidelity": "confirmation"' in algo.worker.prompts[1]
    assert "Inspect shared fallbacks." in algo.worker.prompts[1]


def test_repeat_scores_are_means_instead_of_best_of_k(monkeypatch):
    algo, _ = setup(monkeypatch, ["NOISY"], {"NOISY": {"t0": [1, 1, 0]}})
    asyncio.run(algo.evolve())
    assert algo._archive[1]["per_task"]["t0"] == 0.5
    assert algo._archive[1]["invariant"] == []
    assert algo._archive[1]["samples"] == 2
    assert len(algo._versions[algo._archive[1]["snapshot_id"]][1]) == 2
    assert (
        '"trial": 0' in algo.worker.lessons[0]
        and '"trial": 1' in algo.worker.lessons[0]
    )


def test_rejected_specialists_recombine_from_primary_snapshot(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        ["A", "B", "AB"],
        {
            "SEED": {"t0": 1},
            "A": {"t1": 1, "t2": 1},
            "B": {"t0": 1},
            "AB": {"t0": 1, "t1": 1, "t2": 1},
        },
        merge_every=3,
    )
    final = asyncio.run(algo.evolve())
    assert not algo._archive[1]["accepted"] and not algo._archive[2]["accepted"]
    # Seed and the rejected specialist are complementary measured donors.
    assert algo._archive[3]["parent_id"] == algo._archive[1]["snapshot_id"]
    assert algo._archive[3]["donor_id"] == algo._archive[0]["snapshot_id"]
    assert algo._archive[3]["accepted"]
    assert final.files[PATHS[MiniAgent]].content == b"AB"
    assert algo.worker.prompts[2].startswith("[DarwinX: recombine]")
    assert (
        algo.worker.references[0]["donor"]["snapshot_id"]
        == algo._archive[0]["snapshot_id"]
    )
    assert algo.worker.checkouts[2] == "A"
    assert final.parent_id == algo._archive[1]["snapshot_id"]


def test_merge_must_preserve_secondary_even_if_it_beats_primary(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        ["A", "B", "BADMERGE"],
        {
            "SEED": {"t0": 1},
            "A": {"t1": 1},
            "B": {"t0": 1},
            "BADMERGE": {"t1": 1, "t2": 1},
        },
        merge_every=3,
    )
    original = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == original.id
    assert not algo._archive[-1]["accepted"]
    assert algo._archive[-1]["invariant"] == ["t0", "t1"]


def test_two_siblings_merge_actual_additions_and_deletions(monkeypatch):
    path = PATHS[MiniAgent]
    algo, _ = setup(
        monkeypatch,
        [
            {path: "A", "skills/added.md": "Capability A."},
            {path: "B", "skills/main.md": None},
            {path: "AB", "skills/added.md": "Capability A.", "skills/main.md": None},
        ],
        {"A": {"t0": 1}, "B": {"t1": 1}, "AB": {"t0": 1, "t1": 1}},
        exploration_probability=1.0,
        seed=4,
        merge_every=3,
    )
    final = asyncio.run(algo.evolve())
    assert (
        algo._archive[1]["parent_id"]
        == algo._archive[2]["parent_id"]
        == algo._archive[0]["snapshot_id"]
    )
    assert algo._archive[3]["parent_id"] == algo._archive[1]["snapshot_id"]
    assert algo._archive[3]["donor_id"] == algo._archive[2]["snapshot_id"]
    assert final.parent_id == algo._archive[1]["snapshot_id"]
    assert algo._archive[3]["invariant"] == ["t0", "t1"]
    assert algo.worker.references[0]["donor"]["text"] == "B"
    assert "skills/main.md" in algo.worker.references[0]["ancestor"]["files"]
    assert "skills/main.md" not in algo.worker.references[0]["donor"]["files"]
    assert not any(p.startswith("checkout-") for p in final.files)
    assert final.files["skills/added.md"].content == b"Capability A."
    assert "skills/main.md" not in final.files


def test_merge_records_and_later_ancestry_use_persisted_snapshots(
    monkeypatch, tmp_path
):
    algo, _ = setup(
        monkeypatch,
        ["A", "B", "AB"],
        {"A": {"t0": 1}, "B": {"t1": 1}, "AB": {"t0": 1, "t1": 1}},
        exploration_probability=1.0,
        seed=4,
        merge_every=3,
    )
    attach(algo, tmp_path)
    asyncio.run(algo.evolve())
    seed, primary, donor, merged = [
        Snapshot.load(tmp_path / "snapshots" / (r["snapshot_id"] + ".json"))
        for r in algo._archive
    ]
    assert merged.parent_id == primary.id
    records = [
        json.loads(p.read_text())
        for p in sorted((tmp_path / "trajectories").glob("*-decision.json"))
    ]
    merge_record = records[-2]
    assert merge_record["snapshot_id"] == merged.id
    assert merge_record["parent_id"] == merged.parent_id
    assert merge_record["donor_id"] == donor.id
    assert "index" not in merge_record and "parents" not in merge_record

    # Run another proposal using loaded Snapshots. The donor must not become an
    # ancestor just because its changes were integrated into the merged version.
    with merged.check_out() as directory:
        (directory / PATHS[MiniAgent]).write_text("AB-next")
        descendant = merged.commit(directory)
    algo._versions[descendant.id] = (descendant, algo._versions[merged.id][1])
    algo.worker.edits = iter(["next"])
    primary_row = {**algo._archive[-1], "snapshot_id": descendant.id}
    for snapshot in (seed, primary, donor, merged):
        algo._versions[snapshot.id] = (snapshot, algo._versions[snapshot.id][1])
    asyncio.run(algo._propose([primary_row, algo._archive[2]], {"t0", "t1"}, 3))
    assert algo.worker.references[-1]["ancestor"]["snapshot_id"] == seed.id
    assert not list((tmp_path / "working").iterdir())


@pytest.mark.parametrize("initial,desired", [(False, True), (True, False)])
@pytest.mark.parametrize(
    "content", [b"#!/bin/sh\necho capability\n", b"\x7fELF\xffbinary"]
)
def test_recombination_restores_permission_only_changes(
    monkeypatch, initial, desired, content
):
    tool = "tools/capability"
    algo, _ = setup(
        monkeypatch,
        ["A", "B", "AB"],
        {"A": {"t0": 1}, "B": {"t1": 1, "t2": 1}, "AB": {"t0": 1, "t1": 1, "t2": 1}},
        exploration_probability=1.0,
        seed=4,
        merge_every=3,
    )
    with algo.target.snapshot.check_out() as directory:
        (directory / tool).write_bytes(content)
        (directory / tool).chmod(0o755 if initial else 0o644)
        baseline = algo._commit(algo.target.snapshot, directory)
    algo.target.update(baseline)

    target_run, worker_run = MiniAgent._run, Worker._run

    async def score_permission(self, prompt, working_dir=None):
        result = await target_run(self, prompt, working_dir)
        if prompt == "t0" and self.snapshot.files[tool].executable != desired:
            return replace(result, output="0")
        return result

    async def edit_permission(self, prompt, working_dir=None):
        result = await worker_run(self, prompt, working_dir)
        if working_dir is not None:
            if len(self.prompts) == 1:
                (working_dir / tool).chmod(0o755 if desired else 0o644)
            elif prompt.startswith("[DarwinX: recombine]"):
                merge = json.loads(
                    prompt.split("RECOMBINATION INPUT (empty for mutation):\n")[
                        1
                    ].split("\nFor recombination")[0]
                )
                donor = next(r for r in merge if r["role"] == "donor")
                ancestor = next(r for r in merge if r["role"] == "ancestor")
                donor_file = working_dir / donor["directory"] / tool
                ancestor_file = working_dir / ancestor["directory"] / tool
                assert donor_file.read_bytes() == ancestor_file.read_bytes() == content
                assert bool(ancestor_file.stat().st_mode & 0o111) == initial
                assert bool(donor_file.stat().st_mode & 0o111) == desired
                assert bool((working_dir / tool).stat().st_mode & 0o111) == initial
                shutil.copy2(donor_file, working_dir / tool)

        return result

    monkeypatch.setattr(MiniAgent, "_run", score_permission)
    monkeypatch.setattr(Worker, "_run", edit_permission)
    final = asyncio.run(algo.evolve())

    assert (
        algo._versions[algo._archive[1]["snapshot_id"]][0].files[tool].content
        == baseline.files[tool].content
    )
    assert (
        algo._versions[algo._archive[2]["snapshot_id"]][0].files[tool].executable
        == initial
    )
    assert (
        algo._archive[3]["accepted"]
        and algo._archive[3]["parent_id"] == algo._archive[2]["snapshot_id"]
    )
    assert algo._archive[3]["donor_id"] == algo._archive[1]["snapshot_id"]
    assert final.files[tool].content == content
    assert final.files[tool].executable == desired


def test_exploration_uses_an_eligible_sibling_instead_of_only_the_best(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        ["A", "B"],
        {
            "A": {"t0": 1},
            "B": {"t1": 1},
        },
        exploration_probability=1.0,
        seed=4,
    )
    asyncio.run(algo.evolve())
    assert algo._archive[1]["accepted"] and algo._archive[2]["accepted"]
    assert algo._archive[2]["parent_id"] == algo._archive[0]["snapshot_id"]
    assert algo.worker.checkouts[0] == algo.worker.checkouts[1]


def test_screen_failure_remains_archived_but_does_not_get_confirmation(monkeypatch):
    algo, calls = setup(monkeypatch, ["FAIL"], {})
    original = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == original.id
    assert len(calls) == 12
    assert algo._archive[1]["fidelity"] == "screen"
    assert not algo._archive[1]["accepted"]
    assert len(algo.worker.lessons) == 1


@pytest.mark.parametrize(
    "edit,problem",
    [({}, "unchanged"), ({"outside.txt": "oops"}, "exactly one component")],
)
def test_declined_edit_costs_a_step_and_search_continues(monkeypatch, edit, problem):
    algo, _ = setup(monkeypatch, [edit, "GOOD"], {"GOOD": {"t0": 1}})
    final = asyncio.run(algo.evolve())
    assert final.files[PATHS[MiniAgent]].content == b"GOOD"
    assert len(algo._archive) == 2 and len(algo.worker.lessons) == 1
    assert problem in algo._declined[0]["problem"]
    assert algo._declined[0]["problem"] in algo.worker.prompts[1]


def test_duplicate_files_are_declined_despite_different_snapshot_ids(monkeypatch):
    algo, _ = setup(monkeypatch, ["GOOD", "GOOD"], {"GOOD": {"t0": 1}})
    asyncio.run(algo.evolve())
    assert len(algo._archive) == 2
    assert len(algo._declined) == 1


@pytest.mark.parametrize("tolerance,accepted", [(0.4, False), (0.5, True)])
def test_fractional_regression_budget_is_sum_not_mean(monkeypatch, tolerance, accepted):
    algo, _ = setup(
        monkeypatch,
        ["TRADE"],
        {"SEED": {"t0": 0.5, "t1": 0.5}, "TRADE": {"t0": 0.25, "t1": 0.25, "t2": 1}},
        regression_tolerance=tolerance,
    )
    asyncio.run(algo.evolve())
    record = algo._archive[1]
    assert record["gain"] == record["regression_mass"] == 0.5
    assert record["accepted"] == accepted


def test_nonzero_tolerance_still_preserves_inherited_solved_set(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        ["TRADE"],
        {
            "SEED": {"t0": 1},
            "TRADE": {"t0": 0.75, "t1": 1},
        },
        regression_tolerance=1.0,
    )
    original = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == original.id
    assert not algo._archive[1]["accepted"]


@pytest.mark.parametrize(
    "config,field",
    [
        ({"max_steps": 0}, "max_steps"),
        ({"screen_size": 0}, "screen_size"),
        ({"screen_samples": True}, "screen_samples"),
        ({"confirm_samples": 0}, "confirm_samples"),
        ({"screen_samples": 3, "confirm_samples": 2}, "confirm_samples"),
        ({"regression_tolerance": -1}, "regression_tolerance"),
        ({"screen_regression_tolerance": -1}, "screen_regression_tolerance"),
        ({"solved_threshold": 0}, "solved_threshold"),
        ({"solved_threshold": 1.1}, "solved_threshold"),
        ({"exploration_probability": 1.1}, "exploration_probability"),
        ({"merge_every": -1}, "merge_every"),
        ({"seed": False}, "seed"),
        ({"max_evidence_chars": 0}, "max_evidence_chars"),
    ],
)
def test_invalid_parameters_fail_at_startup(monkeypatch, config, field):
    with pytest.raises(ValueError, match=field):
        setup(monkeypatch, [], {}, **config)


@pytest.mark.parametrize(
    "tasks,problem",
    [
        ((), "non-empty train"),
        ((Task("same", "one"), Task("same", "two")), "unique train task_id"),
    ],
)
def test_train_prerequisites(monkeypatch, tasks, problem):
    benchmark = Scores()
    benchmark._splits = {"train": tasks, "dev": (), "test": ()}
    with pytest.raises(ValueError, match=problem):
        setup(monkeypatch, [], {}, benchmark=benchmark)


@pytest.mark.parametrize("role", [None, "llm", "agent"])
def test_text_worker_is_refused_before_any_evaluation(monkeypatch, role):
    algo, calls = setup(monkeypatch, [], {})
    config = {"llm": {"model_name": "offline-worker"}}
    if role is not None:
        config["type"] = role
    with pytest.raises(ValueError, match="worker.type"):
        DarwinX(
            {},
            target=algo.target,
            benchmark=Scores(),
            worker=LLM(config),
        )
    assert calls == []


def test_out_of_range_primary_scores_fail_explicitly(monkeypatch):
    algo, _ = setup(monkeypatch, [], {"SEED": {"t0": 2}})
    with pytest.raises(ValueError, match=r"scores in \[0, 1\]"):
        asyncio.run(algo.evolve())
