"""tau3 Banking tasks and grading from the tau2 simulator's native reward."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks.tau3_banking._data import _download_domain
from flashrsi.core.benchmark import Benchmark, Task
from flashrsi.core.trajectory import Trajectory

_DOMAIN = "banking_knowledge"
_GIT_URL = "https://github.com/sierra-research/tau2-bench.git"
_UPSTREAM_TAG = "v1.0.1"
_UPSTREAM_REVISION = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
_REVISION = "40aa3932298226b2b5063351519291c989b85087"


class Tau3Banking(Benchmark):
    """Multi-turn banking tasks graded by their native tau2 reward.

    tau2 owns the user simulator, the tool implementations and the reward, so
    every task carries the domain directory in ``env`` rather than a prompt to
    answer. ``question`` is the agent's own policy instruction; the simulated
    customer's script stays in metadata for the integration to hand to the user
    simulator, never to the agent under test.

    Terminal-Bench publishes one collection without training splits and so does
    this domain: ``split=auto`` partitions its 97 tasks by the shared seeded
    rule. A local ``data_path`` may name an extracted domain directory.
    """

    name = "tau3_banking"
    description = "Multi-turn banking support tasks graded by the tau2 simulator."
    primary_metric = "reward"
    metadata = MappingProxyType(
        {
            "source": "jinjiajie/flashrsi",
            "config": "tau3_banking",
            "revision": _REVISION,
            "upstream": {
                "git_url": _GIT_URL,
                "tag": _UPSTREAM_TAG,
                "revision": _UPSTREAM_REVISION,
                "domain": f"data/tau2/domains/{_DOMAIN}",
            },
        }
    )

    def __init__(self, config: Mapping[str, Any]) -> None:
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("Tau3Banking requires benchmark.name: tau3_banking")
        self._tasks_by_id: dict[str, Task] = {}

    def load(self) -> Mapping[str, tuple[Task, ...]]:
        """Load a local domain or the pinned Hugging Face domain archive."""
        if self._splits is None:
            self._splits = _split_tasks(self._iter_tasks(), self.config)
            self._tasks_by_id = {
                task.task_id: task for split in self._splits.values() for task in split
            }
        return self._splits

    def grade(self, trajs: tuple[Trajectory, ...]) -> tuple[Trajectory, ...]:
        """Read the host-added simulator reward, never an Agent's self-score."""
        if self._splits is None:
            raise RuntimeError("tau3_banking has not been loaded; call load() first")
        graded = []
        for trajectory in trajs:
            task = trajectory.task
            if task is None or self._tasks_by_id.get(task.task_id) != task:
                raise ValueError("Tau3Banking grading requires a loaded benchmark Task")
            reward = 0.0
            if trajectory.status == "finished":
                event = trajectory.messages[-1] if trajectory.messages else {}
                if (
                    event.get("type") != "Tau2Simulator"
                    or event.get("task_id") != task.task_id
                    or event.get("task_checksum") != task.metadata["task_checksum"]
                ):
                    raise ValueError(
                        "Tau3Banking requires a final Tau2Simulator event "
                        f"for task {task.task_id}"
                    )
                value = event.get("reward")
                if type(value) not in (int, float) or not 0 <= value <= 1:
                    raise ValueError(
                        "Tau3Banking simulator reward must be a finite number "
                        f"between 0 and 1 for task {task.task_id}"
                    )
                reward = float(value)
            graded.append(
                replace(trajectory, metrics={**trajectory.metrics, "reward": reward})
            )
        return tuple(graded)

    def _iter_tasks(self) -> Iterable[Task]:
        data_path = self.config.get("data_path")
        if data_path is None:
            domain, index = _download_domain(self.metadata)
            for row in index:
                yield _task_from_row(row, domain, dict(self.metadata))
            return

        if not isinstance(data_path, (str, Path)) or not str(data_path).strip():
            raise ValueError("benchmark.data_path must be a path")
        domain = Path(data_path).expanduser().resolve()
        if not (domain / "tasks").is_dir() or not (domain / "db.json").is_file():
            raise ValueError(
                f"Tau3Banking data_path must be a tau2 domain directory: {domain}"
            )
        self.metadata = MappingProxyType({"source": "local", "data_path": str(domain)})
        for row in _read_local_index(domain):
            yield _task_from_row(row, domain, dict(self.metadata))


def _read_local_index(domain: Path) -> Iterable[Mapping[str, Any]]:
    """Read the authoritative tasks/ directory, as the tau2 runtime does."""
    paths = sorted((domain / "tasks").glob("task_*.json"))
    if not paths:
        raise ValueError(f"Tau3Banking domain has no task files: {domain / 'tasks'}")
    for path in paths:
        task = json.loads(path.read_text(encoding="utf-8"))
        scenario = task.get("user_scenario") or {}
        criteria = task.get("evaluation_criteria") or {}
        yield {
            "id": task.get("id"),
            "user_instructions": scenario.get("instructions"),
            "reward_basis": criteria.get("reward_basis") or [],
            "user_tools": task.get("user_tools") or [],
            "required_documents": task.get("required_documents") or [],
            "has_initial_state": task.get("initial_state") is not None,
        }


def _task_from_row(
    row: Mapping[str, Any], domain: Path, source: Mapping[str, Any]
) -> Task:
    task_id = row.get("id")
    instructions = row.get("user_instructions")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("tau3 Banking row has no non-empty id")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError(f"tau3 Banking task {task_id} has no user instructions")
    path = domain / "tasks" / f"{task_id}.json"
    if not path.is_file():
        raise ValueError(f"tau3 Banking task file is missing: {path}")
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return Task(
        task_id=task_id,
        # The agent is a support representative; it is not answering a question.
        question=(
            "You are a customer service representative for this bank. Handle the "
            "customer's request using the domain's tools and knowledge base, "
            "following its policy."
        ),
        env=str(domain),
        metadata={
            "source_split": "unassigned",
            "source": dict(source),
            "task_checksum": checksum,
            "task_path": f"tasks/{task_id}.json",
            # The simulated customer's script belongs to the user simulator.
            "user_instructions": instructions,
            "reward_basis": tuple(row.get("reward_basis") or ()),
            "user_tools": tuple(row.get("user_tools") or ()),
            "required_documents": tuple(row.get("required_documents") or ()),
            "has_initial_state": bool(row.get("has_initial_state")),
        },
    )


__all__ = ["Tau3Banking"]
