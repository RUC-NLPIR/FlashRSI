"""Native filename format survives a Hub symlink to an extensionless blob."""

import json

import pytest

from flashrsi.benchmarks._data import _load_local_rows


@pytest.mark.parametrize("filename", ["widesearch.jsonl", "train.json"])
def test_hub_symlink_retains_filename_format(tmp_path, filename):
    blob = tmp_path / "blobs" / "0123456789abcdef"
    blob.parent.mkdir()
    rows = [{"question": "first"}, {"question": "second"}]
    text = (
        "\n".join(json.dumps(r) for r in rows)
        if filename.endswith("jsonl")
        else json.dumps(rows)
    )
    blob.write_text(text, encoding="utf-8")
    native = tmp_path / filename
    try:
        native.symlink_to(blob)
    except OSError:
        pytest.skip("This host does not allow creating symlinks")
    loaded = list(_load_local_rows(native))
    assert [r for _, r in loaded] == rows
    assert {split for split, _ in loaded} == (
        {"train"} if filename == "train.json" else {"local"}
    )
    assert native.is_symlink() and blob.read_text(encoding="utf-8") == text
