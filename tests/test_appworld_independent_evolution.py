import json

import pytest

from flashrsi.benchmarks.appworld import AppWorldBenchmark
from flashrsi.core import Trajectory


@pytest.fixture
def native(tmp_path):
    (tmp_path / "datasets").mkdir()
    (tmp_path / "base_dbs").mkdir()
    (tmp_path / "base_dbs/base.db").write_bytes(b"native fixture")

    def task(task_id, instruction):
        directory = tmp_path / "tasks" / task_id
        for folder in ("dbs", "ground_truth"):
            (directory / folder).mkdir(parents=True)
            (directory / folder / "data.txt").write_text("fixture")
        (directory / "specs.json").write_text(
            json.dumps(
                {
                    "instruction": instruction,
                    "datetime": "2026-01-01T00:00:00",
                    "db_version": "fixture",
                    "supervisor": {
                        "first_name": "A",
                        "last_name": "B",
                        "email": "a@example.test",
                        "phone_number": "123",
                    },
                }
            )
        )

    for split, ids in {
        "train": ["aa_1"],
        "dev": ["bb_1"],
        "test_normal": ["cc_1"],
        "test_challenge": ["dd_1", "ee_1"],
    }.items():
        (tmp_path / "datasets" / f"{split}.txt").write_text("\n".join(ids))
        for task_id in ids:
            task(task_id, f"Original instruction {task_id}")
    return tmp_path, task


def config(root, **kwargs):
    return {"name": "appworld", "data_path": str(root), "seed": 42, **kwargs}


def test_independent_native_tasks_preserve_heldout_and_scoring(native):
    root, _ = native
    old = AppWorldBenchmark(config(root)).load()
    bench = AppWorldBenchmark(
        config(root, evolution_test_set="test_challenge", evolution_limit=1)
    )
    splits = bench.load()
    assert splits["dev"] == old["dev"] and splits["test"] == old["test"]
    assert len(splits["train"]) == 1
    task = splits["train"][0]
    assert task.metadata["upstream_split"] == "test_challenge"
    assert task.metadata["source_split"] == "test"
    assert task.env == str(root / "tasks" / task.task_id)
    source = bench.metadata["evolution_source"]
    assert source["pool_size"] == 2
    assert source["experiment_role"] == "external_evolution"
    assert source["native_role"] == "published_evaluation"
    assert bench.load() is splits
    traj = Trajectory(
        task=task,
        status="finished",
        messages=(
            {
                "type": "AppWorldVerifier",
                "task_id": task.task_id,
                "task_checksum": task.metadata["task_checksum"],
                "success": True,
            },
        ),
    )
    assert bench.grade((traj,))[0].metrics["reward"] == 1


@pytest.mark.parametrize("kind", ["id", "scenario", "instruction"])
def test_guard_checks_full_pools_before_limits(native, kind):
    root, add = native
    task_id = {"id": "cc_1", "scenario": "cc_2", "instruction": "ff_1"}[kind]
    if kind != "id":
        add(
            task_id,
            "  ORIGINAL   instruction CC_1  " if kind == "instruction" else "different",
        )
    with (root / "datasets/test_challenge.txt").open("a") as stream:
        stream.write("\n" + task_id)
    bench = AppWorldBenchmark(
        config(root, limit=3, evolution_test_set="test_challenge", evolution_limit=1)
    )
    with pytest.raises(ValueError, match="overlaps"):
        bench.load()
    assert bench._splits is None


@pytest.mark.parametrize("value", ["test_normal", "train", "../test_challenge", True])
def test_rejects_selected_heldout_or_invalid_external_split(native, value):
    root, _ = native
    with pytest.raises(ValueError, match="evolution_test_set"):
        AppWorldBenchmark(config(root, evolution_test_set=value)).load()


def test_invalid_evolution_limit_does_not_publish_partial_splits(native):
    root, _ = native
    bench = AppWorldBenchmark(
        config(root, evolution_test_set="test_challenge", evolution_limit=0)
    )
    with pytest.raises(ValueError, match="limit"):
        bench.load()
    assert bench._splits is None


def test_pool_checksum_binds_native_evaluation_files(native):
    root, _ = native
    cfg = config(root, evolution_test_set="test_challenge", evolution_limit=1)
    first = AppWorldBenchmark(cfg)
    first.load()
    (root / "tasks/ee_1/ground_truth/data.txt").write_text("changed fixture")
    second = AppWorldBenchmark(cfg)
    second.load()
    assert (
        first.metadata["evolution_source"]["pool_checksum"]
        != second.metadata["evolution_source"]["pool_checksum"]
    )
