"""Datacurve DeepSWE v1.1 at 0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea.

Upstream: https://github.com/datacurve-ai/deep-swe
Native tasks, collect hooks and separate verifiers are passed through to Harbor.
"""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks._git import _download_git
from flashrsi.benchmarks._harbor import _grade, _task_from_directory
from flashrsi.core import Benchmark

_SOURCE = "https://github.com/datacurve-ai/deep-swe.git"
_REVISION = "0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea"


class DeepSWE(Benchmark):
    """Solve repository tasks; grade committed patches with native isolated tests.

    The public collection remains test by default. Evolution experiments can
    explicitly partition it with the existing split or split_counts options.
    """

    name = "deepswe"
    description = "DeepSWE v1.1 repository tasks with native separate-verifier reward."
    primary_metric = "reward"

    def __init__(self, config: Mapping):
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("DeepSWE requires benchmark.name: deepswe")
        self.metadata = MappingProxyType(
            {
                "source": _SOURCE,
                "revision": _REVISION,
                "version": "1.1",
                "native_split": "test",
                "scoring": "native-separate-verifier",
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

    def grade(self, trajs):
        if self._splits is None:
            raise RuntimeError("deepswe has not been loaded; call load() first")
        return _grade(trajs, self._tasks_by_id, "DeepSWE")

    def _iter_tasks(self):
        try:
            from harbor.models.task.task import Task as HarborTask
        except ImportError:
            raise ValueError(
                "DeepSWE requires flashrsi-lite[harbor] and Python >=3.12"
            ) from None
        data = self.config.get("data_path")
        if data is None:
            root = _download_git(_SOURCE, _REVISION, ["tasks"]) / "tasks"
        else:
            if not isinstance(data, (str, Path)) or not str(data).strip():
                raise ValueError("DeepSWE data_path must be a native task directory")
            root = Path(data).expanduser().resolve()
            if (root / "tasks").is_dir() and not (root / "task.toml").is_file():
                root /= "tasks"
            if not root.is_dir():
                raise ValueError(f"DeepSWE directory does not exist: {root}")
            self.metadata = MappingProxyType(
                {
                    **self.metadata,
                    "source": "local",
                    "revision": "local",
                    "data_path": str(root),
                }
            )
        directories = (
            [root]
            if (root / "task.toml").is_file()
            else sorted(p for p in root.iterdir() if (p / "task.toml").is_file())
        )
        if not directories:
            raise ValueError(f"DeepSWE directory contains no native tasks: {root}")
        for directory in directories:
            native = HarborTask(directory)
            if (
                native.config.verifier.environment_mode != "separate"
                or not native.config.verifier.collect
            ):
                raise ValueError(
                    "DeepSWE v1.1 requires a separate verifier and native collect hooks"
                )
            if (
                native.config.agent.network_mode != "no-network"
                or native.config.verifier.network_mode != "no-network"
            ):
                raise ValueError(
                    "DeepSWE v1.1 requires native agent/verifier network_mode=no-network"
                )
            task = _task_from_directory(
                directory, self.metadata, "DeepSWE", native=native
            )
            yield replace(
                task,
                metadata={
                    **task.metadata,
                    "source_split": "test",
                    **{
                        key: native.config.metadata[key]
                        for key in ("language", "repository_url", "base_commit_hash")
                        if key in native.config.metadata
                    },
                },
            )


__all__ = ["DeepSWE"]
