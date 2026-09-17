"""The evolution loop owns policy; the runner supplies its collaborators."""

from __future__ import annotations

import copy
import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from flashrsi._records import _redact, _secrets, _trajectory_record, _write_record
from flashrsi.config import Config
from flashrsi.core.agent import Agent
from flashrsi.core.benchmark import Task
from flashrsi.core.snapshot import Snapshot, _validate_path
from flashrsi.core.trajectory import Trajectory


class Algorithm:
    """Shared setup, execution and file recording; subclasses own search policy."""

    name: str
    description: str
    evolve_scope = frozenset()
    observation_scope = frozenset()
    _defaults = {}

    def __init__(self, config, *, target, worker, benchmark):
        self.config = Config(copy.deepcopy({**self._defaults, **config}))
        self.target = target
        self.worker = worker
        self.benchmark = benchmark
        # The runner attaches the prepared experiment directory. Direct Python
        # use can evolve in memory without inventing another runtime object.
        self._run_dir: Path | None = None
        self._sequence = 0

        self.target.set_scope(
            {
                **{component: "r" for component in self.observation_scope},
                **{component: "rw" for component in self.evolve_scope},
            }
        )
        for role, agent in (("target", target), ("worker", worker)):
            if type(agent)._run is Agent._run:
                raise ValueError(f"Algorithm {role} must implement Agent._run")
        splits = self.benchmark.load()
        if type(self.target).rollout is Agent.rollout and any(
            task.env is not None for tasks in splits.values() for task in tasks
        ):
            raise ValueError(
                "Algorithm target needs environment-aware rollout for these tasks"
            )
        self._check()

    def _check(self) -> None:
        """Algorithm-specific setup checks, after loading data and applying scope."""

    async def evolve(self) -> Snapshot:
        raise NotImplementedError

    async def _evaluate(
        self,
        snapshot: Snapshot,
        tasks: Iterable[Task],
        *,
        label: str = "evaluation",
    ) -> tuple[Trajectory, ...]:
        """Evaluate without selecting; label only names the scored trace record."""
        self._save_snapshot(snapshot)
        tasks = tuple(tasks)
        results = self.benchmark.grade(
            await self.target.rollout(tasks, snapshot=snapshot)
        )
        if tuple(item.task for item in results) != tasks:
            raise ValueError(
                "rollout/grade must preserve the requested tasks and order"
            )
        self._record(
            label,
            {
                "snapshot_id": snapshot.id,
                "trajectories": [_trajectory_record(item) for item in results],
            },
        )
        return results

    async def _ask(self, prompt: str, *, label: str = "worker") -> str:
        """Keep the Worker trajectory and return its text.

        label only names the record and identifies the stage in errors.
        """
        result = await self.worker.run(prompt)
        self._record(
            label, {"prompt": prompt, "trajectory": _trajectory_record(result)}
        )
        if result.status != "finished":
            detail = _redact(result.error_message, self._runtime_secrets())
            raise RuntimeError(f"Worker failed during {label}: {detail}")
        return result.output

    def _read_text(self, snapshot: Snapshot) -> dict[str, str]:
        """Read the declared visible components; leave binary resources untouched."""
        visible = self.observation_scope | self.evolve_scope
        files = {}
        for path, entry in sorted(snapshot.files.items()):
            if entry.component in visible:
                try:
                    files[path] = entry.content.decode("utf-8")
                except UnicodeDecodeError:
                    continue
        return files

    def _candidate(self, baseline: Snapshot, files: Mapping[str, str]) -> Snapshot:
        """Apply text updates to a checkout; Snapshot enforces component permissions.

        Omitted files are preserved. Algorithms that delete files or edit binary
        resources can use Snapshot.check_out()/commit() directly.
        """
        changed = {}
        secrets = self._runtime_secrets()
        for path, content in files.items():
            _validate_path(path)
            encoded = content.encode("utf-8")
            original = baseline.files.get(path)
            if original is not None:
                if original.content == encoded:
                    continue
                try:
                    original.content.decode("utf-8")
                except UnicodeDecodeError:
                    raise ValueError("cannot overwrite a non-text resource") from None
            if any(secret in content for secret in secrets):
                raise ValueError("candidate contains a runtime credential")
            changed[path] = encoded
        if not changed:
            return baseline

        working = self._run_dir / "working" if self._run_dir else None
        with baseline.check_out(working_dir=working) as directory:
            for path, content in changed.items():
                destination = directory / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            candidate = baseline.commit(directory)
        self._save_snapshot(candidate)
        return candidate

    def _record(self, label: str, payload: Mapping) -> None:
        if self._run_dir is not None:
            self._sequence += 1
            _write_record(
                self._run_dir / "trajectories" / f"{self._sequence:05d}-{label}.json",
                payload,
                {"target": self.target.config, "worker": self.worker.config},
            )

    def _save_snapshot(self, snapshot: Snapshot) -> None:
        if self._run_dir is not None:
            path = self._run_dir / "snapshots" / f"{snapshot.id}.json"
            if not path.exists():
                snapshot.save(path)

    def _runtime_secrets(self) -> list[str]:
        return sorted(
            set(
                _secrets(self.target.config)
                + _secrets(self.worker.config)
                + _secrets(os.environ)
            ),
            key=len,
            reverse=True,
        )
