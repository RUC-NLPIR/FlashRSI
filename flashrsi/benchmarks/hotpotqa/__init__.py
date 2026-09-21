"""HotpotQA dataset loading and local answer grading."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._qa import QABenchmark
from flashrsi.core.benchmark import Task

_PROMPT = (
    "Answer the multi-hop question using the supplied Wikipedia context. "
    "Return only the short answer.\n\nContext:\n{context}\n\nQuestion:\n{question}"
)


class HotpotQA(QABenchmark):
    """HotpotQA fullwiki with the published held-out splits and EM/F1 grading.

    The published splits already implement ``flashrsi-hotpotqa-heldout-v1``: the
    labeled official validation split is ``test`` and ``dev`` is a seeded holdout
    of official train. ``split=auto`` preserves that partition; explicit ratios
    merge and repartition it, which discards the held-out guarantee.

    Those splits are not drawn from one pool. Official train always contains the
    gold paragraphs, while the official validation split used as ``test`` is
    entirely ``hard`` and contains them for only 28% of its rows, so train and
    dev scores do not predict test scores.

    Only the short answer is scored. Supporting-fact and joint metrics need the
    agent to report its evidence, which this prompt does not ask for.
    """

    name = "hotpotqa"
    description = "Multi-hop question answering over retrieved Wikipedia paragraphs."
    metadata = MappingProxyType(
        {
            "source": "jinjiajie/flashrsi",
            "config": "hotpotqa",
            "revision": "40aa3932298226b2b5063351519291c989b85087",
        }
    )

    @staticmethod
    def _task_from_row(row: Mapping[str, Any], source_split: str) -> Task:
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
    if (
        not _is_list(titles)
        or not _is_list(paragraphs)
        or len(titles) != len(paragraphs)
    ):
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
