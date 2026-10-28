"""JobBench native data and official Harbor renderer at 660b33a86ed032559df0b2fdc1ad38cf7ceb83f3."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks._harbor import _grade, _task_from_directory
from flashrsi.benchmarks.jobbench._data import _prepare_tasks
from flashrsi.core import Benchmark, Trajectory

_SOURCE = "JobBench/job-bench"
_REVISION = "d43a66575635da0d3f6cb9a20976dc1a60f3ffc9"


class JobBench(Benchmark):
    """Score native file deliverables with JobBench's separate rubric judge.

    Main and easy select native task collections; experiment roles are explicit
    user partitions. The official renderer keeps rubrics outside the agent image.
    """

    name = "jobbench"
    description = (
        "JobBench professional file tasks with official weighted rubric reward."
    )
    primary_metric = "reward"

    def __init__(self, config: Mapping) -> None:
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("JobBench requires benchmark.name: jobbench")
        self.collection = self.config.get("collection", "main")
        if self.collection not in ("main", "easy", "all"):
            raise ValueError("JobBench collection must be main, easy or all")
        self.metadata = MappingProxyType(
            {
                "source": _SOURCE,
                "revision": _REVISION,
                **self.config.get("dataset", {}),
                "collection": self.collection,
                "scoring": "official-weighted-rubric",
            }
        )
        self._tasks_by_id = {}

    def load(self):
        if self._splits is None:
            self._splits = _split_tasks(self._iter_tasks(), self.config)
            self._tasks_by_id = {
                task.task_id: task for group in self._splits.values() for task in group
            }
        return self._splits

    def grade(self, trajs: tuple[Trajectory, ...]) -> tuple[Trajectory, ...]:
        if self._splits is None:
            raise RuntimeError("jobbench has not been loaded; call load() first")
        return _grade(trajs, self._tasks_by_id, "JobBench")

    def _iter_tasks(self):
        try:
            from harbor.models.task.task import Task as HarborTask
        except ImportError:
            raise ValueError(
                "JobBench requires flashrsi-lite[harbor] and Python >=3.12"
            ) from None

        judge_info = self.metadata.get("judge")
        data = self.config.get("data_path")
        if data is not None:
            if not isinstance(data, (str, Path)) or not str(data).strip():
                raise ValueError("JobBench data_path must be a native directory")
            data = Path(data).expanduser().resolve()
            if not data.is_dir():
                raise ValueError(f"JobBench data_path is not a directory: {data}")
        raw = data is not None and any(
            (data / name).is_dir() for name in ("dataset", "dataset_easy")
        )
        if data is None or raw:
            root, provenance = _prepare_tasks(self.metadata, data)
            self.metadata = MappingProxyType({**self.metadata, **provenance})
        else:
            root = data / "tasks" if (data / "tasks").is_dir() else data
            self.metadata = MappingProxyType(
                {
                    "source": "local",
                    "data_path": str(data),
                    "collection": self.collection,
                    "scoring": "native-verifier",
                }
            )
        if judge_info is not None:
            self.metadata = MappingProxyType({**self.metadata, "judge": judge_info})
        directories = (
            [root]
            if (root / "task.toml").is_file()
            else sorted(
                child for child in root.iterdir() if (child / "task.toml").is_file()
            )
        )
        for directory in directories:
            native = HarborTask(directory)
            split = native.config.metadata.get("split")
            if split not in ("main", "easy"):
                raise ValueError(
                    f"JobBench task has no native main/easy split: {directory}"
                )
            if self.collection != "all" and split != self.collection:
                continue
            if native.config.verifier.environment_mode != "separate":
                raise ValueError(f"JobBench requires a separate verifier: {directory}")
            task = _task_from_directory(
                directory, dict(self.metadata), "JobBench", native=native
            )
            yield replace(
                task,
                metadata={
                    **task.metadata,
                    "native_split": split,
                    **{
                        key: native.config.metadata[key]
                        for key in ("occupation", "task_number", "repo_id", "revision")
                        if key in native.config.metadata
                    },
                },
            )


__all__ = ["JobBench"]
