import asyncio
import json

import pytest

from flashrsi import runner
from flashrsi.cli import main
from flashrsi.config import load_config
from flashrsi.core import Agent, Snapshot, Trajectory


class Target(Agent):
    name = "offline"
    description = "Runner fixture."

    async def _run(self, prompt, working_dir=None):
        return Trajectory(
            output="Paris"
            if b"check evidence" in self.snapshot.files["skills/main.md"].content
            else "Rome"
        )


class Worker(Agent):
    name = "offline_worker"
    description = "Runner Worker fixture."

    async def _run(self, prompt, working_dir=None):
        return Trajectory(
            output=json.dumps(
                {
                    "edits": [
                        {
                            "op": "append",
                            "path": "skills/main.md",
                            "content": "check evidence",
                        }
                    ]
                }
            )
        )


@pytest.fixture
def config(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / "skills").mkdir(parents=True)
    (source / "skills/main.md").write_text("Initial rules.")
    (source / "components.yaml").write_text("skill: ['skills/**']")
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            [
                {
                    "id": str(i),
                    "question": "Capital?",
                    "context": "Paris.",
                    "answers": ["Paris"],
                }
                for i in range(5)
            ]
        )
    )
    monkeypatch.setitem(runner._AGENTS, "offline", Target)
    monkeypatch.setattr(runner, "LLM", Worker)
    return load_config(
        overrides={
            "run": {"output_dir": str(tmp_path / "runs")},
            "agent": {
                "name": "offline",
                "source_dir": str(source),
                "llm": {"model_name": "target", "api_key": "target-private-secret"},
            },
            "benchmark": {"data_path": str(data)},
            "algorithm": {
                "max_steps": 1,
                "worker": {
                    "llm": {"model_name": "worker", "api_key": "worker-private-secret"}
                },
            },
        }
    )


def test_runner_persists_full_experiment_and_final_test(config):
    run_dir, result = asyncio.run(runner._run(config))
    assert result["test_score"] == 1.0
    assert result["test_tasks"] == 1
    assert Snapshot.load(run_dir / "snapshots" / f"{result['snapshot_id']}.json")
    saved_config = load_config(run_dir / "config.yaml")
    assert saved_config.algorithm.num_epochs == 4
    assert saved_config.algorithm.edit_budget == 4
    assert "num_epochs" not in config.algorithm
    assert len(list((run_dir / "snapshots").glob("*.json"))) == 2
    assert len(list((run_dir / "trajectories").glob("*-test.json"))) == 1
    assert (run_dir / "result.json").is_file()
    assert not (run_dir / "error.json").exists()
    assert not list((run_dir / "working").iterdir())
    text = "".join(path.read_text() for path in run_dir.rglob("*") if path.is_file())
    assert "target-private-secret" not in text and "worker-private-secret" not in text


def test_benchmark_is_loaded_once_by_algorithm_initialization(config, monkeypatch):
    original = runner.SearchQA.load
    loads = []

    def load(self):
        loads.append(self)
        return original(self)

    monkeypatch.setattr(runner.SearchQA, "load", load)
    asyncio.run(runner._run(config))
    assert len(loads) == 1


def test_cli_executes_and_reports_actual_result(config, tmp_path, capsys):
    # Write a real config to exercise CLI parsing and the complete runner.
    import yaml

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(json.loads(json.dumps(config, default=dict))))
    assert main(["run", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Completed experiment" in out
    assert "Test exact_match: 1.0" in out


def test_runner_failure_keeps_evidence_and_reports_redacted_error(config, monkeypatch):
    async def fail(self, prompt, working_dir=None):
        raise RuntimeError("provider failed worker-private-secret")

    monkeypatch.setattr(Worker, "_run", fail)
    with pytest.raises(RuntimeError, match="provider failed"):
        asyncio.run(runner._run(config))
    from pathlib import Path

    (run_dir,) = Path(config.run.output_dir).iterdir()
    assert "worker-private-secret" not in (run_dir / "error.json").read_text()
    assert not (run_dir / "result.json").exists()
    assert list((run_dir / "trajectories").glob("*-train.json"))


def test_cli_redacts_runtime_exceptions(config, monkeypatch, tmp_path, capsys):
    async def fail(config):
        raise RuntimeError("worker-private-secret")

    monkeypatch.setattr(runner, "_run", fail)
    with pytest.raises(SystemExit):
        main(
            [
                "run",
                "--model",
                "target",
                "--worker-model",
                "worker",
                "--algorithm.worker.llm.api_key=worker-private-secret",
            ]
        )
    assert "worker-private-secret" not in capsys.readouterr().err
