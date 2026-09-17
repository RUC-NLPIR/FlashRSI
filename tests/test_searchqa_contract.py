import json
import re
import sys
from types import ModuleType
from unittest.mock import Mock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flashrsi.benchmarks.searchqa import SearchQA
from flashrsi.config import load_config
from flashrsi.core import Trajectory


def _config(**benchmark):
    return load_config(
        overrides={
            "agent": {"llm": {"model_name": "target"}},
            "algorithm": {"worker": {"llm": {"model_name": "worker"}}},
            "benchmark": benchmark,
        }
    )


def _row(index, answers=None):
    return {
        "id": f"task-{index}",
        "question": f"Question {index}?",
        "context": f"Context {index}",
        "answers": answers if answers is not None else [f"Answer {index}"],
    }


def test_default_loader_uses_pinned_source_and_all_source_splits(monkeypatch):
    datasets = ModuleType("datasets")
    datasets.load_dataset = Mock(
        return_value={
            "train": [_row(0)],
            "dev": [_row(1)],
            "test": [_row(2)],
        }
    )
    monkeypatch.setitem(sys.modules, "datasets", datasets)
    benchmark = SearchQA(_config(split={"train": 0, "dev": 1, "test": 0}))

    splits = benchmark.load()

    datasets.load_dataset.assert_called_once_with(
        "jinjiajie/flashrsi",
        name="searchqa",
        revision=benchmark.metadata["revision"],
    )
    assert re.fullmatch(r"[0-9a-f]{40}", benchmark.metadata["revision"])
    assert splits["train"] == splits["test"] == ()
    assert {task.task_id: task.metadata["source_split"] for task in benchmark.dev} == {
        "task-0": "train",
        "task-1": "dev",
        "task-2": "test",
    }
    assert benchmark.load() is splits
    assert datasets.load_dataset.call_count == 1


@pytest.mark.parametrize(
    ("seed", "limit", "ratios"),
    [
        (0, None, {"train": 0.6, "dev": 0.4, "test": 0}),
        (17, 7, {"train": 0, "dev": 0.6, "test": 0.4}),
        (-3, 1, {"train": 0.6, "dev": 0, "test": 0.4}),
        (0, 40, {"train": 0.6, "dev": 0.4, "test": 0}),
    ],
)
def test_seed_limit_and_zero_ratios_are_order_independent(
    monkeypatch, seed, limit, ratios
):
    rows = tuple(("source", _row(index)) for index in range(24))
    config = _config(seed=seed, limit=limit, split=ratios)
    first = SearchQA(config)
    second = SearchQA(config)
    monkeypatch.setattr(first, "_load_source_rows", lambda: iter(rows))
    monkeypatch.setattr(second, "_load_source_rows", lambda: reversed(rows))

    splits = first.load()

    assert splits == second.load()
    ids = [task.task_id for tasks in splits.values() for task in tasks]
    assert len(ids) == len(set(ids)) == min(limit or len(rows), len(rows))
    for name, ratio in ratios.items():
        if ratio == 0:
            assert splits[name] == ()


def test_seed_controls_limited_task_selection(monkeypatch):
    selections = []
    for seed in (0, 1):
        benchmark = SearchQA(_config(seed=seed, limit=7))
        monkeypatch.setattr(
            benchmark,
            "_load_source_rows",
            lambda: (("source", _row(index)) for index in range(24)),
        )
        selections.append(
            {task.task_id for tasks in benchmark.load().values() for task in tasks}
        )

    assert selections[0] != selections[1]


def test_duplicate_ids_outside_the_limit_are_rejected(monkeypatch):
    rows = tuple(("source", _row(index)) for index in range(8))
    config = _config(seed=7, limit=1, split={"train": 1, "dev": 0, "test": 0})
    original = SearchQA(config)
    monkeypatch.setattr(original, "_load_source_rows", lambda: iter(rows))
    (selected,) = original.load()["train"]
    excluded = next(row for row in rows if row[1]["id"] != selected.task_id)

    duplicate = SearchQA(config)
    monkeypatch.setattr(duplicate, "_load_source_rows", lambda: iter((*rows, excluded)))

    with pytest.raises(ValueError, match="duplicate task id"):
        duplicate.load()


@pytest.mark.parametrize("directory", [False, True], ids=["json-file", "split-dir"])
def test_local_sources_preserve_provenance_when_reassigned(tmp_path, directory):
    rows = [_row(index) for index in range(6)]
    if directory:
        path = tmp_path
        (path / "train.json").write_text(json.dumps(rows[:2]))
        (path / "validation.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows[2:4])
        )
        (path / "test.json").write_text(json.dumps(rows[4:]))
        expected_sources = (
            "train",
            "train",
            "validation",
            "validation",
            "test",
            "test",
        )
    else:
        path = tmp_path / "questions.json"
        path.write_text(json.dumps(rows))
        expected_sources = ("local",) * len(rows)
    benchmark = SearchQA(
        _config(data_path=str(path), split={"train": 0, "dev": 1, "test": 0})
    )

    splits = benchmark.load()

    assert splits["train"] == splits["test"] == ()
    assert {task.task_id: task.metadata["source_split"] for task in benchmark.dev} == {
        row["id"]: source for row, source in zip(rows, expected_sources, strict=True)
    }


@pytest.mark.parametrize("directory", [False, True], ids=["parquet-file", "split-dir"])
def test_local_parquet_loads_canonical_records(tmp_path, directory):
    rows = [_row(index, [f"Answer {index}", f"Alias {index}"]) for index in range(6)]
    if directory:
        path = tmp_path
        expected_sources = {}
        for index, split in enumerate(("train", "dev", "test")):
            records = rows[index * 2 : (index + 1) * 2]
            pq.write_table(pa.Table.from_pylist(records), path / f"{split}.parquet")
            expected_sources.update({row["id"]: split for row in records})
    else:
        path = tmp_path / "questions.parquet"
        pq.write_table(pa.Table.from_pylist(rows), path)
        expected_sources = {row["id"]: "local" for row in rows}
    benchmark = SearchQA(
        _config(data_path=path, split={"train": 0, "dev": 1, "test": 0})
    )

    splits = benchmark.load()

    assert splits["train"] == splits["test"] == ()
    tasks = {task.task_id: task for task in benchmark.dev}
    assert tasks.keys() == expected_sources.keys()
    for row in rows:
        task = tasks[row["id"]]
        assert task.ground_truth == row["answers"][0]
        assert task.metadata["answers"] == tuple(row["answers"])
        assert task.metadata["source_split"] == expected_sources[row["id"]]
        assert (
            f"Context:\n{row['context']}\n\nQuestion:\n{row['question']}"
            in task.question
        )
    assert benchmark.metadata == {"source": "local", "data_path": str(path)}


def test_grading_preserves_trajectories_and_counts_repeated_tokens(monkeypatch):
    benchmark = SearchQA(_config(split={"train": 1, "dev": 0, "test": 0}))
    monkeypatch.setattr(
        benchmark,
        "_load_source_rows",
        lambda: [("source", _row(0, ["red red blue", "Crimson Tide"]))],
    )
    (task,) = benchmark.load()["train"]
    original_metrics = {"latency": 0.5, "exact_match": 0.2, "f1": 0.4}
    messages = ({"role": "assistant", "content": "recorded response"},)
    usage = {"input_tokens": 13, "output_tokens": 3}
    trajectories = tuple(
        Trajectory(
            task,
            status,
            output,
            messages=messages,
            metrics=original_metrics,
            error_message=error,
            usage=usage,
        )
        for status, output, error in (
            ("finished", "The CRIMSON tide!", None),
            ("finished", "red blue blue", None),
            ("error", "Crimson Tide", "backend failed after producing output"),
        )
    )

    graded = benchmark.grade(trajectories)

    assert isinstance(graded, tuple)
    assert [item.metrics["exact_match"] for item in graded] == [1.0, 0.0, 0.0]
    assert [item.metrics["f1"] for item in graded] == pytest.approx([1.0, 2 / 3, 0.0])
    for original, result in zip(trajectories, graded, strict=True):
        assert result is not original
        assert result.task is original.task
        assert result.messages == original.messages == messages
        assert result.usage == original.usage == usage
        assert result.output == original.output
        assert result.status == original.status
        assert result.error_message == original.error_message
        assert result.metrics["latency"] == original_metrics["latency"]
        assert original.metrics == original_metrics
    assert original_metrics == {"latency": 0.5, "exact_match": 0.2, "f1": 0.4}


def test_split_access_and_grading_require_load():
    benchmark = SearchQA(_config())

    for name in ("train", "dev", "test"):
        with pytest.raises(RuntimeError, match=r"call load\(\) first"):
            getattr(benchmark, name)
    with pytest.raises(RuntimeError, match=r"call load\(\) first"):
        benchmark.grade(())
