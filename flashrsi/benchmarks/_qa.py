"""Shared scaffolding for question-answering benchmarks.

SearchQA and HotpotQA differ only in how a source row becomes a Task: both
load rows through the same dataset plumbing, apply the same configured splits,
and score answers with the same normalized EM/F1 metrics. This base owns that
common half so each benchmark file is just its own data contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from flashrsi.benchmarks._data import _load_rows, _split_tasks
from flashrsi.benchmarks.metrics import qa_metrics
from flashrsi.core.benchmark import Benchmark, Task
from flashrsi.core.trajectory import Trajectory


class QABenchmark(Benchmark):
    """A benchmark whose Tasks are graded by comparing text to references.

    Subclasses set the usual class attributes and implement ``_task_from_row``,
    which must put every acceptable answer in ``metadata["answers"]``.
    """

    primary_metric = "exact_match"

    def __init__(self, config: Mapping[str, Any]) -> None:
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError(
                f"{type(self).__name__} requires benchmark.name: {self.name}"
            )
        self._tasks_by_id: dict[str, Task] = {}

    def load(self) -> Mapping[str, tuple[Task, ...]]:
        """Load the pinned dataset (or local data), then apply configured splits."""
        if self._splits is None:
            self._splits = _split_tasks(self._iter_tasks(), self.config)
            self._tasks_by_id = {
                task.task_id: task for split in self._splits.values() for task in split
            }
        return self._splits

    def grade(self, trajs: tuple[Trajectory, ...]) -> tuple[Trajectory, ...]:
        """Score the best EM/F1 over references; failed runs score zero."""
        if self._splits is None:
            raise RuntimeError(f"{self.name} has not been loaded; call load() first")
        graded = []
        for trajectory in trajs:
            if trajectory.task is None:
                raise ValueError(
                    f"{type(self).__name__} grading requires a Task; use Agent.rollout"
                )
            try:
                task = self._tasks_by_id[trajectory.task.task_id]
            except KeyError as error:
                raise ValueError(
                    f"trajectory has unknown {type(self).__name__} task: "
                    f"{trajectory.task.task_id}"
                ) from error
            scores = (
                qa_metrics(trajectory.output, task.metadata["answers"])
                if trajectory.status == "finished"
                else {"exact_match": 0.0, "f1": 0.0}
            )
            graded.append(replace(trajectory, metrics={**trajectory.metrics, **scores}))
        return tuple(graded)

    def _iter_tasks(self) -> Iterable[Task]:
        for source, row in self._load_source_rows():
            if not isinstance(row, Mapping):
                raise ValueError(f"{type(self).__name__} rows must be mappings")
            yield self._task_from_row(row, source)

    def _load_source_rows(self) -> Iterable[tuple[str, Mapping[str, Any]]]:
        rows, self.metadata = _load_rows(
            self.config.get("data_path"), type(self).metadata
        )
        return rows

    @staticmethod
    def _task_from_row(row: Mapping[str, Any], source_split: str) -> Task:
        """Build one Task, recording its references in metadata["answers"]."""
        raise NotImplementedError
