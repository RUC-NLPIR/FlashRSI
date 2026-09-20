"""Exercise experiment replay and cancellation without any external model calls."""

import asyncio
import copy
import json
from dataclasses import replace

import pytest

from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.core import Task, Trajectory
from scripts._experiment_runtime import CachedClaudeCode, CachedLLM, CachedMiniAgent


@pytest.fixture
def source(tmp_path):
    directory = tmp_path / "source"
    (directory / "skills").mkdir(parents=True)
    (directory / "components.yaml").write_text("skill: ['skills/**']\n")
    (directory / "skills" / "base.md").write_text("initial skill")
    return directory


def _config(source=None):
    result = {
        "llm": {
            "model_name": "model-one",
            "api_key": "private-test-key",
            "base_url": "https://local.invalid/v1",
        },
        "timeout": 30,
    }
    if source is not None:
        result["source_dir"] = str(source)
    return result


def _agent(source, cache_dir, *, cls=CachedMiniAgent, concurrency=2):
    agent = cls(_config(source))
    agent.configure_experiment(cache_dir, concurrency=concurrency)
    agent._experiment_retry_delay = 0
    return agent


def _answer(prompt):
    return Trajectory(
        output=f"answer: {prompt}",
        messages=({"type": "NativeMessage", "nested": {"content": prompt}},),
        usage={"model_calls": [{"input_tokens": 7, "output_tokens": 3}]},
        metrics={"example": 0.5},
    )


@pytest.mark.parametrize(
    "cls,base", [(CachedMiniAgent, MiniAgent), (CachedClaudeCode, ClaudeCode)]
)
def test_both_harnesses_limit_concurrency_pin_config_and_keep_order(
    monkeypatch, tmp_path, source, cls, base
):
    agent = _agent(source, tmp_path / "run" / "cache", cls=cls)
    active, maximum = 0, 0
    observed = []

    async def exercise():
        started = asyncio.Event()

        async def run(self, prompt, working_dir=None):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            started.set()
            await asyncio.sleep(0.01 if prompt == "1" else 0.02)
            observed.append(self.config.llm.model_name)
            assert (
                self.files_dir / "skills" / "base.md"
            ).read_text() == "initial skill"
            active -= 1
            return _answer(prompt)

        monkeypatch.setattr(base, "_run", run)
        tasks = tuple(Task(str(index), str(index)) for index in range(5))
        pending = asyncio.create_task(agent.rollout(tasks))
        await started.wait()
        agent.config.llm.model_name = "next-batch-model"
        result = await pending
        assert tuple(item.task for item in result) == tasks
        assert [item.output for item in result] == [f"answer: {i}" for i in range(5)]
        assert all(item.messages[0]["type"] == "RunConfig" for item in result)

    asyncio.run(exercise())
    assert maximum == 2
    assert observed == ["model-one"] * 5
    assert agent.config.llm.model_name == "next-batch-model"
    assert agent.name == base.name


def test_resume_replays_complete_trajectory_and_full_task_identity(
    monkeypatch, tmp_path, source
):
    calls = []

    async def run(self, prompt, working_dir=None):
        calls.append(prompt)
        return _answer(prompt)

    monkeypatch.setattr(MiniAgent, "_run", run)
    cache = tmp_path / "run" / "cache"
    original = Task("a", "question", "truth", metadata={"split": "dev", "nested": [1]})
    first = asyncio.run(_agent(source, cache).rollout((original,)))[0]
    resumed = _agent(source, cache)
    second = asyncio.run(resumed.rollout((original,)))[0]
    assert second == first
    assert second.task is original
    assert second.usage["model_calls"][0]["input_tokens"] == 7
    assert len(calls) == 1

    variants = (
        replace(original, task_id="different-id"),
        replace(original, question="different-question"),
        replace(original, ground_truth="different-truth"),
        replace(original, metadata={"split": "test", "nested": [1]}),
    )
    for variant in variants:
        asyncio.run(_agent(source, cache).rollout((variant,)))
    assert len(calls) == 5
    # Cache files belong to this supplied run, and cannot leak into another run.
    asyncio.run(_agent(source, tmp_path / "other-run" / "cache").rollout((original,)))
    assert len(calls) == 6


def test_keys_exclude_credentials_but_include_model_config_and_snapshot(
    monkeypatch, tmp_path, source
):
    calls = 0

    async def run(self, prompt, working_dir=None):
        nonlocal calls
        calls += 1
        return _answer(prompt)

    monkeypatch.setattr(MiniAgent, "_run", run)
    cache = tmp_path / "run" / "cache"
    task = Task("a", "question")
    agent = _agent(source, cache)
    asyncio.run(agent.rollout((task,)))
    agent.config.llm.api_key = "replacement-test-key"
    agent.configure_experiment(cache)
    asyncio.run(agent.rollout((task,)))
    assert calls == 1
    agent.config.llm.model_name = "model-two"
    agent.configure_experiment(cache)
    asyncio.run(agent.rollout((task,)))
    agent.config.llm.base_url = "https://other.invalid/v1"
    agent.configure_experiment(cache)
    asyncio.run(agent.rollout((task,)))
    agent.config.timeout = 60
    agent.configure_experiment(cache)
    asyncio.run(agent.rollout((task,)))
    assert calls == 4
    with agent.snapshot.check_out() as directory:
        (directory / "skills" / "base.md").write_text("changed skill")
        candidate = agent.snapshot.commit(directory)
    agent.configure_experiment(cache)
    asyncio.run(agent.rollout((task,), snapshot=candidate))
    assert calls == 5
    assert agent.snapshot.id != candidate.id
    # A changed source captured on restart cannot reuse the initial source cache.
    (source / "skills" / "base.md").write_text("new source")
    asyncio.run(_agent(source, cache).rollout((task,)))
    assert calls == 6
    for path in cache.rglob("*.json"):
        text = path.read_text()
        assert "private-test-key" not in text
        assert "replacement-test-key" not in text


def test_repeated_evaluations_sample_again_and_resume_by_call_ordinal(
    monkeypatch, tmp_path, source
):
    calls = 0

    async def run(self, prompt, working_dir=None):
        nonlocal calls
        calls += 1
        return _answer(f"{prompt} sample {calls}")

    monkeypatch.setattr(MiniAgent, "_run", run)
    cache = tmp_path / "run" / "cache"
    agent = _agent(source, cache)
    task = Task("same", "same question")
    first = asyncio.run(agent.rollout((task,)))
    second = asyncio.run(agent.rollout((task,)))
    assert calls == 2
    assert first[0].output != second[0].output
    resumed = _agent(source, cache)
    assert asyncio.run(resumed.rollout((task,))) == first
    assert asyncio.run(resumed.rollout((task,))) == second
    assert calls == 2
    # Configuring the same instance explicitly starts replay from ordinal zero.
    resumed.configure_experiment(cache)
    assert asyncio.run(resumed.rollout((task,))) == first
    assert calls == 2


def test_duplicate_tasks_sample_per_position_and_replay_per_position(
    monkeypatch, tmp_path, source
):
    calls = 0

    async def run(self, prompt, working_dir=None):
        nonlocal calls
        calls += 1
        sample = calls
        await asyncio.sleep(0.01)
        return _answer(f"{prompt} sample {sample}")

    monkeypatch.setattr(MiniAgent, "_run", run)
    cache = tmp_path / "run" / "cache"
    agent = _agent(source, cache)
    task = Task("same", "same question")
    result = asyncio.run(agent.rollout((task,) * 6))
    assert len(result) == 6
    assert len({item.output for item in result}) == 6
    assert calls == 6
    replay = asyncio.run(_agent(source, cache).rollout((task,) * 6))
    assert replay == result
    assert calls == 6


def test_interrupt_preserves_finished_tasks_and_cancels_outstanding_work(
    monkeypatch, tmp_path, source
):
    calls = []
    cancelled = []
    cache = tmp_path / "run" / "cache"
    tasks = (Task("done", "done"), Task("pending", "pending"))

    async def exercise():
        pending_started = asyncio.Event()
        resumed = False

        async def run(self, prompt, working_dir=None):
            calls.append(prompt)
            if prompt == "pending" and not resumed:
                pending_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(prompt)
            return _answer(prompt)

        monkeypatch.setattr(MiniAgent, "_run", run)
        agent = _agent(source, cache)
        future = asyncio.create_task(agent.rollout(tasks))
        await pending_started.wait()
        future.cancel()
        with pytest.raises(asyncio.CancelledError):
            await future
        assert len(list((cache / "target").rglob("*.json"))) == 1
        resumed = True
        result = await _agent(source, cache).rollout(tasks)
        assert all(item.status == "finished" for item in result)

    asyncio.run(exercise())
    assert calls == ["done", "pending", "pending"]
    assert cancelled == ["pending"]


@pytest.mark.parametrize("raises", [False, True])
def test_errors_are_saved_retried_once_and_never_graded_as_finished(
    monkeypatch, tmp_path, source, raises
):
    calls = 0

    async def run(self, prompt, working_dir=None):
        nonlocal calls
        calls += 1
        if raises:
            raise RuntimeError("failed with private-test-key")
        return Trajectory(
            status="error",
            error_message="failed with private-test-key",
            messages=({"type": "Partial", "text": "partial response"},),
            usage={"total_tokens": 10},
        )

    monkeypatch.setattr(MiniAgent, "_run", run)
    cache = tmp_path / "run" / "cache"
    agent = _agent(source, cache)
    task = Task("failed", "question")
    with pytest.raises(RuntimeError, match="failed twice") as failure:
        asyncio.run(agent.rollout((task,)))
    assert "private-test-key" not in str(failure.value)
    assert calls == 2
    assert not list((cache / "target").rglob("*.json"))
    errors = list((cache / "errors").rglob("*.json"))
    assert len(errors) == 2
    for path in errors:
        assert "private-test-key" not in path.read_text()
        record = json.loads(path.read_text())["trajectory"]
        assert record["status"] == "error"
        assert record["task"]["task_id"] == "failed"
        if not raises:
            assert record["usage"] == {"total_tokens": 10}
    with pytest.raises(RuntimeError, match="failed twice"):
        asyncio.run(agent.rollout((task,)))
    assert calls == 4


def test_transient_error_retries_then_caches_success(monkeypatch, tmp_path, source):
    calls = 0

    async def run(self, prompt, working_dir=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Trajectory(status="error", error_message="temporary")
        return _answer(prompt)

    monkeypatch.setattr(MiniAgent, "_run", run)
    cache = tmp_path / "run" / "cache"
    task = Task("a", "question")
    asyncio.run(_agent(source, cache).rollout((task,)))
    asyncio.run(_agent(source, cache).rollout((task,)))
    assert calls == 2
    assert len(list((cache / "errors").rglob("*.json"))) == 1
    assert len(list((cache / "target").rglob("*.json"))) == 1


def test_worker_replays_messages_usage_and_invalidates_config_and_prompt(
    monkeypatch, tmp_path
):
    calls = []

    async def run(self, prompt, working_dir=None):
        calls.append((self.config.llm.model_name, prompt))
        return _answer(f"{prompt} sample {len(calls)}")

    monkeypatch.setattr(LLM, "_run", run)
    cache = tmp_path / "run" / "cache"
    config = _config()
    worker = CachedLLM(config).configure_experiment(cache)
    first = asyncio.run(worker.run("reflect"))
    second = asyncio.run(worker.run("reflect"))
    assert first.output != second.output
    assert len(calls) == 2
    restart = CachedLLM(copy.deepcopy(config)).configure_experiment(cache)
    assert asyncio.run(restart.run("reflect")) == first
    assert asyncio.run(restart.run("reflect")) == second
    assert len(calls) == 2
    restart.config.llm.api_key = "new-key"
    restart.configure_experiment(cache)
    assert asyncio.run(restart.run("reflect")) == first
    assert len(calls) == 2
    restart.configure_experiment(cache)
    asyncio.run(restart.run("merge"))
    restart.config.llm.model_name = "model-two"
    restart.configure_experiment(cache)
    asyncio.run(restart.run("reflect"))
    assert len(calls) == 4
    other = CachedLLM(config).configure_experiment(tmp_path / "other-run" / "cache")
    asyncio.run(other.run("reflect"))
    assert len(calls) == 5
    assert first.usage["model_calls"][0]["input_tokens"] == 7
    assert first.messages[0]["type"] == "RunConfig"


def test_worker_failures_and_bad_arguments_do_not_create_success_cache(
    monkeypatch, tmp_path
):
    calls = 0

    async def run(self, prompt, working_dir=None):
        nonlocal calls
        calls += 1
        return Trajectory(
            status="error", error_message="no response", usage={"tokens": 8}
        )

    monkeypatch.setattr(LLM, "_run", run)
    cache = tmp_path / "run" / "cache"
    worker = CachedLLM(_config()).configure_experiment(cache)
    worker._experiment_retry_delay = 0
    with pytest.raises(RuntimeError, match="failed twice"):
        asyncio.run(worker.run("reflect"))
    assert calls == 2
    assert not list((cache / "worker").rglob("*.json"))
    assert len(list((cache / "errors" / "worker").rglob("*.json"))) == 2
    with pytest.raises(ValueError, match="prompt"):
        asyncio.run(worker.run(""))
    with pytest.raises(NotImplementedError, match="cannot edit"):
        asyncio.run(worker.run("edit", working_dir=tmp_path))
    assert calls == 2


def test_explicit_run_cache_and_source_are_required(tmp_path):
    worker = CachedLLM(_config())
    with pytest.raises(RuntimeError, match="run-local"):
        asyncio.run(worker.run("reflect"))
    with pytest.raises(ValueError, match="positive integer"):
        worker.configure_experiment(tmp_path / "cache", concurrency=0)
    agent = CachedMiniAgent(_config()).configure_experiment(tmp_path / "cache")
    with pytest.raises(ValueError, match="source_dir"):
        asyncio.run(agent.rollout((Task("a", "question"),)))


def test_replay_progress_is_compact_and_never_prints_prompts(
    monkeypatch, tmp_path, source, capsys
):
    async def run(self, prompt, working_dir=None):
        return _answer(prompt)

    monkeypatch.setattr(MiniAgent, "_run", run)
    cache = tmp_path / "run" / "cache"
    tasks = tuple(Task(str(index), f"private-prompt-{index}") for index in range(70))
    asyncio.run(_agent(source, cache).rollout(tasks))
    capsys.readouterr()
    asyncio.run(_agent(source, cache).rollout(tasks))
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 2
    assert "70/70 finished (cached=70, fresh=0)" in output
    assert "private-prompt" not in output
    assert "private-test-key" not in output
