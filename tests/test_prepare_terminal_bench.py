import hashlib
import json
import os
import stat
import tarfile
import warnings
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from scripts import prepare_terminal_bench as module

harbor = pytest.importorskip("harbor.models.task.task")


def _task(root: Path, name: str, *, metadata: bool = True) -> Path:
    directory = root / name
    (directory / "environment" / "empty").mkdir(parents=True)
    (directory / "tests").mkdir()
    (directory / "solution").mkdir()
    (directory / "task.toml").write_text(
        'version = "1.0"\n'
        + ('[metadata]\ncategory = "coding"\ndifficulty = "easy"\n' if metadata else "")
    )
    (directory / "instruction.md").write_text(
        "<!-- benchmark canary: do not train on this -->\n\nCreate answer.txt.\n"
    )
    (directory / "environment" / "Dockerfile").write_text("FROM scratch\n")
    (directory / "environment" / "bytes.bin").write_bytes(bytes(range(256)))
    (directory / "tests" / "test.sh").write_text("#!/bin/sh\necho 1\n")
    (directory / "tests" / "test.sh").chmod(0o751)
    (directory / "solution" / "solve.sh").write_text("SECRET_ORACLE\n")
    (directory / "solution" / "solve.sh").chmod(0o755)
    return directory


def test_package_round_trip_index_and_manifest(tmp_path):
    one = _task(tmp_path / "source", "one")
    two = _task(tmp_path / "source", "two", metadata=False)
    output = tmp_path / "publish"
    output.mkdir()
    (output / "README.md").write_text("existing repository card")
    (output / "searchqa").mkdir()
    (output / "searchqa" / "train.parquet").write_bytes(b"existing benchmark")

    manifest = module.prepare(output, [two, one])

    destination = output / "terminal_bench"
    assert manifest == json.loads((destination / "manifest.json").read_text())
    assert manifest["schema"] == "flashrsi.terminal_bench.v1"
    assert manifest["source"] == {
        "dataset": module.DATASET,
        "git_url": module.GIT_URL,
        "revision": module.REVISION,
    }
    for section in ("archive", "index"):
        file = output / manifest[section]["file"]
        assert (
            manifest[section]["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
        )
    assert manifest["archive"]["bytes"] == (destination / "tasks.tar.gz").stat().st_size
    assert manifest["index"]["count"] == 2
    rows = pq.read_table(destination / "tasks.parquet").to_pylist()
    assert list(rows[0]) == [
        "id",
        "question",
        "task_path",
        "task_checksum",
        "category",
        "difficulty",
    ]
    assert [row["id"] for row in rows] == ["one", "two"]
    assert rows[0]["question"] == "Create answer.txt.\n"
    assert rows[0]["category"] == "coding"
    assert rows[0]["difficulty"] == "easy"
    assert rows[1]["category"] is rows[1]["difficulty"] is None
    assert "SECRET_ORACLE" not in repr(rows)
    assert manifest["tasks"] == [
        {
            "id": row["id"],
            "path": row["task_path"],
            "task_checksum": row["task_checksum"],
        }
        for row in rows
    ]

    restored = tmp_path / "restored"
    with tarfile.open(destination / "tasks.tar.gz") as tar:
        assert all(member.isfile() or member.isdir() for member in tar.getmembers())
        assert all(
            member.mtime == member.uid == member.gid == 0 for member in tar.getmembers()
        )
        tar.extractall(restored, filter="data")
    for source in (one, two):
        for file in source.rglob("*"):
            copy = restored / source.name / file.relative_to(source)
            if file.is_file():
                assert copy.read_bytes() == file.read_bytes()
                assert stat.S_IMODE(copy.stat().st_mode) == stat.S_IMODE(
                    file.stat().st_mode
                )
            else:
                assert copy.is_dir()
        with warnings.catch_warnings(action="ignore", category=DeprecationWarning):
            assert (
                harbor.Task(restored / source.name).checksum
                == harbor.Task(source).checksum
            )
    assert (output / "README.md").read_text() == "existing repository card"
    assert (output / "searchqa" / "train.parquet").read_bytes() == b"existing benchmark"
    assert (destination / "README.md").is_file()


def test_preparation_is_stable_across_order_mtime_and_output_directory(tmp_path):
    one = _task(tmp_path / "source", "one")
    two = _task(tmp_path / "source", "two")
    first, second = tmp_path / "first", tmp_path / "second"
    module.prepare(first, [one, two])
    for directory in (one, two):
        for path in [directory, *directory.rglob("*")]:
            os.utime(path, (1234567890, 1234567890))
    module.prepare(second, [two, one])
    for name in ("tasks.tar.gz", "tasks.parquet", "manifest.json", "README.md"):
        assert (first / "terminal_bench" / name).read_bytes() == (
            second / "terminal_bench" / name
        ).read_bytes()


@pytest.mark.parametrize("kind", ["file_link", "directory_link", "source_link", "fifo"])
def test_prepare_rejects_links_and_special_files(tmp_path, kind):
    directory = _task(tmp_path / "source", "one")
    if kind == "file_link":
        (directory / "link").symlink_to(directory / "instruction.md")
    elif kind == "directory_link":
        (directory / "link").symlink_to(
            directory / "environment", target_is_directory=True
        )
    elif kind == "source_link":
        link = tmp_path / "link"
        link.symlink_to(directory, target_is_directory=True)
        directory = link
    else:
        os.mkfifo(directory / "pipe")
    with pytest.raises(ValueError, match="link|special"):
        module.prepare(tmp_path / "output", [directory])
    assert not (tmp_path / "output").exists()


def test_prepare_rejects_empty_or_duplicate_tasks(tmp_path):
    one = _task(tmp_path / "first", "one")
    duplicate = _task(tmp_path / "second", "one")
    with pytest.raises(ValueError, match="no native task"):
        module.prepare(tmp_path / "empty", [])
    with pytest.raises(ValueError, match="duplicate"):
        module.prepare(tmp_path / "duplicate", [one, duplicate])
