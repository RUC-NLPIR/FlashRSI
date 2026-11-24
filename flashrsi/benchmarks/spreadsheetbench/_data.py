"""Build one isolated Harbor task per workbook case, with a separate verifier."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from filelock import FileLock
from huggingface_hub import constants

from flashrsi.benchmarks._archive import _is_safe
from flashrsi.benchmarks._source_file import source_file

REVISION = "49b73a94775fb489063f60ca1865e3a650079a79"
_HASHES = {
    "evaluation.py": "4ae77cee8df01d1f34684fceab972810d696886533d33be2e89373de6b4d3de3",
    "open_spreadsheet.py": "8eafeb70aee06eaefc995ddc0b10747a713792ce15a122cdcd406d90b30ef9b8",
}
_DOCKERFILE = """FROM python:3.12-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-calc fonts-liberation && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir openpyxl==3.1.5 numpy==1.26.4 tqdm==4.67.1
WORKDIR /app
"""


@lru_cache(maxsize=1)
def evaluator_files():
    return {
        name: source_file(
            f"https://raw.githubusercontent.com/RUCKBReasoning/SpreadsheetBench/{REVISION}/evaluation/{name}",
            digest,
        ).read_bytes()
        for name, digest in _HASHES.items()
    }


def materialize(row, index, inputs, answers):
    from harbor.models.task.task import Task as HarborTask

    input_path, answer_path = row["input_files"][index], row["answer_files"][index]
    if not _is_safe(input_path) or not _is_safe(answer_path):
        raise ValueError("Unsafe SpreadsheetBench workbook path")
    input_name = PurePosixPath(input_path).name
    output_name = f"{index + 1}_{row['id']}_output.xlsx"
    package = Path(__file__).parent
    native = evaluator_files()
    files = {
        "instruction.md": (
            row["instruction"] + "\n\nSpreadsheetBench task environment:\n"
            f"Input workbook: /app/{input_name}. Use the native shell tool and Python /usr/local/bin/python.\n"
            f"Save the completed workbook to /logs/artifacts/{output_name}.\n"
            "The host evaluates this output after the session ends.\n"
        ).encode(),
        "task.toml": (
            'version = "1.0"\n[agent]\ntimeout_sec = 1800\n'
            '[verifier]\ntimeout_sec = 600\nenvironment_mode = "separate"\n'
            "[environment]\nbuild_timeout_sec = 1800\ncpus = 2\nmemory_mb = 4096\n"
        ).encode(),
        "environment/Dockerfile": (
            _DOCKERFILE + "COPY inputs/ /app/\nRUN mkdir -p /logs/artifacts\n"
        ).encode(),
        "environment/inputs/" + input_name: inputs.read(input_path),
        "tests/Dockerfile": (_DOCKERFILE + "COPY . /tests/\n").encode(),
        "tests/test.sh": b"#!/bin/bash\nset -euo pipefail\n/usr/local/bin/python /tests/_verify.py\n",
        "tests/_verify.py": (package / "_verify.py").read_bytes(),
        "tests/evaluation.py": native["evaluation.py"],
        "tests/open_spreadsheet.py": native["open_spreadsheet.py"],
        "tests/golden.xlsx": answers.read(answer_path),
        "tests/record.json": json.dumps(
            {
                "instruction_type": row["instruction_type"],
                "answer_position": row["answer_position"],
                "output_name": output_name,
            }
        ).encode(),
    }
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(content).digest())
    cache = Path(constants.HF_HOME) / "flashrsi/spreadsheetbench" / digest.hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f"{row['id']}-{index + 1}"
    with FileLock(str(cache / ".lock")):
        checksum_file = cache / "checksum.txt"
        if not destination.exists():
            with TemporaryDirectory(dir=cache) as temporary:
                root = Path(temporary) / destination.name
                for name, content in files.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                checksum = HarborTask(root).checksum
                root.rename(destination)
                checksum_file.write_text(checksum, encoding="utf-8")
        if not checksum_file.is_file() or HarborTask(
            destination
        ).checksum != checksum_file.read_text(encoding="utf-8"):
            raise ValueError("SpreadsheetBench task cache changed; use a fresh cache")
    return destination
