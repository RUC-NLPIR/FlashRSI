"""Native MATH train provides independent evolution for the full MATH-500 pool."""

import pytest

from flashrsi.benchmarks.math import MATH
from flashrsi.core import Trajectory


@pytest.fixture
def pools(monkeypatch):
    rows = {
        split: [
            {
                "unique_id": f"{split}/{i}",
                "problem": f"Problem {split} {i}",
                "solution": r"The answer is \boxed{2}.",
            }
            for i in range(6)
        ]
        for split in ("train", "test")
    }
    calls = []

    def load_dataset(source, *, name, revision, streaming):
        assert streaming is True
        calls.append((source, name, revision))
        if source == "HuggingFaceH4/MATH-500":
            assert name is None
            assert revision == "6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be"
            return {"test": rows["test"]}
        assert source == MATH.metadata["source"]
        assert revision == MATH.metadata["revision"]
        # The fixture distributes a small native pool across the seven subjects.
        return rows if name == "algebra" else {"train": [], "test": []}

    monkeypatch.setattr("datasets.load_dataset", load_dataset)
    return rows, calls


def config(**extra):
    return {
        "variant": "math500",
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
        **extra,
    }


def test_independent_train_preserves_heldout_native_rows_and_grading(pools):
    pytest.importorskip("math_verify")
    baseline = MATH(config()).load()
    benchmark = MATH(config(evolution_split="train", evolution_limit=1))
    splits = benchmark.load()
    assert benchmark.load() is splits
    assert splits["dev"] == baseline["dev"]
    assert splits["test"] == baseline["test"]
    assert len(splits["train"]) == 1
    assert splits["train"][0].metadata["source_split"] == "train"
    source = benchmark.metadata["evolution_source"]
    assert source["source"] == MATH.metadata["source"]
    assert source["revision"] == MATH.metadata["revision"]
    assert source["native_split"] == "train"
    assert source["pool_size"] == 6
    assert len(source["pool_checksum"]) == 64
    for task in (*benchmark.train, *benchmark.dev, *benchmark.test):
        native = benchmark._rows_by_id[task.task_id]
        assert native["problem"] in task.question
        graded = benchmark.grade((Trajectory(task=task, output=r"\boxed{2}"),))[0]
        assert graded.metrics == {"accuracy": 1.0}


@pytest.mark.parametrize("collision", ["id", "question"])
def test_complete_pools_checked_before_sampling(pools, collision):
    rows, _ = pools
    if collision == "id":
        rows["train"][-1]["unique_id"] = rows["test"][-1]["unique_id"]
    else:
        rows["train"][-1]["problem"] = "  PROBLEM\ntest\t5 "
    benchmark = MATH(config(evolution_split="train", evolution_limit=1))
    with pytest.raises(ValueError, match="overlaps downstream"):
        benchmark.load()
    assert benchmark._splits is None
    assert "evolution_source" not in benchmark.metadata


def test_original_test_cannot_be_relabelled_independent(pools):
    with pytest.raises(ValueError, match="overlaps downstream"):
        MATH(config(evolution_split="test", evolution_limit=1)).load()


@pytest.mark.parametrize(
    "extra",
    [
        {"evolution_split": "dev"},
        {"evolution_limit": 1},
        {"evolution_subjects": ["geometry"]},
        {"evolution_split": "train", "evolution_subjects": []},
        {"evolution_split": "train", "evolution_subjects": ["unknown"]},
        {"evolution_split": "train", "evolution_subjects": ["algebra", "algebra"]},
    ],
)
def test_invalid_evolution_configuration(pools, extra):
    with pytest.raises(ValueError, match="MATH evolution"):
        MATH(config(**extra)).load()


def test_explicit_native_subjects_are_preserved_in_provenance(pools):
    _, calls = pools
    benchmark = MATH(
        config(
            evolution_split="train", evolution_subjects=["algebra"], evolution_limit=1
        )
    )
    benchmark.load()
    source = benchmark.metadata["evolution_source"]
    assert source["configs"] == ("algebra",)
    assert source["pool_size"] == 6
    assert [name for repo, name, _ in calls if repo == MATH.metadata["source"]] == [
        "algebra"
    ]
