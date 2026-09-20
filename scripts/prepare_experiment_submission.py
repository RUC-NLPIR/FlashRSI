"""Package a finished run for a collaborator's Git commit; no model calls."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flashrsi._records import _secrets  # noqa: E402

_SUMMARIES = {
    "end-summary.json",
    "end-summary.md",
    "report.json",
    "report.md",
    "summary.json",
}
_CONFIGS = {"config.yaml", "plan.json", "data-manifest.json"}
_TRANSIENT = {"working", "__pycache__", ".git"}


def _private_values():
    values = dict(os.environ)
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    return [value.encode() for value in _secrets(values) if len(value) >= 8]


def _check_private(data, secrets):
    if any(secret in data for secret in secrets) or re.search(
        rb"sk-[A-Za-z0-9_-]{24,}", data
    ):
        raise ValueError(
            "Potential credential in log content; inspect locally before packaging"
        )
    # Snapshots encode component contents; inspect those without altering hashes.
    try:
        record = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return
    if isinstance(record, dict) and isinstance(record.get("files"), dict):
        import base64

        for row in record["files"].values():
            if isinstance(row, dict) and isinstance(row.get("content"), str):
                try:
                    decoded = base64.b64decode(row["content"], validate=True)
                except ValueError:
                    continue
                if any(secret in decoded for secret in secrets) or re.search(
                    rb"sk-[A-Za-z0-9_-]{24,}", decoded
                ):
                    raise ValueError("Potential credential in snapshot content")


def _git_version():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return {
        "packaging_commit": result.stdout.strip() if result.returncode == 0 else None,
        "packaging_worktree_dirty": bool(dirty.stdout)
        if dirty.returncode == 0
        else None,
        "note": "Packaging version only. Execution versions/configurations remain in the saved run; a dirty tree is not reproducible from this commit alone.",
    }


def prepare(source, destination, run_id, contributor, *, secrets=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ValueError("Require an existing run directory and a simple unique run ID")
    if destination.is_relative_to(source):
        raise ValueError("Submission output must be outside the source run")
    target = destination / run_id
    if target.exists():
        raise FileExistsError(f"Submission already exists: {target}")
    outcomes = [source / "result.json", *source.glob("*/result.json")]
    outcomes += [source / "error.json", *source.glob("*/error.json")]
    if not any(p.exists() for p in outcomes):
        raise ValueError(
            "No saved result/error found; supply one completed run or SearchQA profile directory"
        )
    for path in (source / "status.json", *source.glob("*/status.json")):
        if path.exists() and json.loads(path.read_text()).get("status") == "running":
            raise ValueError("Run is still marked running; finish it before packaging")
    secrets = _private_values() if secrets is None else secrets
    destination.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=destination))
    count = size = 0
    excluded = []
    try:
        archive = temporary / "logs.tar.gz"
        with tarfile.open(archive, "w:gz", compresslevel=1) as bundle:
            for path in sorted(source.rglob("*")):
                relative = path.relative_to(source)
                if path.is_symlink():
                    raise ValueError("Symlinks are not supported in a submission")
                if not path.is_file():
                    continue
                if (
                    _TRANSIENT.intersection(relative.parts)
                    or path.name.startswith(".env")
                    or path.suffix in {".lock", ".tmp", ".pyc"}
                ):
                    excluded.append(relative.as_posix())
                    continue
                before = path.stat()
                data = path.read_bytes()
                _check_private(data, secrets)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ValueError(
                        "Run changed while packaging; retry after it stops"
                    )
                info = tarfile.TarInfo("run/" + relative.as_posix())
                info.size = len(data)
                info.mode = 0o644
                bundle.addfile(info, io.BytesIO(data))
                count += 1
                size += len(data)
                # Small review files only; attempts and caches stay in the complete archive.
                if len(relative.parts) <= 2 and path.name in _SUMMARIES | _CONFIGS | {
                    "result.json"
                }:
                    folder = "configs" if path.name in _CONFIGS else "summaries"
                    output = temporary / folder / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(data)
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "contributor": contributor,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "framework": _git_version(),
            "logs": {
                "path": "logs.tar.gz",
                "sha256": digest,
                "bytes": archive.stat().st_size,
                "uncompressed_bytes": size,
                "files": count,
            },
            "excluded_transient_files": excluded,
            "privacy": "Known local credentials and sk-token patterns checked, including snapshot contents. Original paths/endpoints and prompts are preserved; review before public release.",
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        (temporary / "README.md").write_text(
            f"# {run_id}\n\nContributor: {contributor}\n\nSee `summaries/` for scores and usage, `configs/` for saved configuration.\n`logs.tar.gz` contains the complete persistent run evidence (including failures), under `run/`.\nUse Git LFS for the archive. Its SHA256 and excluded transient files are in `manifest.json`.\nOriginal paths in logs are historical references; extraction does not automatically make resume paths portable.\n"
        )
        temporary.rename(target)
        return target
    except BaseException:
        shutil.rmtree(temporary)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--contributor", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "experiments")
    args = parser.parse_args()
    print(prepare(args.run_dir, args.output, args.run_id, args.contributor))


if __name__ == "__main__":
    main()
