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
    (domain / "prompts" / "components").mkdir(parents=True)
    (domain / "db.json").write_text('{"users": {}}')
    for name, title in (("doc_a", "Fees"), ("doc_b", "Cards")):
        (domain / "documents" / f"{name}.json").write_text(
            json.dumps({"id": name, "title": title, "content": f"{title} content."})
        )
    (domain / "prompts" / "components" / "policy_header.md").write_text(
        "# Rho-Bank Customer Service Policy\n"
    )
    # One template per placeholder kind the renderer has to handle.
    (domain / "prompts" / "all_tools.md").write_text(
        "{{component:policy_header}}\n\n{{all_tools_dense_instructions}}\n"
    )
    (domain / "prompts" / "full_kb.md").write_text(
        "{{component:policy_header}}\n\n<kb>\n{{full_knowledge_base}}\n</kb>\n"
    )
    (domain / "prompts" / "required_docs.md").write_text(
        "{{component:policy_header}}\n\n<docs>\n{{required_documents}}\n</docs>\n"
    )
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
    # The agent receives the domain's own policy, not text written here.
    assert task.question.startswith("# Rho-Bank Customer Service Policy")
    assert task.metadata["variant"] == "alltools"
    # A placeholder the simulator fills at run time is left untouched.
    assert "{{all_tools_dense_instructions}}" in task.question
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
    assert benchmark.metadata == {
        "source": "local",
        "data_path": str(domain),
        "variant": "alltools",
    }

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


def test_reads_the_id_from_the_file_rather_than_its_name(tmp_path):
    """The tau2 runtime keys on the id inside each file, not the filename."""
    domain = _domain(tmp_path)
    path = domain / "tasks" / "task_001.json"
    task = json.loads(path.read_text())
    task["id"] = "task_999"
    path.write_text(json.dumps(task))

    (loaded,) = Tau3Banking(_single(domain)).load()["train"]

    assert loaded.task_id == "task_999"
    assert loaded.metadata["task_path"] == "tasks/task_001.json"


def test_variant_selects_the_policy_and_the_knowledge_it_inlines(tmp_path):
    domain = _domain(tmp_path)

    full = Tau3Banking({**_single(domain), "variant": "full_kb"}).load()["train"][0]
    golden = Tau3Banking({**_single(domain), "variant": "golden_retrieval"}).load()[
        "train"
    ][0]

    # full_kb inlines every document; golden_retrieval only the required ones.
    assert "Fees content." in full.question and "Cards content." in full.question
    assert "Fees content." in golden.question
    assert "Cards content." not in golden.question
    assert "{{" not in full.question and "{{" not in golden.question
    assert full.metadata["variant"] == "full_kb"
    assert golden.metadata["variant"] == "golden_retrieval"
    # Components are expanded in every variant.
    assert full.question.startswith("# Rho-Bank Customer Service Policy")


def test_variant_is_validated_and_recorded_in_metadata(tmp_path):
    domain = _domain(tmp_path)
    with pytest.raises(ValueError, match="Unknown tau3 Banking retrieval variant"):
        Tau3Banking({**_single(domain), "variant": "does-not-exist"})

    benchmark = Tau3Banking({**_single(domain), "variant": "full_kb"})
    benchmark.load()
    assert benchmark.metadata["variant"] == "full_kb"


def test_rejects_a_domain_without_its_prompts(tmp_path):
    domain = _domain(tmp_path)
    (domain / "prompts" / "all_tools.md").unlink()
    with pytest.raises(ValueError, match="missing all_tools.md"):
        Tau3Banking(_single(domain)).load()

    other = _domain(tmp_path / "other")
    (other / "prompts" / "components" / "policy_header.md").unlink()
    with pytest.raises(ValueError, match="missing component: policy_header"):
        Tau3Banking(_single(other)).load()


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
