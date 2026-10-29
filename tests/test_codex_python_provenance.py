"""Reject provenance changes that can otherwise hide drift in vendored data."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_codex_python_port.py"
SPEC = importlib.util.spec_from_file_location("codex_python_provenance", SCRIPT)
provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provenance)
REFERENCE = provenance.DEFAULT_CORE.parent / "runtime"


@pytest.fixture
def candidate(tmp_path):
    core = tmp_path / "core"
    shutil.copytree(
        provenance.DEFAULT_CORE, core, ignore=shutil.ignore_patterns("__pycache__")
    )
    return core


def _manifest(core):
    return json.loads((core / "UPSTREAM.json").read_text())


def _write(core, manifest):
    (core / "UPSTREAM.json").write_text(json.dumps(manifest))


def test_fixed_python_provenance_baseline():
    result = provenance.verify(provenance.DEFAULT_CORE, REFERENCE)
    assert provenance.COMMIT in result
    assert "Semantic equivalence is not established" in result


@pytest.mark.parametrize("field", ["repository", "version", "tag", "commit"])
def test_upstream_identity_is_fixed(candidate, field):
    manifest = _manifest(candidate)
    manifest[field] = "moving-or-unrelated-upstream"
    _write(candidate, manifest)
    with pytest.raises(ValueError, match=f"{field} is not pinned"):
        provenance.verify(candidate, REFERENCE)


@pytest.mark.parametrize(
    "relative",
    ["assets/prompt.md", "tool_assets/deunicode_mapping.txt"],
)
def test_rehashed_copied_asset_still_must_match_upstream(candidate, relative):
    path = candidate / relative
    path.write_bytes(path.read_bytes() + b"CHANGED")
    manifest = _manifest(candidate)
    manifest["assets"][relative]["sha256"] = provenance.sha256(path.read_bytes())
    _write(candidate, manifest)
    with pytest.raises(ValueError, match="copied asset differs from upstream"):
        provenance.verify(candidate, REFERENCE)


def test_rehashed_derived_data_is_reconstructed_from_rust(candidate):
    relative = "resource_assets/skills_prompt.json"
    path = candidate / relative
    data = json.loads(path.read_text())
    data["SKILLS_INTRO_WITH_ALIASES"] = "Different skill instructions"
    path.write_text(json.dumps(data))
    manifest = _manifest(candidate)
    manifest["assets"][relative]["sha256"] = provenance.sha256(path.read_bytes())
    _write(candidate, manifest)
    with pytest.raises(ValueError, match="derived asset differs from upstream"):
        provenance.verify(candidate, REFERENCE)


def test_rehashed_shell_capture_script_must_match_fixed_upstream(candidate):
    relative = "tool_assets/shell_snapshot_scripts.json"
    path = candidate / relative
    scripts = json.loads(path.read_text())
    scripts["bash"] += "\nexport PWD=/different\n"
    path.write_text(json.dumps(scripts))
    manifest = _manifest(candidate)
    manifest["assets"][relative]["sha256"] = provenance.sha256(path.read_bytes())
    _write(candidate, manifest)
    with pytest.raises(ValueError, match="derived asset differs from upstream"):
        provenance.verify(candidate, REFERENCE)


def test_every_python_module_requires_provenance_mapping(candidate):
    manifest = _manifest(candidate)
    del manifest["modules"]["loop.py"]
    _write(candidate, manifest)
    with pytest.raises(ValueError, match="module inventory differs"):
        provenance.verify(candidate, REFERENCE)


def test_added_runtime_asset_requires_provenance_mapping(candidate):
    (candidate / "assets/unrecorded.txt").write_text("New model instructions")
    with pytest.raises(ValueError, match="asset inventory differs"):
        provenance.verify(candidate, REFERENCE)


def test_dependency_checksums_cannot_be_rewritten_in_core_manifest(candidate):
    manifest = _manifest(candidate)
    manifest["dependencies"][0]["checksum"] = "0" * 64
    _write(candidate, manifest)
    with pytest.raises(ValueError, match="dependency is not pinned"):
        provenance.verify(candidate, REFERENCE)
