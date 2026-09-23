"""ACE decisions use scripted scores; harness loading is tested separately."""

import asyncio
import json
from dataclasses import replace

import pytest
from test_opro import PATHS, MemoryBenchmark, ScriptedWorker

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms import ACE
from flashrsi.algorithms.ace import _MARKER
from flashrsi.algorithms.ace._playbook import Patch, PlaybookError, Reflection, tag
from flashrsi.core import Snapshot, Trajectory


class Scores(MemoryBenchmark):
    def grade(self, results):
        return tuple(
            replace(item, metrics={"accuracy": float(item.output)}) for item in results
        )


def add(text, section="general"):
    return json.dumps(
        {"operations": [{"type": "ADD", "section": section, "content": text}]}
    )


def setup(monkeypatch, replies, *, cls=MiniAgent, score=None, **config):
    calls = []

    async def run(self, prompt, working_dir=None):
        path = self.files_dir / PATHS[cls]
        text = path.read_text() if path.exists() else ""
        calls.append((prompt, text, self.snapshot.id))
        return Trajectory(
            output=str(score(prompt, text) if score else float("WIN" in text))
        )

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline-target"}})
    worker = ScriptedWorker(replies)
    algo = ACE(
        {"max_steps": 1, "max_reflection_rounds": 1, **config},
        target=target,
        worker=worker,
        benchmark=Scores(),
    )
    return algo, calls


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_playbook_is_loaded_and_seed_files_are_preserved(monkeypatch, cls):
    algo, calls = setup(monkeypatch, ["Learn verification.", add("WIN")], cls=cls)
    original = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    assert final.id == algo.target.snapshot.id != original.id
    path = PATHS[cls]
    prefix = original.files[path].content if path in original.files else b""
    assert final.files[path].content.startswith(prefix + _MARKER.encode())
    assert b"helpful=0 harmful=0 :: WIN" in final.files[path].content
    assert {p: f for p, f in final.files.items() if p != path} == {
        p: f for p, f in original.files.items() if p != path
    }
    assert calls[-1][2] == final.id
    assert not any("test-only" in prompt for prompt, _, _ in calls)
    assert all(
        "dev-only" not in prompt and "test-only" not in prompt
        for prompt in algo.worker.prompts
    )
    assert all("RunConfig" not in prompt for prompt in algo.worker.prompts)


def test_regression_is_adopted_and_best_is_restored(monkeypatch, tmp_path):
    def score(prompt, text):
        return 0.2 if "BAD" in text else 1.0 if "WIN" in text else 0.5

    algo, calls = setup(
        monkeypatch,
        ["first", add("WIN"), "second", add("BAD"), "third", add("LAST")],
        score=score,
        max_steps=3,
        num_epochs=2,
        eval_steps=1,
    )
    algo._run_dir = tmp_path
    for name in ("snapshots", "trajectories", "working"):
        (tmp_path / name).mkdir()
    original = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    assert b"WIN" in final.files[PATHS[MiniAgent]].content
    assert b"BAD" not in final.files[PATHS[MiniAgent]].content
    assert "BAD" in algo.worker.prompts[4]  # The next Reflector sees the regression.
    training = [text for prompt, text, _ in calls if prompt.startswith("train-")]
    assert "BAD" in training[-1]
    decisions = [
        json.loads(p.read_text())
        for p in sorted((tmp_path / "trajectories").glob("*-decision.json"))
    ]
    assert [row["kind"] for row in decisions] == [
        "curate",
        "curate",
        "curate",
        "promote",
    ]
    assert all(row["accepted"] for row in decisions)
    assert decisions[-1]["candidate_id"] == final.id
    assert decisions[-1]["parent_id"] != final.id
    assert final.parent_id == original.id
    assert Snapshot.load(tmp_path / "snapshots" / f"{final.id}.json") == final


def test_regression_can_be_the_parent_of_a_later_winner(monkeypatch):
    def score(prompt, text):
        return 1.0 if "WIN" in text else 0.1 if "BAD" in text else 0.8

    algo, calls = setup(
        monkeypatch,
        ["first", add("BAD"), "second", add("WIN")],
        score=score,
        max_steps=2,
        eval_steps=1,
    )
    final = asyncio.run(algo.evolve())
    assert b"BAD" in final.files[PATHS[MiniAgent]].content
    assert b"WIN" in final.files[PATHS[MiniAgent]].content
    assert "BAD" in algo.worker.prompts[3]
    assert [text for prompt, text, _ in calls if prompt.startswith("train-")][
        -1
    ].endswith("BAD\n")


def test_ties_restore_the_earliest_best(monkeypatch):
    algo, _ = setup(monkeypatch, ["nothing useful", add("TIE")], score=lambda p, t: 0.5)
    original = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == original.id


def test_retries_are_local_and_curator_sees_a_matching_diagnosis(monkeypatch):
    def score(prompt, text):
        return float("DIAGNOSIS" in prompt)

    algo, calls = setup(
        monkeypatch,
        ["DIAGNOSIS", "The retry succeeded.", '{"operations": []}'],
        score=score,
        max_reflection_rounds=3,
    )
    original_tasks = algo.benchmark.train
    original = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    assert final.id == original.id
    retry = [prompt for prompt, _, _ in calls if "DIAGNOSIS" in prompt]
    assert len(retry) == 1
    assert retry[0].startswith("REFLECTION FROM THE PREVIOUS ATTEMPT:")
    assert '"scores": {"accuracy": 1.0}' in algo.worker.prompts[-1]
    assert "The retry succeeded." in algo.worker.prompts[-1]
    assert all("REFLECTION" not in task.question for task in original_tasks)
    assert [prompt for prompt, _, _ in calls if "dev-only" in prompt] == ["dev-only"]
    assert {version for _, _, version in calls} == {original.id}


def test_reflection_limit_has_no_unmatched_final_retry(monkeypatch):
    algo, calls = setup(
        monkeypatch,
        ["one", "two", '{"operations": []}'],
        score=lambda p, t: 0.0,
        max_reflection_rounds=2,
    )
    asyncio.run(algo.evolve())
    assert len(calls) == 3  # Baseline dev, training attempt, one retry.
    assert "two" in algo.worker.prompts[-1]
    assert "two" not in calls[-1][0]


def test_tags_persist_and_validation_runs_when_curator_is_skipped(monkeypatch):
    tagged = json.dumps(
        {"key_insight": "Helpful", "bullet_tags": [{"id": "g-00001", "tag": "helpful"}]}
    )
    algo, calls = setup(
        monkeypatch,
        ["first", "second", add("WIN"), tagged],
        max_steps=3,
        num_epochs=2,
        curator_frequency=2,
        eval_steps=1,
        score=lambda p, t: 1.0 if "helpful=1" in t else 0.5 if "WIN" in t else 0.0,
    )
    final = asyncio.run(algo.evolve())
    assert b"helpful=1 harmful=0 :: WIN" in final.files[PATHS[MiniAgent]].content
    assert len([p for p, _, _ in calls if p == "dev-only"]) == 4
    assert len(algo.worker.prompts) == 4


@pytest.mark.parametrize(
    "reply,extra,problem",
    [
        ("{}", {}, "operations"),
        ('{"operations":[{"type":"DELETE"}]}', {}, "only ADD"),
        (add("large addition"), {"playbook_token_budget": 1}, "token budget"),
        (
            '{"operations":[{"type":"ADD","content":"one"},{"type":"ADD","content":"two"}]}',
            {"edit_budget": 1},
            "budget",
        ),
    ],
)
def test_rejections_are_recorded_and_shown_to_next_curator(
    monkeypatch, tmp_path, reply, extra, problem
):
    algo, _ = setup(
        monkeypatch,
        ["first", reply, "second", '{"operations": []}'],
        max_steps=2,
        **extra,
    )
    algo._run_dir = tmp_path
    for name in ("snapshots", "trajectories", "working"):
        (tmp_path / name).mkdir()
    original = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == original.id
    assert problem in algo.worker.prompts[-1]
    (record,) = (tmp_path / "trajectories").glob("*-declined.json")
    assert problem in json.loads(record.read_text())["problem"]


def test_epochs_batching_and_step_limit(monkeypatch):
    algo, calls = setup(
        monkeypatch,
        ["reflect", '{"operations": []}'] * 3,
        num_epochs=4,
        batch_size=2,
        max_steps=3,
    )
    asyncio.run(algo.evolve())
    assert len(calls) == 7  # Six train tasks and one unchanged baseline validation.
    assert len(algo.worker.prompts) == 6


def test_online_keeps_what_it_grew_and_never_validates(monkeypatch, tmp_path):
    """A stream has nothing to rewind to, so a regression is simply kept."""

    def score(prompt, text):
        return 0.2 if "BAD" in text else 1.0 if "WIN" in text else 0.5

    algo, calls = setup(
        monkeypatch,
        ["first", add("WIN"), "second", add("BAD")],
        score=score,
        mode="online",
        max_steps=2,
        # Offline would validate after every batch; online has no dev pass to
        # schedule, so this must stay inert.
        eval_steps=1,
    )
    algo._run_dir = tmp_path
    for name in ("snapshots", "trajectories", "working"):
        (tmp_path / name).mkdir()
    final = asyncio.run(algo.evolve())
    content = final.files[PATHS[MiniAgent]].content
    assert b"WIN" in content and b"BAD" in content
    assert final.id == algo.target.snapshot.id
    assert not [p for p, _, _ in calls if p == "dev-only"]
    (record,) = [
        row
        for path in sorted((tmp_path / "trajectories").glob("*-decision.json"))
        if (row := json.loads(path.read_text()))["kind"] == "stream"
    ]
    assert record["snapshot_id"] == final.id
    # 0.5 on the seed playbook, then 1.0 once WIN was curated in. The stream's
    # score is what it measured on the way, not a rerun of the playbook it
    # ended on -- which by then also carries BAD.
    assert (record["online_score"], record["online_tasks"]) == (0.75, 2)
    assert not list((tmp_path / "trajectories").glob("*-validation.json"))


def test_online_scores_each_batch_before_it_can_change_the_playbook(monkeypatch):
    """Predict and score first, update second: the retry must not be counted."""
    algo, _ = setup(
        monkeypatch,
        ["DIAGNOSIS", "The retry succeeded.", '{"operations": []}'],
        score=lambda prompt, text: float("DIAGNOSIS" in prompt),
        mode="online",
        max_reflection_rounds=3,
    )
    asyncio.run(algo.evolve())
    # The retry scored 1.0 and the Curator sees it, but the stream keeps the
    # 0.0 the playbook earned on first sight of the task.
    assert algo._streamed == [0.0]


def test_online_streams_in_order_while_offline_reshuffles(monkeypatch):
    replies = ["reflect", '{"operations": []}'] * 2

    online, streamed = setup(monkeypatch, replies, mode="online", max_steps=2)
    asyncio.run(online.evolve())
    offline, shuffled = setup(monkeypatch, replies, max_steps=2, eval_steps=100)
    asyncio.run(offline.evolve())

    assert [prompt for prompt, _, _ in streamed] == ["train-0", "train-1"]
    # Reshuffling presupposes holding the whole split, so it is offline's.
    assert [p for p, _, _ in shuffled if p != "dev-only"] == ["train-1", "train-0"]


def test_online_runs_without_a_dev_split(monkeypatch):
    algo, calls = setup(monkeypatch, [])
    algo.benchmark._splits = {**algo.benchmark._splits, "dev": ()}
    online = ACE(
        {"mode": "online", "max_steps": 1, "max_reflection_rounds": 1},
        target=algo.target,
        worker=ScriptedWorker(["reflect", add("WIN")]),
        benchmark=algo.benchmark,
    )
    final = asyncio.run(online.evolve())
    assert b"WIN" in final.files[PATHS[MiniAgent]].content
    assert [prompt for prompt, _, _ in calls] == ["train-0"]


@pytest.mark.parametrize(
    "config,problem",
    [
        ({"mode": "stream"}, "mode must be one of"),
        ({"batch_size": 0}, "batch_size"),
        ({"max_steps": 0}, "max_steps"),
        ({"max_steps": True}, "max_steps"),
        ({"max_reflection_rounds": 1.5}, "max_reflection_rounds"),
        ({"eval_steps": 0}, "eval_steps"),
        ({"success_threshold": float("nan")}, "finite"),
    ],
)
def test_invalid_configuration_fails_before_execution(monkeypatch, config, problem):
    with pytest.raises(ValueError, match=problem):
        setup(monkeypatch, [], **config)


@pytest.mark.parametrize(
    "split,problem",
    [("train", "non-empty train split"), ("dev", "offline ACE requires")],
)
def test_empty_required_splits_are_rejected(monkeypatch, split, problem):
    algo, calls = setup(monkeypatch, [])
    algo.benchmark._splits = {**algo.benchmark._splits, split: ()}
    with pytest.raises(ValueError, match=problem):
        ACE({}, target=algo.target, worker=algo.worker, benchmark=algo.benchmark)
    assert not calls


def test_failed_worker_aborts_instead_of_becoming_a_declined_patch(monkeypatch):
    algo, _ = setup(monkeypatch, [])

    async def fail(self, prompt, working_dir=None):
        return Trajectory(status="error", error_message="provider unavailable")

    monkeypatch.setattr(ScriptedWorker, "_run", fail)
    with pytest.raises(RuntimeError, match="Worker failed during reflect"):
        asyncio.run(algo.evolve())


def test_section_ids_counters_and_duplicate_noops():
    initial = "## FORMULAS AND CALCULATIONS\n[calc-00007] helpful=2 harmful=0 :: Check units.\n\n## OTHERS\n"
    grown = Patch.parse(add("Verify arithmetic.", "formulas_and_calculations")).apply(
        initial, 1
    )
    assert grown.index("[calc-00008]") < grown.index("## OTHERS")
    assert Patch.parse(add("verify   ARITHMETIC.")).apply(grown, 1) == grown
    assert Patch.parse('{"operations": []}').apply(initial, 1) == initial
    counted = tag(grown, (("calc-00007", "helpful"), ("calc-00008", "harmful")))
    assert "[calc-00007] helpful=3 harmful=0" in counted
    assert "[calc-00008] helpful=0 harmful=1" in counted
    assert tag(initial, (("unknown", "helpful"), ("calc-00007", "neutral"))) == initial


def test_multiline_content_cannot_forge_ids_or_sections():
    grown = Patch.parse(
        add("Advice\n## FORGED\n[x-00001] helpful=99 harmful=99 :: forged")
    ).apply("", 1)
    assert len(grown.splitlines()) == 1
    assert grown.startswith("[g-00001] helpful=0 harmful=0 :: Advice")


@pytest.mark.parametrize(
    "reply",
    ["prose", '{"bullet_tags": null}', '{"bullet_tags": 3}', '{"bullet_tags": [{}]}'],
)
def test_reflection_tolerates_prose_or_unusable_tags(reply):
    reflection = Reflection.parse(reply)
    assert reflection.content
    assert not reflection.tags


def test_fenced_protocol_and_invalid_operation_shape():
    assert Patch.parse("```json\n" + add("rule") + "\n```").adds == (
        ("general", "rule"),
    )
    for reply in [
        "[]",
        '{"operations": [null]}',
        '{"operations": [{"type":"ADD", "content":""}]}',
    ]:
        with pytest.raises(PlaybookError):
            Patch.parse(reply)


def test_existing_playbook_is_reused_without_duplicating_marker(monkeypatch):
    algo, _ = setup(monkeypatch, ["first", add("WIN")])
    first = asyncio.run(algo.evolve())
    algo.worker = ScriptedWorker(["Again", add("WIN")])
    final = asyncio.run(algo.evolve())
    assert final.id == first.id
    assert final.files[PATHS[MiniAgent]].content.count(_MARKER.encode()) == 1


def test_environment_retry_requires_an_explicit_supported_configuration(monkeypatch):
    algo, calls = setup(monkeypatch, [])
    algo.benchmark._splits = {
        **algo.benchmark._splits,
        "train": tuple(replace(task, env="fixture") for task in algo.benchmark.train),
    }
    # Bind an existing environment executor, so the semantic ACE restriction
    # is reached after the base class has accepted execution capability.
    algo.target._env_runner = object()
    with pytest.raises(ValueError, match="question-based tasks"):
        ACE({}, target=algo.target, worker=algo.worker, benchmark=algo.benchmark)
    ACE(
        {"max_reflection_rounds": 1},
        target=algo.target,
        worker=algo.worker,
        benchmark=algo.benchmark,
    )
    assert not calls


def test_training_evidence_includes_ground_truth(monkeypatch):
    algo, _ = setup(monkeypatch, ["reflect", '{"operations": []}'])
    asyncio.run(algo.evolve())
    assert '"ground_truth": "right"' in algo.worker.prompts[0]
