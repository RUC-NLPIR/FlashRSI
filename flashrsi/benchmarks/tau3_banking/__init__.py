"""tau3 Banking tasks and grading from the tau2 simulator's native reward."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._tau import (
    _GIT_URL,
    _UPSTREAM_REVISION,
    _UPSTREAM_TAG,
    _TauBenchmark,
)
from flashrsi.benchmarks.tau3_banking._data import _download_domain
from flashrsi.benchmarks.tau3_banking._policy import (
    _DEFAULT_VARIANT,
    _policy,
    _variants,
)
from flashrsi.core.benchmark import Task

_DOMAIN = "banking_knowledge"
_REVISION = "8d4ab8ad7bce903fe9959fc46b39d7e414f6711e"


class Tau3Banking(_TauBenchmark):
    """Multi-turn banking tasks graded by their native tau2 reward.

    tau2 owns the user simulator, the tool implementations and the reward, so
    every task carries the domain directory in ``env`` rather than a prompt to
    answer. ``question`` is the domain's own agent policy, rendered from its
    prompt templates; the simulated customer's script stays in metadata for the
    user simulator and never reaches the agent.

    ``benchmark.variant`` selects the retrieval variant, defaulting to
    upstream's own ``alltools``. The variant chooses both the policy text and,
    once the simulator is connected, the agent's knowledge-base tools, so it
    must be reported alongside any score.

    The domain publishes one collection without training splits. Users
    explicitly configure experiment partitions with ratios or counts. A local
    ``data_path`` may name an extracted domain directory.
    """

    name = "tau3_banking"
    description = "Multi-turn banking support tasks graded by the tau2 simulator."
    primary_metric = "reward"
    metadata = MappingProxyType(
        {
            "source": _GIT_URL,
            "config": "tau3_banking",
            "revision": _UPSTREAM_REVISION,
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
        self.metadata = MappingProxyType(
            {**type(self).metadata, **self.config.get("dataset", {})}
        )
        if self.config.get("name", self.name) != self.name:
            raise ValueError("Tau3Banking requires benchmark.name: tau3_banking")
        variant = self.config.get("variant", _DEFAULT_VARIANT)
        if variant not in _variants():
            raise ValueError(
                f"Unknown tau3 Banking retrieval variant: {variant!r}; "
                f"available: {', '.join(_variants())}"
            )
        self.variant = variant
        self.metadata = MappingProxyType({**self.metadata, "variant": self.variant})

    def _iter_tasks(self) -> Iterable[Task]:
        """Read the tasks/ directory, which is what the tau2 runtime loads."""
        paths, domain = self._task_files()
        for path in paths:
            yield _task_from_file(path, domain, dict(self.metadata), self.variant)

    def _task_files(self) -> tuple[tuple[Path, ...], Path]:
        data_path = self.config.get("data_path")
        if data_path is None:
            paths = _download_domain(self.metadata)
            return paths, paths[0].parents[1]

        if not isinstance(data_path, (str, Path)) or not str(data_path).strip():
            raise ValueError("benchmark.data_path must be a path")
        domain = Path(data_path).expanduser().resolve()
        if not (domain / "tasks").is_dir() or not (domain / "db.json").is_file():
            raise ValueError(
                f"Tau3Banking data_path must be a tau2 domain directory: {domain}"
            )
        self.metadata = MappingProxyType(
            {"source": "local", "data_path": str(domain), "variant": self.variant}
        )
        paths = tuple(sorted((domain / "tasks").glob("task_*.json")))
        if not paths:
            raise ValueError(
                f"Tau3Banking domain has no task files: {domain / 'tasks'}"
            )
        return paths, domain


def _task_from_file(
    path: Path, domain: Path, source: Mapping[str, Any], variant: str
) -> Task:
    """Describe one task; grading criteria stay in the file, not on the Task."""
    task = json.loads(path.read_text(encoding="utf-8"))
    task_id = task.get("id")
    scenario = task.get("user_scenario") or {}
    instructions = (
        scenario.get("instructions") if isinstance(scenario, Mapping) else None
    )
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"tau3 Banking task file has no id: {path.name}")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError(f"tau3 Banking task {task_id} has no user instructions")
    criteria = task.get("evaluation_criteria") or {}
    required = tuple(task.get("required_documents") or ())
    return Task(
        task_id=task_id,
        question=_policy(domain, variant, required),
        env=str(domain),
        metadata={
            "source_split": "unassigned",
            "source": dict(source),
            "task_checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
            "task_path": path.relative_to(domain).as_posix(),
            "variant": variant,
            # The simulated customer's script belongs to the user simulator.
            "user_instructions": instructions,
            "reward_basis": tuple(criteria.get("reward_basis") or ()),
            "user_tools": tuple(task.get("user_tools") or ()),
            "required_documents": required,
            "has_initial_state": task.get("initial_state") is not None,
        },
    )


__all__ = ["Tau3Banking"]
