"""Shared pinned tau runtime provenance, partitions and simulator reward mapping."""

from dataclasses import replace

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.core import Benchmark

_GIT_URL = "https://github.com/sierra-research/tau2-bench.git"
_UPSTREAM_TAG = "v1.0.1"
_UPSTREAM_REVISION = "fc0055dc4e0a316c3f83133267fbd6faaa770992"


class _TauBenchmark(Benchmark):
    primary_metric = "reward"

    def __init__(self):
        super().__init__()
        self._tasks_by_id = {}

    def load(self):
        if self._splits is None:
            self._splits = _split_tasks(self._iter_tasks(), self.config)
            self._tasks_by_id = {
                task.task_id: task for group in self._splits.values() for task in group
            }
        return self._splits

    def grade(self, trajs):
        """Only the host-added native simulator event can supply a reward."""
        if self._splits is None:
            raise RuntimeError(f"{self.name} has not been loaded; call load() first")
        graded = []
        for trajectory in trajs:
            task = trajectory.task
            if task is None or self._tasks_by_id.get(task.task_id) != task:
                raise ValueError(
                    f"{self.name} grading requires a loaded benchmark Task"
                )
            reward = 0.0
            if trajectory.status == "finished":
                event = trajectory.messages[-1] if trajectory.messages else {}
                if (
                    event.get("type") != "Tau2Simulator"
                    or event.get("task_id") != task.task_id
                    or event.get("task_checksum") != task.metadata["task_checksum"]
                ):
                    raise ValueError(
                        f"{self.name} requires a final Tau2Simulator event "
                        f"for task {task.task_id}"
                    )
                value = event.get("reward")
                if type(value) not in (int, float) or not 0 <= value <= 1:
                    raise ValueError(
                        f"{self.name} simulator reward must be a finite number "
                        f"between 0 and 1 for task {task.task_id}"
                    )
                reward = float(value)
            graded.append(
                replace(trajectory, metrics={**trajectory.metrics, "reward": reward})
            )
        return tuple(graded)
