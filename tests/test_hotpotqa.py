import json

import pytest

from flashrsi.benchmarks import HotpotQA
from flashrsi.config import load_config
from flashrsi.core import Trajectory


def _config(**benchmark):
    values = {
        "agent": {"llm": {"model_name": "target"}},
        "algorithm": {"worker": {"llm": {"model_name": "worker"}}},
        "benchmark": {"name": "hotpotqa", **benchmark},
    }
    return load_config(overrides=values)


def _row(index, **overrides):
    return {
        "id": f"hotpot-{index}",
        "question": f"Question {index}?",
        "answer": f"Answer {index}",
        "type": "bridge",
        "level": "hard",
        "supporting_facts": {"title": [f"Title {index}"], "sent_id": [0]},
        "context": {
            "title": [f"Title {index}", f"Other {index}"],
            "sentences": [[f"Gold {index}. ", "More."], [f"Noise {index}."]],
        },
        **overrides,
    }


def _rows(count=10, split="train"):
    return tuple((split, _row(index)) for index in range(count))


def test_published_heldout_splits_survive_auto_loading(monkeypatch):
    benchmark = HotpotQA(_config(split="auto", seed=7))
    published = (
        *((("train", _row(index))) for index in range(6)),
        *((("dev", _row(index))) for index in range(6, 8)),
        *((("test", _row(index))) for index in range(8, 12)),
    )
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: published)

    splits = benchmark.load()

    assert tuple(splits) == ("train", "dev", "test")
    assert tuple(map(len, splits.values())) == (6, 2, 4)
    # The published partition is preserved, not repartitioned.
    assert {task.task_id for task in splits["test"]} == {
        f"hotpot-{index}" for index in range(8, 12)
    }
    assert {task.task_id for task in splits["dev"]} == {"hotpot-6", "hotpot-7"}
    assert benchmark.load() is splits


def test_task_carries_the_rendered_context_and_reporting_metadata(monkeypatch):
    benchmark = HotpotQA(_config(split={"train": 1, "dev": 0, "test": 0}))
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: (("train", _row(3)),))

    task = benchmark.load()["train"][0]

    assert task.task_id == "hotpot-3"
    assert "multi-hop" in task.question
    assert task.question.endswith("Question:\nQuestion 3?")
    # Paragraph sentences are joined and labeled by title, gold and noise alike.
    assert "Title 3: Gold 3. More." in task.question
    assert "Other 3: Noise 3." in task.question
    assert task.ground_truth == "Answer 3"
    assert task.metadata["answers"] == ("Answer 3",)
    assert task.metadata["type"] == "bridge"
    assert task.metadata["level"] == "hard"
    # supporting_facts stays out of the prompt: the agent is not told which
    # paragraphs are gold, only which were retrieved.
    assert "sent_id" not in task.question
    assert "supporting" not in task.question.lower()


def test_grades_exact_match_f1_and_errors(monkeypatch):
    benchmark = HotpotQA(_config(split={"train": 1, "dev": 0, "test": 0}))
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: _rows(2))
    task, other = benchmark.load()["train"]
    trajectories = (
        Trajectory(
            task=task,
            status="finished",
            output=f"The {task.ground_truth}!",
            metrics={"latency": 0.5},
        ),
        Trajectory(task=other, status="finished", output="Answer"),
        Trajectory(
            task=other, status="error", output="", error_message="backend unavailable"
        ),
    )

    graded = benchmark.grade(trajectories)

    assert graded[0].metrics == {"latency": 0.5, "exact_match": 1.0, "f1": 1.0}
    assert graded[1].metrics["exact_match"] == 0.0
    assert 0.0 < graded[1].metrics["f1"] < 1.0
    assert graded[2].metrics == {"exact_match": 0.0, "f1": 0.0}
    assert trajectories[0].metrics == {"latency": 0.5}
    assert benchmark.primary_metric == "exact_match"


def test_grading_requires_a_loaded_benchmark_and_known_tasks(monkeypatch):
    benchmark = HotpotQA(_config())
    with pytest.raises(RuntimeError, match="call load"):
        benchmark.grade(())
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: _rows(4))
    benchmark.load()
    with pytest.raises(ValueError, match="requires a Task"):
        benchmark.grade((Trajectory(status="finished", output="x"),))


def test_rejects_rows_that_cannot_be_scored(monkeypatch):
    cases = {
        "no non-empty id": {"id": " "},
        "has no question": {"question": ""},
        "has no answer": {"answer": None},
        "malformed context": {"context": {"title": ["a"], "sentences": []}},
    }
    for match, override in cases.items():
        benchmark = HotpotQA(_config())
        monkeypatch.setattr(
            benchmark,
            "_load_source_rows",
            lambda o=override: (("train", _row(0, **o)),),
        )
        with pytest.raises(ValueError, match=match):
            benchmark.load()


def test_keeps_rows_whose_retrieval_returned_nothing(monkeypatch):
    """fullwiki retrieval can come back empty; 10 published test rows do."""
    benchmark = HotpotQA(_config(split={"train": 1, "dev": 0, "test": 0}))
    empty = {"context": {"title": [], "sentences": []}}
    monkeypatch.setattr(
        benchmark, "_load_source_rows", lambda: (("train", _row(0, **empty)),)
    )

    task = benchmark.load()["train"][0]

    assert "no paragraphs were retrieved" in task.question
    assert task.question.endswith("Question:\nQuestion 0?")
    assert task.ground_truth == "Answer 0"


def test_reads_local_jsonl_relative_to_cwd(tmp_path, monkeypatch):
    path = tmp_path / "hotpotqa.jsonl"
    path.write_text("\n".join(json.dumps(_row(index)) for index in range(3)))
    monkeypatch.chdir(tmp_path)
    benchmark = HotpotQA(
        _config(
            data_path="hotpotqa.jsonl", limit=2, split={"train": 1, "dev": 0, "test": 0}
        )
    )

    splits = benchmark.load()

    assert sum(map(len, splits.values())) == 2
    assert {
        task.metadata["source_split"] for tasks in splits.values() for task in tasks
    } == {"local"}


def test_requires_its_own_benchmark_name():
    with pytest.raises(ValueError, match="benchmark.name: hotpotqa"):
        HotpotQA({"benchmark": {"name": "searchqa"}})
