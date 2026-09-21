"""Download and materialize the pinned tau3 Banking domain archive."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flashrsi.benchmarks._archive import _download_archive, _has_only_plain_files

_SCHEMA = "flashrsi.tau3_banking.v1"
_ARCHIVE = "tau3_banking/domain.tar.gz"
_LABEL = "tau3 Banking"


def _download_domain(source: Mapping[str, Any]) -> tuple[Path, ...]:
    """Return the task file paths inside the cached domain directory."""
    extracted, tasks = _download_archive(
        source,
        schema=_SCHEMA,
        label=_LABEL,
        archive=_ARCHIVE,
        validate=_validate_cache,
    )
    return tuple(extracted / task["path"] for task in tasks)


def _validate_cache(directory: Path, tasks: list[dict]) -> None:
    """Every manifest task must be an unchanged regular file on disk."""
    if not _has_only_plain_files(directory):
        raise ValueError(f"Invalid {_LABEL} domain cache: {directory}")
    for task in tasks:
        path = directory / task["path"]
        if not path.is_file():
            raise ValueError(f"{_LABEL} cache is missing {task['path']}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != task["task_checksum"]:
            raise ValueError(f"{_LABEL} task changed on disk: {task['id']}")
