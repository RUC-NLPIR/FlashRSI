"""Materialize original JobBench inputs using its pinned, unmodified renderer."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from filelock import FileLock

from flashrsi._records import _redact, _secrets
from flashrsi.benchmarks._git import _download_git

_GIT_URL = "https://github.com/Job-Bench/job-bench-eval.git"
_GIT_REVISION = "660b33a86ed032559df0b2fdc1ad38cf7ceb83f3"


def _prepare_tasks(source, data_path):
    if data_path is None and (
        not isinstance(source["revision"], str)
        or re.fullmatch(r"[0-9a-f]{40}", source["revision"]) is None
    ):
        raise ValueError("JobBench dataset.revision must be an immutable HF commit")
    upstream = _download_git(_GIT_URL, _GIT_REVISION, ["."])
    # Generated trees are upstream-managed and Git-ignored. Its own manifest
    # validation rejects modified cached task files instead of overwriting them.
    with FileLock(str(upstream / "harbor/.setup.lock")):
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).with_name("_prepare.py")),
                str(upstream),
                source["source"],
                source["revision"],
                str(data_path) if data_path is not None else "",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=1800,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        if result.returncode:
            error = _redact(result.stderr, _secrets(os.environ))
            raise ValueError(f"JobBench native preparation failed: {error}")
        prepared = json.loads(result.stdout)
    return Path(prepared["tasks_path"]), {
        "source": "local" if data_path is not None else source["source"],
        "revision": "local" if data_path is not None else source["revision"],
        "evaluator_source": _GIT_URL,
        "evaluator_revision": _GIT_REVISION,
        "generation_fingerprint": prepared["fingerprint"],
        **({"data_path": str(data_path)} if data_path is not None else {}),
    }
