"""Terminal-Bench 2.0 tasks and grading from Harbor's native verifier."""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks.terminal_bench._data import _download_tasks
from flashrsi.core.benchmark import Benchmark, Task
from flashrsi.core.trajectory import Trajectory

_DATASET = "terminal-bench@2.0"
_GIT_URL = "https://github.com/laude-institute/terminal-bench-2.git"
_UPSTREAM_REVISION = "69671fbaac6d67a7ef0dfec016cc38a64ef7a77c"
_REVISION = "d96c128fbc4f7eea52d355f07de3ea3a6e36627c"


class TerminalBench(Benchmark):
    """Native Linux tasks with reproducible local train/dev/test partitions.

    Terminal-Bench publishes one task collection, without training splits.
    ``split=auto`` partitions it by the shared seeded splitting rule. A local
    ``data_path`` may name a single task or a directory containing task folders.
    """

    name = "terminal_bench"
    description = "Terminal-Bench 2.0 tasks graded by their native Harbor verifier."
    primary_metric = "reward"
    metadata = MappingProxyType(
        {
            "source": "jinjiajie/flashrsi",
            "config": "terminal_bench",
            "revision": _REVISION,
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
        graded = []
        for trajectory in trajs:
            task = trajectory.task
            if task is None or self._tasks_by_id.get(task.task_id) != task:
                raise ValueError(
                    "TerminalBench grading requires a loaded benchmark Task"
                )
            reward = 0.0
            if trajectory.status == "finished":
                event = trajectory.messages[-1] if trajectory.messages else {}
                if (
                    event.get("type") != "HarborVerifier"
                    or event.get("task_id") != task.task_id
                    or event.get("task_checksum") != task.metadata["task_checksum"]
                ):
                    raise ValueError(
                        "TerminalBench requires a final HarborVerifier event "
                        f"for task {task.task_id}"
                    )
                rewards = event.get("rewards")
                value = rewards.get("reward") if isinstance(rewards, Mapping) else None
                if type(value) not in (int, float) or not 0 <= value <= 1:
                    raise ValueError(
                        "TerminalBench verifier reward must be a finite number "
                        f"between 0 and 1 for task {task.task_id}"
                    )
                reward = float(value)
            graded.append(
                replace(trajectory, metrics={**trajectory.metrics, "reward": reward})
            )
        return tuple(graded)

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
        self.metadata = MappingProxyType({"source": "local", "data_path": str(path)})
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


def _task_from_directory(directory: Path, source: Mapping[str, Any]) -> Task:
    try:
        from harbor.models.task.task import Task as HarborTask
    except ImportError:
        raise ValueError("TerminalBench requires flashrsi-lite[harbor]") from None

    native = HarborTask(task_dir=directory)
    if native.has_steps or native.config.environment.os != "linux":
        raise ValueError(
            "TerminalBench currently supports single-step Linux tasks only"
        )
    # Use Harbor's checksum so rollout can detect changes to local task resources.
    with warnings.catch_warnings(action="ignore", category=DeprecationWarning):
        checksum = native.checksum
    return Task(
        task_id=native.name,
        question=native.instruction,
        env=str(native.task_dir),
        metadata={
            "source_split": "unassigned",
            "source": dict(source),
            "task_checksum": checksum,
            **{
                key: native.config.metadata[key]
                for key in ("category", "difficulty")
                if key in native.config.metadata
            },
        },
    )


__all__ = ["TerminalBench"]
