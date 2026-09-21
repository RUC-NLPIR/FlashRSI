import json
import os
import stat
import tarfile

import pyarrow.parquet as pq
import pytest

from scripts import prepare_tau3_banking as module

SECRET_ACTION = "SECRET_GRADING_ACTION"


def _task(directory, name: str, *, initial_state=None, documents=("doc_a",)) -> dict:
    task = {
        "id": name,
        "description": {"purpose": f"Task: {name}", "relevant_policies": None},
        "user_scenario": {
            "persona": None,
            "instructions": f"You are a customer, {name}.",
        },
        "initial_state": initial_state,
        "evaluation_criteria": {
            "actions": [{"name": SECRET_ACTION, "action_id": f"{name}_0"}],
            "communicate_info": [],
            "reward_basis": ["DB"],
        },
        "annotations": None,
        "user_tools": ["apply_for_credit_card"],
        "required_documents": list(documents),
    }
    (directory / "tasks" / f"{name}.json").write_text(json.dumps(task, indent=2))
    return task


@pytest.fixture
def source(tmp_path):
    """A minimal domain with the same shape as the pinned banking_knowledge."""
    directory = tmp_path / "banking_knowledge"
    (directory / "tasks").mkdir(parents=True)
    (directory / "documents").mkdir()
    (directory / "prompts" / "components").mkdir(parents=True)
    (directory / "db.json").write_text('{"users": {}}')
    (directory / "documents" / "doc_a.json").write_text('{"id": "doc_a"}')
    (directory / "prompts" / "all_tools.md").write_text("# tools\n")
    (directory / "prompts" / "components" / "policy_header.md").write_text("# policy\n")
    (directory / "binary.bin").write_bytes(bytes(range(256)))
    (directory / "run.sh").write_text("#!/bin/sh\necho 1\n")
    (directory / "run.sh").chmod(0o755)
    _task(directory, "task_002", initial_state={"initialization_data": {"users": {}}})
    _task(directory, "task_001", documents=("doc_a", "doc_b"))
    # The upstream aggregate disagrees with tasks/ on required_documents.
    (directory / "tasks.json").write_text(
        json.dumps([{"id": "task_001", "required_documents": ["doc_a"]}])
    )
    return directory


def test_package_round_trip_index_and_manifest(tmp_path, source):
    output = tmp_path / "publish"
    output.mkdir()
    (output / "README.md").write_text("existing repository card")
    (output / "searchqa").mkdir()
    (output / "searchqa" / "train.parquet").write_bytes(b"existing benchmark")
    license_file = tmp_path / "LICENSE"
    license_file.write_text("MIT License\n")

    manifest = module.prepare(output, source, license_file)

    destination = output / "tau3_banking"
    assert manifest == json.loads((destination / "manifest.json").read_text())
    assert manifest["schema"] == "flashrsi.tau3_banking.v1"
    assert manifest["source"] == {
        "git_url": module.GIT_URL,
        "tag": module.TAG,
        "revision": module.REVISION,
        "domain": module.DOMAIN,
    }
    for section in ("archive", "index", "license"):
        file = output / manifest[section]["file"]
        assert manifest[section]["sha256"] == module._sha256(file)
    assert (
        manifest["archive"]["bytes"] == (destination / "domain.tar.gz").stat().st_size
    )
    assert manifest["index"]["count"] == 2
    assert (destination / "LICENSE").read_text() == "MIT License\n"

    rows = pq.read_table(destination / "tasks.parquet").to_pylist()
    assert list(rows[0]) == [
        "id",
        "user_instructions",
        "reward_basis",
        "user_tools",
        "required_documents",
        "has_initial_state",
    ]
    assert [row["id"] for row in rows] == ["task_001", "task_002"]
    assert rows[0]["user_instructions"] == "You are a customer, task_001."
    assert rows[0]["required_documents"] == ["doc_a", "doc_b"]
    assert rows[0]["has_initial_state"] is False
    assert rows[1]["has_initial_state"] is True
    assert SECRET_ACTION not in repr(rows)
    # Paths are archive-relative, so a loader can join them to the extraction.
    assert manifest["tasks"] == [
        {
            "id": name,
            "path": f"tau3_banking/tasks/{name}.json",
            "task_checksum": module._sha256(source / "tasks" / f"{name}.json"),
        }
        for name in ("task_001", "task_002")
    ]

    restored = tmp_path / "restored"
    with tarfile.open(destination / "domain.tar.gz") as tar:
        assert all(member.isfile() or member.isdir() for member in tar.getmembers())
        assert all(
            member.mtime == member.uid == member.gid == 0 for member in tar.getmembers()
        )
        tar.extractall(restored, filter="data")
    for file in source.rglob("*"):
        copy = restored / "tau3_banking" / file.relative_to(source)
        if file.is_file():
            assert copy.read_bytes() == file.read_bytes()
            assert stat.S_IMODE(copy.stat().st_mode) == stat.S_IMODE(
                file.stat().st_mode
            )
        else:
            assert copy.is_dir()
    # The full domain, including the grading criteria, stays inside the archive.
    assert (
        SECRET_ACTION
        in (restored / "tau3_banking" / "tasks" / "task_001.json").read_text()
    )

    assert (output / "README.md").read_text() == "existing repository card"
    assert (output / "searchqa" / "train.parquet").read_bytes() == b"existing benchmark"
    assert (destination / "README.md").is_file()


def test_preparation_is_stable_across_mtime_and_output_directory(tmp_path, source):
    first, second = tmp_path / "first", tmp_path / "second"
    module.prepare(first, source)
    for path in [source, *source.rglob("*")]:
        os.utime(path, (1234567890, 1234567890))
    module.prepare(second, source)
    for name in ("domain.tar.gz", "tasks.parquet", "manifest.json", "README.md"):
        assert (first / "tau3_banking" / name).read_bytes() == (
            second / "tau3_banking" / name
        ).read_bytes()
    assert not (first / "tau3_banking" / "LICENSE").exists()
    assert "license" not in json.loads(
        (first / "tau3_banking" / "manifest.json").read_text()
    )


def test_prepare_rejects_links_and_special_files(tmp_path, source):
    (source / "link").symlink_to(source / "db.json")
    with pytest.raises(ValueError, match="link|special"):
        module.prepare(tmp_path / "output", source)


def test_prepare_rejects_missing_or_unusable_tasks(tmp_path, source):
    with pytest.raises(ValueError, match="no tasks directory"):
        module.prepare(tmp_path / "output", tmp_path)
    (source / "tasks" / "task_001.json").write_text(
        json.dumps({"id": "task_001", "user_scenario": {"instructions": "  "}})
    )
    with pytest.raises(ValueError, match="instructions"):
        module.prepare(tmp_path / "output", source)


def test_prepare_rejects_a_task_file_named_for_another_id(tmp_path, source):
    """The manifest path is only meaningful if the file name tracks the id."""
    _task(source, "task_003")
    renamed = json.loads((source / "tasks" / "task_003.json").read_text())
    renamed["id"] = "task_099"
    (source / "tasks" / "task_003.json").write_text(json.dumps(renamed))
    with pytest.raises(ValueError, match="does not match id"):
        module.prepare(tmp_path / "output", source)
