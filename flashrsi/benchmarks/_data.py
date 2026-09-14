"""Shared dataset I/O and deterministic task splitting."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from flashrsi.core import Task


def _split_tasks(
    tasks: Iterable[Task], config: Mapping[str, Any]
) -> Mapping[str, tuple[Task, ...]]:
    seed = config.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("benchmark.seed must be an integer")
    limit = config.get("limit")
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
    ):
        raise ValueError("benchmark.limit must be a positive integer")

    def unique_tasks() -> Iterable[Task]:
        seen = set()
        for task in tasks:
            if task.task_id in seen:
                raise ValueError(
                    f"benchmark contains duplicate task id: {task.task_id}"
                )
            seen.add(task.task_id)
            yield task

    def split_key(task: Task) -> tuple[bytes, str]:
        digest = hashlib.sha256(f"{seed}:{task.task_id}".encode()).digest()
        return digest, task.task_id

    selected = unique_tasks()
    if config.get("split", "auto") == "auto":
        return _auto_split(selected, seed=seed, limit=limit)

    ordered = tuple(
        sorted(selected, key=split_key)
        if limit is None
        else heapq.nsmallest(limit, selected, key=split_key)
    )
    if not ordered:
        raise ValueError("benchmark dataset contains no tasks")

    names = ("train", "dev", "test")
    counts = _split_counts(len(ordered), [config["split"][name] for name in names])
    train_end, dev_end = counts[0], counts[0] + counts[1]
    return MappingProxyType(
        {
            "train": ordered[:train_end],
            "dev": ordered[train_end:dev_end],
            "test": ordered[dev_end:],
        }
    )


def _split_counts(total: int, weights: list[float], *, minimum: int = 0) -> list[int]:
    if total < minimum * len(weights):
        raise ValueError(
            "benchmark.split=auto needs enough training/unassigned tasks to fill "
            "train, dev and test without overlap; add data or set explicit split ratios"
        )
    exact = [total * weight / sum(weights) for weight in weights]
    counts = [math.floor(value) for value in exact]
    order = sorted(
        range(len(weights)), key=lambda index: (-(exact[index] - counts[index]), index)
    )
    for index in order[: total - sum(counts)]:
        counts[index] += 1
    for index in range(len(counts)):
        while counts[index] < minimum:
            donor = max(
                (i for i, count in enumerate(counts) if count > minimum),
                key=lambda i: (counts[i] - exact[i], -i),
            )
            counts[donor] -= 1
            counts[index] += 1
    return counts


def _auto_split(
    tasks: Iterable[Task], *, seed: int, limit: int | None
) -> Mapping[str, tuple[Task, ...]]:
    """Preserve provided holdouts; fill missing ones only from training data."""
    names = ("train", "dev", "test")
    if limit is not None and limit < len(names):
        raise ValueError("benchmark.limit must be at least 3 when benchmark.split=auto")
    groups: dict[str, list[Task]] = {name: [] for name in names}
    for task in tasks:
        source = task.metadata.get("source_split", "train")
        if source == "validation":
            source = "dev"
        groups[source if source in groups else "train"].append(task)
    if not any(groups.values()):
        raise ValueError("benchmark dataset contains no tasks")
    if not groups["train"]:
        raise ValueError(
            "benchmark.split=auto needs training/unassigned data; existing dev/test "
            "tasks are held out. Provide train data or set explicit split ratios"
        )

    def split_key(task: Task) -> tuple[bytes, str]:
        return hashlib.sha256(f"{seed}:{task.task_id}".encode()).digest(), task.task_id

    for group in groups.values():
        group.sort(key=split_key)
    missing = [name for name in ("dev", "test") if not groups[name]]
    if missing:
        pool = groups["train"]
        weights = [1 - 0.2 * len(missing), *[0.2 for _ in missing]]
        counts = _split_counts(len(pool), weights, minimum=1)
        start = 0
        for name, count in zip(("train", *missing), counts, strict=True):
            groups[name] = pool[start : start + count]
            start += count

    sizes = [len(groups[name]) for name in names]
    counts = (
        sizes
        if limit is None
        else _split_counts(min(limit, sum(sizes)), sizes, minimum=1)
    )
    return MappingProxyType(
        {
            name: tuple(groups[name][:count])
            for name, count in zip(names, counts, strict=True)
        }
    )


def _load_rows(
    data_path: str | Path | None, source: Mapping[str, Any]
) -> tuple[Iterable[tuple[str, Mapping[str, Any]]], Mapping[str, Any]]:
    if data_path is not None:
        if not isinstance(data_path, (str, Path)) or not str(data_path).strip():
            raise ValueError("benchmark.data_path must be a path")
        path = Path(data_path).expanduser().resolve()
        return _load_local_rows(path), MappingProxyType(
            {"source": "local", "data_path": str(path)}
        )

    from datasets import load_dataset

    dataset = load_dataset(
        source["source"], name=source["config"], revision=source["revision"]
    )
    return (
        (str(split), row) for split, records in dataset.items() for row in records
    ), source


def _load_local_rows(path: Path) -> Iterable[tuple[str, Mapping[str, Any]]]:
    if path.is_file():
        return (("local", row) for row in _read_records(path))
    if not path.is_dir():
        raise ValueError(f"benchmark.data_path does not exist: {path}")

    sources = []
    for split in ("train", "dev", "validation", "test"):
        for suffix in (".parquet", ".jsonl", ".json"):
            candidate = path / f"{split}{suffix}"
            if candidate.is_file():
                sources.append((split, candidate))
                break
    if not sources:
        raise ValueError(
            f"benchmark.data_path has no train/dev/validation/test data files: {path}"
        )
    return ((split, row) for split, source in sources for row in _read_records(source))


def _read_records(path: Path) -> Iterable[Mapping[str, Any]]:
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq

        for batch in pq.ParquetFile(path).iter_batches():
            yield from batch.to_pylist()
        return
    try:
        if path.suffix.lower() == ".jsonl":
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        row = json.loads(line)
                        if not isinstance(row, Mapping):
                            raise ValueError(f"dataset rows must be objects: {path}")
                        yield row
        else:
            values = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(values, list) or not all(
                isinstance(row, Mapping) for row in values
            ):
                raise ValueError(f"dataset must be a list of objects: {path}")
            yield from values
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read dataset {path}: {error}") from error
