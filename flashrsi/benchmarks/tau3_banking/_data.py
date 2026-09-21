"""Download and materialize the pinned tau3 Banking domain archive."""

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

_MANIFEST = "tau3_banking/manifest.json"
_ARCHIVE = "tau3_banking/domain.tar.gz"
_INDEX = "tau3_banking/tasks.parquet"
_ROOT = "tau3_banking"


def _download_domain(
    source: Mapping[str, Any],
) -> tuple[Path, tuple[Mapping[str, Any], ...]]:
    """Reuse HF authentication and cache; publish the extracted domain atomically."""
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
    cache = Path(constants.HF_HOME) / "flashrsi" / "tau3_banking"
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
                raise ValueError("tau3 Banking archive checksum or size mismatch")
            with TemporaryDirectory(prefix=".extract-", dir=cache) as temporary:
                extracted = Path(temporary) / "domain"
                extracted.mkdir()
                _extract_archive(archive_path, extracted)
                _validate_cache(extracted / _ROOT, tasks)
                (extracted / _ROOT).rename(destination)
        _validate_cache(destination, tasks)
    index = Path(hf_hub_download(filename=_INDEX, **download))
    return destination, _read_index(index, manifest)


def _read_index(
    path: Path, manifest: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    import pyarrow.parquet as pq

    with path.open("rb") as stream:
        if (
            hashlib.file_digest(stream, "sha256").hexdigest()
            != manifest["index"]["sha256"]
        ):
            raise ValueError("tau3 Banking index checksum mismatch")
    rows = pq.read_table(path).to_pylist()
    expected = [task["id"] for task in manifest["tasks"]]
    if [row.get("id") for row in rows] != expected:
        raise ValueError("tau3 Banking index does not match its manifest tasks")
    return tuple(rows)


def _validate_manifest(manifest: Any, upstream: Mapping[str, Any]) -> None:
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "flashrsi.tau3_banking.v1"
        or manifest.get("source") != upstream
    ):
        raise ValueError("tau3 Banking manifest does not match the pinned source")
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
        raise ValueError("Invalid tau3 Banking archive or index manifest")
    names = set()
    for task in tasks:
        name = task.get("id") if isinstance(task, dict) else None
        if (
            not isinstance(name, str)
            or not name.strip()
            or not _is_sha256(task.get("task_checksum"))
            or task.get("path") != f"tasks/{name}.json"
            or name in names
        ):
            raise ValueError("Invalid or duplicate tau3 Banking manifest task")
        names.add(name)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _extract_archive(archive: Path, destination: Path) -> None:
    """Extract only regular files and directories beneath the domain root."""
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
                or relative.parts[0] != _ROOT
                or not (member.isdir() or member.isfile())
                or name in seen
            ):
                raise ValueError(f"Unsafe tau3 Banking archive member: {member.name}")
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
        or not (directory / "db.json").is_file()
        or any(
            item.is_symlink() or not (item.is_file() or item.is_dir())
            for item in directory.rglob("*")
        )
    ):
        raise ValueError(f"Invalid tau3 Banking domain cache: {directory}")
    for task in tasks:
        path = directory / task["path"]
        if not path.is_file():
            raise ValueError(f"tau3 Banking cache is missing {task['path']}")
        with path.open("rb") as stream:
            if (
                hashlib.file_digest(stream, "sha256").hexdigest()
                != task["task_checksum"]
            ):
                raise ValueError(f"tau3 Banking task changed on disk: {task['id']}")
