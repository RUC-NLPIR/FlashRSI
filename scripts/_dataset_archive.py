"""Deterministic tar.gz packaging shared by the native dataset preparers.

Archives contain only directories and regular files. Timestamps and owner
identifiers are normalized so repeated preparation of unchanged sources
produces identical bytes; file contents and permission bits are preserved.
"""

from __future__ import annotations

import gzip
import hashlib
import stat
import tarfile
from pathlib import Path


def _entries(directory: Path) -> list[Path]:
    """Validate before reading: archives contain directories and regular files."""
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ValueError(f"task source must be a directory, not a link: {directory}")
    entries = [directory, *sorted(directory.rglob("*"))]
    for path in entries:
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(f"symlinks and special files are unsupported: {path}")
    return entries


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_archive(path: Path, tasks: list[tuple[str, Path, list[Path]]]) -> None:
    with path.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as zipped:
            with tarfile.open(
                fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT
            ) as tar:
                for name, directory, entries in tasks:
                    for entry in entries:
                        relative = entry.relative_to(directory)
                        archive_path = (
                            name
                            if relative == Path(".")
                            else f"{name}/{relative.as_posix()}"
                        )
                        info = tarfile.TarInfo(archive_path)
                        metadata = entry.lstat()
                        info.mode = stat.S_IMODE(metadata.st_mode) & 0o777
                        info.mtime = info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        if stat.S_ISDIR(metadata.st_mode):
                            info.type = tarfile.DIRTYPE
                            tar.addfile(info)
                        elif stat.S_ISREG(metadata.st_mode):
                            info.size = metadata.st_size
                            with entry.open("rb") as source:
                                tar.addfile(info, source)
                        else:
                            raise ValueError(f"task source changed file type: {entry}")
