"""The evolution loop owns policy; the runner supplies its collaborators."""

from __future__ import annotations

import copy
import math
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from statistics import mean
from typing import get_args

from flashrsi._records import _redact, _secrets, _trajectory_record, _write_record
from flashrsi.config import Config
from flashrsi.core.agent import Agent
from flashrsi.core.benchmark import Task
from flashrsi.core.snapshot import Snapshot, _matching_components, _validate_path
from flashrsi.core.trajectory import Trajectory


class Algorithm:
    """Shared setup, execution and file recording; subclasses own search policy."""

    name: str
    description: str
    evolve_scope = frozenset()
    observation_scope = frozenset()
    _defaults = {}
    _ranges = {}

    def __init__(self, config, *, target, worker, benchmark):
        self.config = Config(copy.deepcopy({**self._defaults, **config}))
        self._normalize()
        for key, spec in self._ranges.items():
            _check_parameter(key, self.config[key], spec)
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
        if (
            type(self.target).rollout is Agent.rollout
            and self.target._env_runner is None
            and any(task.env is not None for tasks in splits.values() for task in tasks)
        ):
            raise ValueError(
                "Algorithm target needs environment-aware rollout for these tasks"
            )
        self._check()

    def _normalize(self) -> None:
        """Rewrite accepted spellings to canonical ones, before ``_ranges`` runs.

        An upstream CLI name that this port also accepts belongs here: the loop
        then compares against one spelling and the saved configuration records
        what actually ran.
        """

    def _check(self) -> None:
        """Algorithm-specific setup checks, after loading data and applying scope."""

    async def evolve(self) -> Snapshot:
        raise NotImplementedError

    def _instruction_path(self, component: str = "prompt") -> str:
        """The one instruction file this algorithm rewrites, as the target names it.

        The target declares the file it loads its instructions from, so a run
        needs no knowledge of the harness's layout and no algorithm branches on
        the harness name. The declaration is the only source, so it is checked
        rather than trusted: it must be a usable path inside the component this
        algorithm may edit.
        """
        path = self.target.instruction_file
        if not isinstance(path, str) or not path:
            raise ValueError(
                f"{self.target.name} declares no instruction_file, so "
                f"{type(self).__name__} has nothing to rewrite"
            )
        _validate_path(path)
        rules = self.target.component_rules
        if _matching_components(path, rules) != {component}:
            patterns = ", ".join(rules.get(component, ()))
            raise ValueError(
                f"{self.target.name} declares an instruction_file outside its "
                f"{component} component ({patterns}), which "
                f"{type(self).__name__} cannot evolve: {path}"
            )
        return path

    def _score(self, results: Iterable[Trajectory]) -> float:
        """The mean primary metric over an evaluation: one algorithm's fitness."""
        return mean(item.metrics[self.benchmark.primary_metric] for item in results)

    def _promote(self, current: Snapshot, best: Snapshot, **details) -> Snapshot:
        """Select one version at the end of the search and record the decision.

        Algorithms that never move the incumbent during the search call this
        once: every candidate was scored against the same baseline, which is why
        they record a whole pool through ``details`` rather than a sequence of
        accept/reject decisions.
        """
        self._record(
            "decision",
            {
                "kind": "promote",
                "parent_id": current.id,
                "candidate_id": best.id,
                "accepted": best.id != current.id,
                **details,
            },
        )
        if best.id != current.id:
            self.target.update(best)
        return self.target.snapshot

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


def _check_parameter(key: str, value, spec) -> None:
    """Check one ``_ranges`` entry, so each algorithm declares rather than tests.

    A spec is either the accepted values as a tuple of strings, or a type with
    an optional inclusive minimum: ``int``, ``(int, 1)``, ``(float, 0)``. Write
    the type as ``int | None`` when unset is meaningful -- an unset budget is
    then distinct from a bad one, and null is rejected everywhere else.
    """
    if isinstance(spec, tuple) and isinstance(spec[0], str):
        if value not in spec:
            raise ValueError(f"algorithm.{key} must be one of: " + ", ".join(spec))
        return
    kind, minimum = spec if isinstance(spec, tuple) else (spec, None)
    optional = type(None) in get_args(kind)
    kind = next(iter(get_args(kind)), kind)
    if optional and value is None:
        return
    name = {int: "an integer", float: "a number", bool: "a boolean"}[kind]
    suffix = " or null" if optional else ""
    # bool is an int subclass and 1.5 is not an integer step count, so the exact
    # type is what matters here rather than isinstance.
    if kind is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"algorithm.{key} must be {name}{suffix}")
        if not math.isfinite(value):
            raise ValueError(f"algorithm.{key} must be finite")
    elif type(value) is not kind:
        raise ValueError(f"algorithm.{key} must be {name}{suffix}")
    if minimum is not None and value < minimum:
        raise ValueError(f"algorithm.{key} must be {name} >= {minimum}{suffix}")
