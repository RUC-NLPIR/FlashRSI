"""Independent official Hotpot split preserves held-out roles and native scoring."""

import json

import pytest

from flashrsi.benchmarks import HotpotQA
from flashrsi.core import Trajectory


@pytest.fixture
def pools(monkeypatch):
    rows = {
        split: [
            {
                "id": f"{split}-{i}",
                "question": f"Question {split} {i}?",
                "answer": "Gold",
                "context": {"title": ["Article"], "sentences": [["Gold. "]]},
                "supporting_facts": {"title": ["Article"], "sent_id": [0]},
            }
            for i in range(6)
        ]
        for split in ("train", "validation")
    }

    def load_dataset(source, *, split, name, revision, streaming):
        assert source == HotpotQA.metadata["source"]
        assert name == "fullwiki"
        assert revision == HotpotQA.metadata["revision"]
        assert streaming is True
        return rows[split]

    monkeypatch.setattr("datasets.load_dataset", load_dataset)
    return rows


def config(**extra):
    return {
        "dataset": {**HotpotQA.metadata, "splits": ["validation"]},
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
        **extra,
    }


@pytest.mark.parametrize("mode", ["context", "fullwiki"])
def test_official_train_is_independent_and_preserves_grading(pools, mode):
    baseline = HotpotQA(config(mode=mode)).load()
    benchmark = HotpotQA(config(mode=mode, evolution_split="train", evolution_limit=1))
    splits = benchmark.load()
    assert benchmark.load() is splits
    assert splits["dev"] == baseline["dev"]
    assert splits["test"] == baseline["test"]
    assert len(splits["train"]) == 1
    assert splits["train"][0].metadata["source_split"] == "train"
    source = benchmark.metadata["evolution_source"]
    assert source["source"] == HotpotQA.metadata["source"]
    assert source["revision"] == HotpotQA.metadata["revision"]
    assert source["native_split"] == "train"
    assert source["pool_size"] == 6
    assert len(source["pool_checksum"]) == 64
    for task in (*benchmark.train, *benchmark.dev, *benchmark.test):
        output = (
            "Gold"
            if mode == "context"
            else json.dumps({"answer": "Gold", "sp": [["Article", 0]]})
        )
        result = benchmark.grade((Trajectory(task=task, output=output),))[0]
        assert result.metrics[benchmark.primary_metric] == 1.0


@pytest.mark.parametrize("collision", ["id", "question"])
def test_full_pools_checked_before_sampling(pools, collision):
    if collision == "id":
        pools["train"][-1]["id"] = pools["validation"][-1]["id"]
    else:
        pools["train"][-1]["question"] = "  QUESTION\nvalidation\t5? "
        pools["train"][-1]["context"]["sentences"] = [["Changed context"]]
    benchmark = HotpotQA(config(evolution_split="train", evolution_limit=1))
    with pytest.raises(ValueError, match="overlaps downstream"):
        benchmark.load()
    assert benchmark._splits is None
    assert "evolution_source" not in benchmark.metadata


def test_default_pools_cannot_be_relabelled_independent(pools):
    benchmark = HotpotQA(
        {
            "split_counts": {"train": 1, "dev": 1, "test": 1},
            "evolution_split": "train",
            "evolution_limit": 1,
        }
    )
    with pytest.raises(ValueError, match="overlaps downstream"):
        benchmark.load()


@pytest.mark.parametrize(
    "options", [{"evolution_split": "test"}, {"evolution_limit": 1}]
)
def test_invalid_evolution_configuration_is_rejected(pools, options):
    with pytest.raises(ValueError, match="HotpotQA evolution"):
        HotpotQA(config(**options)).load()


def test_legacy_scoring_does_not_claim_official_scorer(pools):
    benchmark = HotpotQA(
        config(scoring="legacy", evolution_split="train", evolution_limit=1)
    )
    benchmark.load()
    assert "scorer_revision" not in benchmark.metadata
