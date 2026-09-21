"""SearchQA dataset loading and local grading."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._qa import QABenchmark
from flashrsi.core.benchmark import Task


class SearchQA(QABenchmark):
    """SearchQA with deterministic configured splits and local EM/F1 grading."""

    name = "searchqa"
    description = "Open-domain question answering over retrieved search snippets."
    metadata = MappingProxyType(
        {
            "source": "jinjiajie/flashrsi",
            "config": "searchqa",
            "revision": "97f222eda79b77ac217848a18ed3b415b60d8e89",
        }
    )

    @staticmethod
    def _task_from_row(row: Mapping[str, Any], source_split: str) -> Task:
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
