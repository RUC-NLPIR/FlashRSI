"""DeepSWE interface checks using synthetic tasks; no data/image/model requests."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from flashrsi import _launch
from flashrsi._startup import _HARBOR
from flashrsi.benchmarks import DeepSWE
from flashrsi.benchmarks import deepswe as dataset
from flashrsi.config import load_config
from flashrsi.core import Trajectory
from flashrsi.runner import _BENCHMARKS


@pytest.fixture
def tasks(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    root = tmp_path / "upstream"
    for index in range(3):
        path = root / "tasks" / f"fixture-{index}"
        (path / "environment").mkdir(parents=True)
        (path / "environment/Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        (path / "tests").mkdir()
        (path / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (path / "instruction.md").write_text(
            f"Synthetic task {index}. Commit your changes.", encoding="utf-8"
        )
        (path / "task.toml").write_text(
            f'''
schema_version = "1.3"
artifacts = ["/logs/artifacts/model.patch"]
[task]
name = "datacurve/fixture-{index}"
[metadata]
language = "python"
base_commit_hash = "{"0" * 40}"
[agent]
network_mode = "no-network"
timeout_sec = 100
[verifier]
environment_mode = "separate"
network_mode = "no-network"
timeout_sec = 100
[verifier.environment]
cpus = 2
[[verifier.collect]]
command = "git diff HEAD~1 HEAD > /logs/artifacts/model.patch"
timeout_sec = 30
[environment]
os = "linux"
''',
            encoding="utf-8",
        )

    def no_download(*args):
        pytest.fail("Offline local tasks must not download upstream data")

    monkeypatch.setattr(dataset, "_download_git", no_download)
    return root


def test_lazy_init_and_pinned_download_contract(tasks, monkeypatch):
    calls = []
    monkeypatch.setattr(
        dataset, "_download_git", lambda *args: calls.append(args) or tasks
    )
    bench = DeepSWE({})
    assert calls == []
    bench.load()
    assert calls == [(dataset._SOURCE, dataset._REVISION, ["tasks"])]
    assert len(bench.test) == 3 and not bench.train and not bench.dev
    bench.load()
    assert len(calls) == 1


@pytest.mark.parametrize("location", ["root", "tasks", "single"])
def test_local_layout_native_identity_and_partitions(tasks, location):
    path = tasks if location == "root" else tasks / "tasks"
    if location == "single":
        path /= "fixture-0"
    bench = DeepSWE({"data_path": path})
    bench.load()
    assert len(bench.test) == (1 if location == "single" else 3)
    assert all(t.task_id.startswith("datacurve/") for t in bench.test)
    assert bench.metadata["source"] == bench.metadata["revision"] == "local"
    assert all(t.metadata["language"] == "python" for t in bench.test)
    config = {
        "data_path": tasks,
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
    }
    assert DeepSWE(config).load() == DeepSWE(config).load()
    assert {k: len(v) for k, v in DeepSWE(config).load().items()} == {
        "train": 1,
        "dev": 1,
        "test": 1,
    }


@pytest.mark.parametrize(
    "old,new,error",
    [
        (
            'environment_mode = "separate"',
            'environment_mode = "shared"',
            "separate verifier",
        ),
        ("[[verifier.collect]]", "[[unused.collect]]", "collect hooks"),
        ('network_mode = "no-network"', 'network_mode = "public"', "network_mode"),
        ('os = "linux"', 'os = "windows"', "Linux"),
    ],
)
def test_unsupported_protocols_rejected(tasks, old, new, error):
    path = tasks / "tasks/fixture-0/task.toml"
    text = path.read_text(encoding="utf-8").replace(old, new)
    # A shared verifier cannot also declare its own environment in Harbor.
    if 'environment_mode = "shared"' in text:
        text = text.replace("[verifier.environment]\ncpus = 2\n", "")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        DeepSWE({"data_path": path.parent}).load()


def test_native_reward_and_loaded_task_integrity(tasks):
    bench = DeepSWE({"data_path": tasks})
    with pytest.raises(RuntimeError, match="call load"):
        bench.grade(())
    bench.load()
    task = bench.test[0]
    trajectory = Trajectory(
        task=task,
        messages=(
            {
                "type": "HarborVerifier",
                "task_id": task.task_id,
                "task_checksum": task.metadata["task_checksum"],
                "rewards": {"reward": 1, "pass_fraction": 0.5},
            },
        ),
    )
    assert bench.grade((trajectory,))[0].metrics == {"reward": 1.0}
    assert bench.grade((replace(trajectory, status="error", error_message="fixture"),))[
        0
    ].metrics == {"reward": 0.0}
    with pytest.raises(ValueError, match="final HarborVerifier"):
        bench.grade((replace(trajectory, messages=()),))
    with pytest.raises(ValueError, match="loaded benchmark Task"):
        bench.grade((replace(trajectory, task=replace(task, question="forged")),))


def test_launcher_plan_without_dataset_access():
    config = load_config(
        overrides={
            "benchmark": {"name": "deepswe"},
            "agent": {"llm": {"model_name": "fixture"}},
            "algorithm": {"worker": {"llm": {"model_name": "fixture"}}},
        }
    )
    assert _BENCHMARKS["deepswe"] is DeepSWE and "deepswe" in _HARBOR
    plan = _launch._plan(config)
    assert "harbor" in plan["extras"] and "Docker Compose" in plan["prerequisites"]


def test_binding_recomputes_model_hosts_for_next_run(tasks, monkeypatch):
    from flashrsi.integrations import deepswe

    bench = DeepSWE({"data_path": tasks})
    bench.load()
    agent = SimpleNamespace(config={"llm": {"base_url": "https://model.example/v1"}})
    monkeypatch.setattr(deepswe, "bind_harbor", lambda agent: None)
    run = AsyncMock(return_value=Trajectory())
    monkeypatch.setattr(deepswe, "_run", run)
    deepswe.bind(agent, bench)
    agent.config["llm"] = {
        "base_url": "https://next.example/v1",
        "side_base_url": "https://vision.example/v1",
    }
    asyncio.run(agent._env_runner(agent, bench.test[0]))
    assert run.call_args.kwargs == {
        "agent_allowed_hosts": ["next.example", "vision.example"]
    }
    with pytest.raises(ValueError, match="loaded benchmark Task"):
        asyncio.run(agent._env_runner(agent, replace(bench.test[0], question="forged")))


@pytest.mark.parametrize(
    "url", [None, "file:///tmp/api", "https://user:secret@model.example/v1"]
)
def test_missing_or_unsafe_model_endpoint(url):
    pytest.importorskip("harbor")
    from flashrsi.integrations.deepswe import _model_hosts

    with pytest.raises(ValueError):
        _model_hosts({"llm": {"base_url": url}})


def test_harbor_forwards_agent_allowlist_and_keeps_native_verifier(
    tasks, tmp_path, monkeypatch
):
    from harbor.trial.network_policy import (
        resolve_agent_phase_policy,
        resolve_verifier_phase_policy,
    )

    from flashrsi.integrations import harbor

    bench = DeepSWE({"data_path": tasks})
    bench.load()
    task = bench.test[0]
    agent = SimpleNamespace(
        config={
            "llm": {"model_name": "fixture", "base_url": "https://model.example/v1"}
        },
        snapshot=SimpleNamespace(id="fixture-snapshot"),
        _check_container=lambda: None,
    )
    monkeypatch.setattr(
        harbor.shutil, "which", lambda name: "offline-docker-placeholder"
    )
    monkeypatch.setattr(harbor, "_stage", lambda *args: None)
    log = tmp_path / "agent"
    log.mkdir()
    (log / "flashrsi.json").write_text(
        json.dumps(
            {"messages": [{"type": "RunConfig", "snapshot_id": "fixture-snapshot"}]}
        )
    )
    trial = SimpleNamespace(
        paths=SimpleNamespace(
            agent_dir=log,
            test_stdout_path=log / "stdout",
            test_stderr_path=log / "stderr",
        ),
        run=AsyncMock(
            return_value=SimpleNamespace(
                id="fixture-trial",
                exception_info=None,
                verifier_result=SimpleNamespace(rewards={"reward": 1}),
            )
        ),
    )
    create = AsyncMock(return_value=trial)
    monkeypatch.setattr(harbor.Trial, "create", create)
    result = asyncio.run(
        harbor._run(agent, task, agent_allowed_hosts=["model.example"])
    )
    assert result.status == "finished"
    config = create.call_args.args[0]
    native = harbor.HarborTask(Path(task.env)).config
    assert config.agent.extra_allowed_hosts == ["model.example"]
    assert config.verifier.disable is False
    baseline = native.environment.resolve_baseline()
    policy = resolve_agent_phase_policy(native, config.agent, baseline)
    assert policy.network_mode == "allowlist" and policy.allowed_hosts == [
        "model.example"
    ]
    assert (
        resolve_verifier_phase_policy(native, baseline=baseline).network_mode
        == "no-network"
    )
    assert native.verifier.collect[0].command.endswith("/logs/artifacts/model.patch")
    assert result.messages[-1]["rewards"] == {"reward": 1}
