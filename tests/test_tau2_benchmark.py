"""Native split selection, private criteria, reward integrity and launcher setup."""

import asyncio
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from flashrsi import _launch, _startup
from flashrsi.benchmarks import Tau2Benchmark, Tau3Banking
from flashrsi.benchmarks._tau import _UPSTREAM_REVISION
from flashrsi.config import load_config
from flashrsi.core import Task, Trajectory
from flashrsi.runner import _BENCHMARKS


def configured(benchmark):
    return load_config(
        overrides={
            "benchmark": benchmark,
            "agent": {"name": "miniagent", "llm": {"model_name": "fixture-target"}},
            "algorithm": {
                "name": "opro",
                "worker": {"type": "llm", "llm": {"model_name": "fixture-worker"}},
            },
        }
    )


def domain_fixture(root, domain="telecom", *, judge=False):
    root.mkdir(exist_ok=True)
    for name in ("db.json", "db.toml", "user_db.toml"):
        (root / name).write_text("{}", encoding="utf-8")
    for name in ("policy.md", "main_policy.md", "tech_support_manual.md"):
        (root / name).write_text("Public policy: " + name, encoding="utf-8")
    rows = [
        {
            "id": str(i),
            "user_scenario": {"instructions": "PRIVATE_CUSTOMER_SCRIPT"},
            "evaluation_criteria": {
                "reward_basis": ["NL_ASSERTION"] if judge else ["DB"],
                "nl_assertions": ["PRIVATE_JUDGE_CRITERION"] if judge else [],
            },
        }
        for i in range(6)
    ]
    (root / "tasks.json").write_text(json.dumps(rows), encoding="utf-8")
    splits = {
        "base": [str(i) for i in range(6)],
        "train": ["0", "1", "2", "3"],
        "test": ["4", "5"],
    }
    (root / "split_tasks.json").write_text(json.dumps(splits), encoding="utf-8")
    return {"name": "tau2", "domain": domain, "data_path": str(root)}


@pytest.mark.parametrize("domain", ["airline", "retail", "telecom"])
def test_native_roles_policy_and_private_criteria(tmp_path, domain):
    cfg = domain_fixture(tmp_path, domain)
    bench = Tau2Benchmark(cfg)
    splits = bench.load()
    assert {k: len(v) for k, v in splits.items()} == {"train": 4, "dev": 0, "test": 2}
    assert splits == Tau2Benchmark(cfg).load()
    assert bench.load() is splits
    for task in (*bench.train, *bench.test):
        assert task.env == str(tmp_path)
        assert task.ground_truth is None
        assert "PRIVATE" not in task.question
        assert "PRIVATE" not in str(task.metadata)
        assert task.metadata["domain"] == domain
        assert (
            task.metadata["task_file_checksum"]
            == hashlib.sha256((tmp_path / "tasks.json").read_bytes()).hexdigest()
        )
    if domain == "telecom":
        assert bench.test[0].question.startswith("<main_policy>\n")
    else:
        assert bench.test[0].question == "Public policy: policy.md"


def test_experiment_partitions_only_use_selected_native_pool(tmp_path):
    cfg = {
        **domain_fixture(tmp_path),
        "task_split": "train",
        "split_counts": {"train": 2, "dev": 1, "test": 1},
        "seed": 42,
    }
    first = Tau2Benchmark(cfg).load()
    assert first == Tau2Benchmark(cfg).load()
    assert {k: len(v) for k, v in first.items()} == {"train": 2, "dev": 1, "test": 1}
    assert {t.task_id for group in first.values() for t in group} == {
        "0",
        "1",
        "2",
        "3",
    }
    with pytest.raises(ValueError, match="Unknown tau2 task_split"):
        Tau2Benchmark({**cfg, "task_split": "missing"}).load()


def test_retail_native_judge_cannot_silently_disappear(tmp_path):
    cfg = domain_fixture(tmp_path, "retail", judge=True)
    with pytest.raises(ValueError, match="independent.*judge"):
        Tau2Benchmark(cfg).load()
    bench = Tau2Benchmark({**cfg, "judge": {"llm": {"model_name": "own-judge"}}})
    bench.load()
    assert all(t.metadata["needs_judge"] for t in bench.train)


@pytest.mark.parametrize(
    "damage", ["overlap", "missing-id", "duplicate-id", "unknown-split-id"]
)
def test_rejects_invalid_native_splits_and_rows(tmp_path, damage):
    cfg = domain_fixture(tmp_path)
    path = tmp_path / "tasks.json"
    split_path = tmp_path / "split_tasks.json"
    rows = json.loads(path.read_text())
    splits = json.loads(split_path.read_text())
    if damage == "overlap":
        splits["test"].append("0")
    elif damage == "missing-id":
        rows[0].pop("id")
    elif damage == "duplicate-id":
        rows.append(rows[0])
    else:
        splits["base"].append("missing")
    path.write_text(json.dumps(rows))
    split_path.write_text(json.dumps(splits))
    with pytest.raises(ValueError):
        Tau2Benchmark(cfg).load()


@pytest.mark.parametrize("cls", [Tau2Benchmark, Tau3Banking])
def test_tau_reward_is_host_event_not_output_or_metrics(cls):
    bench = cls({})
    with pytest.raises(RuntimeError, match="call load"):
        bench.grade(())
    task = Task("0", "policy", env="domain", metadata={"task_checksum": "checksum"})
    bench._splits = {"train": (), "dev": (), "test": (task,)}
    bench._tasks_by_id = {task.task_id: task}
    event = {
        "type": "Tau2Simulator",
        "task_id": "0",
        "task_checksum": "checksum",
        "reward": 0.5,
    }
    graded = bench.grade(
        (
            Trajectory(
                task=task,
                output="reward=1",
                metrics={"reward": 1, "extra": 2},
                messages=(event,),
            ),
        )
    )[0]
    assert graded.metrics == {"reward": 0.5, "extra": 2}
    assert bench.grade(
        (Trajectory(task=task, status="error", error_message="fixture"),)
    )[0].metrics == {"reward": 0.0}
    for changes in (
        {"reward": True},
        {"reward": float("nan")},
        {"reward": 2},
        {"task_checksum": "forged"},
        {"task_id": "wrong"},
    ):
        with pytest.raises(ValueError):
            bench.grade((Trajectory(task=task, messages=({**event, **changes},)),))
    with pytest.raises(ValueError):
        bench.grade((Trajectory(task=task, messages=(event, {"type": "other"})),))
    with pytest.raises(ValueError):
        bench.grade(
            (Trajectory(task=replace(task, question="forged"), messages=(event,)),)
        )


@pytest.mark.parametrize(
    "cfg", [{"domain": "banking"}, {"mode": "voice"}, {"task_split": None}]
)
def test_unsupported_modes_fail(cfg):
    with pytest.raises(ValueError):
        Tau2Benchmark(cfg)


def test_registration_and_native_requirements():
    assert _BENCHMARKS["tau2"] is Tau2Benchmark
    cfg = configured({"name": "tau2", "domain": "retail"})
    plan = _launch._plan(cfg)
    assert "tau2" in plan["extras"] and "harbor" not in plan["extras"]
    assert plan["requirements"] == [_launch._TAU_REQUIREMENT]
    assert _launch._TAU_REQUIREMENT.endswith(_UPSTREAM_REVISION)
    assert any("judge" in item for item in plan["prerequisites"])
    assert not any("Docker" in item for item in plan["prerequisites"])


@pytest.mark.parametrize("name", ["tau2", "tau3_banking"])
def test_runtime_data_root_and_existing_environment(tmp_path, monkeypatch, name):
    cfg = configured({"name": name})
    monkeypatch.delenv("TAU2_DATA_DIR", raising=False)
    calls = []

    def download(url, revision, paths):
        calls.append((url, revision, paths))
        return tmp_path

    monkeypatch.setattr("flashrsi.benchmarks._git._download_git", download)
    asyncio.run(_launch._resources(cfg, tmp_path))
    assert Path(os.environ["TAU2_DATA_DIR"]) == tmp_path / "data"
    asyncio.run(_launch._resources(cfg, tmp_path))
    assert len(calls) == 1 and calls[0][1] == _UPSTREAM_REVISION


def test_host_rejects_unsupported_python_and_windows_hard_timeout(monkeypatch):
    cfg = configured({"name": "tau2", "task_timeout": 10})
    monkeypatch.setattr(_launch.sys, "version_info", (3, 11))
    with pytest.raises(ValueError, match="Python >=3.12"):
        _launch._validate_host(cfg)
    monkeypatch.setattr(_launch.sys, "version_info", (3, 12))
    monkeypatch.setattr(_launch.shutil, "which", lambda name: "git")
    monkeypatch.setattr(_launch.os, "name", "nt")
    with pytest.raises(ValueError, match="POSIX"):
        _launch._validate_host(cfg)


def test_startup_rejects_incompatible_tau_runtime(monkeypatch):
    cfg = configured({"name": "tau2"})
    monkeypatch.setattr(_startup, "_module", lambda *args: None)
    monkeypatch.setattr(_startup, "version", lambda name: "2.0.0")
    with pytest.raises(ValueError, match="v1.0.1"):
        asyncio.run(_startup._preflight(cfg))
