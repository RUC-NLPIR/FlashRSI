import asyncio
import json
import random
from dataclasses import replace

import pytest

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms import GEPA
from flashrsi.algorithms.gepa import _instruction
from flashrsi.algorithms.gepa._population import Member, frontier, prune
from flashrsi.core import Agent, Benchmark, Snapshot, Task, Trajectory

# Both harnesses load a prompt file, at their own native path.
PATHS = {MiniAgent: "prompts/system.md", ClaudeCode: "CLAUDE.md"}


class MemoryBenchmark(Benchmark):
    name = "memory"
    description = "Offline disjoint splits."
    primary_metric = "accuracy"
    metadata = {}

    def load(self):
        if self._splits is None:
            self._splits = {
                "train": tuple(
                    Task(f"train-{i}", f"train-{i}", "right") for i in range(2)
                ),
                "dev": (Task("dev-only", "dev-only", "right"),),
                "test": (Task("test-only", "test-only", "right"),),
            }
        return self._splits

    def grade(self, results):
        return tuple(
            replace(
                item,
                metrics={
                    "accuracy": float(
                        item.output == "right" and item.status == "finished"
                    )
                },
            )
            for item in results
        )


class ScriptedWorker(Agent):
    name = "scripted"
    description = "Finite offline Worker."

    def __init__(self, replies):
        super().__init__({"llm": {"model_name": "offline-worker"}})
        self.replies = iter(replies)
        self.prompts = []

    async def _run(self, prompt, working_dir=None):
        self.prompts.append(prompt)
        return Trajectory(output=next(self.replies))


def make_target(monkeypatch, cls=MiniAgent, winner="SOLVED"):
    """A target that answers correctly whenever its instruction holds `winner`."""
    calls = []

    async def run(self, prompt, working_dir=None):
        entry = self.snapshot.files.get(PATHS[cls])
        text = entry.content.decode() if entry is not None else ""
        # Access the activated version to exercise the real Agent context.
        for name, item in self.snapshot.files.items():
            assert (self.files_dir / name).read_bytes() == item.content
        calls.append((prompt, self.snapshot.id))
        return Trajectory(output="right" if winner in text else "wrong")

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline-target"}})
    return target, calls


def fenced(text):
    return f"Here it is:\n```\n{text}\n```\n"


def algorithm(target, worker, *, cls=MiniAgent, **config):
    return GEPA(
        {
            "reflection_minibatch_size": 2,
            # One baseline pass (1) plus one iteration (2 + 2 + 1).
            "max_metric_calls": 6,
            **config,
        },
        target=target,
        worker=worker,
        benchmark=MemoryBenchmark(),
    )


def member(index, per_task, score, text="", parents=()):
    return Member(
        index=index,
        snapshot=None,
        text=text or str(index),
        per_task=per_task,
        score=score,
        parents=parents,
    )


# -- the loop --------------------------------------------------------------


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_same_algorithm_rewrites_each_native_instruction_path(monkeypatch, cls):
    target, calls = make_target(monkeypatch, cls)
    original = target.snapshot
    worker = ScriptedWorker([fenced("Check the answer. SOLVED")])

    final = asyncio.run(algorithm(target, worker, cls=cls).evolve())

    assert isinstance(final, Snapshot)
    assert target.snapshot.id == final.id != original.id
    assert final.parent_id == original.id
    # The instruction is the file's whole content, not an appended fragment.
    assert final.files[PATHS[cls]].content == b"Check the answer. SOLVED\n"
    assert {p: f for p, f in final.files.items() if f.component != "prompt"} == {
        p: f for p, f in original.files.items() if f.component != "prompt"
    }
    # Train and dev only: test never reaches the target or the Worker.
    assert {prompt for prompt, _ in calls} == {"train-0", "train-1", "dev-only"}
    assert "test-only" not in worker.prompts[0]
    assert "RunConfig" not in worker.prompts[0]
    assert worker.prompts[0].splitlines()[0] == "[GEPA: propose]"
    assert PATHS[cls] in worker.prompts[0]


def test_claude_code_starts_from_an_absent_instruction_file(monkeypatch):
    target, _ = make_target(monkeypatch, ClaudeCode)
    # Claude Code's seed carries no CLAUDE.md; the empty baseline is its native
    # prompt, and the population still has a member zero to mutate.
    assert "CLAUDE.md" not in target.snapshot.files
    worker = ScriptedWorker([fenced("SOLVED")])

    algo = algorithm(target, worker, cls=ClaudeCode)
    final = asyncio.run(algo.evolve())

    assert algo._population[0].text == ""
    assert [member.score for member in algo._population] == [0.0, 1.0]
    assert final.files["CLAUDE.md"].content == b"SOLVED\n"


def test_the_reflection_reads_the_parents_own_scored_trajectories(monkeypatch):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker([fenced("SOLVED"), fenced("SOLVED again")])

    # Two iterations: 1 + 5 + 5 = 11.
    asyncio.run(algorithm(target, worker, max_metric_calls=11).evolve())

    # The first reflection sees the baseline failing; the second is given the
    # winner it just admitted, so it reads that member's successes.
    assert '"output": "wrong"' in worker.prompts[0]
    assert '"metrics": {"accuracy": 0.0}' in worker.prompts[0]
    assert '"output": "right"' in worker.prompts[1]
    assert "SOLVED" in worker.prompts[1].split("```")[1]


def test_a_candidate_failing_the_minibatch_screen_never_reaches_dev(monkeypatch):
    target, calls = make_target(monkeypatch)
    original = target.snapshot
    worker = ScriptedWorker([fenced("unrelated advice")])

    algo = algorithm(target, worker)
    final = asyncio.run(algo.evolve())

    assert final.id == original.id
    assert len(algo._population) == 1
    # Baseline dev, the parent minibatch and the candidate minibatch; the
    # rejected candidate is never scored on dev.
    assert algo._metric_calls == 5
    assert [prompt for prompt, _ in calls].count("dev-only") == 1


def test_the_current_version_never_moves_during_the_search(monkeypatch):
    target, _ = make_target(monkeypatch)
    original = target.snapshot
    # A winner, then two proposals that lose to it.
    worker = ScriptedWorker([fenced("SOLVED"), fenced("no good"), fenced("worse")])
    algo = algorithm(target, worker, max_metric_calls=16)

    # Record when the selected version moves, against how far the search got.
    updates = []
    update = type(target).update

    def spy(self, snapshot):
        updates.append((len(worker.prompts), snapshot.id))
        update(self, snapshot)

    monkeypatch.setattr(type(target), "update", spy)

    final = asyncio.run(algo.evolve())

    # Three iterations ran, and the one update happened only after all of them:
    # every candidate was therefore scored against the same baseline.
    assert len(worker.prompts) == 3
    assert updates == [(3, final.id)]
    assert final.id != original.id
    assert final.files["prompts/system.md"].content == b"SOLVED\n"
    assert algo._population[1].snapshot.id == final.id
    assert algo._population[1].parents == (0,)


def test_a_search_without_improvement_keeps_the_original_version(monkeypatch):
    target, _ = make_target(monkeypatch)
    original = target.snapshot
    algo = algorithm(target, ScriptedWorker([fenced("no improvement")]))

    final = asyncio.run(algo.evolve())

    assert final.id == target.snapshot.id == original.id


def test_reproposing_the_parents_own_instruction_costs_no_candidate(monkeypatch):
    target, calls = make_target(monkeypatch)
    worker = ScriptedWorker([fenced("SOLVED"), fenced("SOLVED")])

    algo = algorithm(target, worker, max_metric_calls=11)
    asyncio.run(algo.evolve())

    # The second iteration selects the winner it just admitted and proposes that
    # same text back, so it is dropped before a candidate is ever built: the
    # baseline (1), one full iteration (5) and the second parent screen (2).
    assert len(algo._population) == 2
    assert algo._metric_calls == 8
    assert [prompt for prompt, _ in calls].count("dev-only") == 2


def test_a_proposal_matching_another_member_is_dropped_before_evaluation(
    monkeypatch, tmp_path
):
    target, calls = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([fenced("SOLVED")]))
    algo._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algo._run_dir / name).mkdir(parents=True)
    # A population where the frontier owner is not the member that already
    # carries the instruction about to be proposed.
    algo._population = [
        member(0, {"dev-only": 1.0}, 1.0, text=""),
        member(1, {"dev-only": 0.0}, 0.0, text="SOLVED\n"),
    ]
    algo._population[0] = replace(algo._population[0], snapshot=target.snapshot)
    algo._metric_calls = 0

    asyncio.run(algo._iterate(algo.benchmark.train, algo.benchmark.dev, 0))

    # Only the parent's own minibatch was spent; no candidate reached dev.
    assert len(algo._population) == 2
    assert algo._metric_calls == 2
    assert "dev-only" not in [prompt for prompt, _ in calls]
    (record,) = (algo._run_dir / "trajectories").glob("*-decision.json")
    assert json.loads(record.read_text())["reason"] == "duplicate_instruction"


def test_promotion_is_recorded_with_the_whole_population(monkeypatch, tmp_path):
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([fenced("SOLVED")]))
    algo._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algo._run_dir / name).mkdir(parents=True)

    final = asyncio.run(algo.evolve())

    records = sorted((algo._run_dir / "trajectories").glob("*-decision.json"))
    admit, promote = (json.loads(path.read_text()) for path in records)
    assert admit["kind"] == "admit" and admit["candidate_id"] == final.id
    assert admit["parent_score"] == 0.0 and admit["score"] == 1.0
    assert promote["accepted"] is True and promote["metric_calls"] == 6
    assert [row["score"] for row in promote["population"]] == [0.0, 1.0]
    assert [row["per_task"] for row in promote["population"]] == [
        {"dev-only": 0.0},
        {"dev-only": 1.0},
    ]
    assert Snapshot.load(algo._run_dir / "snapshots" / f"{final.id}.json") == final


def test_a_rejected_proposal_records_its_reason(monkeypatch, tmp_path):
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([fenced("unrelated")]))
    algo._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algo._run_dir / name).mkdir(parents=True)

    asyncio.run(algo.evolve())

    records = sorted((algo._run_dir / "trajectories").glob("*-decision.json"))
    reject = json.loads(records[0].read_text())
    assert reject["kind"] == "reject"
    assert reject["reason"] == "failed_minibatch_screen"
    assert reject["iteration"] == 0 and reject["parent_index"] == 0


@pytest.mark.parametrize(
    "reply,reason",
    [
        ("```\n\n```", "empty_proposal"),
        # The seed's own text back, so nothing changed.
        (None, "unchanged_instruction"),
    ],
)
def test_each_unusable_proposal_records_its_own_reason(
    monkeypatch, tmp_path, reply, reason
):
    """A dead proposal is distinguishable from a scored rejection in the log."""
    target, calls = make_target(monkeypatch)
    seed = target.snapshot.files["prompts/system.md"].content.decode()
    worker = ScriptedWorker([fenced(seed) if reply is None else reply])
    algo = algorithm(target, worker)  # Budget for exactly one iteration.
    algo._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algo._run_dir / name).mkdir(parents=True)

    asyncio.run(algo.evolve())

    (record,) = sorted((algo._run_dir / "trajectories").glob("*-decision.json"))[:1]
    assert json.loads(record.read_text())["reason"] == reason
    # No candidate is built, so none is ever scored on dev.
    assert len(algo._population) == 1
    assert [prompt for prompt, _ in calls].count("dev-only") == 1


def test_a_failing_worker_aborts_the_run_rather_than_skipping(monkeypatch):
    """A provider error is not a search outcome; it must not be swallowed."""

    class Failing(Agent):
        name = "failing"
        description = "A Worker whose provider errors."

        def __init__(self):
            super().__init__({"llm": {"model_name": "offline-worker"}})

        async def _run(self, prompt, working_dir=None):
            return Trajectory(status="error", error_message="provider exploded")

    target, _ = make_target(monkeypatch)
    algo = algorithm(target, Failing())

    with pytest.raises(RuntimeError, match="Worker failed during propose"):
        asyncio.run(algo.evolve())

    # The baseline member survives; the run stops instead of promoting anything.
    assert len(algo._population) == 1


def test_only_the_rewritten_file_is_named_to_the_reflection(monkeypatch):
    """Other prompt files in the same component are neither shown nor touched."""
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker([fenced("SOLVED")])
    # MiniAgent's prompt component also holds prompts/extract.md, which serves
    # the evidence summariser and is not the agent's instructions.
    other = target.snapshot.files["prompts/extract.md"]

    algo = algorithm(target, worker)
    final = asyncio.run(algo.evolve())

    assert "prompts/system.md" in worker.prompts[0].splitlines()[1]
    assert "prompts/extract.md" not in worker.prompts[0]
    assert final.files["prompts/extract.md"] == other
    assert algo._path == "prompts/system.md"


# -- Pareto selection ------------------------------------------------------


def test_a_member_that_wins_one_task_stays_selectable(monkeypatch):
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([]))
    # Neither member dominates: each owns one task, so both can be parents.
    algo._population = [
        member(0, {"task-a": 1.0, "task-b": 0.0}, 0.5),
        member(1, {"task-a": 0.0, "task-b": 1.0}, 0.5),
    ]

    chosen = {algo._select(random.Random(seed)).index for seed in range(20)}

    assert chosen == {0, 1}


def test_a_dominated_member_is_pruned_out_of_the_frontier(monkeypatch):
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([]))
    algo._population = [
        member(0, {"task-a": 1.0, "task-b": 0.0}, 0.5),
        member(1, {"task-a": 1.0, "task-b": 1.0}, 1.0),
    ]

    chosen = {algo._select(random.Random(seed)).index for seed in range(20)}

    # Member 1 ties on task-a and wins task-b, so member 0 owns nothing.
    assert chosen == {1}


def test_current_best_ignores_the_frontier(monkeypatch):
    target, _ = make_target(monkeypatch)
    algo = algorithm(
        target, ScriptedWorker([]), candidate_selection_strategy="current_best"
    )
    algo._population = [
        member(0, {"task-a": 1.0, "task-b": 0.0}, 0.5),
        member(1, {"task-a": 0.0, "task-b": 1.0}, 0.9),
    ]

    assert {algo._select(random.Random(seed)).index for seed in range(20)} == {1}


def test_the_frontier_maps_each_task_to_its_best_members():
    population = [
        member(0, {"a": 1.0, "b": 0.0}, 0.5),
        member(1, {"a": 1.0, "b": 1.0}, 1.0),
    ]

    assert frontier(population) == {"a": {0, 1}, "b": {1}}


def test_pruning_keeps_one_owner_per_task_and_breaks_ties_by_score():
    population = [member(0, {}, 0.5), member(1, {}, 0.6), member(2, {}, 0.6)]

    assert prune({"a": {0, 1}, "b": {0, 2}}, population) == {"a": {1}, "b": {2}}


# -- parsing ---------------------------------------------------------------


def test_a_fenced_proposal_is_read_after_a_provider_preamble():
    assert (
        _instruction("Here it is:\n```text\nUse evidence.\n```\n") == "Use evidence.\n"
    )
    assert _instruction("```Verify inline.```") == "Verify inline.\n"
    assert _instruction("```\nLine one\nLine two\n```") == "Line one\nLine two\n"
    assert _instruction("no fence at all") == "no fence at all\n"
    assert _instruction("```\n\n```") == ""


def test_a_dangling_fence_in_an_echoed_request_is_not_a_block():
    """The prompt's own closing sentence ends in a lone ``` marker.

    A provider that quotes the request back after answering leaves an odd marker
    trailing the real block; pairing fences from the left keeps the answer,
    while taking the last two markers would return the echoed request.
    """
    reply = (
        "```\nAlways cite the source.\n```\n"
        "Provide the new instructions within ``` blocks."
    )

    assert _instruction(reply) == "Always cite the source.\n"


# -- configuration ---------------------------------------------------------


@pytest.mark.parametrize(
    "config,message",
    [
        ({"reflection_minibatch_size": 0}, "reflection_minibatch_size must be"),
        ({"max_metric_calls": 1.5}, "max_metric_calls must be a positive integer"),
        ({"seed": "42"}, "seed must be an integer"),
        ({"candidate_selection_strategy": "greedy"}, "must be one of"),
        ({"use_merge": True}, "merge is not implemented"),
    ],
)
def test_configuration_is_checked_before_any_execution(monkeypatch, config, message):
    target, calls = make_target(monkeypatch)
    with pytest.raises(ValueError, match=message):
        algorithm(target, ScriptedWorker([]), **config)
    assert not calls


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_the_target_names_its_own_instruction_file(monkeypatch, cls):
    """Unset, GEPA rewrites whatever file the harness declares as its own."""
    target, _ = make_target(monkeypatch, cls)

    algo = algorithm(target, ScriptedWorker([fenced("SOLVED")]), cls=cls)
    final = asyncio.run(algo.evolve())

    # Not a fixture: the real harness's own declaration, which is the path the
    # migration relies on so no algorithm branches on the harness name.
    assert algo._path == cls.instruction_file == PATHS[cls]
    assert final.files[PATHS[cls]].content == b"SOLVED\n"


@pytest.mark.parametrize(
    "declared,message",
    [
        (None, "declares no instruction_file"),
        ("", "declares no instruction_file"),
        # Outside the prompt component, so beyond what GEPA may evolve.
        ("skills/main.md", "outside its prompt component"),
        ("../escape.md", "invalid snapshot file path"),
    ],
)
def test_an_unusable_declared_instruction_file_is_rejected(
    monkeypatch, declared, message
):
    """The declaration is the only source, so GEPA checks it rather than trusting it."""
    target, calls = make_target(monkeypatch)
    monkeypatch.setattr(type(target), "instruction_file", declared)

    with pytest.raises(ValueError, match=message):
        algorithm(target, ScriptedWorker([]))

    assert not calls


def test_a_budget_too_small_for_one_iteration_is_rejected_at_startup(monkeypatch):
    """Reported at construction, before the runner creates an experiment dir."""
    target, calls = make_target(monkeypatch)

    with pytest.raises(ValueError, match="at least 6"):
        algorithm(target, ScriptedWorker([]), max_metric_calls=5)

    assert not calls


def test_the_default_budget_scales_to_the_data(monkeypatch):
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([]), max_metric_calls=None)

    # Below the 100-call floor: dev (1) + 10 × (2 + 2 + 1).
    assert algo._resolved_budget == (100, 5)


@pytest.mark.parametrize("split", ["train", "dev"])
def test_an_empty_required_split_is_rejected(monkeypatch, split):
    class Missing(MemoryBenchmark):
        def load(self):
            super().load()
            self._splits = {**self._splits, split: ()}
            return self._splits

    target, _ = make_target(monkeypatch)
    with pytest.raises(ValueError, match="non-empty train and dev splits"):
        GEPA(
            {},
            target=target,
            worker=ScriptedWorker([]),
            benchmark=Missing(),
        )


def test_duplicate_dev_task_ids_are_rejected(monkeypatch):
    class Duplicated(MemoryBenchmark):
        def load(self):
            super().load()
            repeated = Task("dev-only", "another question", "right")
            self._splits = {**self._splits, "dev": (*self._splits["dev"], repeated)}
            return self._splits

    target, _ = make_target(monkeypatch)
    with pytest.raises(ValueError, match="unique task_id"):
        GEPA(
            {},
            target=target,
            worker=ScriptedWorker([]),
            benchmark=Duplicated(),
        )
