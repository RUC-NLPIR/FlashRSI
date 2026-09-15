import asyncio
import inspect
import json
import sys

import pytest

from flashrsi.benchmarks import SearchQA
from flashrsi.config import load_config
from flashrsi.core import Agent, Snapshot, SnapshotFile, Task, Trajectory
from flashrsi.core.snapshot import _create_snapshot


class FileAgent(Agent):
    name = "file_agent"
    description = "Offline backend with versioned instructions."

    async def _run(self, prompt, working_dir=None):
        answer = (self.files_dir / "skills/main.md").read_text()
        return Trajectory(
            output=answer,
            messages=({"role": "user", "content": prompt},),
            usage={"input_tokens": 10, "output_tokens": 2},
        )


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "skills").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "skills/main.md").write_text("initial answer")
    (root / "src/run.py").write_text("print('original code')\n")
    (root / "README.md").write_text("not an execution resource")
    (root / "components.yaml").write_text("skill: ['skills/**']\ncode: ['src/**']\n")
    return root


@pytest.fixture
def agent(source):
    return FileAgent({"source_dir": source, "model_name": "offline"})


def _candidate(agent, content, baseline=None):
    baseline = agent.snapshot if baseline is None else baseline
    with baseline.check_out() as directory:
        (directory / "skills/main.md").write_text(content)
        candidate = baseline.commit(directory)
    return candidate


def test_agent_constructs_snapshot_automatically_and_has_one_public_run(agent, source):
    assert agent.snapshot.files["skills/main.md"] == SnapshotFile(
        b"initial answer", "skill"
    )
    assert set(agent.snapshot.files) == {"skills/main.md", "src/run.py"}
    assert set(inspect.signature(Agent).parameters) == {"config"}
    assert set(inspect.signature(Agent.run).parameters) == {
        "self",
        "prompt",
        "working_dir",
    }
    for name in ("ask", "edit", "check_out", "commit", "seed"):
        assert not hasattr(agent, name)
    assert not hasattr(agent.snapshot, "validate")
    (source / "skills/main.md").write_text("external edit")
    assert asyncio.run(agent.run("question")).output == "initial answer"


def test_instance_source_override_uses_existing_native_file_layout(source):
    agent = FileAgent({"source_dir": source, "model_name": "offline"})
    assert asyncio.run(agent.run("question")).output == "initial answer"
    with pytest.raises(RuntimeError, match="only inside"):
        agent.files_dir


def test_runtime_config_credentials_never_enter_snapshot(source, tmp_path):
    (source / ".env").write_text("SECRET=source-secret")
    agent = FileAgent({"source_dir": source, "api_key": "runtime-secret"})
    assert agent.config["api_key"] == "runtime-secret"
    path = tmp_path / "snapshot.json"
    agent.snapshot.save(path)
    assert "api_key" not in path.read_text()
    assert all(b"secret" not in file.content for file in agent.snapshot.files.values())
    assert ".env" not in agent.snapshot.files


def test_manifest_rules_are_captured_once_and_entries_are_read_only(source):
    agent = FileAgent({"source_dir": source})
    (source / "components.yaml").write_text("skill: ['**']\n")
    assert agent.component_rules["skill"] == ("skills/**",)
    assert agent.component_rules is agent.snapshot.component_rules
    with pytest.raises(TypeError):
        agent.component_rules["code"] = ("skills/**",)


def test_question_and_editing_share_run_and_preserve_trace(tmp_path):
    class Worker(Agent):
        name = "worker"

        async def _run(self, prompt, working_dir=None):
            if working_dir is not None:
                (working_dir / "answer.txt").write_text(prompt)
            return Trajectory(output=prompt.upper(), usage={"tokens": 3})

    worker = Worker()
    text = asyncio.run(worker.run("hello"))
    editing = asyncio.run(worker.run("edited", working_dir=tmp_path))
    assert text.output == "HELLO" and text.task is None
    assert editing.output == "EDITED" and editing.usage == {"tokens": 3}
    assert (tmp_path / "answer.txt").read_text() == "edited"
    with pytest.raises(RuntimeError, match="no versioned files"):
        worker.snapshot


def test_worker_own_files_are_separate_from_editing_target(source, tmp_path):
    calls = []

    class SDKWorker(FileAgent):
        async def _run(self, prompt, working_dir=None):
            # Analogue of explicit SDK configuration: always load this worker's
            # instructions from files_dir, even when cwd contains another agent.
            instructions = (self.files_dir / "skills/main.md").read_text()
            calls.append((instructions, working_dir))
            (working_dir / "skills/main.md").write_text(instructions + ":" + prompt)
            return Trajectory(output="edited", usage={"tokens": 7})

    target = tmp_path / "target"
    (target / "skills").mkdir(parents=True)
    (target / "skills/main.md").write_text("target instructions")
    worker = SDKWorker({"source_dir": source})
    initial = worker.snapshot
    result = asyncio.run(worker.run("improve", working_dir=target))
    assert calls == [("initial answer", target.resolve())]
    assert (target / "skills/main.md").read_text() == "initial answer:improve"
    assert worker.snapshot is initial
    assert result.usage == {"tokens": 7}


def test_rollout_rebinds_exact_task_preserving_trace_usage_metrics(agent):
    task = Task("one", "question", "answer", metadata={"answers": ["answer"]})
    result = asyncio.run(agent.rollout([task]))[0]
    assert result.task is task
    assert result.messages == ({"role": "user", "content": "question"},)
    assert result.usage == {"input_tokens": 10, "output_tokens": 2}
    assert result.metrics == {}
    assert asyncio.run(agent.rollout(())) == ()


def test_rollout_preserves_error_result_and_continues_next_task():
    class SometimesFails(Agent):
        name = "sometimes_fails"

        async def _run(self, prompt, working_dir=None):
            if prompt == "fail":
                return Trajectory(
                    status="error", error_message="backend failure", usage={"tokens": 1}
                )
            return Trajectory(output=prompt)

    tasks = [Task("bad", "fail"), Task("good", "success")]
    first, second = asyncio.run(SometimesFails().rollout(tasks))
    assert first.task is tasks[0] and first.status == "error"
    assert first.error_message == "backend failure" and first.usage == {"tokens": 1}
    assert second.task is tasks[1] and second.output == "success"


def test_candidate_evaluation_and_updates_use_selected_files(agent, tmp_path):
    initial = agent.snapshot
    one = _candidate(agent, "one")
    two = _candidate(agent, "two", baseline=initial)
    tasks = (Task("one", "question"), Task("two", "question"))
    assert [t.output for t in asyncio.run(agent.rollout(tasks, snapshot=one))] == [
        "one"
    ] * 2
    assert agent.snapshot is initial
    path = tmp_path / "one.json"
    one.save(path)
    for snapshot, answer in (
        (Snapshot.load(path), "one"),
        (two, "two"),
        (initial, "initial answer"),
    ):
        agent.update(snapshot)
        assert asyncio.run(agent.run("question")).output == answer


def test_open_harness_executes_changed_source_and_resources(source):
    script = source / "src/run.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "print('original:' + (root / 'skills/main.md').read_text() + ':' + sys.argv[1])\n"
    )

    class ProcessAgent(FileAgent):
        async def _run(self, prompt, working_dir=None):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-B",
                str(self.files_dir / "src/run.py"),
                prompt,
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, error = await process.communicate()
            assert process.returncode == 0, error.decode()
            return Trajectory(output=output.decode().strip())

    agent = ProcessAgent({"source_dir": source})
    agent.set_scope({"code": "rw", "skill": "rw"})
    initial = agent.snapshot
    with initial.check_out() as directory:
        script_copy = directory / "src/run.py"
        script_copy.write_text(script_copy.read_text().replace("original:", "evolved:"))
        (directory / "skills/main.md").write_text("new skill")
        candidate = initial.commit(directory)
    assert asyncio.run(agent.run("Q")).output == "original:initial answer:Q"
    assert (
        asyncio.run(agent.rollout([Task("q", "Q")], snapshot=candidate))[0].output
        == "evolved:new skill:Q"
    )
    agent.update(candidate)
    assert asyncio.run(agent.run("Q")).output == "evolved:new skill:Q"
    assert "original:" in script.read_text()


def test_concurrent_calls_and_update_keep_files_and_version_pinned(source):
    async def scenario():
        started, proceed = asyncio.Event(), asyncio.Event()
        observed = []

        class PausingAgent(FileAgent):
            async def _run(self, prompt, working_dir=None):
                first_dir, first_id = self.files_dir, self.snapshot.id
                if prompt == "pause":
                    started.set()
                    await proceed.wait()
                observed.append((first_dir, self.files_dir, first_id, self.snapshot.id))
                return await super()._run(prompt, working_dir)

        agent = PausingAgent({"source_dir": source})
        initial = agent.snapshot
        candidate = _candidate(agent, "new version")
        running = asyncio.create_task(agent.run("pause"))
        await started.wait()
        agent.update(candidate)
        assert agent.snapshot is candidate
        assert (await agent.run("new call")).output == "new version"
        proceed.set()
        assert (await running).output == "initial answer"
        assert all(
            before == after and old == new for before, after, old, new in observed
        )
        assert {item[2] for item in observed} == {initial.id, candidate.id}
        assert all(not item[0].exists() for item in observed)

    asyncio.run(scenario())


def test_rollout_batch_pinned_with_update_and_candidates_run_concurrently(source):
    async def scenario():
        started, proceed = asyncio.Event(), asyncio.Event()

        class PausingAgent(FileAgent):
            async def _run(self, prompt, working_dir=None):
                if prompt == "pause":
                    started.set()
                    await proceed.wait()
                return await super()._run(prompt, working_dir)

        agent = PausingAgent({"source_dir": source})
        candidate = _candidate(agent, "candidate")
        batch = asyncio.create_task(
            agent.rollout([Task("a", "pause"), Task("b", "next")])
        )
        await started.wait()
        agent.update(candidate)
        other = await agent.rollout([Task("c", "other")], snapshot=candidate)
        proceed.set()
        assert [item.output for item in await batch] == ["initial answer"] * 2
        assert other[0].output == "candidate"
        assert agent.snapshot is candidate

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["error", "cancel", "bad_return"])
def test_failed_runs_cleanup_files_and_reset_context(source, mode):
    async def scenario():
        started, wait = asyncio.Event(), asyncio.Event()
        paths = []

        class BrokenAgent(FileAgent):
            async def _run(self, prompt, working_dir=None):
                paths.append(self.files_dir)
                if prompt == "ok":
                    return await super()._run(prompt, working_dir)
                if mode == "error":
                    raise RuntimeError("backend failed")
                if mode == "bad_return":
                    return "not a trace"
                started.set()
                await wait.wait()

        agent = BrokenAgent({"source_dir": source})
        if mode == "cancel":
            task = asyncio.create_task(agent.run("bad"))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(RuntimeError if mode == "error" else TypeError):
                await agent.run("bad")
        assert not paths[0].exists()
        with pytest.raises(RuntimeError, match="only inside"):
            agent.files_dir
        assert (await agent.run("ok")).output == "initial answer"
        assert not paths[-1].exists()

    asyncio.run(scenario())


def test_execution_writes_never_automatically_change_snapshot(source):
    class WritingAgent(FileAgent):
        async def _run(self, prompt, working_dir=None):
            path = self.files_dir / "skills/main.md"
            before = path.read_text()
            path.write_text("temporary execution mutation")
            return Trajectory(output=before)

    agent = WritingAgent({"source_dir": source})
    original = agent.snapshot
    for _ in range(2):
        assert asyncio.run(agent.run("question")).output == "initial answer"
    assert agent.snapshot is original
    assert (source / "skills/main.md").read_text() == "initial answer"


@pytest.mark.parametrize("entrypoint", ["update", "rollout"])
@pytest.mark.parametrize("invalid", ["type", "root", "value"])
def test_invalid_snapshots_rejected(agent, entrypoint, invalid):
    initial = agent.snapshot
    files = dict(initial.files)
    if invalid == "type":
        candidate = _create_snapshot(
            files, agent_type="other", component_rules=initial.component_rules
        )
    elif invalid == "root":
        files["skills/main.md"] = SnapshotFile(b"other", "skill")
        candidate = _create_snapshot(
            files, agent_type=agent.name, component_rules=initial.component_rules
        )
    else:
        candidate = "not a snapshot"
    with pytest.raises(ValueError):
        if entrypoint == "update":
            agent.update(candidate)
        else:
            asyncio.run(agent.rollout([], snapshot=candidate))
    assert agent.snapshot is initial


def test_scope_controls_editing_without_changing_execution_or_version(agent, tmp_path):
    original = agent.snapshot
    scope = {"skill": "rw"}
    agent.set_scope(scope)
    scope["code"] = "rw"
    scoped = agent.snapshot
    assert scoped == original
    assert scoped.id == original.id
    with scoped.check_out() as directory:
        assert not (directory / "src").exists()
        (directory / "skills/main.md").write_text("new skill")
        candidate = scoped.commit(directory)
    assert candidate.files["src/run.py"] == original.files["src/run.py"]
    assert (
        asyncio.run(agent.rollout([Task("q", "Q")], snapshot=candidate))[0].output
        == "new skill"
    )
    agent.update(candidate)
    assert agent.snapshot is candidate
    assert agent.component_rules is candidate.component_rules
    assert asyncio.run(agent.run("Q")).output == "new skill"
    path = tmp_path / "candidate.json"
    candidate.save(path)
    loaded = Snapshot.load(path)
    assert loaded == candidate
    assert "_scope" not in json.loads(path.read_text())
    agent.update(loaded)
    with agent.snapshot.check_out() as directory:
        assert not (directory / "src").exists()


@pytest.mark.parametrize("permission", ["r", "none"])
@pytest.mark.parametrize("entrypoint", ["update", "rollout"])
def test_current_scope_rejects_loaded_or_old_unrestricted_candidates(
    agent, tmp_path, permission, entrypoint
):
    original = agent.snapshot
    with original.check_out() as directory:
        (directory / "src/run.py").write_text("changed code")
        candidate = original.commit(directory)
    path = tmp_path / "candidate.json"
    candidate.save(path)
    agent.set_scope({"skill": "rw", "code": permission})
    baseline = agent.snapshot
    for version in (candidate, Snapshot.load(path)):
        with pytest.raises(ValueError, match="outside allowed components"):
            if entrypoint == "update":
                agent.update(version)
            else:
                asyncio.run(agent.rollout([Task("q", "Q")], snapshot=version))
        assert agent.snapshot is baseline


@pytest.mark.parametrize(
    "scope",
    [
        None,
        {"skill"},
        {"unknown": "rw"},
        {1: "rw"},
        {"skill": "write"},
        {"skill": True},
    ],
)
def test_invalid_scope_does_not_change_agent(agent, scope):
    original = agent.snapshot
    with pytest.raises(ValueError):
        agent.set_scope(scope)
    assert agent.snapshot is original


def test_set_scope_replaces_defaults_and_running_batch_retains_its_view(source):
    async def scenario():
        started, proceed = asyncio.Event(), asyncio.Event()
        observed = []

        class ScopedAgent(FileAgent):
            async def _run(self, prompt, working_dir=None):
                if prompt == "pause":
                    started.set()
                    await proceed.wait()
                # Runtime always has full code even when the editing view hides it.
                assert (self.files_dir / "src/run.py").exists()
                with self.snapshot.check_out() as directory:
                    observed.append((directory / "src/run.py").exists())
                return await super()._run(prompt, working_dir)

        agent = ScopedAgent({"source_dir": source})
        agent.set_scope({"skill": "rw"})
        batch = asyncio.create_task(
            agent.rollout([Task("a", "pause"), Task("b", "next")])
        )
        await started.wait()
        agent.set_scope({"code": "r"})
        with agent.snapshot.check_out() as directory:
            assert not (directory / "skills").exists()
            assert not (directory / "src/run.py").stat().st_mode & 0o222
        proceed.set()
        assert len(await batch) == 2
        assert observed == [False, False]
        assert (await agent.run("new call")).output == "initial answer"
        assert observed[-1] is True

    asyncio.run(scenario())


def test_unsupported_or_invalid_inputs_fail_before_execution(agent, tmp_path):
    with pytest.raises(ValueError, match="components.yaml"):
        FileAgent({"source_dir": tmp_path})
    with pytest.raises(ValueError, match="mapping"):
        FileAgent(agent.snapshot)
    for prompt in (None, "", "   "):
        with pytest.raises(ValueError, match="prompt"):
            asyncio.run(agent.run(prompt))
    with pytest.raises(ValueError, match="working_dir"):
        asyncio.run(agent.run("q", tmp_path / "absent"))
    with pytest.raises(ValueError, match="Task instances"):
        asyncio.run(agent.rollout(["q"]))
    with pytest.raises(NotImplementedError, match="environment-aware"):
        asyncio.run(agent.rollout([Task("env", "q", env="container:image")]))
    with pytest.raises(ValueError, match="expected a Snapshot"):
        agent.update(None)


def test_question_only_trajectory_and_searchqa_grading_contract(agent, tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": f"q-{i}",
                    "question": "Capital of France?",
                    "context": "Paris",
                    "answers": ["Paris"],
                }
                for i in range(3)
            ]
        )
    )
    config = load_config(
        overrides={
            "benchmark": {"data_path": path},
            "agent": {"model_name": "offline"},
            "algorithm": {"worker": {"model_name": "offline"}},
        }
    )
    bench = SearchQA(config)
    bench.load()

    class Worker(Agent):
        name = "worker"

        async def _run(self, prompt, working_dir=None):
            (working_dir / "skills/main.md").write_text(prompt)
            return Trajectory(output="applied", usage={"tokens": 2})

    async def scenario():
        agent.set_scope({"skill": "rw"})
        (before,) = bench.grade(await agent.rollout(bench.dev))
        baseline = agent.snapshot
        with baseline.check_out() as directory:
            editing = await Worker().run("Paris", working_dir=directory)
            candidate = baseline.commit(directory)
        (after,) = bench.grade(await agent.rollout(bench.dev, snapshot=candidate))
        assert before.metrics[bench.primary_metric] == 0
        assert after.metrics[bench.primary_metric] == 1
        assert editing.output == "applied" and editing.usage == {"tokens": 2}
        assert agent.snapshot is baseline
        agent.update(candidate)
        (accepted,) = bench.grade(await agent.rollout(bench.test))
        assert accepted.metrics[bench.primary_metric] == 1
        with pytest.raises(ValueError, match="requires a Task"):
            bench.grade((await agent.run("question"),))
        with pytest.raises(ValueError, match="Task or None"):
            Trajectory(task="bad")

    asyncio.run(scenario())
