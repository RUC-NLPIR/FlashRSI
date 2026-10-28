"""Independent 2Wiki train/validation preserves the canonical answer protocol."""

import pytest

from flashrsi.benchmarks import TwoWikiMultiHopQA
from flashrsi.core import Trajectory


@pytest.fixture
def pools(monkeypatch):
    rows = {
        split: [
            {
                "_id": f"{split}-{i}",
                "question": f"Which city for {split} {i}?",
                "answer": "London",
                "context": [["Article", ["London is the answer."]]],
                "supporting_facts": [["SECRET_SUPPORT", 0]],
                "evidences": [["SECRET_EVIDENCE", "relation", "London"]],
            }
            for i in range(6)
        ]
        for split in ("train", "validation")
    }

    def load_dataset(source, *, split, name, revision, streaming):
        assert source == TwoWikiMultiHopQA.metadata["source"]
        assert name == "default" and streaming is True
        assert revision == TwoWikiMultiHopQA.metadata["revision"]
        return rows[split]

    monkeypatch.setattr("datasets.load_dataset", load_dataset)
    return rows


def config(**extra):
    return {
        "dataset": {**TwoWikiMultiHopQA.metadata, "splits": ["validation"]},
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
        **extra,
    }


def test_independent_train_retains_heldout_and_answer_protocol(pools):
    baseline = TwoWikiMultiHopQA(config()).load()
    b = TwoWikiMultiHopQA(config(evolution_split="train", evolution_limit=1))
    splits = b.load()
    assert b.load() is splits
    assert splits["dev"] == baseline["dev"] and splits["test"] == baseline["test"]
    assert b.train[0].metadata["source_split"] == "train"
    source = b.metadata["evolution_source"]
    assert source["source"] == TwoWikiMultiHopQA.metadata["source"]
    assert source["revision"] == TwoWikiMultiHopQA.metadata["revision"]
    assert source["native_split"] == "train" and source["pool_size"] == 6
    assert len(source["pool_checksum"]) == 64
    for task in (*b.train, *b.dev, *b.test):
        assert "SECRET" not in task.question
        good, failed = b.grade(
            (
                Trajectory(task=task, output="the London"),
                Trajectory(
                    task=task, output="London", status="error", error_message="failed"
                ),
            )
        )
        assert good.metrics == {"exact_match": 1.0, "f1": 1.0}
        assert failed.metrics == {"exact_match": 0.0, "f1": 0.0}


@pytest.mark.parametrize("collision", ["id", "question"])
def test_full_pools_checked_before_limit(pools, collision):
    if collision == "id":
        pools["train"][-1]["_id"] = pools["validation"][-1]["_id"]
    else:
        pools["train"][-1]["question"] = " WHICH\nCITY FOR validation\t5? "
        pools["train"][-1]["context"] = [["Other article", ["Different evidence"]]]
    b = TwoWikiMultiHopQA(config(evolution_split="train", evolution_limit=1))
    with pytest.raises(ValueError, match="overlaps downstream"):
        b.load()
    assert b._splits is None and "evolution_source" not in b.metadata


def test_default_combined_source_cannot_be_claimed_independent(pools):
    cfg = config(evolution_split="train", evolution_limit=1)
    cfg.pop("dataset")
    with pytest.raises(ValueError, match="overlaps downstream"):
        TwoWikiMultiHopQA(cfg).load()


@pytest.mark.parametrize("extra", [{"evolution_split": "test"}, {"evolution_limit": 1}])
def test_invalid_independent_source_configuration(pools, extra):
    with pytest.raises(ValueError, match="evolution"):
        TwoWikiMultiHopQA(config(**extra)).load()
