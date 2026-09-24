"""Agent rollout record shared by Agents, Benchmarks, and Algorithms."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from statistics import mean
from types import MappingProxyType
from typing import Any

from flashrsi.core.benchmark import Task


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class Trajectory:
    """The result and accounting information from one Agent task run."""

    task: Task | None = None
    status: str = "finished"
    output: str = ""
    messages: tuple[Mapping[str, Any], ...] = ()
    metrics: Mapping[str, float] = field(default_factory=dict)
    error_message: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.task is not None and not isinstance(self.task, Task):
            raise ValueError("task must be a Task or None")
        if self.status not in {"finished", "error"}:
            raise ValueError("status must be 'finished' or 'error'")
        if not isinstance(self.output, str):
            raise ValueError("output must be a string")
        if self.status == "error" and not self.error_message:
            raise ValueError("error_message is required when status is 'error'")
        if self.error_message is not None and not isinstance(self.error_message, str):
            raise ValueError("error_message must be a string or None")
        if not isinstance(self.metrics, Mapping):
            raise ValueError("metrics must be a mapping")
        for name, value in self.metrics.items():
            if (
                not isinstance(name, str)
                or not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError("metrics must map string names to finite numbers")
        if not isinstance(self.usage, Mapping):
            raise ValueError("usage must be a mapping")
        object.__setattr__(
            self,
            "messages",
            tuple(_immutable_mapping(message) for message in self.messages),
        )
        object.__setattr__(self, "metrics", _immutable_mapping(self.metrics))
        object.__setattr__(self, "usage", _immutable_mapping(self.usage))


class Results(tuple):
    """Graded trajectories that know their own score.

    An algorithm asks "how did this version do", not "what is the mean of the
    benchmark's primary metric over these trajectories" -- the evaluation
    carries the metric it was graded on, so reading the score needs no help
    from the algorithm.

    This is a tuple, so iterating, ``len()`` and ``zip()`` work as before.
    Slicing returns a plain tuple and drops the score, which is why a caller
    that needs a subset scored evaluates that subset.
    """

    def __new__(cls, trajectories, *, metric: str):
        results = super().__new__(cls, trajectories)
        # Read once here rather than on each access: a caller that wants both
        # the mean and the per-task scores -- GEPA does -- would otherwise walk
        # the trajectories twice. A tuple subclass cannot declare __slots__, so
        # this is an ordinary instance attribute.
        results._per_task = MappingProxyType(
            {item.task.task_id: item.metrics[metric] for item in results}
        )
        return results

    @property
    def score(self) -> float:
        """The mean primary metric: one evaluation's fitness.

        An empty evaluation has no score rather than a zero one, which a
        caller distinguishes by checking the results themselves.
        """
        if not self:
            raise ValueError("an empty evaluation has no score")
        return mean(self._per_task.values())

    @property
    def per_task(self) -> Mapping[str, float]:
        """The same scores read one task at a time, keyed by ``task_id``.

        A comparison that the mean cannot express reads this instead: a Pareto
        frontier over individual tasks, or which tasks one edit flipped.
        """
        return self._per_task
