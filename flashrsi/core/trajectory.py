"""Agent rollout record shared by Agents, Benchmarks, and Algorithms."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
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
