import hashlib
import json

import pyarrow.parquet as pq
import pytest

from scripts import prepare_searchqa as module


def _record(task_id: str) -> dict:
    return {
        "id": task_id,
        "input": f"{module.PREFIX}context for {task_id}"
        f"{module.SEPARATOR}question {task_id}?",
        "metadata": {"task_type": "searchqa"},
        "answers": [f"answer {task_id}"],
        "grader": "qa",
    }


@pytest.fixture
def source(tmp_path, monkeypatch):
    """A locked export with the same shape as the pinned EvoOS source."""
    directory = tmp_path / "source"
    directory.mkdir()
    counts = {"train": 2, "dev": 1, "test": 1}
    checksums = {}
    for split, count in counts.items():
        raw = (
            "\n".join(json.dumps(_record(f"{split}_{index}")) for index in range(count))
            + "\n"
        ).encode()
        (directory / f"{split}.jsonl").write_bytes(raw)
        checksums[f"sha256.{split}"] = hashlib.sha256(raw).hexdigest()
    (directory / "manifest.json").write_text(
        json.dumps({"id": "searchqa", "metadata": checksums})
    )
    monkeypatch.setattr(module, "COUNTS", counts)
    return directory


def test_manifest_and_splits_follow_the_shared_conventions(tmp_path, source):
    output = tmp_path / "publish"
    output.mkdir()
    (output / "README.md").write_text("existing repository card")
    (output / "terminal_bench").mkdir()
    (output / "terminal_bench" / "tasks.parquet").write_bytes(b"existing benchmark")

    manifest = module.prepare(output, source)

    destination = output / "searchqa"
    assert manifest == json.loads((destination / "manifest.json").read_text())
    assert manifest["schema"] == "flashrsi.searchqa.v1"
    # The source is an object, as in every other benchmark manifest.
    assert manifest["source"] == {
        "repo": module.SOURCE,
        "revision": module.REVISION,
        "path": "benchmarks/searchqa",
    }
    assert list(manifest["splits"]) == ["train", "dev", "test"]
    for split, value in manifest["splits"].items():
        file = output / value["file"]
        assert list(value) == [
            "count",
            "file",
            "bytes",
            "sha256",
            "origin",
            "source_sha256",
        ]
        assert value["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
        assert value["bytes"] == file.stat().st_size
        assert value["count"] == module.COUNTS[split]
        assert value["source_sha256"] == {
            f"{split}.jsonl": manifest["upstream"]["metadata"][f"sha256.{split}"]
        }

    rows = pq.read_table(destination / "train.parquet").to_pylist()
    assert rows[0] == {
        "id": "train_0",
        "question": "question train_0?",
        "context": "context for train_0",
        "answers": ["answer train_0"],
    }
    # The prompt wrapper is split out, never rewritten.
    assert (
        module.PREFIX + rows[0]["context"] + module.SEPARATOR + rows[0]["question"]
        == _record("train_0")["input"]
    )

    # Preparation writes only its own subdirectory.
    assert (output / "README.md").read_text() == "existing repository card"
    assert (
        output / "terminal_bench" / "tasks.parquet"
    ).read_bytes() == b"existing benchmark"
    assert (destination / "README.md").is_file()


def test_preparation_is_byte_stable(tmp_path, source):
    first, second = tmp_path / "first", tmp_path / "second"
    module.prepare(first, source)
    module.prepare(second, source)
    for name in ("train.parquet", "dev.parquet", "test.parquet", "manifest.json"):
        assert (first / "searchqa" / name).read_bytes() == (
            second / "searchqa" / name
        ).read_bytes()


def test_prepare_rejects_a_modified_source(tmp_path, source):
    (source / "train.jsonl").write_bytes(b'{"id": "x"}\n')
    with pytest.raises(ValueError, match="checksum mismatch"):
        module.prepare(tmp_path / "output", source)


def test_prepare_rejects_an_unexpected_prompt_shape(tmp_path, source):
    record = _record("train_0")
    record["input"] = "no wrapper at all"
    raw = (json.dumps(record) + "\n" + json.dumps(_record("train_1")) + "\n").encode()
    (source / "train.jsonl").write_bytes(raw)
    upstream = json.loads((source / "manifest.json").read_text())
    upstream["metadata"]["sha256.train"] = hashlib.sha256(raw).hexdigest()
    (source / "manifest.json").write_text(json.dumps(upstream))
    with pytest.raises(ValueError, match="unexpected prompt format"):
        module.prepare(tmp_path / "output", source)
