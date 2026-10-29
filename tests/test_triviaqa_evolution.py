"""Independent native TriviaQA train preserves aliases and the sealed heldout."""

import pytest

from flashrsi.benchmarks import TriviaQA
from flashrsi.core import Trajectory


@pytest.fixture
def pools(monkeypatch):
    rows = {
        split: [
            {
                "question_id": f"{split}-{i}",
                "question": f"Question {split} {i}?",
                "answer": {
                    "value": "Canonical",
                    "aliases": ["Native Alias"],
                    "normalized_aliases": ["canonical", "native alias"],
                    "human_answers": [],
                },
                "entity_pages": {"title": ["Page"], "wiki_context": ["Original text"]},
            }
            for i in range(6)
        ]
        for split in ("train", "validation")
    }
    calls = []

    def load_dataset(source, *, split, name, revision, streaming):
        calls.append({"source": source, "split": split})
        assert name == "rc.wikipedia" and revision == TriviaQA.metadata["revision"]
        assert streaming is True
        return rows[split]

    monkeypatch.setattr("datasets.load_dataset", load_dataset)
    return rows, calls


def config(**extra):
    return {
        "dataset": {**TriviaQA.metadata, "splits": ["validation"]},
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
        **extra,
    }


@pytest.mark.parametrize("scoring", ["official", "legacy"])
def test_native_train_alias_grading_and_heldout_preserved(pools, scoring):
    baseline = TriviaQA(config(scoring=scoring)).load()
    bench = TriviaQA(
        config(scoring=scoring, evolution_split="train", evolution_limit=1)
    )
    splits = bench.load()
    assert bench.load() is splits
    assert splits["dev"] == baseline["dev"] and splits["test"] == baseline["test"]
    assert bench.train[0].task_id.startswith("train-")
    source = bench.metadata["evolution_source"]
    assert source["source"] == TriviaQA.metadata["source"]
    assert source["revision"] == TriviaQA.metadata["revision"]
    assert source["native_split"] == "train" and source["pool_size"] == 6
    assert len(source["pool_checksum"]) == 64
    for task in (*bench.train, *bench.dev, *bench.test):
        good, bad = bench.grade(
            (
                Trajectory(task=task, output="Native Alias"),
                Trajectory(task=task, output="wrong"),
            )
        )
        assert good.metrics == {"exact_match": 1.0, "f1": 1.0}
        assert bad.metrics == {"exact_match": 0.0, "f1": 0.0}
    assert ("scorer_revision" in bench.metadata) is (scoring == "official")


@pytest.mark.parametrize("collision", ["question_id", "question"])
def test_complete_raw_pools_guard_before_limit(pools, collision):
    rows, _ = pools
    rows["train"][-1][collision] = (
        rows["validation"][-1][collision]
        if collision == "question_id"
        else "  QUESTION\nvalidation\t5? "
    )
    rows["train"][-1]["entity_pages"]["wiki_context"] = ["Different context"]
    bench = TriviaQA(config(evolution_split="train", evolution_limit=1))
    with pytest.raises(ValueError, match="overlaps downstream"):
        bench.load()
    assert bench._splits is None and "evolution_source" not in bench.metadata


def test_public_streaming_source_override_is_recorded(pools):
    _, calls = pools
    bench = TriviaQA(
        config(
            evolution_split="train",
            evolution_limit=1,
            evolution_dataset={"source": "/absolute/native-parquet-cache"},
        )
    )
    bench.load()
    assert {"source": "/absolute/native-parquet-cache", "split": "train"} in calls
    assert (
        bench.metadata["evolution_source"]["source"] == "/absolute/native-parquet-cache"
    )


def test_default_full_pool_cannot_be_called_independent(pools):
    with pytest.raises(ValueError, match="overlaps downstream"):
        TriviaQA(
            {
                "split_counts": {"train": 1, "dev": 1, "test": 1},
                "evolution_split": "train",
            }
        ).load()


@pytest.mark.parametrize(
    "extra",
    [
        {"evolution_split": "unknown"},
        {"evolution_limit": 1},
        {"evolution_dataset": {}},
        {"evolution_split": "train", "evolution_dataset": "path"},
    ],
)
def test_invalid_evolution_configuration(pools, extra):
    with pytest.raises(ValueError, match="TriviaQA evolution"):
        TriviaQA(config(**extra)).load()


def test_malformed_original_aliases_are_not_repaired(pools):
    rows, _ = pools
    del rows["train"][-1]["answer"]["normalized_aliases"]
    with pytest.raises(ValueError, match="normalized_aliases"):
        TriviaQA(config(evolution_split="train", evolution_limit=1)).load()
