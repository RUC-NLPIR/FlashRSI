"""Compare parallel scheduling with serial SkillOpt using deterministic Workers."""

import asyncio
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from flashrsi.agents import LLM
from flashrsi.algorithms import SkillOpt
from flashrsi.algorithms.skillopt._patch import _Patch
from flashrsi.core import Agent, Benchmark, Task, Trajectory
from scripts._experiment_runtime import CachedLLM
from scripts._parallel_skillopt import ParallelSkillOpt


class FakeBenchmark(Benchmark):
    name = "fake"
    description = "Independent offline splits."
    primary_metric = "accuracy"
    metadata = {}

    def load(self):
        if self._splits is None:
            self._splits = {
                "train": tuple(Task(f"t{i}", f"train-{i}", "yes") for i in range(12)),
                "dev": (Task("d", "dev", "yes"),),
                "test": (Task("test", "test", "yes"),),
            }
        return self._splits

    def grade(self, trajectories):
        return tuple(
            replace(t, metrics={"accuracy": float(t.output == "yes")})
            for t in trajectories
        )


class FakeTarget(Agent):
    name = "fake"
    description = "Use versioned skill content without a model."

    async def _run(self, prompt, working_dir=None):
        self.calls.append((prompt, self.snapshot.id))
        solved = b"SOLVED" in self.snapshot.files["skills/main.md"].content
        return Trajectory(
            output="yes"
            if solved or (prompt.startswith("train-") and int(prompt[6:]) % 2 == 0)
            else "no"
        )


def _reply(prompt, ordinal, empty_ordinals=()):
    prefix = prompt.splitlines()[0]
    if prefix in {"[SkillOpt: failure]", "[SkillOpt: success]"}:
        if ordinal in empty_ordinals:
            return {"edits": []}
        return {
            "reasoning": f"request {ordinal}",
            "edits": [
                {
                    "path": "skills/main.md",
                    "op": "append",
                    "content": "SOLVED " + hashlib.sha256(prompt.encode()).hexdigest(),
                }
            ],
        }
    if prefix == "[SkillOpt: merge]":
        patches = json.loads(prompt.split("PROPOSALS:\n", 1)[1])
        return {
            "reasoning": f"merge request {ordinal}",
            "edits": [edit for patch in patches for edit in patch["edits"]],
        }
    if prefix == "[SkillOpt: rank]":
        budget = int(re.search(r"Select at most (\d+) edits", prompt)[1])
        return {"selected_indices": list(range(budget))}
    if prefix == "[SkillOpt: meta]":
        return {"meta_skill_content": "Keep the grounded procedure."}
    if prefix == "[SkillOpt: slow]":
        return {"guidance": [{"path": "skills/main.md", "content": "SOLVED guidance"}]}
    raise AssertionError(prefix)


class FakeWorker(Agent):
    name = "fake-worker"
    description = "Return deterministic prompt- and ordinal-dependent JSON."

    def __init__(self, *, empty_ordinals=(), error_at=None):
        super().__init__({"llm": {"model_name": "offline"}})
        self.requests = []
        self.completions = []
        self.active = 0
        self.max_active = 0
        self.events = []
        self.empty_ordinals = empty_ordinals
        self.error_at = error_at
        self.started = asyncio.Event()

    async def _run(self, prompt, working_dir=None):
        ordinal = len(self.requests)
        self.requests.append(prompt)
        self.events.append(("start", ordinal))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            delay = 0.025 if ordinal % 3 == 0 else 0.004
            if self.error_at is not None:
                delay = 0.001 if ordinal == self.error_at else 0.1
            await asyncio.sleep(delay)
            if ordinal == self.error_at:
                return Trajectory(status="error", error_message="offline failure")
            return Trajectory(
                output=json.dumps(_reply(prompt, ordinal, self.empty_ordinals)),
                usage={"ordinal": ordinal},
            )
        finally:
            self.active -= 1
            self.completions.append(ordinal)
            self.events.append(("finish", ordinal))


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "skills").mkdir(parents=True)
    (root / "skills/main.md").write_text("Initial skill\n")
    (root / "components.yaml").write_text("skill: ['skills/**']\n")
    return root


def _algorithm(cls, source, worker=None, **config):
    target = FakeTarget({"source_dir": str(source), "llm": {"model_name": "offline"}})
    target.calls = []
    result = cls(
        {"reflection_minibatch_size": 8, "merge_batch_size": 2, **config},
        target=target,
        worker=worker or FakeWorker(),
        benchmark=FakeBenchmark(),
    )
    result._rejected = [{"score": 0.25, "patch": {"edits": []}}]
    result._meta_skill = "Existing optimizer guidance."
    return result


def _training(count=41):
    return tuple(
        Trajectory(
            task=Task(f"t{i}", f"train-{i}", "yes"),
            status="error" if i % 13 == 0 else "finished",
            error_message="failed" if i % 13 == 0 else None,
            output="yes" if i % 3 == 0 else "no",
            metrics={"accuracy": float(i % 3 == 0)},
        )
        for i in range(count)
    )


def test_reflection_and_consolidation_match_serial_prompts_ordinals_and_results(source):
    serial = _algorithm(SkillOpt, source, FakeWorker(empty_ordinals=(1,)))
    parallel = _algorithm(
        ParallelSkillOpt, source, FakeWorker(empty_ordinals=(1,)), worker_concurrency=3
    )

    async def execute(algo):
        files = algo._read_text(algo.target.snapshot)
        proposals = await algo._reflect(algo.target.snapshot, files, _training())
        patch = await algo._consolidate(files, proposals)
        return proposals, patch

    expected = asyncio.run(execute(serial))
    actual = asyncio.run(execute(parallel))
    assert actual == expected
    assert parallel.worker.requests == serial.worker.requests
    assert list(actual[0]) == ["failure", "success"]
    assert parallel.worker.max_active == 3
    assert serial.worker.max_active == 1
    assert parallel.worker.completions != list(range(len(parallel.worker.requests)))
    # The last short minibatch contains one failure and never invents a success.
    reflection = [p for p in parallel.worker.requests if "EVIDENCE (" in p]
    assert len(reflection) == 11
    assert reflection[-1].startswith("[SkillOpt: failure]")
    assert '"task_id": "t40"' in reflection[-1]


def test_merge_tree_and_source_order_match_while_branches_overlap(source):
    proposals = {
        source_type: [
            _Patch.parse(
                json.dumps(
                    {
                        "edits": [
                            {
                                "path": "skills/main.md",
                                "op": "append",
                                "content": f"{source_type}-{index}",
                            }
                        ]
                    }
                ),
                source_type,
            )
            for index in range(count)
        ]
        for source_type, count in (("failure", 5), ("success", 3))
    }
    serial = _algorithm(SkillOpt, source, edit_budget=2)
    parallel = _algorithm(ParallelSkillOpt, source, edit_budget=2, worker_concurrency=4)
    expected = asyncio.run(serial._consolidate({}, proposals))
    actual = asyncio.run(parallel._consolidate({}, proposals))
    assert actual == expected
    assert parallel.worker.requests == serial.worker.requests
    groups = [
        p.split("SOURCE GROUP: ", 1)[1].splitlines()[0]
        for p in parallel.worker.requests
        if p.startswith("[SkillOpt: merge]")
    ]
    assert groups == ["failure"] * 4 + ["success"] * 2 + ["failure_first"]
    assert parallel.worker.requests[-1].startswith("[SkillOpt: rank]")
    # Source success starts after the last failure request starts, but before it
    # finishes. Its ordinal stays 4, exactly as in the original serial traversal.
    events = parallel.worker.events
    assert events.index(("start", 3)) < events.index(("start", 4))
    assert events.index(("start", 4)) < events.index(("finish", 3))
    assert 1 < parallel.worker.max_active <= 4
    assert {s: len(g) for s, g in proposals.items()} == {"failure": 5, "success": 3}


@pytest.mark.parametrize("concurrency", [1, 2, 4])
def test_configured_limit_is_effective_and_actual_source_is_recorded(
    source, concurrency
):
    algo = _algorithm(ParallelSkillOpt, source, worker_concurrency=concurrency)
    asyncio.run(algo._reflect(algo.target.snapshot, {}, _training()))
    assert algo.worker.max_active == concurrency
    assert algo.config.worker_concurrency == concurrency
    assert (
        algo.config.parallel_skillopt_sha256
        == hashlib.sha256(
            (Path(__file__).parents[1] / "scripts/_parallel_skillopt.py").read_bytes()
        ).hexdigest()
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_concurrency_fails_before_requests(source, value):
    with pytest.raises(ValueError, match="worker_concurrency"):
        _algorithm(ParallelSkillOpt, source, worker_concurrency=value)


def test_complete_epochs_keep_target_calls_slow_meta_and_strict_gates_identical(source):
    config = {
        "num_epochs": 2,
        "batch_size": 6,
        "reflection_minibatch_size": 2,
        "slow_update_samples": 4,
        "edit_budget": 2,
    }
    serial = _algorithm(SkillOpt, source, **config)
    parallel = _algorithm(ParallelSkillOpt, source, worker_concurrency=4, **config)
    expected = asyncio.run(serial.evolve())
    actual = asyncio.run(parallel.evolve())
    assert actual == expected
    assert parallel.worker.requests == serial.worker.requests
    assert parallel.target.calls == serial.target.calls
    assert parallel._rejected == serial._rejected
    assert parallel._meta_skill == serial._meta_skill
    assert any(p.startswith("[SkillOpt: meta]") for p in parallel.worker.requests)
    assert any(p.startswith("[SkillOpt: slow]") for p in parallel.worker.requests)
    assert all(question != "test" for question, _ in parallel.target.calls)
    for method in ("evolve", "_fast_update", "_merge", "_slow_update", "_select"):
        assert getattr(ParallelSkillOpt, method) is getattr(SkillOpt, method)


def test_cached_worker_keys_match_serial_and_parallel_replay(
    monkeypatch, source, tmp_path
):
    requests = {}

    async def run(self, prompt, working_dir=None):
        calls = requests.setdefault(self, [])
        ordinal = len(calls)
        calls.append(prompt)
        await asyncio.sleep(0.005 if ordinal % 2 else 0.01)
        return Trajectory(output=json.dumps(_reply(prompt, ordinal)))

    monkeypatch.setattr(LLM, "_run", run)

    def make(cls, folder):
        worker = CachedLLM({"llm": {"model_name": "offline"}}).configure_experiment(
            folder
        )
        return _algorithm(cls, source, worker)

    async def execute(algo):
        files = algo._read_text(algo.target.snapshot)
        proposals = await algo._reflect(algo.target.snapshot, files, _training(17))
        return await algo._consolidate(files, proposals)

    serial = make(SkillOpt, tmp_path / "serial-cache")
    parallel = make(ParallelSkillOpt, tmp_path / "parallel-cache")
    assert asyncio.run(execute(serial)) == asyncio.run(execute(parallel))
    assert requests[serial.worker] == requests[parallel.worker]
    assert {p.name for p in (tmp_path / "serial-cache").rglob("*.json")} == {
        p.name for p in (tmp_path / "parallel-cache").rglob("*.json")
    }
    replay = make(ParallelSkillOpt, tmp_path / "parallel-cache")
    serial_replay = make(SkillOpt, tmp_path / "serial-cache")
    assert asyncio.run(execute(replay)) == asyncio.run(execute(serial_replay))
    assert replay.worker not in requests


def test_worker_failure_cancels_all_parallel_waits(source):
    worker = FakeWorker(error_at=0)
    algo = _algorithm(ParallelSkillOpt, source, worker, worker_concurrency=3)
    with pytest.raises(RuntimeError, match="Worker failed"):
        asyncio.run(algo._reflect(algo.target.snapshot, {}, _training()))
    assert worker.active == 0
    assert worker.max_active == 3
    assert sorted(worker.completions) == list(range(len(worker.requests)))
    assert all("[SkillOpt: merge]" not in prompt for prompt in worker.requests)


def test_cancellation_does_not_leave_worker_tasks_running(source):
    worker = FakeWorker()
    algo = _algorithm(ParallelSkillOpt, source, worker)

    async def exercise():
        future = asyncio.create_task(
            algo._reflect(algo.target.snapshot, {}, _training())
        )
        await worker.started.wait()
        future.cancel()
        with pytest.raises(asyncio.CancelledError):
            await future

    asyncio.run(exercise())
    assert worker.active == 0


@pytest.mark.parametrize("proposals", [{}, {"failure": [], "success": []}])
def test_empty_groups_do_not_add_worker_requests(source, proposals):
    algo = _algorithm(ParallelSkillOpt, source)
    assert asyncio.run(algo._reflect(algo.target.snapshot, {}, ())) == {
        "failure": [],
        "success": [],
    }
    assert asyncio.run(algo._consolidate({}, proposals)) == _Patch()
    assert algo.worker.requests == []
