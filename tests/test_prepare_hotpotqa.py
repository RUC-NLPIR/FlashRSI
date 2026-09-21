import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import prepare_hotpotqa as module

SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("question", pa.string()),
        ("answer", pa.string()),
        ("type", pa.string()),
        ("level", pa.string()),
        (
            "supporting_facts",
            pa.struct(
                [("title", pa.list_(pa.string())), ("sent_id", pa.list_(pa.int32()))]
            ),
        ),
        (
            "context",
            pa.struct(
                [
                    ("title", pa.list_(pa.string())),
                    ("sentences", pa.list_(pa.list_(pa.string()))),
                ]
            ),
        ),
    ],
    metadata={"huggingface": '{"info": {"features": {}}}'},
)
TRAIN = [f"t{index}" for index in range(20)]
VALIDATION = ["v0", "v1"]


def _row(task_id: str) -> dict:
    return {
        "id": task_id,
        "question": f"question {task_id}?",
        "answer": f"answer {task_id}",
        "type": "bridge",
        "level": "hard",
        "supporting_facts": {"title": ["A"], "sent_id": [0]},
        "context": {"title": ["A", "B"], "sentences": [["a one.", "a two."], ["b."]]},
    }


@pytest.fixture
def source(tmp_path, monkeypatch):
    """Write shards matching the pinned layout, with checksums patched to match."""
    directory = tmp_path / "source"
    directory.mkdir()
    shards = {
        "fullwiki/train-00000-of-00002.parquet": TRAIN[:12],
        "fullwiki/train-00001-of-00002.parquet": TRAIN[12:],
        "fullwiki/validation-00000-of-00001.parquet": VALIDATION,
    }
    digests = {}
    for name, ids in shards.items():
        path = directory / name.rsplit("/", 1)[1]
        pq.write_table(
            pa.Table.from_pylist([_row(task_id) for task_id in ids], schema=SCHEMA),
            path,
        )
        digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    names = list(shards)
    monkeypatch.setattr(
        module,
        "SOURCES",
        {
            "train": tuple((name, digests[name]) for name in names[:2]),
            "validation": ((names[2], digests[names[2]]),),
        },
    )
    monkeypatch.setattr(
        module,
        "SOURCE_COUNTS",
        {"train": len(TRAIN), "validation": len(VALIDATION)},
    )
    return directory


def _ids(path) -> list[str]:
    return pq.read_table(path).column("id").to_pylist()


def test_publishes_three_disjoint_splits_from_the_official_pools(tmp_path, source):
    output = tmp_path / "publish"
    output.mkdir()
    (output / "README.md").write_text("existing repository card")
    (output / "searchqa").mkdir()
    (output / "searchqa" / "train.parquet").write_bytes(b"existing benchmark")

    manifest = module.prepare(output, source)

    destination = output / "hotpotqa"
    assert manifest == json.loads((destination / "manifest.json").read_text())
    assert manifest["schema"] == "flashrsi.hotpotqa.v1"
    assert manifest["source"]["revision"] == module.REVISION
    assert manifest["split_policy"] == module.SPLIT_POLICY
    assert list(manifest["splits"]) == ["train", "dev", "test"]

    train, dev, test = (
        _ids(destination / f"{name}.parquet") for name in ("train", "dev", "test")
    )
    # The labeled official validation pool is held out whole as the final test.
    assert test == VALIDATION
    assert len(dev) == len(TRAIN) // module.DEV_FRACTION
    assert set(train) | set(dev) == set(TRAIN)
    assert not set(train) & set(dev)
    # Row order inside each split still follows the official files.
    assert train == [task_id for task_id in TRAIN if task_id in set(train)]
    assert dev == [task_id for task_id in TRAIN if task_id in set(dev)]

    for split, value in manifest["splits"].items():
        file = output / value["file"]
        assert value["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
        assert value["bytes"] == file.stat().st_size
        assert value["count"] == len(_ids(file))
        assert value["origin"]
        # Each split records the checksums of the official pool it came from.
        pool = "validation" if split == "test" else "train"
        assert value["source_sha256"] == dict(module.SOURCES[pool])

    assert (output / "README.md").read_text() == "existing repository card"
    assert (output / "searchqa" / "train.parquet").read_bytes() == b"existing benchmark"
    assert (destination / "README.md").is_file()


def test_reencode_preserves_every_value_and_the_upstream_schema(tmp_path, source):
    module.prepare(tmp_path / "publish", source)
    destination = tmp_path / "publish" / "hotpotqa"

    # Parquet renames list fields on write, so compare with the source file.
    schema = pq.ParquetFile(source / "train-00000-of-00002.parquet").schema_arrow
    rows = {}
    for name in ("train", "dev", "test"):
        table = pq.read_table(destination / f"{name}.parquet")
        assert table.schema.equals(schema, check_metadata=True)
        assert table.schema.metadata == {b"huggingface": b'{"info": {"features": {}}}'}
        assert (
            pq.ParquetFile(destination / f"{name}.parquet")
            .metadata.row_group(0)
            .column(0)
            .compression
            == "ZSTD"
        )
        rows.update({row["id"]: row for row in table.to_pylist()})
    assert rows == {task_id: _row(task_id) for task_id in TRAIN + VALIDATION}


def test_split_is_reproducible_and_byte_stable(tmp_path, source):
    first, second = tmp_path / "first", tmp_path / "second"
    module.prepare(first, source)
    module.prepare(second, source)
    for name in (
        "train.parquet",
        "dev.parquet",
        "test.parquet",
        "manifest.json",
        "README.md",
    ):
        assert (first / "hotpotqa" / name).read_bytes() == (
            second / "hotpotqa" / name
        ).read_bytes()


def test_prepare_rejects_a_modified_source(tmp_path, source, monkeypatch):
    name = "fullwiki/validation-00000-of-00001.parquet"
    monkeypatch.setattr(
        module, "SOURCES", {**module.SOURCES, "validation": ((name, "0" * 64),)}
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        module.prepare(tmp_path / "output", source)


def test_prepare_rejects_rows_that_collide_across_pools(tmp_path, source, monkeypatch):
    path = source / "validation-00000-of-00001.parquet"
    pq.write_table(pa.Table.from_pylist([_row(TRAIN[0])], schema=SCHEMA), path)
    name = "fullwiki/validation-00000-of-00001.parquet"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        module, "SOURCES", {**module.SOURCES, "validation": ((name, digest),)}
    )
    monkeypatch.setattr(
        module, "SOURCE_COUNTS", {**module.SOURCE_COUNTS, "validation": 1}
    )
    with pytest.raises(ValueError, match="duplicate"):
        module.prepare(tmp_path / "output", source)
