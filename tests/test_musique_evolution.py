"""Independent native MuSiQue train/dev pools retain answer and support grading."""

import json

import pytest

from flashrsi.benchmarks import MuSiQue
from flashrsi.core import Trajectory


@pytest.fixture
def pools(tmp_path, monkeypatch):
    rows = {
        split: [
            {
                "id": f"{split}-{i}",
                "question": f"Which answer for {split} {i}?",
                "answer": "Gold",
                "answer_aliases": ["gold"],
                "answerable": True,
                "paragraphs": [
                    {
                        "idx": 0,
                        "title": "Article",
                        "paragraph_text": "The answer is Gold.",
                        "is_supporting": True,
                    }
                ],
            }
            for i in range(6)
        ]
        for split in ("train", "dev")
    }
    paths = {s: tmp_path / f"{s}.jsonl" for s in rows}

    def download(*, repo_id, filename, repo_type, revision):
        assert repo_id == MuSiQue.metadata["source"] and repo_type == "dataset"
        assert revision == MuSiQue.metadata["revision"]
        split = "train" if filename.endswith("_train.jsonl") else "dev"
        paths[split].write_text(
            "".join(json.dumps(row) + "\n" for row in rows[split]), encoding="utf-8"
        )
        return str(paths[split])

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    return rows


def config(**extra):
    return {
        "dataset": {**MuSiQue.metadata, "splits": ["dev"]},
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
        **extra,
    }


@pytest.mark.parametrize("mode", ["context", "answer_support"])
def test_independent_pool_retains_heldout_and_official_grading(pools, mode):
    baseline = MuSiQue(config(mode=mode)).load()
    b = MuSiQue(config(mode=mode, evolution_split="train", evolution_limit=1))
    b.load()
    assert b.load()["dev"] == baseline["dev"]
    assert b.load()["test"] == baseline["test"]
    assert b.train[0].metadata["source_split"] == "train"
    source = b.metadata["evolution_source"]
    assert source["source"] == MuSiQue.metadata["source"]
    assert source["revision"] == MuSiQue.metadata["revision"]
    assert source["native_split"] == "train" and source["pool_size"] == 6
    assert len(source["pool_checksum"]) == 64
    for task in (*b.train, *b.dev, *b.test):
        output = (
            "Gold"
            if mode == "context"
            else json.dumps(
                {
                    "predicted_answer": "Gold",
                    "predicted_support_idxs": [0],
                    "predicted_answerable": True,
                }
            )
        )
        result = b.grade((Trajectory(task=task, output=output),))[0]
        assert all(score == 1.0 for score in result.metrics.values())


@pytest.mark.parametrize("collision", ["id", "question"])
def test_complete_source_pools_compared_before_sampling(pools, collision):
    if collision == "id":
        pools["train"][-1]["id"] = pools["dev"][-1]["id"]
    else:
        pools["train"][-1]["question"] = " WHICH\nanswer for DEV\t5? "
        pools["train"][-1]["paragraphs"][0]["paragraph_text"] = "Changed context"
    b = MuSiQue(config(evolution_split="train", evolution_limit=1))
    with pytest.raises(ValueError, match="overlaps downstream"):
        b.load()
    assert b._splits is None and "evolution_source" not in b.metadata


def test_same_native_pool_cannot_be_relabelled(pools):
    b = MuSiQue({"evolution_split": "train", "evolution_limit": 1})
    with pytest.raises(ValueError, match="overlaps downstream"):
        b.load()


@pytest.mark.parametrize(
    "options", [{"evolution_split": "test"}, {"evolution_limit": 1}]
)
def test_invalid_source_options_are_rejected(pools, options):
    with pytest.raises(ValueError, match="MuSiQue evolution"):
        MuSiQue(config(**options)).load()
