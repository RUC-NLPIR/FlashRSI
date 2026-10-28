"""Native AppWorld data and host-evaluator result grading."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.core import Benchmark, Task, Trajectory


class AppWorldBenchmark(Benchmark):
    """Preserve native holdouts and grade official per-task completion.

    Application execution and evaluation belong to a host environment adapter;
    neither the Agent's answer nor its claimed metrics establish success.
    """

    name = "appworld"
    description = "AppWorld application tasks graded by official task completion."
    primary_metric = "reward"

    def __init__(self, config: Mapping[str, Any]) -> None:
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("AppWorld requires benchmark.name: appworld")
        data_path = self.config.get("data_path")
        if not isinstance(data_path, (str, Path)) or not str(data_path).strip():
            raise ValueError(
                "AppWorld requires benchmark.data_path: native data directory"
            )
        self.data_path = Path(data_path).expanduser().resolve()
        self.test_set = self.config.get("test_set", "test_normal")
        if self.test_set not in ("test_normal", "test_challenge"):
            raise ValueError("AppWorld test_set must be test_normal or test_challenge")
        self.metadata = MappingProxyType(
            {
                "source": "local-appworld",
                "data_path": str(self.data_path),
                "test_set": self.test_set,
                "split_policy": (
                    "official-splits"
                    if self.config.get("split", "auto") == "auto"
                    and self.config.get("split_counts") is None
                    else "seeded-repartition"
                ),
            }
        )
        self._tasks_by_id: dict[str, Task] = {}

    def load(self) -> Mapping[str, tuple[Task, ...]]:
        if self._splits is None:
            external_split = self.config.get("evolution_test_set")
            if external_split is None:
                splits = _split_tasks(self._iter_tasks(), self.config)
            else:
                if (
                    external_split not in ("test_normal", "test_challenge")
                    or external_split == self.test_set
                ):
                    raise ValueError(
                        "AppWorld evolution_test_set must name the unselected published test set"
                    )
                # Inspect both whole native pools before sampling, including
                # scenarios and raw instructions rather than rendered context.
                downstream = tuple(self._iter_tasks())
                ids = {task.task_id for task in downstream}
                scenarios = {task.metadata["scenario_id"] for task in downstream}
                questions = {task.metadata["question_checksum"] for task in downstream}
                digest = hashlib.sha256()
                count = 0

                def evolution_pool():
                    nonlocal count
                    for task in self._iter_tasks((("test", external_split),)):
                        if (
                            task.task_id in ids
                            or task.metadata["scenario_id"] in scenarios
                            or task.metadata["question_checksum"] in questions
                        ):
                            raise ValueError(
                                "AppWorld evolution pool overlaps downstream tasks"
                            )
                        digest.update(
                            json.dumps(
                                (task.task_id, task.metadata["task_checksum"])
                            ).encode()
                            + b"\n"
                        )
                        count += 1
                        yield task

                evolution = _split_tasks(
                    evolution_pool(),
                    {
                        "split": {"train": 1, "dev": 0, "test": 0},
                        "limit": self.config.get("evolution_limit"),
                        "seed": self.config.get("seed", 0),
                    },
                )["train"]
                splits = MappingProxyType(
                    {
                        **_split_tasks(downstream, self.config),
                        "train": evolution,
                    }
                )
                self.metadata = MappingProxyType(
                    {
                        **self.metadata,
                        "evolution_source": {
                            "source": "local-appworld",
                            "data_path": str(self.data_path),
                            "native_split": external_split,
                            "native_role": "published_evaluation",
                            "experiment_role": "external_evolution",
                            "pool_size": count,
                            "pool_checksum": digest.hexdigest(),
                        },
                    }
                )
            self._splits = splits
            self._tasks_by_id = {
                task.task_id: task for group in self._splits.values() for task in group
            }
        return self._splits

    def grade(self, trajs: tuple[Trajectory, ...]) -> tuple[Trajectory, ...]:
        """Consume the native evaluator's boolean success in a bound host event."""
        if self._splits is None:
            raise RuntimeError("appworld has not been loaded; call load() first")
        graded = []
        for trajectory in trajs:
            task = trajectory.task
            if task is None or self._tasks_by_id.get(task.task_id) != task:
                raise ValueError("AppWorld grading requires a loaded benchmark Task")
            reward = 0.0
            if trajectory.status == "finished":
                event = trajectory.messages[-1] if trajectory.messages else {}
                if (
                    event.get("type") != "AppWorldVerifier"
                    or event.get("task_id") != task.task_id
                    or event.get("task_checksum") != task.metadata["task_checksum"]
                ):
                    raise ValueError(
                        f"AppWorld requires a final AppWorldVerifier event for task {task.task_id}"
                    )
                success = event.get("success")
                if type(success) is not bool:
                    raise ValueError("AppWorld verifier success must be a boolean")
                reward = float(success)
            graded.append(
                replace(trajectory, metrics={**trajectory.metrics, "reward": reward})
            )
        return tuple(graded)

    def _iter_tasks(self, native_splits=None) -> Iterable[Task]:
        base_checksum = _tree_checksum(self.data_path / "base_dbs")
        for split, upstream in (
            native_splits
            if native_splits is not None
            else (
                ("train", "train"),
                ("dev", "dev"),
                ("test", self.test_set),
            )
        ):
            path = self.data_path / "datasets" / f"{upstream}.txt"
            ids = [
                line.strip().split(":")[0]
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for task_id in ids:
                if re.fullmatch(r"[0-9a-f]+_[1-9][0-9]*", task_id) is None:
                    raise ValueError(f"Invalid AppWorld task id: {task_id}")
                directory = self.data_path / "tasks" / task_id
                if not directory.resolve().is_relative_to(self.data_path):
                    raise ValueError(
                        f"AppWorld task is outside data directory: {task_id}"
                    )
                specs = json.loads(
                    (directory / "specs.json").read_text(encoding="utf-8")
                )
                if not isinstance(specs, dict):
                    raise ValueError(f"AppWorld specs must be an object: {task_id}")
                for field in ("instruction", "datetime", "db_version"):
                    if (
                        not isinstance(specs.get(field), str)
                        or not specs[field].strip()
                    ):
                        raise ValueError(f"AppWorld specs require {field}: {task_id}")
                datetime.fromisoformat(specs["datetime"])
                supervisor = specs.get("supervisor", specs.get("main_user"))
                fields = ("first_name", "last_name", "email", "phone_number")
                if not isinstance(supervisor, dict) or any(
                    not isinstance(supervisor.get(field), str) for field in fields
                ):
                    raise ValueError(
                        f"AppWorld specs require supervisor identity: {task_id}"
                    )
                public_supervisor = {field: supervisor[field] for field in fields}
                for folder in ("dbs", "ground_truth"):
                    if not (directory / folder).is_dir():
                        raise ValueError(f"AppWorld task requires {folder}: {task_id}")
                checksum = hashlib.sha256(
                    f"{base_checksum}:{_tree_checksum(directory)}".encode()
                ).hexdigest()
                yield Task(
                    task_id=task_id,
                    question=(
                        f"{specs['instruction']}\n\n"
                        f"Supervisor: {json.dumps(public_supervisor, ensure_ascii=False)}\n"
                        f"Current simulated datetime: {specs['datetime']}"
                    ),
                    env=str(directory),
                    metadata={
                        "source_split": split,
                        "upstream_split": upstream,
                        "scenario_id": task_id.rsplit("_", 1)[0],
                        "question_checksum": hashlib.sha256(
                            " ".join(specs["instruction"].split()).casefold().encode()
                        ).hexdigest(),
                        "db_version": specs["db_version"],
                        "task_checksum": checksum,
                    },
                )


def _tree_checksum(directory: Path) -> str:
    """Bind a verdict to input state and evaluation files, without exposing them."""
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"AppWorld requires a native data directory: {directory}")
    digest = hashlib.sha256()
    paths = sorted(directory.rglob("*"))
    files = 0
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"AppWorld data cannot contain symlinks: {path}")
        if not path.is_file():
            continue
        files += 1
        relative = path.relative_to(directory).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        file_digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                file_digest.update(chunk)
        digest.update(file_digest.digest())
    if not files:
        raise ValueError(f"AppWorld data directory is empty: {directory}")
    return digest.hexdigest()


__all__ = ["AppWorldBenchmark"]
