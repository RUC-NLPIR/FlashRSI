"""SearchQA native archives can supply a separate full evolution pool."""

import json
import zipfile

import pytest

from flashrsi.benchmarks import SearchQA
from flashrsi.core import Trajectory


@pytest.fixture
def pools(tmp_path, monkeypatch):
    rows = {
        split: [
            {
                "id": i,
                "question": f"Question {split} {i}?",
                "answer": "Gold",
                "search_results": [
                    {"snippet": "Gold is the answer."},
                    {"snippet": None},
                ],
            }
            for i in range(6)
        ]
        for split in ("train", "validation")
    }

    def download(*, repo_id, repo_type, revision, filename):
        assert repo_id == SearchQA.metadata["source"] and repo_type == "dataset"
        assert revision == SearchQA.metadata["revision"]
        split = "train" if filename.endswith("train.zip") else "validation"
        p = tmp_path / (split + ".zip")
        with zipfile.ZipFile(p, "w") as z:
            for i, row in enumerate(rows[split]):
                z.writestr(f"{i}.json", json.dumps(row))
        return str(p)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    return rows


def config(**extra):
    return {
        "dataset": {**SearchQA.metadata, "splits": ["validation"]},
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
        **extra,
    }


def test_independent_native_archive_preserves_heldout_and_grade(pools):
    baseline = SearchQA(config()).load()
    b = SearchQA(config(evolution_split="train", evolution_limit=1))
    splits = b.load()
    assert b.load() is splits
    assert b.dev == baseline["dev"] and b.test == baseline["test"]
    assert b.train[0].metadata["source_split"] == "train"
    source = b.metadata["evolution_source"]
    assert source["source"] == SearchQA.metadata["source"]
    assert source["revision"] == SearchQA.metadata["revision"]
    assert source["native_split"] == "train" and source["pool_size"] == 6
    assert len(source["pool_checksum"]) == 64
    for task in (*b.train, *b.dev, *b.test):
        assert "None" not in task.question
        scores = b.grade((Trajectory(task=task, output="Gold"),))[0].metrics
        assert scores == {"exact_match": 1.0, "f1": 1.0}


def test_raw_question_overlap_cannot_hide_in_changed_context(pools):
    pools["train"][-1]["question"] = " QUESTION\nvalidation\t5? "
    pools["train"][-1]["search_results"] = [{"snippet": "Different evidence"}]
    b = SearchQA(config(evolution_split="train", evolution_limit=1))
    with pytest.raises(ValueError, match="overlaps downstream"):
        b.load()
    assert b._splits is None and "evolution_source" not in b.metadata


def test_same_archive_cannot_be_claimed_independent(pools):
    with pytest.raises(ValueError, match="overlaps downstream"):
        SearchQA(config(evolution_split="validation", evolution_limit=1)).load()


@pytest.mark.parametrize("extra", [{"evolution_split": "dev"}, {"evolution_limit": 1}])
def test_invalid_source_options(pools, extra):
    with pytest.raises(ValueError, match="evolution"):
        SearchQA(config(**extra)).load()
