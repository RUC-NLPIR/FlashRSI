"""BBH is an explicitly external evaluation pool, never BBEH held-out data."""

import json

import pytest

from flashrsi.benchmarks import BBEH
from flashrsi.core import Trajectory


@pytest.fixture
def pools(tmp_path, monkeypatch):
    root = tmp_path / "native-bbh"
    (root / "bbh").mkdir(parents=True)
    path = root / "bbh/word_sorting.json"
    external = [{"input": f"Sort words {i}", "target": "a b"} for i in range(4)]
    path.write_text(json.dumps({"examples": external}))
    downstream = [
        {"task": "word_sorting", "input": f"Harder words {i}", "target": "c d"}
        for i in range(6)
    ]
    monkeypatch.setattr(
        BBEH, "_load_source_rows", lambda self: (("test", r) for r in downstream)
    )

    def download(url, revision, paths):
        assert url == "https://github.com/suzgunmirac/BIG-Bench-Hard.git"
        assert revision == "9ee07bd481feebf959a6b59d61ea57bdcf30964d"
        assert paths == ["bbh"]
        return root

    monkeypatch.setattr(
        "flashrsi.benchmarks.bbeh._download_git", download, raising=False
    )
    return downstream, external, path


def config(**extra):
    return {
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
        **extra,
    }


def test_external_pool_preserves_heldout_and_native_correctness(pools):
    baseline = BBEH(config()).load()
    before = pools[2].read_bytes()
    bench = BBEH(config(evolution_bbh_tasks=["word_sorting"], evolution_limit=1))
    split = bench.load()
    assert bench.load() is split
    assert split["dev"] == baseline["dev"] and split["test"] == baseline["test"]
    assert len(bench.train) == 1 and bench.train[0].question.startswith("Sort words")
    source = bench.metadata["evolution_source"]
    assert source["source"] == "https://github.com/suzgunmirac/BIG-Bench-Hard"
    assert source["revision"] == "9ee07bd481feebf959a6b59d61ea57bdcf30964d"
    assert source["native_split"] == "published_evaluation"
    assert source["tasks"] == ["word_sorting"] and source["pool_size"] == 4
    assert len(source["pool_checksum"]) == 64
    for task in (*bench.train, *bench.dev, *bench.test):
        good, bad = bench.grade(
            (
                Trajectory(task=task, output=task.ground_truth),
                Trajectory(task=task, output="wrong"),
            )
        )
        assert good.metrics == {"accuracy": 1.0}
        assert bad.metrics == {"accuracy": 0.0}
    assert pools[2].read_bytes() == before


@pytest.mark.parametrize("category", ["word_sorting", "other_category"])
def test_complete_raw_questions_checked_before_limit(pools, category):
    downstream, external, path = pools
    downstream[-1]["task"] = category
    external[-1]["input"] = " HARDER\nWORDS\t5 "
    path.write_text(json.dumps({"examples": external}))
    bench = BBEH(config(evolution_bbh_tasks=["word_sorting"], evolution_limit=1))
    with pytest.raises(ValueError, match="overlaps downstream"):
        bench.load()
    assert bench._splits is None and "evolution_source" not in bench.metadata


@pytest.mark.parametrize(
    "extra",
    [
        {"evolution_bbh_tasks": []},
        {"evolution_bbh_tasks": "word_sorting"},
        {"evolution_bbh_tasks": ["word_sorting", "word_sorting"]},
        {"evolution_bbh_tasks": ["../word_sorting"]},
        {"evolution_limit": 1},
    ],
)
def test_invalid_external_configuration(pools, extra):
    with pytest.raises(ValueError, match="evolution"):
        BBEH(config(**extra)).load()


def test_native_missing_target_is_not_repaired(pools):
    _, external, path = pools
    external[-1].pop("target")
    path.write_text(json.dumps({"examples": external}))
    with pytest.raises(ValueError, match="target"):
        BBEH(config(evolution_bbh_tasks=["word_sorting"], evolution_limit=1)).load()
