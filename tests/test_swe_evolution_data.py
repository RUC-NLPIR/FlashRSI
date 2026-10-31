"""Independent SWE evolution tasks retain native task and grading identities."""

import json
from copy import deepcopy

import pytest

from flashrsi.benchmarks.swe_bench import SWEBench, _checksum
from flashrsi.core import Trajectory


def repair(name):
    return {
        "instance_id": name,
        "repo": "example/project",
        "base_commit": "a" * 40,
        "problem_statement": f"Repair issue {name}",
        "image": f"example/repair-{name}:fixed",
        "version": "1.0",
        "environment_setup_commit": "b" * 40,
        "patch": "reference patch kept on the host",
        "test_patch": "official test patch kept on the host",
        "eval_script": "official evaluation script",
        "log_parser": "pytest",
        "FAIL_TO_PASS": ["test_repair"],
        "PASS_TO_PASS": [],
        "eval_type": "pass_and_fail",
    }


def save(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")
    return str(path)


def test_independent_swe_data_preserves_heldout_and_official_grading(tmp_path):
    config = {
        "data_path": save(tmp_path / "downstream.json", [repair(n) for n in "abc"]),
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
    }
    baseline = SWEBench(config).load()
    rows = [repair("external-x"), repair("external-y")]
    external = save(tmp_path / "external.json", rows)
    benchmark = SWEBench({**config, "evolution_data_path": external})
    splits = benchmark.load()
    assert {task.task_id for task in splits["train"]} == {
        "external-x",
        "external-y",
    }
    assert splits["dev"] == baseline["dev"]
    assert splits["test"] == baseline["test"]
    assert benchmark.load() is splits
    assert benchmark.metadata["evolution_source"]["data_path"] == external
    assert benchmark.metadata["data_path"] == config["data_path"]
    for task in splits["train"]:
        row = next(row for row in rows if row["instance_id"] == task.task_id)
        assert benchmark._rows_by_id[task.task_id] == row
        assert task.metadata["task_checksum"] == _checksum(row)
        assert task.env == row["image"]
        assert "patch" not in task.metadata
        trace = Trajectory(
            task=task,
            status="finished",
            messages=(
                {
                    "type": "SWEBenchVerifier",
                    "task_id": task.task_id,
                    "task_checksum": task.metadata["task_checksum"],
                    "resolved": True,
                },
            ),
        )
        assert benchmark.grade((trace,))[0].metrics["resolved"] == 1.0
        with pytest.raises(ValueError, match="SWEBenchVerifier"):
            benchmark.grade((Trajectory(task=task, status="finished"),))


@pytest.mark.parametrize("collision", ["id", "question", "image", "same_row"])
def test_swe_evolution_cannot_reuse_downstream_tasks(tmp_path, collision):
    downstream = repair("heldout")
    external = repair("external")
    if collision == "same_row":
        external = deepcopy(downstream)
    else:
        key = {"id": "instance_id", "question": "problem_statement", "image": "image"}[
            collision
        ]
        external[key] = downstream[key]
    benchmark = SWEBench(
        {
            "data_path": save(tmp_path / "downstream.json", [downstream]),
            "split": {"train": 0, "dev": 0, "test": 1},
            "evolution_data_path": save(tmp_path / "external.json", [external]),
        }
    )
    with pytest.raises(ValueError, match="overlap"):
        benchmark.load()
    assert benchmark._splits is None
    assert "evolution_source" not in benchmark.metadata


def test_evolution_limit_does_not_change_downstream_partition(tmp_path):
    config = {
        "data_path": save(tmp_path / "downstream.json", [repair(n) for n in "abcd"]),
        "split_counts": {"train": 0, "dev": 1, "test": 1},
        "seed": 42,
    }
    baseline = SWEBench(config).load()
    benchmark = SWEBench(
        {
            **config,
            "evolution_data_path": save(
                tmp_path / "external.json", [repair("x"), repair("y")]
            ),
            "evolution_limit": 1,
        }
    )
    splits = benchmark.load()
    assert len(splits["train"]) == 1
    assert splits["dev"] == baseline["dev"]
    assert splits["test"] == baseline["test"]


def test_evolution_rows_must_satisfy_native_swe_schema(tmp_path):
    benchmark = SWEBench(
        {
            "data_path": save(tmp_path / "downstream.json", [repair("heldout")]),
            "split": {"train": 0, "dev": 0, "test": 1},
            "evolution_data_path": save(
                tmp_path / "external.json", [{"instance_id": "not-a-swe-task"}]
            ),
        }
    )
    with pytest.raises(ValueError, match="requires non-empty repo"):
        benchmark.load()


@pytest.mark.parametrize("field", ["instance_id", "problem_statement", "image"])
def test_overlap_in_unsampled_downstream_is_rejected(tmp_path, field):
    downstream = [repair(f"native-{i}") for i in range(8)]
    cfg = {
        "data_path": save(tmp_path / "downstream.json", downstream),
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
    }
    selected = {t.task_id for group in SWEBench(cfg).load().values() for t in group}
    omitted = next(r for r in downstream if r["instance_id"] not in selected)
    external = repair("external")
    external[field] = omitted[field]
    bench = SWEBench(
        {
            **cfg,
            "evolution_data_path": save(tmp_path / "external.json", [external]),
            "evolution_limit": 1,
        }
    )
    with pytest.raises(ValueError, match="overlap"):
        bench.load()
    assert bench._splits is None


@pytest.mark.parametrize("field", ["problem_statement", "image"])
def test_overlap_in_unsampled_external_pool_is_rejected(tmp_path, field):
    external = [repair(f"external-{i}") for i in range(5)]
    path = tmp_path / "external.json"
    save(path, external)
    one = SWEBench(
        {
            "data_path": str(path),
            "split": {"train": 1, "dev": 0, "test": 0},
            "limit": 1,
            "seed": 42,
        }
    )
    one.load()
    omitted = next(r for r in external if r["instance_id"] != one.train[0].task_id)
    downstream = repair("downstream")
    omitted[field] = downstream[field]
    bench = SWEBench(
        {
            "data_path": save(tmp_path / "downstream.json", [downstream]),
            "split": {"train": 0, "dev": 0, "test": 1},
            "evolution_data_path": save(path, external),
            "evolution_limit": 1,
            "seed": 42,
        }
    )
    with pytest.raises(ValueError, match="overlap"):
        bench.load()


def test_raw_problem_overlap_ignores_only_whitespace_and_case(tmp_path):
    downstream = repair("downstream")
    external = repair("external")
    external["problem_statement"] = "  REPAIR\nissue\tdownstream  "
    bench = SWEBench(
        {
            "data_path": save(tmp_path / "downstream.json", [downstream]),
            "split": {"train": 0, "dev": 0, "test": 1},
            "evolution_data_path": save(tmp_path / "external.json", [external]),
        }
    )
    with pytest.raises(ValueError, match="overlap"):
        bench.load()


def test_complete_evolution_pool_identity_is_recorded(tmp_path):
    bench = SWEBench(
        {
            "data_path": save(tmp_path / "downstream.json", [repair("downstream")]),
            "split": {"train": 0, "dev": 0, "test": 1},
            "evolution_data_path": save(
                tmp_path / "external.json", [repair("x"), repair("y")]
            ),
            "evolution_limit": 1,
        }
    )
    bench.load()
    source = bench.metadata["evolution_source"]
    assert source["pool_size"] == 2 and len(source["pool_checksum"]) == 64
