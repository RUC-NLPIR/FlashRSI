"""Official SWE-bench Pro V2 Harbor tasks at 66f92766bba642462d4bbe5479e83f91f9211862."""

import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks._git import _download_git
from flashrsi.benchmarks._harbor import _task_from_directory
from flashrsi.core import Benchmark

_SOURCE = "https://github.com/scaleapi/SWE-bench_Pro-os.git"
_REVISION = "66f92766bba642462d4bbe5479e83f91f9211862"


def _upstream():
    return _download_git(_SOURCE, _REVISION, ["v2"])


class SWEBenchPro(Benchmark):
    """Preserve V2's native test collection; score patches on pristine images."""

    name = "swe_bench_pro"
    description = "SWE-bench Pro V2 repairs with official fresh-container scoring."
    primary_metric = "resolved"

    def __init__(self, config: Mapping):
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("SWEBenchPro requires benchmark.name: swe_bench_pro")
        self.subset = self.config.get("subset", "all")
        if self.subset not in ("all", "hard"):
            raise ValueError("SWE-bench Pro subset must be all or hard")
        self.metadata = MappingProxyType(
            {
                "source": _SOURCE,
                "revision": _REVISION,
                "version": "2.0.0",
                "native_split": "test",
                "subset": self.subset,
                "scoring": "official-fresh-sandbox-regrade",
            }
        )
        self._tasks_by_id = {}

    def load(self):
        if self._splits is None:
            self._splits = _split_tasks(self._iter_tasks(), self.config)
            self._tasks_by_id = {
                t.task_id: t for group in self._splits.values() for t in group
            }
        return self._splits

    def _iter_tasks(self):
        data = self.config.get("data_path")
        if data is None:
            root = _upstream() / "v2"
        else:
            if not isinstance(data, (str, Path)) or not str(data).strip():
                raise ValueError("SWE-bench Pro data_path must be a native directory")
            root = Path(data).expanduser().resolve()
            if (root / "v2").is_dir():
                root /= "v2"
            if not root.is_dir():
                raise ValueError(f"SWE-bench Pro directory does not exist: {root}")
            self.metadata = MappingProxyType(
                {
                    **self.metadata,
                    "source": "local",
                    "revision": "local",
                    "data_path": str(root),
                }
            )
        # Several official instance IDs exceed Windows' legacy MAX_PATH once
        # placed under the HF cache. Preserve names and bytes with native paths.
        if os.name == "nt" and not str(root).startswith("\\\\?\\"):
            root = Path("\\\\?\\" + str(root.resolve()))
        hard = None
        if self.subset == "hard":
            ids = root / "hard51_ids.txt"
            if not ids.is_file():
                raise ValueError("SWE-bench Pro hard subset needs v2/hard51_ids.txt")
            hard = set(ids.read_text(encoding="utf-8").split())
        tasks = root / "tasks" if (root / "tasks").is_dir() else root
        directories = (
            [tasks]
            if (tasks / "task.toml").is_file()
            else sorted(p for p in tasks.iterdir() if (p / "task.toml").is_file())
        )
        for directory in directories:
            if hard is not None and directory.name not in hard:
                continue
            from harbor.models.task.task import Task as HarborTask

            native = HarborTask(directory)
            if native.config.agent.network_mode != "no-network":
                raise ValueError(
                    "SWE-bench Pro requires native agent network_mode=no-network"
                )
            task = _task_from_directory(
                directory, self.metadata, "SWEBenchPro", native=native
            )
            yield replace(
                task,
                metadata={
                    **task.metadata,
                    "source_split": "test",
                    "native_split": "test",
                },
            )

    def grade(self, trajs):
        if self._splits is None:
            raise RuntimeError("swe_bench_pro has not been loaded; call load() first")
        graded = []
        for trajectory in trajs:
            task = trajectory.task
            if task is None or self._tasks_by_id.get(task.task_id) != task:
                raise ValueError("SWEBenchPro grading requires a loaded benchmark Task")
            resolved = 0.0
            event = trajectory.messages[-1] if trajectory.messages else {}
            # The official protocol grades partial patches even when the solver
            # reaches its deadline. A failed regrade never supplies a verdict.
            if (
                trajectory.status == "finished"
                or event.get("official_evaluation_performed") is True
            ):
                if (
                    event.get("type") != "SWEBenchProVerifier"
                    or event.get("task_id") != task.task_id
                    or event.get("task_checksum") != task.metadata["task_checksum"]
                    or event.get("official_evaluation_performed") is not True
                    or type(event.get("resolved")) is not bool
                ):
                    raise ValueError(
                        "SWEBenchPro requires a final official regrade verdict"
                    )
                resolved = float(event["resolved"])
            graded.append(
                replace(
                    trajectory, metrics={**trajectory.metrics, "resolved": resolved}
                )
            )
        return tuple(graded)


__all__ = ["SWEBenchPro"]
