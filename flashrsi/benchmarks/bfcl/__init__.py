"""BFCL V4 Multi-Turn Base data and host-verifier grading.

Uses the same upstream commit and scoring boundary as the archived OOD adapter:
https://github.com/ShishirPatil/gorilla/tree/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks._git import _download_git
from flashrsi.core import Benchmark, Task, Trajectory

_REVISION = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
_PACKAGE = "berkeley-function-call-leaderboard"
_CATEGORY = "multi_turn_base"


class BFCL(Benchmark):
    """One complete Base conversation per Task; future turns stay with the host.

    Default splits are new experimental partitions of the 200 official cases,
    independent of the historical frozen Base80 OOD evaluation.
    """

    name = "bfcl"
    description = "BFCL V4 Multi-Turn Base, graded by official conversation success."
    primary_metric = "reward"

    def __init__(self, config: Mapping) -> None:
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("BFCL requires benchmark.name: bfcl")
        path = self.config.get("data_path")
        if path is not None and (
            not isinstance(path, (str, Path)) or not str(path).strip()
        ):
            raise ValueError(
                "BFCL requires benchmark.data_path: pinned Gorilla checkout"
            )
        self.data_path = Path(path).expanduser().resolve() if path is not None else None
        self.metadata = MappingProxyType(
            {
                "source": "https://github.com/ShishirPatil/gorilla",
                "revision": _REVISION,
                "category": _CATEGORY,
                "data_path": str(self.data_path)
                if self.data_path is not None
                else None,
                "split_policy": "user-configured",
                "scoring": "official_state_response_and_irrelevance_with_transport_failures_v1",
            }
        )
        self._tasks_by_id = {}

    def load(self) -> Mapping[str, tuple[Task, ...]]:
        if self._splits is None:
            if self.data_path is None:
                self.data_path = _download_git(
                    "https://github.com/ShishirPatil/gorilla.git", _REVISION, [_PACKAGE]
                )
                self.metadata = MappingProxyType(
                    {**self.metadata, "data_path": str(self.data_path)}
                )
            package, source_checksum = _source(self.data_path)
            data = package / "bfcl_eval" / "data"
            filename = f"BFCL_v4_{_CATEGORY}.json"
            rows = _records(data / filename)
            answers = _records(data / "possible_answer" / filename)
            if len(rows) != 200 or rows.keys() != answers.keys():
                raise ValueError(
                    "BFCL Base requires all 200 matching official data/reference IDs"
                )
            tasks = []
            for task_id, row in rows.items():
                if re.fullmatch(r"multi_turn_base_\d+", task_id) is None:
                    raise ValueError(f"Invalid BFCL Base task id: {task_id}")
                turns = row.get("question")
                reference = answers[task_id].get("ground_truth")
                if (
                    not isinstance(turns, list)
                    or not turns
                    or not turns[0]
                    or not isinstance(reference, list)
                    or len(reference) != len(turns)
                    or any(not isinstance(turn, list) for turn in turns)
                    or any(
                        not isinstance(message, Mapping)
                        or message.get("role") != "user"
                        or not isinstance(message.get("content"), str)
                        for turn in turns
                        for message in turn
                    )
                ):
                    raise ValueError(
                        f"Invalid BFCL conversation/reference turns: {task_id}"
                    )
                if (
                    not isinstance(row.get("initial_config"), dict)
                    or not isinstance(row.get("involved_classes"), list)
                    or not row["involved_classes"]
                ):
                    raise ValueError(
                        f"BFCL requires native environment fields: {task_id}"
                    )
                checksum = _checksum(source_checksum, row, answers[task_id])
                # The executor supplies tool docs and releases later user turns
                # incrementally, exactly as the existing OOD session does.
                tasks.append(
                    Task(
                        task_id=task_id,
                        question=json.dumps(
                            {
                                "messages": [
                                    {
                                        "role": message["role"],
                                        "content": message["content"],
                                    }
                                    for message in turns[0]
                                ]
                            },
                            ensure_ascii=False,
                        ),
                        env=str(package),
                        metadata={
                            "source_split": "unassigned",
                            "category": _CATEGORY,
                            "scenario_id": task_id,
                            "task_checksum": checksum,
                        },
                    )
                )
            self._splits = _split_tasks(tasks, self.config)
            self._tasks_by_id = {
                task.task_id: task for group in self._splits.values() for task in group
            }
        return self._splits

    def grade(self, trajs: tuple[Trajectory, ...]) -> tuple[Trajectory, ...]:
        if self._splits is None:
            raise RuntimeError("bfcl has not been loaded; call load() first")
        graded = []
        for trajectory in trajs:
            task = trajectory.task
            if task is None or self._tasks_by_id.get(task.task_id) != task:
                raise ValueError("BFCL grading requires a loaded benchmark Task")
            reward = 0.0
            if trajectory.status == "finished":
                event = trajectory.messages[-1] if trajectory.messages else {}
                if (
                    event.get("type") != "BFCLVerifier"
                    or event.get("task_id") != task.task_id
                    or event.get("task_checksum") != task.metadata["task_checksum"]
                ):
                    raise ValueError(
                        f"BFCL requires a final BFCLVerifier event for task {task.task_id}"
                    )
                fields = (
                    "state_and_response_valid",
                    "irrelevance_valid",
                    "protocol_valid",
                )
                if any(type(event.get(field)) is not bool for field in fields):
                    raise ValueError("BFCL verifier checks must be booleans")
                reward = float(all(event[field] for field in fields))
            graded.append(
                replace(trajectory, metrics={**trajectory.metrics, "reward": reward})
            )
        return tuple(graded)


def _checksum(source_checksum, row, answer):
    return hashlib.sha256(
        json.dumps(
            [source_checksum, row, answer],
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _records(path):
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"BFCL records require string IDs: {path}")
        if row["id"] in records:
            raise ValueError(f"Duplicate BFCL task id: {row['id']}")
        records[row["id"]] = row
    return records


def _source(root):
    """Verify native data and executable sources against immutable Git objects."""

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ValueError("BFCL requires the pinned Gorilla Git checkout")
        return result.stdout

    if git("rev-parse", "HEAD").decode().strip() != _REVISION:
        raise ValueError(f"BFCL requires Gorilla revision {_REVISION}")
    package = root / _PACKAGE
    paths = [
        "README.md",
        "pyproject.toml",
        "bfcl_eval/utils.py",
        "bfcl_eval/constants",
        "bfcl_eval/model_handler/base_handler.py",
        "bfcl_eval/eval_checker/multi_turn_eval",
        "bfcl_eval/data/multi_turn_func_doc",
        "bfcl_eval/data/BFCL_v4_multi_turn_base.json",
        "bfcl_eval/data/possible_answer/BFCL_v4_multi_turn_base.json",
    ]
    raw = git("archive", _REVISION, "--", *(f"{_PACKAGE}/{path}" for path in paths))
    digest = hashlib.sha256()
    expected = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive:
            if member.isdir():
                continue
            relative = Path(member.name)
            path = root / relative
            if (
                not member.isfile()
                or path.is_symlink()
                or not path.resolve().is_relative_to(root)
            ):
                raise ValueError("BFCL native source contains an unsafe path")
            original = archive.extractfile(member).read()
            if not path.is_file() or path.read_bytes() != original:
                raise ValueError(
                    f"Modified or missing official BFCL source: {relative}"
                )
            expected.add(path)
            digest.update(
                member.name.encode() + b"\0" + hashlib.sha256(original).digest()
            )
    for relative in paths:
        directory = package / relative
        if directory.is_dir() and any(
            path not in expected for path in directory.rglob("*.py")
        ):
            raise ValueError(
                f"Unexpected Python module in BFCL native source: {directory}"
            )
    if not expected:
        raise ValueError("BFCL checkout has no native source files")
    return package, digest.hexdigest()


__all__ = ["BFCL"]
