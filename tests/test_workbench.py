"""Native data boundary, isolated tools and upstream state scoring."""

import asyncio
import csv
import json
import os
import shlex
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from flashrsi import _launch
from flashrsi.benchmarks import WorkBench
from flashrsi.benchmarks import workbench as native
from flashrsi.config import load_config
from flashrsi.core import Trajectory
from flashrsi.integrations import workbench
from flashrsi.runner import _BENCHMARKS


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    for name in native.DATABASE_FILES:
        path = tmp_path / "data" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    path = tmp_path / "data/processed/tasks_and_outcomes/email_tasks_and_outcomes.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["task", "outcome"])
        writer.writeheader()
        writer.writerows(
            {"task": f"Question {i}", "outcome": "['HIDDEN_REFERENCE']"}
            for i in range(4)
        )
    monkeypatch.setattr(native, "_upstream", lambda: tmp_path)
    return {"domains": ["email"], "split_counts": {"train": 1, "dev": 1, "test": 1}}


def test_load_requires_explicit_partition_and_hides_reference(dataset):
    with pytest.raises(ValueError, match="No experiment role"):
        WorkBench({"domains": ["email"]}).load()
    benchmark = WorkBench(dataset)
    splits = benchmark.load()
    assert {k: len(v) for k, v in splits.items()} == {"train": 1, "dev": 1, "test": 1}
    assert splits == WorkBench(dataset).load()
    assert len({t.task_id for ts in splits.values() for t in ts}) == 3
    for ts in splits.values():
        for task in ts:
            assert task.ground_truth is None
            assert "HIDDEN_REFERENCE" not in repr(task)


def test_grade_requires_host_provenance(dataset):
    benchmark = WorkBench(dataset)
    benchmark.load()
    task = benchmark.test[0]
    event = {
        "type": "WorkBenchVerifier",
        "task_id": task.task_id,
        "task_checksum": task.metadata["task_checksum"],
        "data_checksum": benchmark._data_checksum,
        "revision": native.REVISION,
        "ground_truth_version": "v2",
        "metrics": {"correct": 1.0, "exact_match": 0.0, "unwanted_side_effects": 0.0},
    }
    trajectory = Trajectory(task=task, messages=(event,))
    assert benchmark.grade((trajectory,))[0].metrics["correct"] == 1
    for field, value in [
        ("revision", "main"),
        ("data_checksum", "changed"),
        ("ground_truth_version", "v1"),
        ("metrics", {"correct": 1}),
    ]:
        with pytest.raises(ValueError):
            benchmark.grade((replace(trajectory, messages=({**event, field: value},)),))
    with pytest.raises(ValueError, match="host verifier"):
        benchmark.grade((Trajectory(task=task, output="Done"),))
    error = replace(trajectory, status="error", error_message="budget exhausted")
    assert benchmark.grade((error,))[0].metrics["correct"] == 0


def test_public_plan_selects_dependencies_without_docker():
    cfg = load_config(
        overrides={
            "benchmark": {"name": "workbench"},
            "agent": {"llm": {"model_name": "target"}},
            "algorithm": {"worker": {"llm": {"model_name": "worker"}}},
        }
    )
    plan = _launch._plan(cfg)
    assert _BENCHMARKS["workbench"] is WorkBench
    assert "workbench" in plan["extras"]
    assert not any("Docker" in p for p in plan["prerequisites"])


@pytest.fixture
def upstream():
    root = os.environ.get("FLASHRSI_WORKBENCH_UPSTREAM")
    if not root:
        pytest.skip("Set FLASHRSI_WORKBENCH_UPSTREAM to the pinned native checkout")
    return Path(root).resolve()


def test_native_state_isolation_and_side_effects(upstream, tmp_path):
    # Two live native processes must never share thread-local database state.
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    first = workbench._Session(upstream, upstream / "data", one)
    second = workbench._Session(upstream, upstream / "data", two)
    try:
        call = {
            "operation": "call",
            "name": "email.get_email_information_by_id",
            "arguments": {"email_id": "00000479", "field": "sender/recipient"},
        }
        original = first.request(call)
        assert "Nadia" in original["result"] or "nadia" in original["result"]
        first.request(
            {
                "operation": "call",
                "name": "email.delete_email",
                "arguments": {"email_id": "00000479"},
            }
        )
        assert first.request(call) != original
        assert second.request(call) == original
        scored = first.request(
            {
                "operation": "grade",
                "reference": ['email.delete_email.func(email_id="00000479")'],
            }
        )
        assert scored["metrics"] == {
            "correct": 1,
            "exact_match": 1,
            "unwanted_side_effects": 0,
        }
        wrong = first.request({"operation": "grade", "reference": []})
        assert wrong["metrics"]["correct"] == 0
        assert wrong["metrics"]["unwanted_side_effects"] == 1
        denied = second.request(
            {"operation": "call", "name": "__import__", "arguments": {}}
        )
        assert "error" in denied
    finally:
        first.close()
        second.close()


def test_native_harness_bridge_and_grader(upstream, tmp_path, monkeypatch):
    monkeypatch.setattr(native, "_upstream", lambda: upstream)
    benchmark = WorkBench(
        {"domains": ["email"], "split_counts": {"train": 1, "dev": 1, "test": 1}}
    )
    benchmark.load()
    task = benchmark.test[0]
    target = SimpleNamespace(
        name="claude_code",
        config={"allowed_tools": ["Bash"]},
        snapshot=SimpleNamespace(id="fixture-snapshot"),
    )
    reference = native.ast.literal_eval(benchmark._rows_by_id[task.task_id]["outcome"])

    async def run(prompt, working_dir):
        # This scripted unit fixture is not model smoke evidence.
        assert task.question in prompt and "2023-11-30" in prompt
        assert not (working_dir / "data").exists()
        assert not (working_dir / "src").exists()
        command = prompt.split("WorkBench tools (use your shell tool):\n", 1)[
            1
        ].splitlines()[0]
        args = shlex.split(command)
        token = args[args.index("--token") + 1]
        url = args[args.index("--bridge") + 1]
        opener = build_opener(ProxyHandler({}))

        def request(value, auth=token):
            with opener.open(
                Request(
                    url, json.dumps(value).encode(), {"Authorization": "Bearer " + auth}
                ),
                timeout=20,
            ) as response:
                return json.load(response)

        with pytest.raises(HTTPError) as exc:
            request({"name": "email.search_emails", "arguments": {}}, auth="wrong")
        assert exc.value.code == 403
        # Grade/reference fields from the solver cannot access the private grader.
        assert "error" in request({"operation": "grade", "reference": reference})
        for action in reference:
            import ast

            call = ast.parse(action.replace("\n", "\\n"), mode="eval").body
            name = ast.unparse(call.func).removesuffix(".func")
            arguments = {
                kw.arg: str(ast.literal_eval(kw.value)) for kw in call.keywords
            }
            assert "result" in request({"name": name, "arguments": arguments})
        return Trajectory(output=token, usage={"input_tokens": 7})

    target.run = run
    workbench.bind(target, benchmark)
    trajectory = asyncio.run(target._env_runner(target, task))
    trajectory = replace(trajectory, task=task)
    graded = benchmark.grade((trajectory,))[0]
    assert graded.metrics["correct"] == 1
    assert graded.usage["input_tokens"] == 7
    assert graded.output == "[REDACTED]"
    assert any(m["type"] == "WorkBenchTool" for m in graded.messages)
    assert graded.messages[-1]["ground_truth_version"] == "v2"


def test_native_all_tasks_and_custom_data_provenance(upstream, monkeypatch):
    monkeypatch.setattr(native, "_upstream", lambda: upstream)
    cfg = {
        "data_path": str(upstream / "data"),
        "split_counts": {"train": 1, "dev": 1, "test": 1},
    }
    benchmark = WorkBench(cfg)
    benchmark.load()
    assert len(benchmark._rows_by_id) == 690
    assert benchmark.metadata["data_mode"] == "local-native"
