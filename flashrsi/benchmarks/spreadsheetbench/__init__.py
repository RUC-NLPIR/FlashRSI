"""SpreadsheetBench V1 instructions, with isolated cases and hard restriction."""

import re
from contextlib import ExitStack
from dataclasses import replace
from types import MappingProxyType
from zipfile import ZipFile

from flashrsi.benchmarks._harbor import _task_from_directory
from flashrsi.benchmarks._native import NativeBenchmark
from flashrsi.benchmarks._prepared_fixed import resource
from flashrsi.benchmarks.spreadsheetbench._data import REVISION, materialize


class SpreadsheetBench(NativeBenchmark):
    name = "spreadsheetbench"
    description = "SpreadsheetBench V1 with Full train/dev and Verified test workbooks."
    primary_metric = "reward"
    metadata = MappingProxyType(
        {
            "source": "KAKA22/SpreadsheetBench",
            "revision": "ab0b742b0fc95b946f212d80ac7771b5531272e4",
            "evaluator_revision": REVISION,
            "scoring": "official-hard-restriction-libreoffice",
        }
    )

    def _iter_tasks(self):
        if not self.config.get("_prepared_assets"):
            raise ValueError(
                "SpreadsheetBench requires the spreadsheetbench HF prepared profile"
            )
        for split, row in self._index_rows:
            task_id = row["task_id"]
            if task_id != row["id"] or not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
                raise ValueError("SpreadsheetBench requires a safe upstream task ID")
            for field in ("instruction", "instruction_type", "answer_position"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError("SpreadsheetBench row requires " + field)
            inputs, answers = row["input_files"], row["answer_files"]
            if (
                not isinstance(inputs, list)
                or not isinstance(answers, list)
                or not inputs
                or len(inputs) != len(answers)
                or len(set(inputs)) != len(inputs)
                or len(set(answers)) != len(answers)
            ):
                raise ValueError(
                    "SpreadsheetBench requires paired, unique workbook cases"
                )
            yield self._register(
                row,
                split,
                task_id,
                row["instruction"],
                env="spreadsheetbench",
                case_count=len(inputs),
                instruction_type=row["instruction_type"],
                upstream_exclude=row.get("exclude"),
            )

    def load(self):
        if self._splits is not None and hasattr(self, "_cases"):
            return self._splits
        self._load_index()
        super().load()
        # Preserve the prepared pool and its notes. The published evaluator
        # iterates every record; callers can inspect upstream_exclude metadata.
        cases = {}
        with ExitStack() as stack:
            archives = {}
            for split, tasks in self._splits.items():
                if not tasks:
                    continue
                archives[split] = tuple(
                    stack.enter_context(
                        ZipFile(
                            resource(
                                self.config["_prepared_assets"],
                                f"native/{split}-{kind}.zip",
                            )
                        )
                    )
                    for kind in ("inputs", "answers")
                )
                for task in tasks:
                    row = self._rows_by_id[task.task_id]
                    cases[task.task_id] = tuple(
                        _task_from_directory(
                            materialize(row, i, *archives[split]),
                            self.metadata,
                            "SpreadsheetBench",
                        )
                        for i in range(task.metadata["case_count"])
                    )
        self._cases = cases
        return self._splits

    def _load_index(self):
        if hasattr(self, "_index_rows"):
            return
        if not self.config.get("_prepared_assets") or not self.config.get(
            "_prepared_splits"
        ):
            raise ValueError(
                "SpreadsheetBench requires the spreadsheetbench HF prepared profile"
            )
        rows = list(self._source_rows())
        excluded = {
            row["task_id"]: {"split": split, "reason": "empty instruction"}
            for split, row in rows
            if isinstance(row.get("instruction"), str)
            and not row["instruction"].strip()
        }
        # Filter before limiting, so an empty instruction cannot consume a
        # split's sample budget. Membership and HF provenance stay separate.
        self.config["_prepared_splits"] = {
            role: [task_id for task_id in ids if task_id not in excluded]
            for role, ids in self.config["_prepared_splits"].items()
        }
        self._index_rows = [
            (split, row) for split, row in rows if row["task_id"] not in excluded
        ]
        self.metadata = MappingProxyType(
            {
                **self.metadata,
                "excluded_tasks": excluded,
                "eligible_counts": {
                    role: len(ids)
                    for role, ids in self.config["_prepared_splits"].items()
                },
            }
        )

    def grade(self, trajs):
        graded = []
        for trajectory in trajs:
            self._row_for(trajectory)
            reward = soft = 0.0
            event = trajectory.messages[-1] if trajectory.messages else {}
            if (
                trajectory.status == "finished"
                or event.get("type") == "SpreadsheetBenchVerifier"
            ):
                task = trajectory.task
                values = event.get("case_rewards")
                if (
                    event.get("type") != "SpreadsheetBenchVerifier"
                    or event.get("task_id") != task.task_id
                    or event.get("task_checksum") != task.metadata["task_checksum"]
                    or not isinstance(values, list)
                    or len(values) != task.metadata["case_count"]
                    or any(
                        type(v) not in (float, int) or v not in (0, 1) for v in values
                    )
                ):
                    raise ValueError(
                        "SpreadsheetBench requires matching host case-verifier results"
                    )
                reward = float(all(values)) if trajectory.status == "finished" else 0.0
                soft = sum(values) / len(values)
            graded.append(
                replace(
                    trajectory,
                    metrics={
                        **trajectory.metrics,
                        "reward": reward,
                        "hard_restriction": reward,
                        "soft_restriction": soft,
                    },
                )
            )
        return tuple(graded)


__all__ = ["SpreadsheetBench"]
