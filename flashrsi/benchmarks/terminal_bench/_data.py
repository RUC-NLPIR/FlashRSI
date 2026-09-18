"""Download and materialize the pinned native Terminal-Bench task archive."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from filelock import FileLock
from huggingface_hub import constants, hf_hub_download

_MANIFEST = "terminal_bench/manifest.json"
_ARCHIVE = "terminal_bench/tasks.tar.gz"
_INDEX = "terminal_bench/tasks.parquet"


def _download_tasks(source: Mapping[str, Any]) -> tuple[tuple[Path, str], ...]:
    """Reuse HF authentication and cache; publish extracted tasks atomically."""
    download = {
        "repo_id": source["source"],
        "repo_type": "dataset",
        "revision": source["revision"],
    }
    manifest_path = hf_hub_download(filename=_MANIFEST, **download)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    _validate_manifest(manifest, source["upstream"])
    archive = manifest["archive"]
    tasks = manifest["tasks"]
    cache = Path(constants.HF_HOME) / "flashrsi" / "terminal_bench"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / archive["sha256"]
    with FileLock(str(destination) + ".lock"):
        if not destination.exists() and not destination.is_symlink():
            archive_path = Path(hf_hub_download(filename=_ARCHIVE, **download))
            with archive_path.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            if (
                checksum != archive["sha256"]
                or archive_path.stat().st_size != archive["bytes"]
            ):
                raise ValueError("Terminal-Bench archive checksum or size mismatch")
            with TemporaryDirectory(prefix=".extract-", dir=cache) as temporary:
                extracted = Path(temporary) / "tasks"
                extracted.mkdir()
                _extract_archive(archive_path, extracted, tasks)
                _validate_cache(extracted, tasks)
                extracted.rename(destination)
        _validate_cache(destination, tasks)
    return tuple((destination / task["path"], task["task_checksum"]) for task in tasks)


def _validate_manifest(manifest: Any, upstream: Mapping[str, Any]) -> None:
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "flashrsi.terminal_bench.v1"
        or manifest.get("source") != upstream
    ):
        raise ValueError("Terminal-Bench manifest does not match the pinned source")
    archive, index, tasks = (
        manifest.get("archive"),
        manifest.get("index"),
        manifest.get("tasks"),
    )
    if (
        not isinstance(archive, dict)
        or archive.get("file") != _ARCHIVE
        or not _is_sha256(archive.get("sha256"))
        or type(archive.get("bytes")) is not int
        or archive["bytes"] <= 0
        or not isinstance(index, dict)
        or index.get("file") != _INDEX
        or not _is_sha256(index.get("sha256"))
        or not isinstance(tasks, list)
        or not tasks
        or type(index.get("count")) is not int
        or index["count"] != len(tasks)
    ):
        raise ValueError("Invalid Terminal-Bench archive or index manifest")
    names = set()
    for task in tasks:
        name = task.get("id") if isinstance(task, dict) else None
        if (
            not isinstance(name, str)
            or not name.strip()
            or name in (".", "..")
            or any(char in name for char in ("/", "\\", "\0"))
            or task.get("path") != name
            or not _is_sha256(task.get("task_checksum"))
            or name in names
        ):
            raise ValueError("Invalid or duplicate Terminal-Bench manifest task")
        names.add(name)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _extract_archive(archive: Path, destination: Path, tasks: list[dict]) -> None:
    """Extract only regular files/directories beneath declared task folders."""
    names = {task["path"] for task in tasks}
    seen = set()
    directories = []
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            name = member.name.rstrip("/") if member.isdir() else member.name
            relative = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or "\0" in name
                or relative.is_absolute()
                or ".." in relative.parts
                or relative.as_posix() != name
                or not relative.parts
                or relative.parts[0] not in names
                or not (member.isdir() or member.isfile())
                or name in seen
            ):
                raise ValueError(f"Unsafe Terminal-Bench archive member: {member.name}")
            seen.add(name)
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                directories.append((target, member.mode & 0o777))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(member) as content, target.open("wb") as output:
                    shutil.copyfileobj(content, output)
                target.chmod(member.mode & 0o777)
    # Apply directory permissions last so children remain writable during extraction.
    for directory, mode in reversed(directories):
        directory.chmod(mode)


def _validate_cache(directory: Path, tasks: list[dict]) -> None:
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or {item.name for item in directory.iterdir()}
        != {task["path"] for task in tasks}
        or any(not (directory / task["path"]).is_dir() for task in tasks)
        or any(
            item.is_symlink() or not (item.is_file() or item.is_dir())
            for item in directory.rglob("*")
        )
    ):
        raise ValueError(f"Invalid Terminal-Bench task cache: {directory}")
