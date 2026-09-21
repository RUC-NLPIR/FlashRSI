"""HotpotQA dataset loading and local answer grading."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._data import _load_rows, _split_tasks
from flashrsi.benchmarks.metrics import qa_metrics
from flashrsi.core.benchmark import Benchmark, Task
from flashrsi.core.trajectory import Trajectory

_PROMPT = (
    "Answer the multi-hop question using the supplied Wikipedia context. "
    "Return only the short answer.\n\nContext:\n{context}\n\nQuestion:\n{question}"
)


class HotpotQA(Benchmark):
    """HotpotQA fullwiki with the published held-out splits and EM/F1 grading.

    The published splits already implement ``flashrsi-hotpotqa-heldout-v1``: the
    labeled official validation split is ``test`` and ``dev`` is a seeded holdout
    of official train. ``split=auto`` preserves that partition; explicit ratios
    merge and repartition it, which discards the held-out guarantee.
    """

    name = "hotpotqa"
    description = "Multi-hop question answering over retrieved Wikipedia paragraphs."
    primary_metric = "exact_match"
    metadata = MappingProxyType(
        {
            "source": "jinjiajie/flashrsi",
            "config": "hotpotqa",
            "revision": "40aa3932298226b2b5063351519291c989b85087",
        }
    )

    def __init__(self, config: Mapping[str, Any]) -> None:
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("HotpotQA requires benchmark.name: hotpotqa")
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
        """Score the short answer only; supporting-fact metrics need more output."""
        if self._splits is None:
            raise RuntimeError("hotpotqa has not been loaded; call load() first")
        graded = []
        for trajectory in trajs:
            if trajectory.task is None:
                raise ValueError("HotpotQA grading requires a Task; use Agent.rollout")
            try:
                task = self._tasks_by_id[trajectory.task.task_id]
            except KeyError as error:
                raise ValueError(
                    f"trajectory has unknown HotpotQA task: {trajectory.task.task_id}"
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
            raise ValueError("HotpotQA rows must be mappings")
        task_id = row.get("id")
        question = row.get("question")
        answer = row.get("answer")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("HotpotQA row has no non-empty id")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"HotpotQA row {task_id} has no question")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"HotpotQA row {task_id} has no answer")
        return Task(
            task_id=task_id,
            question=_PROMPT.format(
                context=_context(row.get("context"), task_id), question=question
            ),
            ground_truth=answer,
            metadata={
                "answers": (answer,),
                "source_split": source_split,
                # Kept for reporting and analysis; not used by the grader.
                **{
                    key: row[key]
                    for key in ("type", "level")
                    if isinstance(row.get(key), str)
                },
            },
        )


def _context(value: Any, task_id: str) -> str:
    """Render the retrieved paragraphs as ``title: sentences`` lines.

    fullwiki is a retrieval setting, so a row may legitimately carry no
    paragraphs at all; 10 of the published test rows do. Those stay in the
    benchmark and are simply unanswerable from context.
    """
    malformed = ValueError(f"HotpotQA row {task_id} has a malformed context")
    if not isinstance(value, Mapping):
        raise malformed
    titles, paragraphs = value.get("title"), value.get("sentences")
    if not _is_list(titles) or not _is_list(paragraphs):
        raise malformed
    if len(titles) != len(paragraphs):
        raise malformed
    lines = []
    for title, sentences in zip(titles, paragraphs, strict=True):
        if not isinstance(title, str) or not _is_list(sentences):
            raise malformed
        if any(not isinstance(sentence, str) for sentence in sentences):
            raise malformed
        lines.append(f"{title}: {''.join(sentences)}")
    return "\n".join(lines) if lines else "(no paragraphs were retrieved)"


def _is_list(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


__all__ = ["HotpotQA"]
