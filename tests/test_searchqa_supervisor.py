import json
from types import SimpleNamespace

import pytest

from scripts import supervise_searchqa_experiment as supervisor
from scripts._parallel_plan_migration import atomic_json


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("llm_error: Error code: 502", True),
        ("timeout after 300s", True),
        ("llm_error: generation did not complete: length", True),
        ("Error code: 400 maximum context length", False),
        ("Invalid patch", False),
    ],
)
def test_failure_uses_saved_error_and_rejects_nontransient(tmp_path, reason, expected):
    path = tmp_path / "cache/errors/target/model/failed.json"
    atomic_json(path, {"key": "request", "trajectory": {"error_message": reason}})
    result = supervisor._failure(
        tmp_path, {"error": f"failed twice; trajectory: {path}"}
    )
    assert result == (expected, reason, "request")


def test_restarts_only_dead_transient_failure_with_identical_command(
    tmp_path, monkeypatch
):
    experiment = tmp_path / "full/miniagent"
    atomic_json(
        experiment / "status.json",
        {"pid": 10, "status": "error", "error": "Error code: 502"},
    )
    record_path = tmp_path / "process.json"
    command = [
        "python",
        "scripts/run_searchqa_parallel_experiment.py",
        "--harness",
        "miniagent",
    ]
    atomic_json(
        record_path, {"pid": 10, "command": command, "log": str(tmp_path / "run.log")}
    )
    calls = []
    sleeps = []

    def popen(args, **kwargs):
        calls.append(args)
        if args == command:
            atomic_json(experiment / "result.json", {"status": "finished"})
        return SimpleNamespace(pid=20, poll=lambda: 0)

    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    monkeypatch.setattr(supervisor, "_alive", lambda pid: (False, ""))
    monkeypatch.setattr(supervisor.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        supervisor.sys,
        "argv",
        [
            "supervise",
            "--harness",
            "miniagent",
            "--run-root",
            str(tmp_path),
            "--process-record",
            str(record_path),
        ],
    )
    assert supervisor.main() == 0
    assert calls[0] == command and len(calls) == 2
    assert sleeps == [15, 15]
    state = json.loads((experiment / "supervisor.json").read_text())
    assert state["status"] == "finished" and len(state["resumes"]) == 1


def test_does_not_start_another_process_when_pid_identity_differs(
    tmp_path, monkeypatch
):
    record_path = tmp_path / "process.json"
    atomic_json(
        record_path,
        {"pid": 10, "command": ["scripts/run_searchqa_parallel_experiment.py"]},
    )
    monkeypatch.setattr(supervisor, "_alive", lambda pid: (True, "different program"))
    monkeypatch.setattr(
        supervisor.sys,
        "argv",
        [
            "supervise",
            "--harness",
            "miniagent",
            "--run-root",
            str(tmp_path),
            "--process-record",
            str(record_path),
        ],
    )
    with pytest.raises(ValueError, match="no longer matches"):
        supervisor.main()
