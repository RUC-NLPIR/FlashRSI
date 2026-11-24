"""Cache small, immutable upstream evaluator files with a content check."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from filelock import FileLock
from huggingface_hub import constants


def source_file(url, sha256):
    root = Path(constants.HF_HOME) / "flashrsi/evaluators" / sha256
    root.mkdir(parents=True, exist_ok=True)
    path = root / url.rsplit("/", 1)[-1]
    with FileLock(str(root / ".lock")):
        if not path.exists():
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            content = response.content
            if hashlib.sha256(content).hexdigest() != sha256:
                raise ValueError("Upstream evaluator SHA256 mismatch")
            with TemporaryDirectory(dir=root) as temporary:
                pending = Path(temporary) / path.name
                pending.write_bytes(content)
                pending.replace(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            raise ValueError("Cached evaluator changed; use a fresh cache")
    return path
