"""Download and materialize the pinned native Terminal-Bench task archive."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flashrsi.benchmarks._archive import _download_archive, _has_only_plain_files
from flashrsi.benchmarks._git import _download_git

_SCHEMA = "flashrsi.terminal_bench.v1"
_ARCHIVE = "terminal_bench/tasks.tar.gz"
_LABEL = "Terminal-Bench"


def _download_tasks(source: Mapping[str, Any]) -> tuple[tuple[Path, str], ...]:
    """Return each cached task directory with its expected Harbor checksum."""
    if source["source"] == source["upstream"]["git_url"]:
        from harbor.models.task.task import Task as HarborTask

        task_path = source["upstream"].get("path", ".")
        root = _download_git(source["source"], source["revision"], [task_path])
        root /= task_path
        return tuple(
            (directory, HarborTask(directory).checksum)
            for directory in sorted(root.iterdir())
            if (directory / "task.toml").is_file()
        )
    extracted, tasks = _download_archive(
        source,
        schema=_SCHEMA,
        label=_LABEL,
        archive=_ARCHIVE,
        validate=_validate_cache,
    )
    return tuple((extracted / task["path"], task["task_checksum"]) for task in tasks)


def _validate_cache(directory: Path, tasks: list[dict]) -> None:
    """Task directories are checksummed later by Harbor's own task model."""
    if (
        not _has_only_plain_files(directory)
        or {item.name for item in directory.iterdir()}
        != {task["path"] for task in tasks}
        or any(not (directory / task["path"]).is_dir() for task in tasks)
    ):
        raise ValueError(f"Invalid {_LABEL} task cache: {directory}")
