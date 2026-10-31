"""Native OfficeQA-Pro CSV and unmodified, pinned Databricks reward scoring."""

import math
from dataclasses import replace
from types import MappingProxyType

from flashrsi.benchmarks._native import NativeBenchmark
from flashrsi.benchmarks.officeqa_pro._reward import score_answer


class OfficeQAPro(NativeBenchmark):
    name = "officeqa_pro"
    description = (
        "OfficeQA-Pro document research with the official numeric/text reward."
    )
    primary_metric = "accuracy"
    metadata = MappingProxyType(
        {
            "source": "databricks/officeqa",
            "revision": "763a8366abf2a3605c381d53586d844dc60fa756",
            "data_files": "officeqa_pro.csv",
            "scorer_revision": "7b9a3c154ef9fb40215bb67934afc43e6799de16",
        }
    )

    def __init__(self, config):
        super().__init__(config)
        self._tolerance = self.config.get("tolerance", 0.0)
        if (
            type(self._tolerance) not in (int, float)
            or not math.isfinite(self._tolerance)
            or not 0 <= self._tolerance <= 1
        ):
            raise ValueError(
                "benchmark.tolerance must be a finite number between 0 and 1"
            )

    def _iter_tasks(self):
        for split, row in self._source_rows():
            # HF labels a lone CSV as train; OfficeQA-Pro declares no such role.
            if self.config.get("data_path") is None:
                split = "unassigned"
            answer, question = row.get("answer"), row.get("question")
            if (
                not isinstance(answer, str)
                or not answer.strip()
                or not isinstance(question, str)
                or not question.strip()
            ):
                raise ValueError(
                    "OfficeQA-Pro requires native question and answer fields"
                )
            # source_docs/source_files identify oracle evidence; they stay private.
            yield self._register(
                row,
                split,
                row.get("uid"),
                question
                + "\n\nSearch the supplied corpus directory. Return your final answer inside <FINAL_ANSWER>...</FINAL_ANSWER>.",
                env="officeqa_pro",
                difficulty=row.get("difficulty"),
            )

    def grade(self, trajs):
        graded = []
        for trajectory in trajs:
            row = self._row_for(trajectory)
            score = (
                score_answer(row["answer"], trajectory.output, self._tolerance)
                if trajectory.status == "finished"
                else 0.0
            )
            graded.append(
                replace(trajectory, metrics={**trajectory.metrics, "accuracy": score})
            )
        return tuple(graded)


__all__ = ["OfficeQAPro"]
