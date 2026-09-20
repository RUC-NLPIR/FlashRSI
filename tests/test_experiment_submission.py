import base64
import hashlib
import json
import tarfile

import pytest

from scripts.prepare_experiment_submission import prepare


def write(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_submission_keeps_evidence_and_uses_same_structure(tmp_path):
    source = tmp_path / "run"
    write(source, "result.json", {"status": "finished"})
    write(source, "end-summary.json", {"usage": {"sdk_cost_usd": None}})
    write(source, "cache/errors/worker/error.json", {"status": "error"})
    write(source, "working/discard.json", {})
    (source / ".env").write_text("PRIVATE=secret")
    target = prepare(
        source, tmp_path / "experiments", "alice-run-1", "alice", secrets=[]
    )
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["logs"]["files"] == 3
    assert (target / "summaries/end-summary.json").exists()
    with tarfile.open(target / "logs.tar.gz") as archive:
        assert "run/cache/errors/worker/error.json" in archive.getnames()
        assert "run/.env" not in archive.getnames()
        assert json.load(archive.extractfile("run/result.json")) == {
            "status": "finished"
        }
    assert (
        hashlib.sha256((target / "logs.tar.gz").read_bytes()).hexdigest()
        == manifest["logs"]["sha256"]
    )
    with pytest.raises(FileExistsError):
        prepare(source, tmp_path / "experiments", "alice-run-1", "alice", secrets=[])


@pytest.mark.parametrize("encoded", [False, True])
def test_submission_rejects_credentials_and_removes_partial_output(tmp_path, encoded):
    source = tmp_path / "run"
    write(source, "result.json", {"status": "finished"})
    secret = b"private-provider-key"
    record = (
        {"message": secret.decode()}
        if not encoded
        else {"files": {"main": {"content": base64.b64encode(secret).decode()}}}
    )
    write(source, "snapshots/source.json", record)
    with pytest.raises(ValueError, match="credential"):
        prepare(
            source, tmp_path / "experiments", "alice-run-1", "alice", secrets=[secret]
        )
    assert list((tmp_path / "experiments").iterdir()) == []


def test_searchqa_profile_and_active_run(tmp_path):
    source = tmp_path / "full"
    write(source, "miniagent/result.json", {"status": "finished"})
    write(source, "miniagent/plan.json", {"model": "test"})
    write(source, "miniagent/status.json", {"status": "running"})
    with pytest.raises(ValueError, match="running"):
        prepare(source, tmp_path / "experiments", "test", "alice", secrets=[])
    write(source, "miniagent/status.json", {"status": "finished"})
    target = prepare(source, tmp_path / "experiments", "test", "alice", secrets=[])
    assert (target / "configs/miniagent/plan.json").exists()
    assert (target / "summaries/miniagent/result.json").exists()
    with pytest.raises(ValueError, match="outside"):
        prepare(source, source / "nested", "nested", "alice", secrets=[])
