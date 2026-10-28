"""Pinned MuSiQue downloads are JSONL even if an HF cache blob has no suffix."""

import json

import pytest

from flashrsi.benchmarks import MuSiQue
from flashrsi.core import Trajectory


def row(split, index):
    return {
        "id": f"{split}-{index}",
        "question": f"Where is {split} {index}?",
        "answer": "London",
        "answer_aliases": ["London city"],
        "answerable": True,
        "paragraphs": [
            {
                "idx": 0,
                "title": "Article",
                "paragraph_text": "A city.",
                "is_supporting": True,
            }
        ],
        "question_decomposition": [{"answer": "HOST_ONLY_LABEL"}],
    }


@pytest.mark.parametrize("mode", ["context", "answer_support"])
def test_native_jsonl_from_extensionless_cache_preserves_roles_and_grading(
    tmp_path, monkeypatch, mode
):
    calls = []

    def download(**options):
        assert options["repo_id"] == MuSiQue.metadata["source"]
        assert options["revision"] == MuSiQue.metadata["revision"]
        split = "train" if "train" in options["filename"] else "dev"
        calls.append(split)
        blob = tmp_path / f"hash-{split}"
        blob.write_text(
            "\n".join(json.dumps(row(split, i)) for i in range(2)) + "\n\n",
            encoding="utf-8",
        )
        return str(blob)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    benchmark = MuSiQue({"mode": mode})
    splits = benchmark.load()
    assert len(splits["train"]) == len(splits["dev"]) == 2
    assert not splits["test"]
    assert calls == ["train", "dev"]
    for task in (*benchmark.train, *benchmark.dev):
        assert "HOST_ONLY_LABEL" not in task.question
        output = (
            "London"
            if mode == "context"
            else json.dumps(
                {
                    "predicted_answer": "London",
                    "predicted_support_idxs": [0],
                    "predicted_answerable": True,
                }
            )
        )
        assert (
            benchmark.grade((Trajectory(task=task, output=output),))[0].metrics[
                benchmark.primary_metric
            ]
            == 1
        )


def test_local_jsonl_data_path_still_loads_without_network(tmp_path, monkeypatch):
    path = tmp_path / "train.jsonl"
    path.write_text(json.dumps(row("local", 0)) + "\n", encoding="utf-8")

    def forbidden(**options):
        raise AssertionError("local data must not download")

    monkeypatch.setattr("huggingface_hub.hf_hub_download", forbidden)
    benchmark = MuSiQue({"data_path": path})
    assert benchmark.load()["train"][0].task_id == "local-0"
