"""GISA encrypted questions, fixed experiment splits and official TSV scoring."""

import base64
import hashlib
import re
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from zipfile import ZipFile

from flashrsi.benchmarks._native import NativeBenchmark
from flashrsi.benchmarks._prepared_fixed import resource
from flashrsi.benchmarks.gisa._scoring import REVISION, evaluator, score


class GISA(NativeBenchmark):
    name = "gisa"
    description = "General information seeking with item, set, list and table answers."
    primary_metric = "global_em"
    metadata = MappingProxyType(
        {
            "source": "RUC-NLPIR/GISA",
            "revision": "417bdcd235bddfd4722a39cc0ae58b41307e5edd",
            "scorer_revision": REVISION,
        }
    )

    def _iter_tasks(self):
        if not self.config.get("data_path") or not self.config.get("_prepared_assets"):
            raise ValueError("GISA requires the gisa HF prepared profile")
        for split, row in self._source_rows():
            task_id = str(row["id"])
            if not re.fullmatch(r"[0-9]+", task_id) or row["task_id"] != task_id:
                raise ValueError("GISA task_id must equal its numeric upstream id")
            if row["answer_type"] not in {"item", "set", "list", "table"} or row[
                "question_type"
            ] not in {"stable", "live"}:
                raise ValueError("Unknown GISA answer_type or question_type")
            key = hashlib.sha256(row["canary"].encode()).digest()
            encrypted = base64.b64decode(row["question"], validate=True)
            question = bytes(
                value ^ key[i % len(key)] for i, value in enumerate(encrypted)
            ).decode("utf-8")
            if not question.strip():
                raise ValueError("GISA decrypted question is empty")
            yield self._register(
                row,
                split,
                task_id,
                question
                + "\n\nReturn your final answer in a fenced tsv block with a header row. "
                "Use tab-separated columns and one data row per item. For item/set/list answers, "
                "use one column named answer; preserve the requested order for lists. "
                "For tables, use the column names requested in the question.",
                env="gisa",
                answer_type=row["answer_type"],
                question_type=row["question_type"],
            )

    def load(self):
        splits = super().load()
        self._answers = resource(self.config["_prepared_assets"], "native/answer.zip")
        with ZipFile(self._answers) as archive:
            if any(
                f"answer/{task_id}.csv" not in archive.namelist()
                for task_id in self._tasks_by_id
            ):
                raise ValueError("GISA reference archive is missing task answers")
        evaluator()
        return splits

    def grade(self, trajs):
        if not hasattr(self, "_answers"):
            raise RuntimeError("gisa has not been loaded; call load() first")
        graded = []
        # References never enter the solving container or the evolvable Snapshot.
        with (
            ZipFile(self._answers) as archive,
            TemporaryDirectory(prefix="flashrsi-gisa-grade-") as temporary,
        ):
            for trajectory in trajs:
                row = self._row_for(trajectory)
                reference = Path(temporary) / "answer.csv"
                reference.write_bytes(archive.read(f"answer/{row['id']}.csv"))
                metrics = score(
                    trajectory.output if trajectory.status == "finished" else "",
                    reference,
                    row["answer_type"],
                )
                graded.append(
                    replace(
                        trajectory,
                        metrics={
                            **trajectory.metrics,
                            **{
                                key: float(value)
                                for key, value in metrics.items()
                                if key != "question_type"
                            },
                        },
                    )
                )
        return tuple(graded)


__all__ = ["GISA"]
