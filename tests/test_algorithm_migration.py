"""New algorithm registration and independent TerminalBench evolution data."""

import pytest

from flashrsi.benchmarks import terminal_bench
from flashrsi.core import Task


def task_tree(root, names):
    for name in names:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "task.toml").touch()
    return root


def native_task(directory, source):
    return Task(
        directory.name,
        f"instruction for {directory.name}",
        env=str(directory),
        metadata={"source_split": "unassigned", "task_checksum": directory.name},
    )


def test_external_evolution_tasks_replace_only_train(tmp_path, monkeypatch):
    monkeypatch.setattr(terminal_bench, "_task_from_directory", native_task)
    downstream = task_tree(tmp_path / "downstream", ["a", "b", "c"])
    external = task_tree(tmp_path / "external", ["x", "y"])
    config = {"data_path": downstream, "split": {"train": 1, "dev": 1, "test": 1}}
    baseline = terminal_bench.TerminalBench(config).load()
    benchmark = terminal_bench.TerminalBench(
        {**config, "evolution_data_path": external}
    )
    splits = benchmark.load()
    assert {task.task_id for task in splits["train"]} == {"x", "y"}
    assert splits["dev"] == baseline["dev"]
    assert splits["test"] == baseline["test"]
    assert benchmark.metadata["evolution_source"]["data_path"] == str(external)
    assert set(benchmark._tasks_by_id) == {
        task.task_id for tasks in splits.values() for task in tasks
    }


@pytest.mark.parametrize("collision", ["id", "question", "checksum"])
def test_external_evolution_overlap_is_rejected(tmp_path, monkeypatch, collision):
    downstream = task_tree(tmp_path / "downstream", ["heldout"])
    external = task_tree(tmp_path / "external", ["evolution"])

    def load(directory, source):
        return Task(
            "same" if collision == "id" else directory.name,
            "same question" if collision == "question" else directory.name,
            env=str(directory),
            metadata={
                "source_split": "unassigned",
                "task_checksum": "same" if collision == "checksum" else directory.name,
            },
        )

    monkeypatch.setattr(terminal_bench, "_task_from_directory", load)
    benchmark = terminal_bench.TerminalBench(
        {
            "data_path": downstream,
            "evolution_data_path": external,
            "split": {"train": 0, "dev": 0, "test": 1},
        }
    )
    with pytest.raises(ValueError, match="overlap"):
        benchmark.load()
