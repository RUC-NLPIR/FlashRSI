"""Shared native Harbor task parsing and host verifier reward mapping."""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from flashrsi.core import Task


def _grade(trajs, tasks_by_id, label):
    graded = []
    for trajectory in trajs:
        task = trajectory.task
        if task is None or tasks_by_id.get(task.task_id) != task:
            raise ValueError(f"{label} grading requires a loaded benchmark Task")
        reward = 0.0
        if trajectory.status == "finished":
            event = trajectory.messages[-1] if trajectory.messages else {}
            if (
                event.get("type") != "HarborVerifier"
                or event.get("task_id") != task.task_id
                or event.get("task_checksum") != task.metadata["task_checksum"]
            ):
                raise ValueError(
                    f"{label} requires a final HarborVerifier event "
                    f"for task {task.task_id}"
                )
            rewards = event.get("rewards")
            value = rewards.get("reward") if isinstance(rewards, Mapping) else None
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError(
                    f"{label} verifier reward must be a finite number "
                    f"between 0 and 1 for task {task.task_id}"
                )
            reward = float(value)
        graded.append(
            replace(trajectory, metrics={**trajectory.metrics, "reward": reward})
        )
    return tuple(graded)


def _task_from_directory(
    directory: Path, source: Mapping[str, Any], label="TerminalBench", *, native=None
) -> Task:
    if native is None:
        try:
            from harbor.models.task.task import Task as HarborTask
        except ImportError:
            raise ValueError(f"{label} requires flashrsi-lite[harbor]") from None
        native = HarborTask(task_dir=directory)
    if native.has_steps or native.config.environment.os != "linux":
        raise ValueError(f"{label} currently supports single-step Linux tasks only")
    # Use Harbor's checksum so rollout can detect changes to local task resources.
    with warnings.catch_warnings(action="ignore", category=DeprecationWarning):
        checksum = native.checksum
    return Task(
        task_id=native.name,
        question=native.instruction,
        env=str(native.task_dir),
        metadata={
            "source_split": "unassigned",
            "source": dict(source),
            "task_checksum": checksum,
            **{
                key: native.config.metadata[key]
                for key in ("category", "difficulty")
                if key in native.config.metadata
            },
        },
    )
