"""Reject corrupted source baselines before updating their provenance records."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/extract_codex_core.py"
_SPEC = importlib.util.spec_from_file_location("codex_core_extraction", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
extraction = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(extraction)


@pytest.fixture
def baseline(tmp_path):
    source = tmp_path / "core/src/lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text("pub const ORIGINAL: bool = true;\n")
    source.chmod(0o644)
    lock = tmp_path / "Cargo.lock"
    lock.write_text("version = 4\n")
    lock.chmod(0o644)
    patch = tmp_path / extraction.PATCH_NAME
    patch.write_text("recorded workspace diff\n")
    metadata = {
        "commit": extraction.UPSTREAM_COMMIT,
        "tag": extraction.UPSTREAM_TAG,
        "repository": extraction.UPSTREAM_REPOSITORY,
        "version": "0.147.0",
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "files": {
            path.relative_to(tmp_path).as_posix(): {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "executable": False,
            }
            for path in (source, lock)
        },
    }
    (tmp_path / extraction.MANIFEST_NAME).write_text(json.dumps(metadata))
    extraction.verify(tmp_path)
    return tmp_path


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable permission bits")
def test_verify_rejects_executable_mode_change(baseline):
    (baseline / "core/src/lib.rs").chmod(0o755)
    with pytest.raises(ValueError, match="core/src/lib.rs"):
        extraction.verify(baseline)


def test_verify_rejects_modified_build_patch(baseline):
    (baseline / extraction.PATCH_NAME).write_text("different build changes\n")
    with pytest.raises(ValueError, match="upstream-build.patch"):
        extraction.verify(baseline)


def test_verify_rejects_different_upstream_revision(baseline):
    path = baseline / extraction.MANIFEST_NAME
    metadata = json.loads(path.read_text())
    metadata["commit"] = "0" * 40
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="pinned upstream release"):
        extraction.verify(baseline)


@pytest.mark.parametrize("corruption", ["source", "patch", "provenance"])
def test_rejected_record_keeps_provenance_and_patch_unchanged(baseline, corruption):
    metadata_path = baseline / extraction.MANIFEST_NAME
    patch_path = baseline / extraction.PATCH_NAME
    if corruption == "source":
        (baseline / "core/src/lib.rs").write_text("pub const ORIGINAL: bool = false;\n")
    elif corruption == "patch":
        patch_path.write_text("unrecorded patch change\n")
    else:
        metadata = json.loads(metadata_path.read_text())
        metadata["tag"] = "rust-v9.9.9"
        metadata_path.write_text(json.dumps(metadata))
    # Cargo is allowed to change this file, but a source/provenance error must
    # stop the operation before either persistent record is rewritten.
    (baseline / "Cargo.lock").write_text("version = 4\n# derived build lock\n")
    before = metadata_path.read_bytes(), patch_path.read_bytes()
    with pytest.raises(ValueError):
        extraction.record_lock(
            baseline / "not-needed-before-validation.tar.gz", baseline
        )
    assert (metadata_path.read_bytes(), patch_path.read_bytes()) == before
