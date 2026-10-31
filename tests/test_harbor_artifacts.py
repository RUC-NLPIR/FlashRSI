"""Collected outputs survive temporary cleanup without copying credentials."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("harbor")
from harbor.models.trial.paths import TrialPaths

from flashrsi.core import Task
from flashrsi.integrations import harbor


@pytest.fixture
def execution(tmp_path, monkeypatch):
    agent = SimpleNamespace(
        config={
            "llm": {"model_name": "fixture", "api_key": "credential-for-archive-test"},
            "harbor": {"artifacts_dir": str(tmp_path / "saved")},
        },
        snapshot=SimpleNamespace(id="snapshot"),
        _check_container=lambda: None,
    )
    task = Task("../untrusted-task-id", "Edit workbook", env=str(tmp_path / "task"))
    native = SimpleNamespace(
        instruction=task.question,
        checksum="checksum",
        config=SimpleNamespace(
            steps=[],
            environment=SimpleNamespace(os=SimpleNamespace(value="linux")),
            agent=SimpleNamespace(timeout_sec=30),
        ),
    )
    monkeypatch.setattr(harbor, "HarborTask", lambda _: native)
    monkeypatch.setattr(harbor.shutil, "which", lambda _: "docker-fixture")
    monkeypatch.setattr(harbor, "_stage", lambda *args: None)
    return agent, task


def outputs(paths):
    paths.mkdir()
    workbook = paths.artifacts_dir / "logs/artifacts/answer.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"PK\x03\x04\x00\xffWORKBOOK")
    paths.test_stdout_path.write_text("credential-for-archive-test")
    (paths.verifier_dir / "native-result.json").write_text('{"accuracy": 1}')
    (paths.agent_dir / "flashrsi.json").write_text(
        json.dumps({"messages": [{"type": "RunConfig", "snapshot_id": "snapshot"}]})
    )
    paths.config_path.write_text('{"api_key": "credential-for-archive-test"}')
    paths.result_path.write_text('{"status": "fixture"}')


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_outputs_survive_trial_cleanup(execution, tmp_path, monkeypatch, outcome):
    agent, task = execution
    originals = []

    async def create(config):
        paths = TrialPaths(config.trials_dir / "same-trial-name")
        outputs(paths)
        originals.append(paths.trial_dir)

        async def run():
            if outcome == "cancel":
                raise asyncio.CancelledError()
            if outcome == "error":
                raise RuntimeError("verifier failed")
            return SimpleNamespace(
                id="same-trial-id",
                exception_info=None,
                verifier_result=SimpleNamespace(rewards={"reward": 1}),
            )

        return SimpleNamespace(paths=paths, run=run)

    monkeypatch.setattr(harbor.Trial, "create", create)
    for _ in range(2):
        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(harbor._run(agent, task))
        else:
            result = asyncio.run(harbor._run(agent, task))
            assert result.status == ("finished" if outcome == "success" else "error")
            assert Path(result.messages[-1]["artifacts"]["directory"]).is_dir()
    assert all(not path.exists() for path in originals)
    archives = list((tmp_path / "saved").iterdir())
    assert len(archives) == 2  # Repeated task, Snapshot and trial IDs never overwrite.
    for archive in archives:
        assert (archive / "artifacts/logs/artifacts/answer.xlsx").read_bytes() == (
            b"PK\x03\x04\x00\xffWORKBOOK"
        )
        assert json.loads((archive / "verifier/native-result.json").read_text()) == {
            "accuracy": 1
        }
        assert (
            "credential-for-archive-test"
            not in (archive / "verifier/test-stdout.txt").read_text()
        )
        assert not (archive / "config.json").exists()
        manifest = json.loads((archive / "manifest.json").read_text())
        assert manifest["task_id"] == task.task_id
        assert manifest["snapshot_id"] == "snapshot"


def test_archive_failure_is_not_reported_as_success(execution, monkeypatch):
    agent, task = execution

    async def create(config):
        paths = TrialPaths(config.trials_dir / "trial")
        outputs(paths)
        return SimpleNamespace(
            paths=paths,
            run=AsyncMock(
                return_value=SimpleNamespace(
                    id="trial",
                    exception_info=None,
                    verifier_result=SimpleNamespace(rewards={"reward": 1}),
                )
            ),
        )

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(harbor.Trial, "create", create)
    monkeypatch.setattr(harbor, "_archive_trial", fail)
    result = asyncio.run(harbor._run(agent, task))
    assert result.status == "error"
    assert "archive failed" in result.error_message
    assert result.messages[-1]["artifact_error"] == "disk full"


def test_archive_rejects_links_outside_trial(tmp_path):
    paths = TrialPaths(tmp_path / "trial")
    paths.mkdir()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("private host data")
    try:
        (paths.artifacts_dir / "link").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires OS permission")
    with pytest.raises(RuntimeError, match="Refusing linked artifact"):
        harbor._archive_trial(
            SimpleNamespace(paths=paths), tmp_path / "saved", {"task_id": "task"}, []
        )
    archive = next((tmp_path / "saved").iterdir())
    assert not (archive / "artifacts/link").exists()
    assert "error" in json.loads((archive / "manifest.json").read_text())


@pytest.mark.parametrize("failed_phase", [None, "solve", "regrade"])
def test_swe_pro_keeps_both_phases(execution, tmp_path, monkeypatch, failed_phase):
    from flashrsi.integrations import swe_bench_pro as pro

    agent, task = execution
    agent.config["timeout"] = 30
    task = replace(task, metadata={"task_checksum": "checksum"})
    monkeypatch.setattr(pro, "HarborTask", harbor.HarborTask)
    monkeypatch.setattr(pro, "_stage", lambda *args: None)
    monkeypatch.setattr(pro, "_runtime", lambda _: (agent.config, []))
    monkeypatch.setattr(pro, "_native_tooling", lambda: ("fixture:ReplayAgent", "true"))
    phases = []
    patch_path = None

    async def create(config):
        nonlocal patch_path
        phase = "solve" if not phases else "regrade"
        phases.append(phase)
        paths = TrialPaths(config.trials_dir / "trial")
        outputs(paths)
        if phase == "solve":
            patch_path = paths.agent_dir / "model.patch"
            patch_path.write_bytes(b"--- before\n+++ after\n")
        else:
            (paths.agent_dir / "replay.json").write_text(
                json.dumps({"patch": str(patch_path), "apply_rc": 0})
            )

        async def run():
            if phase == failed_phase:
                raise RuntimeError(phase + " failed")
            return SimpleNamespace(
                id=phase,
                exception_info=None,
                verifier_result=SimpleNamespace(rewards={"reward": 1}),
            )

        return SimpleNamespace(paths=paths, run=run)

    monkeypatch.setattr(pro.Trial, "create", create)
    result = asyncio.run(pro._run(agent, task, {}))
    assert result.status == ("error" if failed_phase else "finished")
    assert not patch_path.exists()
    for phase in phases:
        archive = Path(result.messages[-1][phase + "_artifacts"]["directory"])
        manifest = json.loads((archive / "manifest.json").read_text())
        assert manifest["phase"] == phase
        assert manifest["snapshot_id"] == "snapshot"
        assert (archive / "verifier/native-result.json").is_file()
        if phase == "solve":
            assert (
                archive / "agent/model.patch"
            ).read_bytes() == b"--- before\n+++ after\n"
    assert len(list((tmp_path / "saved").iterdir())) == len(phases)


@pytest.mark.parametrize("explicit", [False, True])
def test_runner_places_archives_in_experiment(tmp_path, monkeypatch, explicit):
    from flashrsi import runner
    from flashrsi.benchmarks import SpreadsheetBench2
    from flashrsi.config import load_config

    config = load_config(
        overrides={
            "run": {"output_dir": str(tmp_path / "runs")},
            "agent": {"llm": {"model_name": "fixture"}},
            "algorithm": {"worker": {"llm": {"model_name": "fixture"}}},
        }
    )
    benchmark = SpreadsheetBench2({})
    benchmark._splits = {"test": ()}
    target_config = (
        {"harbor": {"artifacts_dir": str(tmp_path / "custom")}} if explicit else {}
    )
    algorithm = SimpleNamespace(
        config=config.algorithm,
        target=SimpleNamespace(config=target_config),
        worker=SimpleNamespace(component_rules={}),
        benchmark=benchmark,
        evolve=AsyncMock(return_value=SimpleNamespace(id="snapshot")),
        _evaluate=AsyncMock(return_value=()),
    )
    monkeypatch.setattr(runner, "_prepare", AsyncMock(return_value=algorithm))
    directory, _ = asyncio.run(runner._run(config))
    expected = tmp_path / "custom" if explicit else directory / "artifacts/harbor"
    assert Path(target_config["harbor"]["artifacts_dir"]) == expected
