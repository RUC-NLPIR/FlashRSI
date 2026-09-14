import json
from dataclasses import FrozenInstanceError

import pytest

from flashrsi.benchmarks.searchqa import SearchQA
from flashrsi.config import load_config
from flashrsi.core import Task, Trajectory


def _config(**benchmark):
    values = {
        "agent": {"model_name": "target"},
        "algorithm": {"worker": {"model_name": "worker"}},
        "benchmark": benchmark,
    }
    return load_config(overrides=values)


def _rows(count=10):
    return tuple(
        (
            "source",
            {
                "key": f"task-{index}",
                "question": f"Question {index}?",
                "context": f"Context {index}",
                "answers": [f"Answer {index}", f"Alias {index}"],
            },
        )
        for index in range(count)
    )


def test_searchqa_loads_deterministic_configured_splits(monkeypatch):
    config = _config(
        split={"train": 0.5, "dev": 0.3, "test": 0.2},
        seed=7,
    )
    first = SearchQA(config)
    second = SearchQA(config)
    monkeypatch.setattr(first, "_load_source_rows", _rows)
    monkeypatch.setattr(second, "_load_source_rows", lambda: reversed(_rows()))

    splits = first.load()
    reversed_splits = second.load()

    assert tuple(splits) == ("train", "dev", "test")
    assert tuple(map(len, splits.values())) == (5, 3, 2)
    assert splits == reversed_splits
    assert first.train is splits["train"]
    assert first.dev is splits["dev"]
    assert first.test is splits["test"]
    assert first.load() is splits
    task = first.train[0]
    assert "Context:" in task.question
    assert "Question:" in task.question
    assert task.ground_truth.startswith("Answer")
    assert task.metadata["answers"][1].startswith("Alias")


def test_small_dataset_split_uses_all_tasks(monkeypatch):
    benchmark = SearchQA(_config())
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: _rows(4))

    splits = benchmark.load()

    assert tuple(map(len, splits.values())) == (2, 1, 1)
    ids = [task.task_id for tasks in splits.values() for task in tasks]
    assert len(ids) == len(set(ids)) == 4


def test_searchqa_grades_exact_match_f1_and_errors(monkeypatch):
    benchmark = SearchQA(_config(split={"train": 1, "dev": 0, "test": 0}))
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: _rows(2))
    task, other = benchmark.load()["train"]
    trajectories = (
        Trajectory(
            task=task,
            status="finished",
            output=f"The {task.ground_truth}!",
            metrics={"latency": 0.5},
        ),
        Trajectory(
            task=other,
            status="finished",
            output=other.ground_truth.split()[0],
        ),
        Trajectory(
            task=other,
            status="error",
            output="",
            error_message="backend unavailable",
        ),
    )

    graded = benchmark.grade(trajectories)

    assert graded[0].metrics == {"latency": 0.5, "exact_match": 1.0, "f1": 1.0}
    assert graded[1].metrics["exact_match"] == 0.0
    assert 0.0 < graded[1].metrics["f1"] < 1.0
    assert graded[2].metrics == {"exact_match": 0.0, "f1": 0.0}
    assert trajectories[0].metrics == {"latency": 0.5}
    assert benchmark.primary_metric == "exact_match"


def test_searchqa_reads_local_jsonl_relative_to_cwd(tmp_path, monkeypatch):
    rows = [row for _, row in _rows(3)]
    path = tmp_path / "searchqa.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    monkeypatch.chdir(tmp_path)
    benchmark = SearchQA(
        _config(
            data_path="searchqa.jsonl", limit=2, split={"train": 1, "dev": 0, "test": 0}
        )
    )

    splits = benchmark.load()

    assert sum(map(len, splits.values())) == 2
    assert {
        task.metadata["source_split"] for tasks in splits.values() for task in tasks
    } == {"local"}


def test_models_validate_and_expose_immutable_mappings():
    task = Task("one", "question", metadata={"kind": "qa"})
    trajectory = Trajectory(
        task,
        "finished",
        "answer",
        messages=({"role": "assistant"},),
        metrics={"score": 1.0},
        usage={"tokens": 3},
    )

    with pytest.raises(TypeError):
        task.metadata["kind"] = "changed"
    with pytest.raises(TypeError):
        trajectory.metrics["score"] = 0
    with pytest.raises(FrozenInstanceError):
        trajectory.output = "changed"
    with pytest.raises(ValueError, match="error_message"):
        Trajectory(task, "error", "")
    with pytest.raises(ValueError, match="status"):
        Trajectory(task, "running", "")


def test_searchqa_rejects_invalid_data_and_unknown_trajectories(monkeypatch):
    duplicate = _rows(1)[0]
    benchmark = SearchQA(_config())
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: (duplicate, duplicate))
    with pytest.raises(ValueError, match="duplicate task id"):
        benchmark.load()

    benchmark = SearchQA(_config(split={"train": 1, "dev": 0, "test": 0}))
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: _rows(1))
    benchmark.load()
    unknown = Task("unknown", "question", "answer")
    with pytest.raises(ValueError, match="unknown SearchQA task"):
        benchmark.grade((Trajectory(unknown, "finished", "answer"),))


@pytest.mark.parametrize("answers", ["", " \t", [], [" "], ["valid", ""], ["valid", 1]])
def test_searchqa_rejects_invalid_answers(monkeypatch, answers):
    benchmark = SearchQA(_config())
    row = {**_rows(1)[0][1], "answers": answers}
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: (("train", row),))

    with pytest.raises(ValueError, match="answers must be non-empty strings"):
        benchmark.load()


def test_searchqa_does_not_reward_blank_output(monkeypatch):
    benchmark = SearchQA(_config(split={"train": 1, "dev": 0, "test": 0}))
    row = {**_rows(1)[0][1], "answers": ["The"]}
    monkeypatch.setattr(benchmark, "_load_source_rows", lambda: (("train", row),))
    task = benchmark.load()["train"][0]

    blank, whitespace, correct = benchmark.grade(
        tuple(Trajectory(task, "finished", output) for output in ("", " \t", "The"))
    )

    assert blank.metrics == whitespace.metrics == {"exact_match": 0.0, "f1": 0.0}
    assert correct.metrics == {"exact_match": 1.0, "f1": 1.0}


@pytest.mark.parametrize("directory", [False, True])
def test_searchqa_rejects_empty_local_data(tmp_path, directory):
    path = tmp_path / "train.json"
    path.write_text("[]", encoding="utf-8")
    benchmark = SearchQA(_config(data_path=tmp_path if directory else path))

    with pytest.raises(ValueError, match="contains no tasks"):
        benchmark.load()


def test_searchqa_records_local_source_without_hf_revision(tmp_path):
    path = tmp_path / "searchqa.json"
    path.write_text(json.dumps([_rows(1)[0][1]]), encoding="utf-8")
    benchmark = SearchQA(
        _config(data_path=path, split={"train": 1, "dev": 0, "test": 0})
    )

    benchmark.load()

    assert benchmark.metadata == {"source": "local", "data_path": str(path)}
    assert SearchQA.metadata["source"] == "jinjiajie/flashrsi"
    assert SearchQA.metadata["config"] == "searchqa"


@pytest.mark.parametrize(
    ("options", "field"),
    [
        ({"seed": True}, "seed"),
        ({"seed": 1.5}, "seed"),
        ({"limit": False}, "limit"),
        ({"limit": 0}, "limit"),
        ({"limit": -1}, "limit"),
        ({"limit": "2"}, "limit"),
        ({"data_path": ""}, "data_path"),
        ({"data_path": 1}, "data_path"),
    ],
)
def test_searchqa_rejects_invalid_module_options(options, field):
    with pytest.raises(ValueError, match=f"benchmark.{field}"):
        SearchQA(_config(**options)).load()
