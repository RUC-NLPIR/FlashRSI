"""Render workbook rows as Harbor tasks; upstream evaluator bytes stay unchanged."""

import hashlib
import json
import os
import re
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from filelock import FileLock
from huggingface_hub import constants, hf_hub_download

from flashrsi.benchmarks._git import _download_git

_SOURCE = "KAKA22/SpreadsheetBench-v2"
_REVISION = "5a2215ed4121945ab09d8723df2995602090b042"
_ARCHIVE = "spreadsheetbench-v2-09-10.zip"
_UPSTREAM = "https://github.com/RUCKBReasoning/SpreadsheetBench-2.git"
_UPSTREAM_REVISION = "a7bdc2d358e052d35a94768e1f487c0d9e9c0011"
_CATEGORIES = ("Debugging", "Financial_Model", "Template")


def _prepare_tasks(category, data_path):
    upstream = _download_git(_UPSTREAM, _UPSTREAM_REVISION, ["evaluation", "SWE-agent"])
    native = {
        name: (upstream / "evaluation" / name).read_bytes()
        for name in ("evaluation.py", "open_spreadsheet.py")
    }
    dockerfile = (upstream / "SWE-agent/spreadsheet.Dockerfile").read_text(
        encoding="utf-8"
    )
    categories = _CATEGORIES if category == "all" else (category,)
    root = None
    if data_path is not None:
        if not isinstance(data_path, (str, Path)) or not str(data_path).strip():
            raise ValueError(
                "SpreadsheetBench2 data_path must be a native dataset directory"
            )
        root = Path(data_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"SpreadsheetBench2 directory does not exist: {root}")
    directories = []
    with ExitStack() as stack:
        archive = None
        if root is None:
            archive = stack.enter_context(
                ZipFile(
                    hf_hub_download(
                        _SOURCE,
                        _ARCHIVE,
                        repo_type="dataset",
                        revision=_REVISION,
                    )
                )
            )

        def read(category, relative):
            path = PurePosixPath(relative)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in relative
                or ":" in relative
            ):
                raise ValueError(f"Invalid SpreadsheetBench2 relative path: {relative}")
            if archive is not None:
                return archive.read(f"spreadsheetbench-v2/{category}/{relative}")
            file = (root / category / relative).resolve()
            if not file.is_relative_to(root):
                raise ValueError(
                    "SpreadsheetBench2 data path escapes dataset directory"
                )
            return file.read_bytes()

        for selected in categories:
            rows = json.loads(read(selected, "dataset.json"))
            for row in rows:
                if not isinstance(row, dict) or any(
                    not isinstance(row.get(key), str) or not row[key].strip()
                    for key in (
                        "id",
                        "instruction",
                        "spreadsheet_path",
                        "golden_response_path",
                        "answer_position",
                    )
                ):
                    raise ValueError(
                        "SpreadsheetBench2 row requires native nonempty string fields"
                    )
                if not re.fullmatch(r"[A-Za-z0-9_-]+", row["id"]):
                    raise ValueError(
                        "SpreadsheetBench2 id must use letters, digits, underscores or hyphens"
                    )
                directories.append(
                    _materialize(
                        selected,
                        row,
                        read(selected, row["spreadsheet_path"]),
                        read(selected, row["golden_response_path"]),
                        native,
                        dockerfile,
                    )
                )
    return directories, (
        {"source": "local", "revision": "local", "data_path": str(root)} if root else {}
    )


def _materialize(category, row, workbook, golden, native, dockerfile):
    from harbor.models.task.task import Task as HarborTask

    package = Path(__file__).parent
    recalculate = (package / "_recalculate.py").read_bytes()
    # Preserve the original filename: the official Debugging grader selects
    # Color / Embedded comparison modes from spreadsheet_path.
    private_input = "original/" + PurePosixPath(row["spreadsheet_path"]).name
    record = {
        "category": category,
        "row": {
            **row,
            "spreadsheet_path": private_input,
            "golden_response_path": "golden.xlsx",
        },
    }
    files = {
        "instruction.md": (
            row["instruction"] + "\n\nSpreadsheetBench2 task environment:\n"
            "Use your native shell tool to work with files in /app.\n"
            "The task's Python interpreter is /usr/local/bin/python; "
            "it is separate from the harness Python environment.\n"
            "Input workbook: /app/input.xlsx (read-only).\n"
            f"Save the completed workbook to /logs/artifacts/{row['id']}_output.xlsx.\n"
            "The host evaluates that output workbook after the session ends.\n"
        ).encode(),
        "task.toml": (
            'version = "1.0"\n[metadata]\n'
            f'category = "{category}"\n'
            "[agent]\ntimeout_sec = 1800\n"
            '[verifier]\ntimeout_sec = 600\nenvironment_mode = "separate"\n'
            "[environment]\nbuild_timeout_sec = 1800\ncpus = 2\nmemory_mb = 4096\n"
        ).encode(),
        "environment/Dockerfile": (
            dockerfile + "\n"
            "RUN pip install tqdm\n"
            "COPY open_spreadsheet.py _recalculate.py /opt/spreadsheetbench2/\n"
            "COPY input.xlsx /app/input.xlsx\n"
            "RUN /usr/local/bin/python /opt/spreadsheetbench2/_recalculate.py /app/input.xlsx\n"
            "RUN mkdir -p /logs/artifacts && chmod 444 /app/input.xlsx\n"
            "WORKDIR /app\n"
        ).encode(),
        "environment/input.xlsx": workbook,
        "environment/open_spreadsheet.py": native["open_spreadsheet.py"],
        "environment/_recalculate.py": recalculate,
        # Harbor builds a separate verifier from tests/, not environment/.
        # Install the same native tools there; private grading files belong
        # only to that container, never in the agent's image.
        # Separate mode skips verifier test upload: this private image must
        # already contain /tests. Its context is never used for the agent.
        "tests/Dockerfile": (
            dockerfile + "\nRUN pip install tqdm\nCOPY . /tests/\n"
        ).encode(),
        "tests/test.sh": b"#!/bin/bash\nset -euo pipefail\n/usr/local/bin/python /tests/_verify.py\n",
        "tests/_verify.py": (package / "_verify.py").read_bytes(),
        "tests/_recalculate.py": recalculate,
        "tests/evaluation.py": native["evaluation.py"],
        "tests/open_spreadsheet.py": native["open_spreadsheet.py"],
        "tests/record.json": json.dumps(record, ensure_ascii=False).encode(),
        "tests/" + private_input: workbook,
        "tests/golden.xlsx": golden,
    }
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(content).digest())
    fingerprint = digest.hexdigest()
    cache = (
        Path(constants.HF_HOME).resolve() / "flashrsi/spreadsheetbench2" / fingerprint
    )
    if os.name == "nt" and not str(cache).startswith("\\\\?\\"):
        cache = Path("\\\\?\\" + str(cache))
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f"{category.lower().replace('_', '-')}-{row['id']}"
    with FileLock(str(cache / ".lock")):
        checksum_file = cache / "checksum.txt"
        if not destination.exists():
            with TemporaryDirectory(dir=cache, prefix=".prepare-") as temp:
                task_dir = Path(temp) / destination.name
                for name, content in files.items():
                    path = task_dir / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                checksum = HarborTask(task_dir).checksum
                task_dir.rename(destination)
                checksum_file.write_text(checksum, encoding="utf-8")
        if not checksum_file.is_file() or HarborTask(
            destination
        ).checksum != checksum_file.read_text(encoding="utf-8"):
            raise ValueError(
                "SpreadsheetBench2 generated task cache changed; use a fresh cache"
            )
    return destination
