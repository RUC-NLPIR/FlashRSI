import hashlib
import json
from dataclasses import replace

import pytest

from flashrsi.benchmarks import Tau3Banking
from flashrsi.core import Task, Trajectory

SECRET_ACTION = "ORACLE-GRADING-ACTION"


def _domain(root, *, count=1):
    """A minimal tau2 domain with the same shape as banking_knowledge."""
    domain = root / "banking_knowledge"
    (domain / "tasks").mkdir(parents=True)
    (domain / "documents").mkdir()
    (domain / "db.json").write_text('{"users": {}}')
    (domain / "documents" / "doc_a.json").write_text('{"id": "doc_a"}')
    for index in range(1, count + 1):
        name = f"task_{index:03d}"
        (domain / "tasks" / f"{name}.json").write_text(
            json.dumps(
                {
                    "id": name,
                    "user_scenario": {
                        "instructions": f"You are a customer, {name}. Ask about fees."
                    },
                    "initial_state": None,
                    "evaluation_criteria": {
                        "actions": [{"name": SECRET_ACTION}],
                        "reward_basis": ["DB"],
                    },
                    "user_tools": ["apply_for_credit_card"],
                    "required_documents": ["doc_a"],
                }
            )
        )
    return domain


def _single(path):
    return {"data_path": path, "split": {"train": 1, "dev": 0, "test": 0}}


def test_local_task_carries_the_domain_not_a_question(tmp_path):
    domain = _domain(tmp_path)
    benchmark = Tau3Banking(_single(domain))

    (task,) = benchmark.load()["train"]

    assert benchmark.load() is benchmark.load()
    assert benchmark.dev == benchmark.test == ()
    assert task.task_id == "task_001"
    # The domain directory travels in env; there is no answer to match.
    assert task.env == str(domain.resolve())
    assert task.ground_truth is None
    # The agent is the support representative, not the simulated customer.
    assert "customer service representative" in task.question
    assert task.metadata["user_instructions"] not in task.question
    assert "Ask about fees" not in task.question
    assert task.metadata["user_instructions"].startswith("You are a customer,")
    assert task.metadata["source_split"] == "unassigned"
    assert task.metadata["reward_basis"] == ("DB",)
    assert task.metadata["user_tools"] == ("apply_for_credit_card",)
    assert task.metadata["required_documents"] == ("doc_a",)
    assert task.metadata["has_initial_state"] is False
    # Grading targets stay in the domain files, never on the Task.
    assert SECRET_ACTION not in repr(task)
    assert benchmark.metadata == {"source": "local", "data_path": str(domain)}

    path = domain / "tasks" / "task_001.json"
    assert task.metadata["task_path"] == "tasks/task_001.json"
    assert (
        task.metadata["task_checksum"] == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    path.write_text(
        json.dumps({"id": "task_001", "user_scenario": {"instructions": "x"}})
    )
    changed = Tau3Banking(_single(domain)).load()["train"][0]
    assert changed.metadata["task_checksum"] != task.metadata["task_checksum"]


def test_collection_uses_reproducible_disjoint_splits_and_limit(tmp_path):
    domain = _domain(tmp_path, count=9)
    full = Tau3Banking({"data_path": domain, "seed": 11}).load()
    limited = Tau3Banking({"data_path": domain, "seed": 11, "limit": 3}).load()
    repeated = Tau3Banking({"data_path": domain, "seed": 11}).load()

    assert tuple(full) == ("train", "dev", "test")
    assert sum(map(len, full.values())) == 9
    assert sum(map(len, limited.values())) == 3
    assert [task.task_id for task in full["train"]] == [
        task.task_id for task in repeated["train"]
    ]
    ids = [task.task_id for tasks in full.values() for task in tasks]
    assert len(ids) == len(set(ids)) == 9
    for name, tasks in limited.items():
        assert {task.task_id for task in tasks} <= {task.task_id for task in full[name]}


def test_grades_only_a_matching_simulator_event(tmp_path):
    domain = _domain(tmp_path)
    benchmark = Tau3Banking(_single(domain))
    (task,) = benchmark.load()["train"]

    def event(**overrides):
        return {
            "type": "Tau2Simulator",
            "task_id": task.task_id,
            "task_checksum": task.metadata["task_checksum"],
            **overrides,
        }

    graded = benchmark.grade(
        (
            Trajectory(
                task=task,
                status="finished",
                output="resolved",
                messages=({"type": "Conversation"}, event(reward=1.0)),
                metrics={"turns": 4},
            ),
            Trajectory(
                task=task,
                status="finished",
                output="",
                messages=(event(reward=0.0),),
            ),
            Trajectory(
                task=task,
                status="error",
                output="",
                error_message="simulator unavailable",
            ),
        )
    )

    assert graded[0].metrics == {"turns": 4, "reward": 1.0}
    assert graded[1].metrics == {"reward": 0.0}
    # A failed run scores zero without needing a simulator event.
    assert graded[2].metrics == {"reward": 0.0}
    assert benchmark.primary_metric == "reward"


@pytest.mark.parametrize(
    "messages",
    [
        (),
        ({"type": "Conversation"},),
        ({"type": "Tau2Simulator", "task_id": "other", "reward": 1.0},),
        ({"type": "Tau2Simulator", "task_id": "task_001", "reward": 1.0},),
    ],
)
def test_grading_rejects_a_missing_or_mismatched_simulator_event(tmp_path, messages):
    benchmark = Tau3Banking(_single(_domain(tmp_path)))
    (task,) = benchmark.load()["train"]
    trajectory = Trajectory(
        task=task, status="finished", output="done", messages=messages
    )
    with pytest.raises(ValueError, match="Tau2Simulator event"):
        benchmark.grade((trajectory,))


@pytest.mark.parametrize("reward", [None, "1.0", -0.5, 1.5, True])
def test_grading_rejects_an_unusable_reward(tmp_path, reward):
    benchmark = Tau3Banking(_single(_domain(tmp_path)))
    (task,) = benchmark.load()["train"]
    trajectory = Trajectory(
        task=task,
        status="finished",
        output="done",
        messages=(
            {
                "type": "Tau2Simulator",
                "task_id": task.task_id,
                "task_checksum": task.metadata["task_checksum"],
                "reward": reward,
            },
        ),
    )
    with pytest.raises(ValueError, match="reward must be"):
        benchmark.grade((trajectory,))


def test_grading_requires_loaded_benchmark_tasks(tmp_path):
    benchmark = Tau3Banking(_single(_domain(tmp_path)))
    with pytest.raises(RuntimeError, match="call load"):
        benchmark.grade(())
    (task,) = benchmark.load()["train"]
    # A Task the benchmark did not produce cannot be graded against its rules.
    forged = replace(task, metadata={**task.metadata, "task_checksum": "0" * 64})
    for candidate in (None, Task("task_001", "q"), forged):
        with pytest.raises(ValueError, match="loaded benchmark Task"):
            benchmark.grade(
                (
                    Trajectory(
                        task=candidate,
                        status="finished",
                        output="done",
                        messages=({"type": "Tau2Simulator"},),
                    ),
                )
            )


def test_rejects_a_path_that_is_not_a_tau2_domain(tmp_path):
    with pytest.raises(ValueError, match="tau2 domain directory"):
        Tau3Banking({"data_path": tmp_path}).load()
    empty = tmp_path / "empty"
    (empty / "tasks").mkdir(parents=True)
    (empty / "db.json").write_text("{}")
    with pytest.raises(ValueError, match="no task files"):
        Tau3Banking({"data_path": empty}).load()


def test_requires_its_own_benchmark_name():
    with pytest.raises(ValueError, match="benchmark.name: tau3_banking"):
        Tau3Banking({"benchmark": {"name": "searchqa"}})
