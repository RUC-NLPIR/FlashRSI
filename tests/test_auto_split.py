import json
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from flashrsi.benchmarks.searchqa import SearchQA
from flashrsi.config import load_config


def _config(**benchmark):
    return load_config(
        overrides={
            "agent": {"model_name": "target"},
            "algorithm": {"worker": {"model_name": "worker"}},
            "benchmark": benchmark,
        }
    )


def _rows(split, count):
    return tuple(
        (
            split,
            {
                "id": f"{split}-{index}",
                "question": f"Question {index}?",
                "context": f"Context {index}",
                "answers": [f"Answer {index}"],
            },
        )
        for index in range(count)
    )


def _ids(tasks):
    return {task.task_id for task in tasks}


def test_default_auto_uses_official_searchqa_splits(monkeypatch):
    sizes = {"train": 400, "dev": 200, "test": 1400}
    datasets = ModuleType("datasets")
    datasets.load_dataset = Mock(
        return_value={
            name: [row for _, row in _rows(name, count)]
            for name, count in sizes.items()
        }
    )
    monkeypatch.setitem(sys.modules, "datasets", datasets)
    benchmark = SearchQA(_config())

    splits = benchmark.load()

    assert {name: len(tasks) for name, tasks in splits.items()} == sizes
    for name, tasks in splits.items():
        assert _ids(tasks) == {row["id"] for _, row in _rows(name, sizes[name])}
        assert {task.metadata["source_split"] for task in tasks} == {name}


def test_auto_recognizes_validation_directory_and_preserves_provenance(tmp_path):
    for name in ("train", "validation", "test"):
        (tmp_path / f"{name}.json").write_text(
            json.dumps([row for _, row in _rows(name, 2)])
        )
    benchmark = SearchQA(_config(data_path=tmp_path))

    splits = benchmark.load()

    assert tuple(map(len, splits.values())) == (2, 2, 2)
    assert _ids(benchmark.dev) == {"validation-0", "validation-1"}
    assert {task.metadata["source_split"] for task in benchmark.dev} == {"validation"}


@pytest.mark.parametrize(
    ("provided", "expected_sizes"),
    [
        ({"train": 10}, (6, 2, 2)),
        ({"local": 10}, (6, 2, 2)),
        ({"train": 10, "test": 3}, (8, 2, 3)),
        ({"train": 10, "dev": 3}, (8, 3, 2)),
        ({"train": 3}, (1, 1, 1)),
        ({"train": 2, "test": 3}, (1, 1, 3)),
    ],
)
def test_auto_fills_missing_splits_from_training_pool(
    monkeypatch, provided, expected_sizes
):
    rows = tuple(row for name, count in provided.items() for row in _rows(name, count))
    first = SearchQA(_config(seed=17))
    second = SearchQA(_config(seed=17))
    monkeypatch.setattr(first, "_load_source_rows", lambda: rows)
    monkeypatch.setattr(second, "_load_source_rows", lambda: reversed(rows))

    splits = first.load()

    assert splits == second.load()
    assert tuple(map(len, splits.values())) == expected_sizes
    all_ids = [task.task_id for tasks in splits.values() for task in tasks]
    assert len(all_ids) == len(set(all_ids)) == len(rows)
    assert set(all_ids) == {row["id"] for _, row in rows}
    for name in ("dev", "test"):
        if name in provided:
            assert _ids(splits[name]) == {
                row["id"] for _, row in _rows(name, provided[name])
            }


@pytest.mark.parametrize(
    ("limit", "expected_sizes"),
    [(3, (1, 1, 1)), (1000, (200, 100, 700)), (3000, (400, 200, 1400))],
)
def test_auto_limit_keeps_all_partitions_and_their_membership(
    monkeypatch, limit, expected_sizes
):
    rows = tuple(
        row
        for name, count in (("train", 400), ("dev", 200), ("test", 1400))
        for row in _rows(name, count)
    )
    full = SearchQA(_config(seed=7))
    limited = SearchQA(_config(seed=7, limit=limit))
    repeated = SearchQA(_config(seed=7, limit=limit))
    monkeypatch.setattr(full, "_load_source_rows", lambda: rows)
    monkeypatch.setattr(limited, "_load_source_rows", lambda: rows)
    monkeypatch.setattr(repeated, "_load_source_rows", lambda: reversed(rows))

    full_splits = full.load()
    limited_splits = limited.load()

    assert limited_splits == repeated.load()
    assert tuple(map(len, limited_splits.values())) == expected_sizes
    for name, tasks in limited_splits.items():
        assert _ids(tasks) <= _ids(full_splits[name])


@pytest.mark.parametrize("limit", [1, 2])
def test_auto_rejects_limit_that_cannot_keep_all_partitions(monkeypatch, limit):
    benchmark = SearchQA(_config(limit=limit))
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: _rows("train", 10))

    with pytest.raises(ValueError, match="limit must be at least 3"):
        benchmark.load()


@pytest.mark.parametrize("count", [1, 2])
def test_auto_rejects_too_few_tasks_instead_of_overlapping_holdouts(monkeypatch, count):
    benchmark = SearchQA(_config())
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: _rows("train", count))

    with pytest.raises(ValueError, match="without overlap"):
        benchmark.load()


@pytest.mark.parametrize("provided", [("test",), ("dev",), ("dev", "test")])
def test_auto_does_not_use_existing_holdouts_for_training(monkeypatch, provided):
    benchmark = SearchQA(_config())
    rows = tuple(row for name in provided for row in _rows(name, 10))
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: rows)
    with pytest.raises(ValueError, match="needs training/unassigned data"):
        benchmark.load()


def test_auto_limit_still_rejects_duplicate_ids_outside_selection(monkeypatch):
    rows = _rows("train", 10)
    first = SearchQA(_config(limit=3))
    monkeypatch.setattr(first, "_load_source_rows", lambda: rows)
    selected = {task.task_id for tasks in first.load().values() for task in tasks}
    excluded = next(row for row in rows if row[1]["id"] not in selected)
    duplicate = SearchQA(_config(limit=3))
    monkeypatch.setattr(duplicate, "_load_source_rows", lambda: (*rows, excluded))

    with pytest.raises(ValueError, match="duplicate task id"):
        duplicate.load()


def test_explicit_ratios_override_source_splits(monkeypatch):
    rows = tuple(row for name in ("train", "dev", "test") for row in _rows(name, 2))
    benchmark = SearchQA(_config(split={"train": 1, "dev": 0, "test": 0}))
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: rows)

    splits = benchmark.load()

    assert tuple(map(len, splits.values())) == (6, 0, 0)
    assert _ids(benchmark.train) == {row["id"] for _, row in rows}
