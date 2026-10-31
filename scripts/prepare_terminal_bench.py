"""Prepare the pinned Terminal-Bench tasks for the FlashRSI dataset repository.

Run from FlashRSI-Lite with Python 3.12 or newer:
    uv run --extra all --extra harbor python scripts/prepare_terminal_bench.py

Use --source-dir for an already downloaded checkout of the pinned source. This
script only downloads upstream data and writes local files; it never uploads.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import warnings
from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._dataset_archive import _entries, _sha256, _write_archive  # noqa: E402

DATASET = "terminal-bench@2.0"
GIT_URL = "https://github.com/laude-institute/terminal-bench-2.git"
REVISION = "69671fbaac6d67a7ef0dfec016cc38a64ef7a77c"
REGISTRY = (
    "https://raw.githubusercontent.com/harbor-framework/harbor/v0.23.0/registry.json"
)
# The pinned task revision predates the upstream LICENSE file, so the license is
# recorded from a later upstream revision that is identified explicitly.
LICENSE_SOURCE = {
    "repository": "https://github.com/harbor-framework/terminal-bench-2",
    "revision": "2fd12b88aafdd04a52c298e3940bcb189f9766d6",
    "license_url": (
        "https://raw.githubusercontent.com/harbor-framework/terminal-bench-2/"
        "2fd12b88aafdd04a52c298e3940bcb189f9766d6/LICENSE"
    ),
    "note": (
        "LICENSE from current upstream; the pinned task revision predates this file."
    ),
}
INDEX_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("question", pa.string()),
        ("task_path", pa.string()),
        ("task_checksum", pa.string()),
        ("category", pa.string()),
        ("difficulty", pa.string()),
    ]
)


def prepare(
    output: Path, task_dirs: Iterable[Path], license_file: Path | None = None
) -> dict:
    """Package explicit native task directories, preserving all task resources.

    The caller supplies directories from the pinned source, including when using
    a local checkout. Task names become single top-level archive directories.
    """
    from harbor.models.task.task import Task

    rows = []
    tasks = []
    seen = set()
    for directory in task_dirs:
        directory = Path(directory).expanduser().absolute()
        entries = _entries(directory)
        native = Task(directory)
        name = native.name
        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or name in seen
        ):
            raise ValueError(f"invalid or duplicate native task name: {name!r}")
        if native.has_steps or native.config.environment.os != "linux":
            raise ValueError("TerminalBench supports single-step Linux tasks only")
        seen.add(name)
        with warnings.catch_warnings(action="ignore", category=DeprecationWarning):
            checksum = native.checksum
        rows.append(
            {
                "id": name,
                "question": native.instruction,
                "task_path": name,
                "task_checksum": checksum,
                "category": native.config.metadata.get("category"),
                "difficulty": native.config.metadata.get("difficulty"),
            }
        )
        tasks.append((name, directory, entries))
    if not tasks:
        raise ValueError("no native task directories were supplied")
    rows.sort(key=lambda row: row["id"])
    tasks.sort(key=lambda task: task[0])

    destination = Path(output) / "terminal_bench"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "tasks.tar.gz"
    index = destination / "tasks.parquet"
    _write_archive(archive, tasks)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=INDEX_SCHEMA), index, compression="zstd"
    )
    manifest = {
        "schema": "flashrsi.terminal_bench.v1",
        "source": {"dataset": DATASET, "git_url": GIT_URL, "revision": REVISION},
        "archive": {
            "file": "terminal_bench/tasks.tar.gz",
            "sha256": _sha256(archive),
            "bytes": archive.stat().st_size,
        },
        "index": {
            "file": "terminal_bench/tasks.parquet",
            "sha256": _sha256(index),
            "count": len(rows),
        },
        "tasks": [
            {
                "id": row["id"],
                "path": row["task_path"],
                "task_checksum": row["task_checksum"],
            }
            for row in rows
        ],
        "notes": {
            "grading": (
                "Harbor runs the native tests against the environment after the "
                "agent finishes. The index is a browsing aid, not an answer key; "
                "reference solutions stay inside the archive."
            ),
            "runtime": (
                "The archive holds task definitions and bundled resources, not "
                "Docker image layers. Execution still needs Docker, task images "
                "and any network access the tasks require."
            ),
        },
    }
    if license_file is not None:
        (destination / "UPSTREAM_LICENSE").write_bytes(license_file.read_bytes())
        (destination / "license-source.json").write_text(
            json.dumps(LICENSE_SOURCE, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest["license"] = {
            "file": "terminal_bench/UPSTREAM_LICENSE",
            "sha256": _sha256(destination / "UPSTREAM_LICENSE"),
            "spdx": "Apache-2.0",
            **LICENSE_SOURCE,
        }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    card = Path(__file__).with_name("terminal_bench_dataset_card.md")
    (destination / "README.md").write_text(
        card.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return manifest


def _download_tasks() -> list[Path]:
    """Download independently of the benchmark's Hugging Face loading code."""
    from harbor.models.task.id import GitTaskId
    from harbor.registry.client.json import JsonRegistryClient

    async def download() -> list[Path]:
        client = JsonRegistryClient(url=REGISTRY)
        metadata = await client.get_dataset_metadata(DATASET)
        if not metadata.task_ids or any(
            not isinstance(task, GitTaskId)
            or task.git_url != GIT_URL
            or task.git_commit_id != REVISION
            for task in metadata.task_ids
        ):
            raise ValueError(
                "Terminal-Bench registry does not match the pinned revision"
            )
        downloaded = await client.download_dataset(DATASET, export=False)
        return [item.downloaded_path for item in downloaded]

    return asyncio.run(download())


def _download_license(directory: Path) -> Path:
    """Fetch the upstream LICENSE from the separately identified revision."""
    from urllib.request import urlopen

    path = directory / "UPSTREAM_LICENSE"
    with urlopen(LICENSE_SOURCE["license_url"]) as response:  # noqa: S310
        path.write_bytes(response.read())
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/terminal_bench/publish")
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Directory containing native tasks from the pinned revision",
    )
    parser.add_argument(
        "--license-file",
        type=Path,
        help="Upstream LICENSE to record; downloaded when omitted",
    )
    args = parser.parse_args()
    if args.source_dir is None:
        task_dirs = _download_tasks()
    else:
        task_dirs = sorted(
            path
            for path in args.source_dir.expanduser().iterdir()
            if (path / "task.toml").is_file()
        )
    with tempfile.TemporaryDirectory(prefix="terminal-bench-") as temporary:
        license_file = args.license_file or _download_license(Path(temporary))
        manifest = prepare(args.output, task_dirs, license_file)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "archive": manifest["archive"],
                "count": manifest["index"]["count"],
            }
        )
    )


if __name__ == "__main__":
    main()
