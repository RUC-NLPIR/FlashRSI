"""External ARC records retain references and never replace SuperGPQA heldout."""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flashrsi.benchmarks import SuperGPQA
from flashrsi.core import Trajectory


@pytest.fixture
def pools(tmp_path, monkeypatch):
    downstream = [
        {
            "uuid": f"graduate-{i}",
            "question": f"Graduate question {i}",
            "options": ["wrong", "right"],
            "answer": "right",
            "answer_letter": "B",
        }
        for i in range(6)
    ]
    external = [
        {
            "id": f"science-{i}",
            "question": f"Science question {i}",
            "choices": {"label": ["1", "2", "3"], "text": ["x", "y", "z"]},
            "answerKey": "2",
        }
        for i in range(4)
    ]
    path = tmp_path / "train.parquet"
    pq.write_table(pa.Table.from_pylist(external), path)
    monkeypatch.setattr(
        SuperGPQA, "_load_source_rows", lambda self: (("test", r) for r in downstream)
    )

    def download(**kwargs):
        assert kwargs == {
            "repo_id": "allenai/ai2_arc",
            "repo_type": "dataset",
            "revision": "210d026faf9955653af8916fad021475a3f00453",
            "filename": "ARC-Challenge/train-00000-of-00001.parquet",
        }
        return str(path)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    return downstream, external, path


def config(**extra):
    return {"split_counts": {"train": 1, "dev": 1, "test": 1}, "seed": 42, **extra}


def evolution():
    return {
        "evolution_arc": {"subset": "ARC-Challenge", "split": "train"},
        "evolution_limit": 1,
    }


def test_external_native_reference_heldout_and_source(pools):
    before = pools[2].read_bytes()
    baseline = SuperGPQA(config()).load()
    bench = SuperGPQA(config(**evolution()))
    splits = bench.load()
    assert bench.load() is splits
    assert splits["dev"] == baseline["dev"] and splits["test"] == baseline["test"]
    task = bench.train[0]
    assert task.task_id.startswith("science-")
    assert task.ground_truth == "B" and "B. y" in task.question
    assert task.metadata["native_answer_key"] == "2"
    assert task.metadata["native_choice_labels"] == ["1", "2", "3"]
    source = bench.metadata["evolution_source"]
    assert source["source"] == "allenai/ai2_arc"
    assert source["subset"] == "ARC-Challenge"
    assert source["native_split"] == "train" and source["pool_size"] == 4
    assert len(source["pool_checksum"]) == 64
    for task in (*bench.train, *bench.dev, *bench.test):
        assert bench.grade((Trajectory(task=task, output=task.ground_truth),))[
            0
        ].metrics == {"accuracy": 1.0}
    assert pools[2].read_bytes() == before


@pytest.mark.parametrize("field", ["id", "question"])
def test_full_raw_pools_guard_before_limit(pools, field):
    downstream, external, path = pools
    external[-1][field] = (
        downstream[-1]["uuid"] if field == "id" else " GRADUATE\nQUESTION\t5 "
    )
    pq.write_table(pa.Table.from_pylist(external), path)
    bench = SuperGPQA(config(**evolution()))
    with pytest.raises(ValueError, match="overlaps downstream"):
        bench.load()
    assert bench._splits is None and "evolution_source" not in bench.metadata


@pytest.mark.parametrize(
    "extra",
    [
        {"evolution_limit": 1},
        {"evolution_arc": "ARC-Challenge"},
        {"evolution_arc": {}},
        {"evolution_arc": {"subset": "../ARC", "split": "train"}},
        {"evolution_arc": {"subset": "ARC-Challenge", "split": "unknown"}},
    ],
)
def test_invalid_source_selection(pools, extra):
    with pytest.raises(ValueError, match="evolution"):
        SuperGPQA(config(**extra)).load()


def test_original_duplicate_training_question_is_preserved(pools):
    _, external, path = pools
    external[-1]["question"] = external[0]["question"]
    pq.write_table(pa.Table.from_pylist(external), path)
    bench = SuperGPQA(config(**{**evolution(), "evolution_limit": 4}))
    bench.load()
    assert len(bench.train) == 4
    assert bench.metadata["evolution_source"]["pool_size"] == 4


def test_unknown_answer_key_is_not_repaired(pools):
    _, external, path = pools
    external[-1]["answerKey"] = "missing"
    pq.write_table(pa.Table.from_pylist(external), path)
    with pytest.raises(ValueError, match="answerKey"):
        SuperGPQA(config(**evolution())).load()
