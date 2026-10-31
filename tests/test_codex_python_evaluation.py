"""Evaluation reuses versioned memory while online runs keep explicit notes."""

import asyncio
import copy
import importlib.metadata
import json
import os
import signal
import time
from collections.abc import Mapping
from types import SimpleNamespace

import pytest
from codex_test_support import _events, _responses_server
from codex_test_support import parity_source as parity_source
from test_codex_python_memory import _call

from flashrsi.agents import Codex
from flashrsi.agents import codex as codex_module
from flashrsi.agents.codex import _python
from flashrsi.agents.codex._python import _run_environment, _version
from flashrsi.core import Task


@pytest.fixture
def evaluation_source(parity_source, tmp_path, monkeypatch):
    isolated_home = tmp_path / "host-home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    config = parity_source / "config.toml"
    config.write_text(
        "project_doc_max_bytes=0\n"
        + config.read_text()
        + "memories=true\n[memories]\ndedicated_tools=true\n"
    )
    notes = parity_source / "memories/extensions/ad_hoc/notes"
    notes.mkdir(parents=True)
    (notes / "2026-10-29T00-00-00-seed.md").write_text("VERSIONED_INITIAL_MEMORY")
    return parity_source


def _agent(source, replay, tmp_path):
    return Codex(
        {
            "source_dir": source,
            "memory_dir": str(tmp_path / "runtime-memory"),
            "sandbox": "danger-full-access",
            "timeout": 30,
            "llm": {
                "model_name": "gpt-5.4",
                "api_key": "evaluation-secret-key",
                "base_url": replay.base_url,
            },
        }
    )


def _manifest(result):
    return next(
        row for row in result.messages if row.get("type") == "CodexRunEnvironment"
    )


def test_rollout_memory_is_fixed_across_tasks_repeats_and_candidate(
    evaluation_source, tmp_path
):
    filename = "2026-10-29T00-00-00-produced.md"
    runtime_name = "2026-10-29T00-00-00-runtime.md"
    prefix = "extensions/ad_hoc/notes/"
    tasks = [Task("write", "Remember during this task."), Task("read", "Read notes.")]
    with _responses_server() as replay:
        agent = _agent(evaluation_source, replay, tmp_path)
        agent.set_scope({"code": "rw", "prompt": "rw", "memory": "rw"})
        baseline = agent.snapshot
        store = tmp_path / "runtime-memory" / baseline.id
        store.mkdir(parents=True)
        (store / runtime_name).write_text("ONLINE_RUNTIME_MEMORY")

        def evaluate(candidate=None):
            replay.reset(
                [
                    (
                        200,
                        _call(
                            "add_ad_hoc_note",
                            {"filename": filename, "note": "TASK_ONLY_MEMORY"},
                            0,
                        ),
                    ),
                    (200, _events("SAVED")),
                    (200, _call("read", {"path": prefix + filename}, 1)),
                    (200, _call("read", {"path": prefix + runtime_name}, 2)),
                    (
                        200,
                        _call(
                            "read", {"path": prefix + "2026-10-29T00-00-00-seed.md"}, 3
                        ),
                    ),
                    (200, _events("READ")),
                ]
            )
            results = asyncio.run(agent.rollout(tasks, snapshot=candidate))
            assert all(row.status == "finished" for row in results), [
                row.error_message for row in results
            ]
            assert not replay.steps and not replay.errors
            outputs = [
                replay.requests[i]["body"]["input"][-1]["output"] for i in (3, 4, 5)
            ]
            assert "TASK_ONLY_MEMORY" not in outputs[0]
            assert "ONLINE_RUNTIME_MEMORY" not in outputs[1]
            assert "VERSIONED_INITIAL_MEMORY" in outputs[2]
            return [_manifest(row) for row in results]

        manifests = evaluate() + evaluate()
        with baseline.check_out() as directory:
            (directory / "AGENTS.md").write_text("CANDIDATE_ONLY_INSTRUCTIONS")
            candidate = baseline.commit(directory)
        manifests += evaluate(candidate)
        assert len({row["initial_memory"]["sha256"] for row in manifests}) == 1
        for row in manifests:
            assert row["mode"] == "evaluation"
            assert row["runtime_memory_ignored"] is True
            assert row["initial_memory"]["source"] == "snapshot"
        assert sorted(path.name for path in store.iterdir()) == [runtime_name]
        assert not (tmp_path / "runtime-memory" / candidate.id).exists()
        assert "_codex_evaluation" not in agent.config
        assert agent.snapshot.id == baseline.id


def test_container_config_transport_retains_evaluation_mode(
    evaluation_source, tmp_path
):
    with _responses_server() as replay:
        agent = _agent(evaluation_source, replay, tmp_path)
        seen = []

        async def environment(pinned, task):
            # Harbor serializes the pinned config and recreates the adapter in
            # a fresh process. A host-only ContextVar would lose this boundary.
            config = json.loads(
                json.dumps(
                    dict(pinned.config),
                    default=lambda value: (
                        dict(value) if isinstance(value, Mapping) else str(value)
                    ),
                )
            )
            seen.append(config)
            child = Codex(config)
            child._snapshot = pinned.snapshot
            return await child.run(task.question)

        agent._env_runner = environment
        replay.reset([(200, _events("CONTAINER_EVALUATION"))])
        (result,) = asyncio.run(agent.rollout([Task("env", "Answer.", env="image")]))
        assert result.status == "finished", result.error_message
        assert seen[0]["_codex_evaluation"] is True
        assert _manifest(result)["mode"] == "evaluation"
        assert _manifest(result)["runtime_memory_ignored"] is True
        assert "_codex_evaluation" not in agent.config


def test_online_run_concurrent_with_rollout_keeps_its_own_memory_mode(
    evaluation_source, tmp_path
):
    filename = "2026-10-29T00-00-00-concurrent.md"
    with _responses_server() as replay:
        agent = _agent(evaluation_source, replay, tmp_path)

        async def scenario():
            waiting, proceed = asyncio.Event(), asyncio.Event()

            async def environment(pinned, task):
                waiting.set()
                await proceed.wait()
                return await pinned.run(task.question)

            agent._env_runner = environment
            pending = asyncio.create_task(
                agent.rollout([Task("env", "Read memory.", env="image")])
            )
            await waiting.wait()
            replay.reset(
                [
                    (
                        200,
                        _call(
                            "add_ad_hoc_note",
                            {"filename": filename, "note": "ONLINE_ONLY_MEMORY"},
                            0,
                        ),
                    ),
                    (200, _events("PERSISTED")),
                ]
            )
            online = await agent.run("Remember for later.")
            assert online.status == "finished", online.error_message
            replay.reset(
                [
                    (
                        200,
                        _call(
                            "read", {"path": "extensions/ad_hoc/notes/" + filename}, 1
                        ),
                    ),
                    (200, _events("ISOLATED")),
                ]
            )
            proceed.set()
            (evaluated,) = await pending
            assert evaluated.status == "finished", evaluated.error_message
            feedback = replay.requests[1]["body"]["input"][-1]["output"]
            assert "ONLINE_ONLY_MEMORY" not in feedback
            assert _manifest(online)["mode"] == "online"
            assert _manifest(evaluated)["mode"] == "evaluation"
            assert _manifest(online)["runtime_memory_ignored"] is False

        asyncio.run(scenario())
        store = tmp_path / "runtime-memory" / agent.snapshot.id
        assert (store / filename).read_text() == "ONLINE_ONLY_MEMORY"
        assert "_codex_evaluation" not in agent.config


def test_manifest_identifies_initial_state_and_environment_without_secrets(
    evaluation_source, tmp_path
):
    with _responses_server() as replay:
        agent = _agent(evaluation_source, replay, tmp_path)
        before = copy.deepcopy(agent.config)
        replay.reset([(200, _events("RECORDED"))])
        first = asyncio.run(agent.run("Answer."))
        assert first.status == "finished", first.error_message
        manifest = _manifest(first)
        assert manifest["snapshot_id"] == agent.snapshot.id
        assert manifest["model"] == "gpt-5.4"
        assert manifest["provider"]["name"] == "FlashRSI endpoint"
        assert manifest["initial_memory"]["files"] == 1
        assert len(manifest["initial_memory"]["sha256"]) == 64
        assert manifest["environment"]["python"]["version"]
        assert manifest["environment"]["platform"]["system"]
        assert manifest["environment"]["shell"]["path"]
        assert manifest["environment"]["dependencies"][
            "httpx"
        ] == importlib.metadata.version("httpx")
        assert manifest["sandbox"] == "danger-full-access"
        assert manifest["budget"]["timeout_seconds"] == 30
        assert "evaluation-secret-key" not in json.dumps(dict(manifest))
        assert agent.config == before

        agent.set_scope({"memory": "rw"})
        with agent.snapshot.check_out() as directory:
            (directory / "memories/memory_summary.md").write_text("NEW_FROZEN_MEMORY")
            candidate = agent.snapshot.commit(directory)
        agent.update(candidate)
        replay.reset([(200, _events("RECORDED_CANDIDATE"))])
        second = asyncio.run(agent.run("Answer."))
        assert second.status == "finished", second.error_message
        assert (
            _manifest(second)["initial_memory"]["sha256"]
            != manifest["initial_memory"]["sha256"]
        )


@pytest.mark.parametrize("banner", ["slow", "oversized"])
def test_version_probe_failure_is_bounded_and_its_output_is_redacted(
    evaluation_source, tmp_path, monkeypatch, banner
):
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    script = executable_dir / "node"
    commands = {
        "slow": "/bin/sleep 20\n",
        "oversized": "printf '%6000s' 'oversized banner'\n",
    }
    script.write_text("#!/bin/sh\n" + commands[banner])
    script.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(executable_dir) + os.pathsep + os.environ.get("PATH", "")
    )
    spawned = []
    original_spawn = asyncio.create_subprocess_exec

    async def record_spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        if args[0] == str(script):
            spawned.append(process.pid)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_spawn)
    # Directly exercise the actual subprocess path before the best-effort task
    # probe, which may legitimately be cancelled before launch on a busy host.
    assert asyncio.run(_version(str(script), dict(os.environ), tmp_path)) is None
    assert spawned
    for pid in spawned:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    with _responses_server() as replay:
        agent = _agent(evaluation_source, replay, tmp_path)
        replay.reset([(200, _events("STILL_SOLVES_TASK"))])
        result = asyncio.run(agent.run("Answer."))
        assert result.status == "finished", result.error_message
        assert _manifest(result)["environment"]["node"]["path"] == str(script)
        version = _manifest(result)["environment"]["node"]["version"]
        assert version is None
        assert "evaluation-secret-key" not in json.dumps(dict(_manifest(result)))
        assert len(replay.requests) == 1
        # The probe owns a separate process group and must be reaped even when
        # its stdout never finishes or cannot fit the bounded line buffer.
        for pid in spawned:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)


def test_probe_output_in_the_manifest_is_redacted(
    evaluation_source, tmp_path, monkeypatch
):
    async def version(*args):
        return "evaluation-secret-key"

    monkeypatch.setattr(_python, "_version", version)
    with _responses_server() as replay:
        agent = _agent(evaluation_source, replay, tmp_path)
        replay.reset([(200, _events("SAFE_LOG"))])
        result = asyncio.run(agent.run("Answer."))
        assert result.status == "finished", result.error_message
        assert _manifest(result)["environment"]["node"]["version"] == "[REDACTED]"
        assert "evaluation-secret-key" not in json.dumps(dict(_manifest(result)))


def test_slow_probe_does_not_change_a_fast_core_result(
    evaluation_source, tmp_path, monkeypatch
):
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    script = executable_dir / "node"
    script.write_text("#!/bin/sh\n/bin/sleep 20\n")
    script.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(executable_dir) + os.pathsep + os.environ.get("PATH", "")
    )
    with _responses_server() as replay:
        (evaluation_source / "python_core/loop.py").write_text(
            "async def run_session(request, emit):\n"
            "    return {'status':'finished','output':'FAST_CORE','usage':{}}\n"
        )
        agent = _agent(evaluation_source, replay, tmp_path)
        agent.config["timeout"] = 3
        replay.reset([(200, _events("MUST_NOT_SAMPLE"))])
        result = asyncio.run(agent.run("Answer."))
        assert result.status == "finished", result.error_message
        assert result.output == "FAST_CORE"
        assert _manifest(result)["environment"]["node"]["version"] is None
        assert not replay.requests


@pytest.mark.skipif(os.name != "posix", reason="requires process groups")
def test_probe_timeout_cleanup_survives_core_completion_and_repeated_cancel(
    evaluation_source, tmp_path, monkeypatch
):
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    script = executable_dir / "node"
    # The parent exits, while its child keeps stdout open until the probe times
    # out. Core completion then cancels a probe already inside cleanup.
    script.write_text("#!/bin/sh\n/bin/sleep 20 &\nprintf 'VERSION\\n'\n")
    script.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(executable_dir) + os.pathsep + os.environ.get("PATH", "")
    )
    (evaluation_source / "python_core/loop.py").write_text(
        "import asyncio\nfrom pathlib import Path\n"
        "async def run_session(request, emit):\n"
        "    while not (Path(request['cwd']) / 'finish-core').exists():\n"
        "        await asyncio.sleep(0.01)\n"
        "    return {'status':'finished','output':'CORE_FINISHED','usage':{}}\n"
    )
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    spawned, probe_tasks = [], []
    original_spawn = asyncio.create_subprocess_exec
    original_version, original_stop = _python._version, codex_module._stop

    async def record_spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        if args[0] == str(script):
            spawned.append(process.pid)
        return process

    async def record_version(*args):
        if args[0] == str(script):
            probe_tasks.append(asyncio.current_task())
        return await original_version(*args)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_spawn)
    monkeypatch.setattr(_python, "_version", record_version)

    async def scenario():
        cleanup_entered, release_cleanup = asyncio.Event(), asyncio.Event()

        async def stop(process, **kwargs):
            if process.pid in spawned:
                cleanup_entered.set()
                (task_dir / "finish-core").touch()
                await release_cleanup.wait()
            return await original_stop(process, **kwargs)

        monkeypatch.setattr(codex_module, "_stop", stop)
        agent = _agent(
            evaluation_source, SimpleNamespace(base_url="http://127.0.0.1:1"), tmp_path
        )
        pending = asyncio.create_task(agent.run("Answer.", working_dir=task_dir))
        try:
            async with asyncio.timeout(5):
                await cleanup_entered.wait()
                while not probe_tasks[0].cancelling():
                    await asyncio.sleep(0.01)
            probe_tasks[0].cancel()
            release_cleanup.set()
            result = await asyncio.wait_for(pending, 10)
            assert result.status == "finished", result.error_message
            assert result.output == "CORE_FINISHED"
            for pid in spawned:
                with pytest.raises(ProcessLookupError):
                    os.killpg(pid, 0)
        finally:
            release_cleanup.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            for pid in spawned:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    asyncio.run(scenario())


def test_version_wrappers_run_outside_task_and_snapshot_directories(
    evaluation_source, tmp_path, monkeypatch
):
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    scripts = [executable_dir / "node", executable_dir / "shell"]
    for script in scripts:
        script.write_text(
            "#!/bin/sh\n: > codex-version-probe-created\nprintf 'VERSION\\n'\n"
        )
        script.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(executable_dir) + os.pathsep + os.environ.get("PATH", "")
    )
    (evaluation_source / "python_core/loop.py").write_text(
        "import asyncio\n"
        "async def run_session(request, emit):\n"
        f"    emit({{'type':'codex.shell.selected','path':{str(scripts[1])!r}}})\n"
        "    await asyncio.sleep(0.2)\n"
        "    return {'status':'finished','output':'CORE_FINISHED','usage':{}}\n"
    )
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    seen = []
    original_spawn = asyncio.create_subprocess_exec

    async def record_spawn(*args, **kwargs):
        if args[0] in {str(script) for script in scripts}:
            seen.append(kwargs["cwd"])
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_spawn)
    agent = _agent(
        evaluation_source, SimpleNamespace(base_url="http://127.0.0.1:1"), tmp_path
    )
    result = asyncio.run(agent.run("Answer.", working_dir=task_dir))
    assert result.status == "finished", result.error_message
    assert result.output == "CORE_FINISHED"
    assert len(seen) == 2
    assert all(path != task_dir and path.name == "diagnostics" for path in seen)
    assert not (task_dir / "codex-version-probe-created").exists()
    assert not (evaluation_source / "codex-version-probe-created").exists()


@pytest.mark.parametrize("resource", ["large_file", "symlink"])
def test_unbounded_memory_is_not_given_a_complete_fingerprint(tmp_path, resource):
    memory = tmp_path / "memories"
    memory.mkdir()
    if resource == "large_file":
        with (memory / "large.md").open("wb") as output:
            output.truncate(17 * 1024 * 1024)
    else:
        (memory / "cycle").symlink_to(memory, target_is_directory=True)
    agent = SimpleNamespace(config={}, snapshot=SimpleNamespace(id="test-version"))
    manifest = _run_environment(agent, tmp_path, {}, {}, time.monotonic() + 1)
    assert manifest["initial_memory"]["complete"] is False
    assert manifest["initial_memory"]["sha256"] is None
