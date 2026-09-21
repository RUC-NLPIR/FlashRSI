"""Prepare the pinned tau3 Banking domain for the FlashRSI dataset repository.

Run from FlashRSI-Lite with:
    uv run python scripts/prepare_tau3_banking.py

Use --source-dir for an already downloaded checkout of the pinned source. This
script only downloads upstream data and writes local files; it never uploads.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._dataset_archive import _entries, _sha256, _write_archive  # noqa: E402

GIT_URL = "https://github.com/sierra-research/tau2-bench.git"
TAG = "v1.0.1"
REVISION = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
DOMAIN = "data/tau2/domains/banking_knowledge"
# The tau2 runtime reads the tasks/ directory, so those files are authoritative.
TASK_DIR = "tasks"
INDEX_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("user_instructions", pa.string()),
        ("reward_basis", pa.list_(pa.string())),
        ("user_tools", pa.list_(pa.string())),
        ("required_documents", pa.list_(pa.string())),
        ("has_initial_state", pa.bool_()),
    ]
)


def _strings(value: object, field: str, task_id: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"task {task_id} has a non-string {field} entry")
    return value


def _index_row(task: dict) -> dict:
    """Describe a task for browsing; evaluation criteria stay archive-only."""
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task file has no id")
    scenario = task.get("user_scenario") or {}
    instruction = scenario.get("instructions") if isinstance(scenario, dict) else None
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError(f"task {task_id} has no user scenario instructions")
    criteria = task.get("evaluation_criteria") or {}
    return {
        "id": task_id,
        "user_instructions": instruction,
        "reward_basis": _strings(criteria.get("reward_basis"), "reward_basis", task_id),
        "user_tools": _strings(task.get("user_tools"), "user_tools", task_id),
        "required_documents": _strings(
            task.get("required_documents"), "required_documents", task_id
        ),
        "has_initial_state": task.get("initial_state") is not None,
    }


def prepare(output: Path, source_dir: Path, license_file: Path | None = None) -> dict:
    """Package the complete domain, plus a browsing index of its task files."""
    source_dir = Path(source_dir).expanduser().absolute()
    task_dir = source_dir / TASK_DIR
    if not task_dir.is_dir():
        raise ValueError(f"source has no {TASK_DIR} directory: {source_dir}")

    rows = []
    files = {}
    for path in sorted(task_dir.glob("task_*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        row = _index_row(task)
        if row["id"] in files:
            raise ValueError(f"duplicate task id: {row['id']}")
        if path.stem != row["id"]:
            raise ValueError(f"task file {path.name} does not match id {row['id']}")
        files[row["id"]] = (f"{TASK_DIR}/{path.name}", _sha256(path))
        rows.append(row)
    if not rows:
        raise ValueError(f"source has no task files: {task_dir}")
    rows.sort(key=lambda row: row["id"])

    destination = output / "tau3_banking"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "domain.tar.gz"
    index = destination / "tasks.parquet"
    _write_archive(archive, [("tau3_banking", source_dir, _entries(source_dir))])
    pq.write_table(
        pa.Table.from_pylist(rows, schema=INDEX_SCHEMA), index, compression="zstd"
    )

    manifest = {
        "schema": "flashrsi.tau3_banking.v1",
        "source": {
            "git_url": GIT_URL,
            "tag": TAG,
            "revision": REVISION,
            "domain": DOMAIN,
        },
        "archive": {
            "file": "tau3_banking/domain.tar.gz",
            "sha256": _sha256(archive),
            "bytes": archive.stat().st_size,
        },
        "index": {
            "file": "tau3_banking/tasks.parquet",
            "sha256": _sha256(index),
            "count": len(rows),
            "source": f"{TASK_DIR}/task_*.json",
        },
        "tasks": [
            {
                "id": row["id"],
                "path": files[row["id"]][0],
                "task_checksum": files[row["id"]][1],
            }
            for row in rows
        ],
        "notes": {
            "authoritative_tasks": (
                "The tau2 runtime loads the tasks/ directory, so the index and "
                "checksums come from those files. The archived tasks.json lists "
                "the same ids but differs for 13 of them, across "
                "required_documents (7), user_scenario (4), evaluation_criteria "
                "(4), description (2) and user_tools (1); it is preserved as an "
                "upstream artifact, not used here."
            ),
            "grading": (
                "Rewards come from the tau2 simulator running this domain, not "
                "from the index. Evaluation criteria stay inside the archive."
            ),
        },
    }
    if license_file is not None:
        (destination / "LICENSE").write_bytes(license_file.read_bytes())
        manifest["license"] = {
            "file": "tau3_banking/LICENSE",
            "sha256": _sha256(destination / "LICENSE"),
            "spdx": "MIT",
            "revision": REVISION,
            "note": "LICENSE copied from the same revision as the domain data.",
        }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    card = Path(__file__).with_name("tau3_banking_dataset_card.md")
    (destination / "README.md").write_text(
        card.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return manifest


def _checkout(directory: Path) -> Path:
    """Fetch only the pinned domain and its license from the locked revision."""

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            args, cwd=directory, check=True, capture_output=True, text=True
        )

    run("git", "init", "--quiet")
    run("git", "remote", "add", "origin", GIT_URL)
    run("git", "fetch", "--quiet", "--depth", "1", "origin", REVISION)
    run("git", "sparse-checkout", "set", "--no-cone", DOMAIN, "LICENSE")
    run("git", "checkout", "--quiet", "FETCH_HEAD")
    head = run("git", "rev-parse", "HEAD").stdout.strip()
    if head != REVISION:
        raise ValueError(f"checkout is not the pinned revision: {head}")
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/tau3_banking/publish")
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        help=f"Existing {DOMAIN} directory from the pinned revision",
    )
    parser.add_argument(
        "--license-file", type=Path, help="Upstream LICENSE to bundle with the domain"
    )
    args = parser.parse_args()
    if args.source_dir is not None:
        manifest = prepare(args.output, args.source_dir, args.license_file)
    else:
        with tempfile.TemporaryDirectory(prefix="tau2-bench-") as temporary:
            checkout = _checkout(Path(temporary))
            manifest = prepare(args.output, checkout / DOMAIN, checkout / "LICENSE")
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
