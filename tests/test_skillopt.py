import asyncio
import json
from dataclasses import replace

import pytest

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms import SkillOpt
from flashrsi.algorithms.skillopt._patch import _Patch
from flashrsi.config import load_config, prepare_run_dir
from flashrsi.core import Agent, Benchmark, Snapshot, Task, Trajectory


class MemoryBenchmark(Benchmark):
    name = "memory"
    description = "Offline disjoint splits."
    primary_metric = "accuracy"
    metadata = {}

    def load(self):
        if self._splits is None:
            self._splits = {
                "train": tuple(
                    Task(f"train-{i}", f"train-{i}", "right") for i in range(2)
                ),
                "dev": (Task("dev-only", "dev-only", "right"),),
                "test": (Task("test-only", "test-only", "right"),),
            }
        return self._splits

    def grade(self, results):
        return tuple(
            replace(
                item,
                metrics={
                    "accuracy": float(
                        item.output == "right" and item.status == "finished"
                    )
                },
            )
            for item in results
        )


class ScriptedWorker(Agent):
    name = "scripted"
    description = "Finite offline Worker."

    def __init__(self, replies):
        super().__init__({"llm": {"model_name": "offline-worker"}})
        self.replies = iter(replies)
        self.prompts = []

    async def _run(self, prompt, working_dir=None):
        assert working_dir is None
        self.prompts.append(prompt)
        reply = next(self.replies)
        return (
            reply
            if isinstance(reply, Trajectory)
            else Trajectory(output=json.dumps(reply))
        )


def patch(content="SOLVED", path="skills/main.md"):
    return {
        "reasoning": "Reusable procedure",
        "edits": [{"path": path, "op": "append", "content": content}],
    }


def make_target(monkeypatch, cls=MiniAgent):
    calls = []

    async def run(self, prompt, working_dir=None):
        texts = [
            entry.content
            for entry in self.snapshot.files.values()
            if entry.component == "skill"
        ]
        # Access the activated version to exercise the real Agent context.
        for path, entry in self.snapshot.files.items():
            assert (self.files_dir / path).read_bytes() == entry.content
        calls.append((prompt, self.snapshot.id))
        return Trajectory(
            output="right" if any(b"SOLVED" in text for text in texts) else "wrong"
        )

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline-target"}})
    return target, calls


def algorithm(target, worker, **config):
    return SkillOpt(
        {"num_epochs": 1, "batch_size": 2, "reflection_minibatch_size": 2, **config},
        target=target,
        worker=worker,
        benchmark=MemoryBenchmark(),
    )


@pytest.mark.parametrize(
    "cls,path",
    [(MiniAgent, "skills/main.md"), (ClaudeCode, "skills/reasoning/SKILL.md")],
)
def test_same_algorithm_accepts_for_both_native_snapshot_layouts(
    monkeypatch, cls, path
):
    target, calls = make_target(monkeypatch, cls)
    original = target.snapshot
    worker = ScriptedWorker(
        [
            patch(
                "---\nname: reasoning\ndescription: Useful reasoning\n---\nSOLVED", path
            )
        ]
    )
    final = asyncio.run(algorithm(target, worker).evolve())
    assert isinstance(final, Snapshot)
    assert target.snapshot.id == final.id != original.id
    assert final.parent_id == original.id
    assert b"SOLVED" in final.files[path].content
    assert {p: f for p, f in final.files.items() if f.component != "skill"} == {
        p: f for p, f in original.files.items() if f.component != "skill"
    }
    assert calls[0] == ("dev-only", original.id)
    assert calls[-1] == ("dev-only", final.id)
    assert "dev-only" not in worker.prompts[0]
    assert "test-only" not in worker.prompts[0]
    assert "right" in worker.prompts[0]  # ground truth is training feedback
    assert "RunConfig" not in worker.prompts[0]


def test_ties_rejected_and_recent_rejections_reach_next_reflection(monkeypatch):
    target, calls = make_target(monkeypatch)
    original = target.snapshot
    worker = ScriptedWorker([patch("No measurable improvement"), {"edits": []}])
    final = asyncio.run(
        algorithm(
            target, worker, num_epochs=2, use_slow_update=False, use_meta_skill=False
        ).evolve()
    )
    assert final.id == original.id
    assert "No measurable improvement" in worker.prompts[1]
    assert len([p for p, _ in calls if p == "dev-only"]) == 2


def test_success_failure_merge_and_rank_honor_budget(monkeypatch):
    target, _ = make_target(monkeypatch)

    async def mixed(self, prompt, working_dir=None):
        return Trajectory(output="right" if prompt == "train-0" else "wrong")

    monkeypatch.setattr(MiniAgent, "_run", mixed)
    failed, passed = patch("Fix failures"), patch("Retain successes")
    merged = {"edits": [*failed["edits"], *passed["edits"]]}
    worker = ScriptedWorker([failed, passed, merged, {"selected_indices": [0]}])
    asyncio.run(algorithm(target, worker, edit_budget=1).evolve())
    assert [p.splitlines()[0] for p in worker.prompts] == [
        "[SkillOpt: failure]",
        "[SkillOpt: success]",
        "[SkillOpt: merge]",
        "[SkillOpt: rank]",
    ]
    assert '"task_id": "train-0"' not in worker.prompts[0]
    assert '"task_id": "train-1"' not in worker.prompts[1]


def test_multilevel_merge_keeps_sources_separate_until_final_ranking(monkeypatch):
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([]), merge_batch_size=2, edit_budget=2)
    proposals = {
        source: [
            _Patch.parse(json.dumps(patch(f"{source}-{index}")), source)
            for index in range(count)
        ]
        for source, count in (("failure", 5), ("success", 3))
    }
    calls = []

    async def ask(prompt, *, label="worker"):
        if label == "rank":
            edits = json.loads(prompt.split("EDITS: ", 1)[1])
            assert len(edits) == 8
            calls.append("rank")
            return json.dumps({"selected_indices": [0, 7]})
        assert label == "merge"
        source, raw = prompt.split("SOURCE GROUP: ", 1)[1].split("\nPROPOSALS:\n", 1)
        patches = json.loads(raw)
        assert len(patches) == 2  # Singleton remainders require no Worker call.
        edits = [edit for proposal in patches for edit in proposal["edits"]]
        if source != "failure_first":
            assert {edit["source_type"] for edit in edits} == {source}
        calls.append(source)
        return json.dumps({"edits": edits})

    monkeypatch.setattr(algo, "_ask", ask)
    result = asyncio.run(algo._consolidate({}, proposals))

    assert calls == ["failure"] * 4 + ["success"] * 2 + ["failure_first", "rank"]
    assert [(edit.content, edit.source_type) for edit in result.edits] == [
        ("failure-0", "failure"),
        ("success-2", "success"),
    ]
    assert {source: len(group) for source, group in proposals.items()} == {
        "failure": 5,
        "success": 3,
    }


def test_worker_error_and_invalid_patch_do_not_change_target(monkeypatch):
    target, _ = make_target(monkeypatch)
    original = target.snapshot
    worker = ScriptedWorker(
        [Trajectory(status="error", error_message="provider unavailable")]
    )
    with pytest.raises(RuntimeError, match="Worker failed"):
        asyncio.run(algorithm(target, worker).evolve())
    assert target.snapshot.id == original.id
    worker = ScriptedWorker([Trajectory(output="invalid json")])
    with pytest.raises(ValueError, match="JSON"):
        asyncio.run(algorithm(target, worker).evolve())
    assert target.snapshot.id == original.id


def test_scope_rejects_new_non_skill_files_without_switching(monkeypatch):
    target, _ = make_target(monkeypatch)
    original = target.snapshot
    worker = ScriptedWorker([patch(path="prompts/new.md")])
    with pytest.raises(ValueError, match="hidden component"):
        asyncio.run(algorithm(target, worker).evolve())
    assert target.snapshot.id == original.id


def test_noop_and_step_limit_do_not_trigger_extra_dev_calls(monkeypatch):
    target, calls = make_target(monkeypatch)
    worker = ScriptedWorker([{"edits": []}])
    asyncio.run(
        algorithm(target, worker, max_steps=1, batch_size=1, num_epochs=4).evolve()
    )
    assert len(worker.prompts) == 1
    assert len(calls) == 2  # baseline and one training task


def test_slow_update_compares_same_training_tasks_and_memory_reaches_next_epoch(
    monkeypatch,
):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(
        [
            {"edits": []},
            {"edits": []},
            {"meta_skill_content": "Preserve the evidence checks"},
            {"guidance": [{"path": "skills/main.md", "content": "SOLVED"}]},
            {"edits": []},
            {"meta_skill_content": "Keep useful checks"},
            {"guidance": []},
        ]
    )
    final = asyncio.run(algorithm(target, worker, num_epochs=3).evolve())
    assert b"SLOW_UPDATE_START" in final.files["skills/main.md"].content
    assert "Preserve the evidence checks" in worker.prompts[4]
    comparison = worker.prompts[2].split("COMPARISON: ")[1]
    pairs = json.loads(comparison)
    assert all(pair["previous"]["task"] == pair["current"]["task"] for pair in pairs)
    assert {pair["previous"]["task"]["task_id"] for pair in pairs} == {
        "train-0",
        "train-1",
    }
    assert "dev-only" not in comparison and "test-only" not in comparison


def test_records_include_rejected_candidates_and_worker_trajectories(
    monkeypatch, tmp_path
):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker([patch("no improvement")])
    algo = algorithm(target, worker)
    config = load_config(
        overrides={
            "run": {"output_dir": str(tmp_path)},
            "agent": dict(target.config),
            "algorithm": {"worker": dict(worker.config)},
        }
    )
    algo._run_dir = prepare_run_dir(config)
    final = asyncio.run(algo.evolve())
    snapshots = list((algo._run_dir / "snapshots").glob("*.json"))
    assert len(snapshots) == 2
    assert final.id in {Snapshot.load(path).id for path in snapshots}
    records = [
        json.loads(p.read_text())
        for p in (algo._run_dir / "trajectories").glob("*.json")
    ]
    assert any(r.get("accepted") is False and "candidate_id" in r for r in records)
    assert any(
        r.get("trajectory", {}).get("messages", [{}])[0].get("type") == "RunConfig"
        for r in records
    )
    assert not list((algo._run_dir / "working").iterdir())


@pytest.mark.parametrize(
    "key,value",
    [
        ("num_epochs", 0),
        ("batch_size", True),
        ("merge_batch_size", 1),
        ("edit_budget", -1),
        ("max_steps", 0),
        ("seed", 1.5),
        ("success_threshold", float("nan")),
        ("use_meta_skill", "yes"),
    ],
)
def test_invalid_algorithm_parameters_fail_before_execution(monkeypatch, key, value):
    target, calls = make_target(monkeypatch)
    with pytest.raises(ValueError, match="algorithm"):
        algorithm(target, ScriptedWorker([]), **{key: value})
    assert calls == []


def test_empty_split_and_environment_tasks_fail_before_any_model(monkeypatch):
    target, calls = make_target(monkeypatch)
    benchmark = MemoryBenchmark()
    benchmark.load()
    benchmark._splits["train"] = ()
    with pytest.raises(ValueError, match="non-empty"):
        SkillOpt({}, target=target, worker=ScriptedWorker([]), benchmark=benchmark)
    benchmark._splits["train"] = (Task("env", "run", env="image"),)
    with pytest.raises(ValueError, match="environment-aware"):
        SkillOpt({}, target=target, worker=ScriptedWorker([]), benchmark=benchmark)
    assert calls == []
