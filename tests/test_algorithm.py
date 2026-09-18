import asyncio
import json
from dataclasses import replace

import pytest

from flashrsi.core import Agent, Algorithm, Benchmark, Snapshot, Task, Trajectory


class MemoryBenchmark(Benchmark):
    def __init__(self, *, env=None):
        super().__init__()
        self.loads = 0
        self.env = env

    def load(self):
        self.loads += 1
        self._splits = {
            "train": (),
            "dev": (),
            "test": (Task("test", "question", env=self.env),),
        }
        return self._splits

    def grade(self, trajectories):
        return trajectories


class Target(Agent):
    name = "test_target"

    async def _run(self, prompt, working_dir=None):
        raise AssertionError("initialization must not execute tasks")


class Worker(Agent):
    name = "test_worker"

    async def _run(self, prompt, working_dir=None):
        return Trajectory(output="unused")


class Example(Algorithm):
    evolve_scope = {"skill"}
    observation_scope = {"skill", "prompt"}
    _defaults = {"rounds": 2, "options": {"enabled": True}}

    def _check(self):
        assert self.benchmark.loads == 1
        assert self.config.rounds > 0
        with self.target.snapshot.check_out() as directory:
            assert (directory / "prompts/main.md").is_file()

    async def evolve(self):
        return self.target.snapshot


@pytest.fixture
def target(tmp_path):
    for component in ("skills", "prompts", "code"):
        (tmp_path / component).mkdir()
        (tmp_path / component / "main.md").write_text(component)
    (tmp_path / "components.yaml").write_text(
        "skill: ['skills/**']\nprompt: ['prompts/**']\ncode: ['code/**']\n"
    )
    return Target({"source_dir": tmp_path})


def test_base_initializes_scope_data_and_defaults_before_algorithm_hook(target):
    benchmark = MemoryBenchmark()
    config = {"rounds": 3}
    algo = Example(config, target=target, worker=Worker(), benchmark=benchmark)
    assert algo.config.rounds == 3
    assert config == {"rounds": 3}
    algo.config.options.enabled = False
    assert Example._defaults["options"]["enabled"] is True

    baseline = target.snapshot
    with baseline.check_out() as directory:
        assert {
            path.relative_to(directory).as_posix() for path in directory.rglob("*.md")
        } == {
            "skills/main.md",
            "prompts/main.md",
        }
        (directory / "skills/main.md").write_text("evolved")
        candidate = baseline.commit(directory)
    assert candidate.files["skills/main.md"].content == b"evolved"
    assert candidate.files["code/main.md"] == baseline.files["code/main.md"]

    with baseline.check_out() as directory:
        prompt = directory / "prompts/main.md"
        prompt.chmod(0o644)
        prompt.write_text("changed observation")
        with pytest.raises(ValueError, match="outside allowed components"):
            baseline.commit(directory)

    assert asyncio.run(algo.evolve()) is target.snapshot
    assert benchmark.loads == 1


def test_unknown_scope_is_rejected_by_agent_at_initialization(target):
    class Unknown(Algorithm):
        observation_scope = {"missing"}

    with pytest.raises(ValueError, match="unsupported components"):
        Unknown({}, target=target, worker=Worker(), benchmark=MemoryBenchmark())


def test_base_checks_environment_support_including_final_test(target):
    with pytest.raises(ValueError, match="environment-aware"):
        Algorithm(
            {}, target=target, worker=Worker(), benchmark=MemoryBenchmark(env="image")
        )

    class EnvironmentTarget(Target):
        async def rollout(self, tasks, *, snapshot=None):
            raise AssertionError("initialization must not execute tasks")

    adapted = EnvironmentTarget(target.config)
    algo = Algorithm(
        {}, target=adapted, worker=Worker(), benchmark=MemoryBenchmark(env="image")
    )
    assert algo.benchmark.test[0].env == "image"


def test_base_accepts_bound_environment_runner_and_text_worker(target):
    async def run_environment(agent, task):
        raise AssertionError("initialization must not execute tasks")

    target._env_runner = run_environment
    algo = Algorithm(
        {}, target=target, worker=Worker(), benchmark=MemoryBenchmark(env="image")
    )
    assert algo.benchmark.test[0].env == "image"
    assert type(target).rollout is Agent.rollout


def test_base_rejects_unimplemented_execution_before_loading_data(target):
    class MissingWorker(Agent):
        name = "missing_worker"

    benchmark = MemoryBenchmark()
    with pytest.raises(ValueError, match="worker.*_run"):
        Algorithm({}, target=target, worker=MissingWorker(), benchmark=benchmark)
    assert benchmark.loads == 0


def recording_algorithm(target, tmp_path, *, worker=None, benchmark=None):
    algo = Example(
        {},
        target=target,
        worker=worker or Worker(),
        benchmark=benchmark or MemoryBenchmark(),
    )
    algo._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algo._run_dir / name).mkdir(parents=True)
    return algo


def test_shared_text_candidate_respects_scope_and_preserves_other_files(
    target, tmp_path
):
    # Add a binary resource before creating the next target version.
    (target.config.source_dir / "skills/image.bin").write_bytes(b"\xff\xfe")
    target = Target(target.config)
    algo = recording_algorithm(target, tmp_path)
    baseline = target.snapshot
    assert algo._read_text(baseline) == {
        "prompts/main.md": "prompts",
        "skills/main.md": "skills",
    }
    assert algo._candidate(baseline, algo._read_text(baseline)) is baseline
    candidate = algo._candidate(
        baseline, {"skills/main.md": "changed", "skills/new.md": "new"}
    )
    assert target.snapshot is baseline
    assert candidate.parent_id == baseline.id
    assert candidate.files["skills/main.md"].content == b"changed"
    for path in ("skills/image.bin", "prompts/main.md", "code/main.md"):
        assert candidate.files[path] == baseline.files[path]
    assert (
        Snapshot.load(algo._run_dir / "snapshots" / f"{candidate.id}.json") == candidate
    )
    assert not list((algo._run_dir / "working").iterdir())

    with pytest.raises(ValueError, match="non-text"):
        algo._candidate(baseline, {"skills/image.bin": "replace binary"})
    # The checkout is read-only; privileged users reach commit's scope check.
    with pytest.raises((PermissionError, ValueError)):
        algo._candidate(baseline, {"prompts/main.md": "change readonly"})
    with pytest.raises(ValueError, match="hidden component"):
        algo._candidate(baseline, {"code/new.md": "change hidden"})
    assert target.snapshot is baseline
    assert not list((algo._run_dir / "working").iterdir())


@pytest.mark.parametrize(
    "path", ["../outside.md", "/tmp/algorithm-outside.md", "skills/../../outside.md"]
)
def test_shared_candidate_validates_paths_before_writing(target, tmp_path, path):
    algo = recording_algorithm(target, tmp_path)
    with pytest.raises(ValueError, match="invalid snapshot file path"):
        algo._candidate(target.snapshot, {path: "escape"})
    assert not list((algo._run_dir / "working").iterdir())
    assert not list((algo._run_dir / "snapshots").iterdir())


@pytest.mark.parametrize(
    "kwargs,record_label",
    [({}, "evaluation"), ({"label": "candidate_dev"}, "candidate_dev")],
)
def test_shared_evaluation_records_scores_without_selecting_candidate(
    target, tmp_path, monkeypatch, kwargs, record_label
):
    class GradedBenchmark(MemoryBenchmark):
        def grade(self, trajectories):
            return tuple(replace(t, metrics={"score": 1.0}) for t in trajectories)

    async def run(self, prompt, working_dir=None):
        return Trajectory(
            output=(self.files_dir / "skills/main.md").read_text(), usage={"tokens": 5}
        )

    monkeypatch.setattr(Target, "_run", run)
    algo = recording_algorithm(target, tmp_path, benchmark=GradedBenchmark())
    baseline = target.snapshot
    candidate = algo._candidate(baseline, {"skills/main.md": "candidate answer"})
    results = asyncio.run(
        algo._evaluate(candidate, iter(algo.benchmark.test), **kwargs)
    )
    assert results[0].output == "candidate answer"
    assert results[0].metrics["score"] == 1.0
    assert results[0].task is algo.benchmark.test[0]
    assert target.snapshot is baseline
    (path,) = (algo._run_dir / "trajectories").iterdir()
    assert path.name == f"00001-{record_label}.json"
    recorded = json.loads(path.read_text())
    assert recorded["snapshot_id"] == candidate.id
    assert recorded["trajectories"][0]["usage"] == {"tokens": 5}
    assert recorded["trajectories"][0]["messages"][0]["snapshot_id"] == candidate.id


@pytest.mark.parametrize(
    "kwargs,record_label", [({}, "worker"), ({"label": "reflection"}, "reflection")]
)
def test_shared_worker_records_errors_and_redacts_both_roles(
    target, tmp_path, monkeypatch, kwargs, record_label
):
    class FailedWorker(Worker):
        async def _run(self, prompt, working_dir=None):
            return Trajectory(
                status="error",
                error_message="target-secret worker-secret environment-secret",
                messages=({"type": "Partial", "text": "worker-secret"},),
                usage={"tokens": 3},
            )

    target.config.llm = {"api_key": "target-secret"}
    worker = FailedWorker({"llm": {"api_key": "worker-secret"}})
    monkeypatch.setenv("TEST_API_KEY", "environment-secret")
    algo = recording_algorithm(target, tmp_path, worker=worker)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(algo._ask("prompt target-secret", **kwargs))
    assert (
        str(error.value)
        == f"Worker failed during {record_label}: [REDACTED] [REDACTED] [REDACTED]"
    )
    (path,) = (algo._run_dir / "trajectories").iterdir()
    assert path.name == f"00001-{record_label}.json"
    text = path.read_text()
    assert all(
        secret not in text
        for secret in ("target-secret", "worker-secret", "environment-secret")
    )
    assert json.loads(text)["trajectory"]["usage"] == {"tokens": 3}
    with pytest.raises(ValueError, match="credential"):
        algo._candidate(target.snapshot, {"skills/main.md": "target-secret"})
    assert not list((algo._run_dir / "working").iterdir())
