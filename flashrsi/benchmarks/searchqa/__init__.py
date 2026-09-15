"""SearchQA dataset loading and local grading."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._data import _load_rows, _split_tasks
from flashrsi.benchmarks.metrics import qa_metrics
from flashrsi.core.benchmark import Benchmark, Task
from flashrsi.core.trajectory import Trajectory


class SearchQA(Benchmark):
    """SearchQA with deterministic configured splits and local EM/F1 grading."""

    name = "searchqa"
    description = "Open-domain question answering over retrieved search snippets."
    primary_metric = "exact_match"
    metadata = MappingProxyType(
        {
            "source": "jinjiajie/flashrsi",
            "config": "searchqa",
            "revision": "97f222eda79b77ac217848a18ed3b415b60d8e89",
        }
    )

    def __init__(self, config: Mapping[str, Any]) -> None:
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("SearchQA requires benchmark.name: searchqa")
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
        if self._splits is None:
            raise RuntimeError("searchqa has not been loaded; call load() first")
        graded = []
        for trajectory in trajs:
            if trajectory.task is None:
                raise ValueError("SearchQA grading requires a Task; use Agent.rollout")
            try:
                task = self._tasks_by_id[trajectory.task.task_id]
            except KeyError as error:
                raise ValueError(
                    f"trajectory has unknown SearchQA task: {trajectory.task.task_id}"
                ) from error

            scores = (
                qa_metrics(trajectory.output, task.metadata["answers"])
                if trajectory.status == "finished"
                else {"exact_match": 0.0, "f1": 0.0}
            )
            metrics = {**trajectory.metrics, **scores}
            graded.append(replace(trajectory, metrics=metrics))
        return tuple(graded)

    def _iter_tasks(self) -> Iterable[Task]:
        for source, row in self._load_source_rows():
            yield self._task_from_row(row, source)

    def _load_source_rows(self) -> Iterable[tuple[str, Mapping[str, Any]]]:
        rows, self.metadata = _load_rows(
            self.config.get("data_path"), type(self).metadata
        )
        return rows

    @staticmethod
    def _task_from_row(row: Mapping[str, Any], source_split: str) -> Task:
        if not isinstance(row, Mapping):
            raise ValueError("SearchQA rows must be mappings")
        task_id = row.get("id", row.get("key"))
        question = row.get("question")
        context = row.get("context")
        answers = row.get("answers", row.get("answer"))
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("SearchQA row has no non-empty key/id")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"SearchQA row {task_id} has no question")
        if not isinstance(context, str):
            raise ValueError(f"SearchQA row {task_id} context must be a string")
        if isinstance(answers, str):
            answers = (answers,)
        elif isinstance(answers, Sequence) and not isinstance(
            answers, (bytes, bytearray)
        ):
            answers = tuple(answers)
        else:
            answers = ()
        if not answers or any(
            not isinstance(answer, str) or not answer.strip() for answer in answers
        ):
            raise ValueError(
                f"SearchQA row {task_id} answers must be non-empty strings"
            )
        prompt = (
            "Answer the question using the supplied context. Return only the short "
            f"answer.\n\nContext:\n{context}\n\nQuestion:\n{question}"
        )
        return Task(
            task_id=task_id,
            question=prompt,
            ground_truth=answers[0],
            metadata={"answers": answers, "source_split": source_split},
        )


__all__ = ["SearchQA"]
