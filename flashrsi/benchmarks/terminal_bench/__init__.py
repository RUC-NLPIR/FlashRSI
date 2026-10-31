"""Pinned Terminal-Bench 2.0/2.1 tasks and Harbor's native verifier."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks._harbor import _grade, _task_from_directory
from flashrsi.benchmarks.terminal_bench._data import _download_tasks
from flashrsi.core.benchmark import Benchmark, Task
from flashrsi.core.trajectory import Trajectory

_DATASET = "terminal-bench@2.0"
_GIT_URL = "https://github.com/laude-institute/terminal-bench-2.git"
_UPSTREAM_REVISION = "69671fbaac6d67a7ef0dfec016cc38a64ef7a77c"
_REVISION = "d96c128fbc4f7eea52d355f07de3ea3a6e36627c"
_VERSIONS = {
    "2.0": {
        "dataset": _DATASET,
        "git_url": _GIT_URL,
        "revision": _UPSTREAM_REVISION,
        "path": ".",
    },
    "2.1": {
        "dataset": "terminal-bench/terminal-bench-2-1",
        "git_url": "https://github.com/harbor-framework/terminal-bench-2-1.git",
        "revision": "7131e4375048a0e408a8fb404b5f499d726b695b",
        "path": "tasks",
    },
}


class TerminalBench(Benchmark):
    """Native Linux tasks with reproducible local train/dev/test partitions.

    Terminal-Bench publishes one task collection, without training splits.
    Users explicitly configure experiment partitions with ratios or counts. A local
    ``data_path`` may name a single task or a directory containing task folders.
    """

    name = "terminal_bench"
    description = "Terminal-Bench 2.0/2.1 tasks graded by their native Harbor verifier."
    primary_metric = "reward"
    metadata = MappingProxyType(
        {
            "source": _GIT_URL,
            "config": "terminal_bench",
            "revision": _UPSTREAM_REVISION,
            "upstream": {
                "dataset": _DATASET,
                "git_url": _GIT_URL,
                "revision": _UPSTREAM_REVISION,
            },
        }
    )

    def __init__(self, config: Mapping[str, Any]) -> None:
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        self.version = self.config.get("version", "2.0")
        if not isinstance(self.version, str) or self.version not in _VERSIONS:
            raise ValueError('TerminalBench version must be "2.0" or "2.1"')
        upstream = _VERSIONS[self.version]
        self.metadata = MappingProxyType(
            {
                **type(self).metadata,
                "source": upstream["git_url"],
                "revision": upstream["revision"],
                "version": self.version,
                "upstream": dict(upstream),
                **self.config.get("dataset", {}),
            }
        )
        if self.config.get("name", self.name) != self.name:
            raise ValueError("TerminalBench requires benchmark.name: terminal_bench")
        self._tasks_by_id: dict[str, Task] = {}

    def load(self) -> Mapping[str, tuple[Task, ...]]:
        """Load local native tasks or the pinned Hugging Face task archive."""
        if self._splits is None:
            splits = _split_tasks(self._iter_tasks(), self.config)
            evolution_path = self.config.get("evolution_data_path")
            if evolution_path is not None:
                # The independent collection uses the same Harbor grading
                # contract. Reuse this loader; never repartition downstream
                # benchmark instances into an alleged external evolution set.
                external = TerminalBench(
                    {
                        "data_path": evolution_path,
                        "version": self.version,
                        "split": {"train": 1, "dev": 0, "test": 0},
                        "seed": self.config.get("seed", 0),
                        "limit": self.config.get("evolution_limit"),
                    }
                )
                evolution = external.load()["train"]
                downstream = [task for tasks in splits.values() for task in tasks]
                if any(
                    a.task_id == b.task_id
                    or a.question.strip() == b.question.strip()
                    or a.metadata["task_checksum"] == b.metadata["task_checksum"]
                    for a in evolution
                    for b in downstream
                ):
                    raise ValueError(
                        "external evolution tasks overlap downstream benchmark tasks"
                    )
                splits = MappingProxyType({**splits, "train": evolution})
                self.metadata = MappingProxyType(
                    {**self.metadata, "evolution_source": dict(external.metadata)}
                )
            self._splits = splits
            self._tasks_by_id = {
                task.task_id: task for split in self._splits.values() for task in split
            }
        return self._splits

    def grade(self, trajs: tuple[Trajectory, ...]) -> tuple[Trajectory, ...]:
        """Read the host-added final verifier event, never an Agent's self-score."""
        if self._splits is None:
            raise RuntimeError("terminal_bench has not been loaded; call load() first")
        return _grade(trajs, self._tasks_by_id, "TerminalBench")

    def _iter_tasks(self) -> Iterable[Task]:
        data_path = self.config.get("data_path")
        if data_path is None:
            for directory, checksum in _download_tasks(self.metadata):
                task = _task_from_directory(
                    directory, {**self.metadata, "path": directory.name}
                )
                if (
                    task.task_id != directory.name
                    or task.metadata["task_checksum"] != checksum
                ):
                    raise ValueError(
                        "Terminal-Bench cached task does not match its manifest: "
                        f"{directory}"
                    )
                yield task
            return

        if not isinstance(data_path, (str, Path)) or not str(data_path).strip():
            raise ValueError("benchmark.data_path must be a path")
        path = Path(data_path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(
                f"TerminalBench data_path must be a task directory: {path}"
            )
        self.metadata = MappingProxyType(
            {**self.metadata, "source": "local", "data_path": str(path)}
        )
        directories = (
            [path]
            if (path / "task.toml").is_file()
            else sorted(
                child
                for child in path.iterdir()
                if child.is_dir() and (child / "task.toml").is_file()
            )
        )
        if not directories:
            raise ValueError(
                f"TerminalBench data_path contains no native tasks: {path}"
            )
        for directory in directories:
            yield _task_from_directory(directory, dict(self.metadata))


__all__ = ["TerminalBench"]
