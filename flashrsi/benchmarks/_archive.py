"""Download, verify and extract a pinned Hugging Face task archive.

Terminal-Bench and tau3 Banking both publish a tar.gz of native task files
beside a manifest that pins the upstream source and a checksum per task. This
module owns that shared retrieval: it validates the manifest against the
benchmark's pinned upstream, verifies the archive, extracts only regular files
and directories, and publishes the result atomically so concurrent loads share
one cache entry. Each benchmark then checks its own extracted tasks, since a
task is a directory for one and a single JSON file for the other.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from filelock import FileLock
from huggingface_hub import constants, hf_hub_download


def _download_archive(
    source: Mapping[str, Any],
    *,
    schema: str,
    label: str,
    archive: str,
    validate: Callable[[Path, list[dict]], None],
) -> tuple[Path, tuple[Mapping[str, Any], ...]]:
    """Return the extracted task directory and the manifest's task entries.

    ``archive`` is the repository path of the tar.gz; its first path segment
    names the benchmark directory. ``validate`` checks one extracted cache and
    must raise if it does not match the manifest tasks.
    """
    name = PurePosixPath(archive).parts[0]
    download = {
        "repo_id": source["source"],
        "repo_type": "dataset",
        "revision": source["revision"],
    }
    path = Path(hf_hub_download(filename=f"{name}/manifest.json", **download))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _validate_manifest(manifest, source["upstream"], schema, archive, label)
    entry, tasks = manifest["archive"], manifest["tasks"]
    cache = Path(constants.HF_HOME) / "flashrsi" / name
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / entry["sha256"]
    with FileLock(str(destination) + ".lock"):
        if not destination.exists() and not destination.is_symlink():
            path = Path(hf_hub_download(filename=archive, **download))
            with path.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            if checksum != entry["sha256"] or path.stat().st_size != entry["bytes"]:
                raise ValueError(f"{label} archive checksum or size mismatch")
            with TemporaryDirectory(prefix=".extract-", dir=cache) as temporary:
                extracted = Path(temporary) / "extracted"
                extracted.mkdir()
                _extract(path, extracted, tasks, label)
                validate(extracted, tasks)
                extracted.rename(destination)
        validate(destination, tasks)
    return destination, tuple(tasks)


def _validate_manifest(
    manifest: Any, upstream: Mapping[str, Any], schema: str, archive: str, label: str
) -> None:
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != schema
        or manifest.get("source") != upstream
    ):
        raise ValueError(f"{label} manifest does not match the pinned source")
    entry, index, tasks = (
        manifest.get("archive"),
        manifest.get("index"),
        manifest.get("tasks"),
    )
    if (
        not isinstance(entry, dict)
        or entry.get("file") != archive
        or not _is_sha256(entry.get("sha256"))
        or type(entry.get("bytes")) is not int
        or entry["bytes"] <= 0
        or not isinstance(index, dict)
        or not _is_sha256(index.get("sha256"))
        or not isinstance(tasks, list)
        or not tasks
        or type(index.get("count")) is not int
        or index["count"] != len(tasks)
    ):
        raise ValueError(f"Invalid {label} archive or index manifest")
    names = set()
    for task in tasks:
        name = task.get("id") if isinstance(task, dict) else None
        # The id identifies the task and may also name its directory, so it is
        # held to the same path rules as the declared path.
        if (
            not _is_safe(name)
            or "/" in name
            or not name.strip()
            or not _is_sha256(task.get("task_checksum"))
            or not _is_safe(task.get("path"))
            or name in names
        ):
            raise ValueError(f"Invalid or duplicate {label} manifest task")
        names.add(name)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _is_safe(value: Any) -> bool:
    """Reject any path that could escape the directory it is joined to."""
    if (
        not isinstance(value, str)
        or not value
        or any(c in value for c in ("\\", "\0", ":"))
    ):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and not {"..", "."} & set(path.parts)
        and path.as_posix() == value
    )


def _extract(archive: Path, destination: Path, tasks: list[dict], label: str) -> None:
    """Extract only regular files and directories beneath the manifest's tasks."""
    roots = {PurePosixPath(task["path"]).parts[0] for task in tasks}
    seen = set()
    directories = []
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            name = member.name.rstrip("/") if member.isdir() else member.name
            if (
                not _is_safe(name)
                or PurePosixPath(name).parts[0] not in roots
                or not (member.isdir() or member.isfile())
                or name in seen
            ):
                raise ValueError(f"Unsafe {label} archive member: {member.name}")
            seen.add(name)
            target = destination.joinpath(*PurePosixPath(name).parts)
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


def _has_only_plain_files(directory: Path) -> bool:
    return (
        not directory.is_symlink()
        and directory.is_dir()
        and all(
            not item.is_symlink() and (item.is_file() or item.is_dir())
            for item in directory.rglob("*")
        )
    )
