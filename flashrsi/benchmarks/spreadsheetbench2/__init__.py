"""SpreadsheetBench 2's three workbook categories with its pinned native grader."""

from collections.abc import Mapping
from types import MappingProxyType

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks._harbor import _grade, _task_from_directory
from flashrsi.benchmarks.spreadsheetbench2._data import (
    _CATEGORIES,
    _REVISION,
    _SOURCE,
    _UPSTREAM,
    _UPSTREAM_REVISION,
    _prepare_tasks,
)
from flashrsi.core import Benchmark


class SpreadsheetBench2(Benchmark):
    """Edit workbooks; score recalculated deliverables in a fresh Harbor container.

    The public collection has no evolution split. Train/dev/test are explicit
    experiment partitions; Visualization needs a different runtime and judge.
    """

    name = "spreadsheetbench2"
    description = "SpreadsheetBench 2 Debugging, Financial_Model and Template tasks."
    primary_metric = "reward"

    def __init__(self, config: Mapping):
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError(
                "SpreadsheetBench2 requires benchmark.name: spreadsheetbench2"
            )
        self.category = self.config.get("category", "all")
        if self.category not in (*_CATEGORIES, "all"):
            raise ValueError(
                "SpreadsheetBench2 category must be Debugging, Financial_Model, "
                "Template or all; Visualization is not supported"
            )
        self.metadata = MappingProxyType(
            {
                "source": _SOURCE,
                "revision": _REVISION,
                "evaluator_source": _UPSTREAM,
                "evaluator_revision": _UPSTREAM_REVISION,
                "category": self.category,
                "scoring": "official-accuracy-libreoffice",
            }
        )
        self._tasks_by_id = {}

    def load(self):
        if self._splits is None:
            try:
                import harbor  # noqa: F401
            except ImportError:
                raise ValueError(
                    "SpreadsheetBench2 requires flashrsi-lite[harbor] and Python >=3.12"
                ) from None
            directories, provenance = _prepare_tasks(
                self.category, self.config.get("data_path")
            )
            self.metadata = MappingProxyType({**self.metadata, **provenance})
            self._splits = _split_tasks(
                (
                    _task_from_directory(p, self.metadata, "SpreadsheetBench2")
                    for p in directories
                ),
                self.config,
            )
            self._tasks_by_id = {
                t.task_id: t for group in self._splits.values() for t in group
            }
        return self._splits

    def grade(self, trajs):
        if self._splits is None:
            raise RuntimeError(
                "spreadsheetbench2 has not been loaded; call load() first"
            )
        return _grade(trajs, self._tasks_by_id, "SpreadsheetBench2")


__all__ = ["SpreadsheetBench2"]
