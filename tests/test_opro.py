import asyncio
import json
from dataclasses import replace

import pytest

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms import OPRO
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
        path = PATHS[cls]
        entry = self.snapshot.files.get(path)
        text = entry.content.decode() if entry is not None else ""
        # Access the activated version to exercise the real Agent context.
        for name, item in self.snapshot.files.items():
            assert (self.files_dir / name).read_bytes() == item.content
        calls.append((prompt, self.snapshot.id))
        return Trajectory(output="right" if winner in text else "wrong")

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline-target"}})
    return target, calls


def graded_target(monkeypatch, scores):
    """A target whose score depends on which marker its instruction carries.

    Lets one step propose candidates of differing quality, which a winner/loser
    target cannot express.
    """
    calls = []

    async def run(self, prompt, working_dir=None):
        text = self.snapshot.files["prompts/system.md"].content.decode()
        marker = next((name for name in scores if name in text), None)
        calls.append((prompt, marker))
        # MemoryBenchmark scores "right" as 1.0; a partial marker answers only
        # the task whose index is under its share.
        share = scores.get(marker, 0.0)
        return Trajectory(output="right" if prompt < f"train-{share * 2:.0f}" else "no")

    monkeypatch.setattr(MiniAgent, "_run", run)
    return MiniAgent({"llm": {"model_name": "offline-target"}}), calls


def algorithm(target, worker, *, cls=MiniAgent, **config):
    # No instruction_path: the target names its own file.
    return OPRO(
        {"max_steps": 1, "num_candidates": 1, "score_threshold": 0.0, **config},
        target=target,
        worker=worker,
        benchmark=MemoryBenchmark(),
    )


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_same_algorithm_rewrites_each_native_instruction_path(monkeypatch, cls):
    target, calls = make_target(monkeypatch, cls)
    original = target.snapshot
    worker = ScriptedWorker(["prelude <INS>Check the answer. SOLVED</INS>"])

    final = asyncio.run(algorithm(target, worker, cls=cls).evolve())

    assert isinstance(final, Snapshot)
    assert target.snapshot.id == final.id != original.id
    assert final.parent_id == original.id
    # The instruction is the file's whole content, not an appended fragment.
    assert final.files[PATHS[cls]].content == b"Check the answer. SOLVED\n"
    assert {p: f for p, f in final.files.items() if f.component != "prompt"} == {
        p: f for p, f in original.files.items() if f.component != "prompt"
    }
    # Training only: dev and test never reach the target or the optimizer.
    assert {prompt for prompt, _ in calls} == {"train-0", "train-1"}
    assert calls[0][1] == original.id and calls[-1][1] == final.id
    assert "dev-only" not in worker.prompts[0]
    assert "test-only" not in worker.prompts[0]
    assert "RunConfig" not in worker.prompts[0]
    assert worker.prompts[0].splitlines()[0] == "[OPRO: propose]"
    assert PATHS[cls] in worker.prompts[0]


def test_claude_code_starts_from_an_absent_instruction_file(monkeypatch):
    target, _ = make_target(monkeypatch, ClaudeCode)
    # Claude Code's seed carries no CLAUDE.md; the empty baseline is its native
    # prompt, and the search still has a row zero to re-rank.
    assert "CLAUDE.md" not in target.snapshot.files
    worker = ScriptedWorker(["<INS>SOLVED</INS>"])

    algo = algorithm(target, worker, cls=ClaudeCode)
    final = asyncio.run(algo.evolve())

    assert algo._history[0]["text"] == ""
    assert [item["score"] for item in algo._history] == [0.0, 1.0]
    assert final.files["CLAUDE.md"].content == b"SOLVED\n"


def test_incumbent_never_moves_and_the_global_best_is_promoted_once(monkeypatch):
    target, calls = make_target(monkeypatch)
    original = target.snapshot
    worker = ScriptedWorker(
        ["<INS>SOLVED first</INS>", "<INS>a regression</INS>", "<INS>another one</INS>"]
    )

    algo = algorithm(target, worker, max_steps=3)
    final = asyncio.run(algo.evolve())

    assert [item["score"] for item in algo._history] == [0.0, 1.0, 0.0, 0.0]
    # Candidates branch from the best so far, so the two regressions descend
    # from the winner rather than replacing it.
    winner = algo._history[1]
    assert [
        algo._snapshots[item["snapshot_id"]].parent_id for item in algo._history[1:]
    ] == [
        original.id,
        winner["snapshot_id"],
        winner["snapshot_id"],
    ]
    assert final.files["prompts/system.md"].content == b"SOLVED first\n"
    assert final.id == winner["snapshot_id"]
    # Promotion is a pointer move, not a rerun: the last execution belongs to
    # the final regression, and the winner was only ever scored once.
    assert [snapshot for _, snapshot in calls].count(final.id) == 2
    assert calls[-1][1] == algo._history[-1]["snapshot_id"] != final.id


def test_promotion_is_recorded_with_the_whole_pool(monkeypatch, tmp_path):
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker(["<INS>SOLVED</INS>"]))
    algo._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algo._run_dir / name).mkdir(parents=True)

    final = asyncio.run(algo.evolve())

    (record,) = (algo._run_dir / "trajectories").glob("*-decision.json")
    decision = json.loads(record.read_text())
    assert decision["accepted"] is True
    assert decision["baseline_score"] == 0.0 and decision["score"] == 1.0
    assert decision["candidate_id"] == final.id
    assert [row["score"] for row in decision["history"]] == [0.0, 1.0]
    assert Snapshot.load(algo._run_dir / "snapshots" / f"{final.id}.json") == final


def test_a_search_without_improvement_keeps_the_original_version(monkeypatch):
    target, _ = make_target(monkeypatch)
    original = target.snapshot
    algo = algorithm(target, ScriptedWorker(["<INS>no improvement</INS>"]))

    final = asyncio.run(algo.evolve())

    assert final.id == target.snapshot.id == original.id


def test_history_rows_ascend_and_honor_threshold_and_size(monkeypatch):
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([]), history_size=2, score_threshold=0.5)
    snapshot = target.snapshot
    algo._history = [
        _scored("low", 0.25, snapshot),
        _scored("high", 1.0, snapshot),
        _scored("middle", 0.5, snapshot),
        _scored("upper", 0.75, snapshot),
    ]

    rendered = algo._render_history()

    assert "low" not in rendered  # Below score_threshold.
    assert "middle" not in rendered  # Trimmed by history_size.
    assert rendered.index("upper") < rendered.index("high")  # Ascending.
    assert "score:\n75" in rendered and "score:\n100" in rendered

    algo._history = [_scored("low", 0.25, snapshot)]
    assert algo._render_history() == "\n(none above threshold)\n"


def test_evidence_follows_the_leading_instruction(monkeypatch):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(["<INS>SOLVED</INS>", "<INS>a regression</INS>"])

    asyncio.run(algorithm(target, worker, max_steps=2).evolve())

    # Step one sees the baseline's failures; step two sees the new leader's
    # successes, not the regression scored most recently.
    assert '"output": "wrong"' in worker.prompts[0]
    assert '"output": "right"' in worker.prompts[1]


def test_evidence_is_bounded_by_max_evidence_chars(monkeypatch):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(["<INS>SOLVED</INS>"])

    asyncio.run(algorithm(target, worker, max_evidence_chars=20).evolve())

    evidence = worker.prompts[0].split("SCORED TASK EXAMPLES:\n")[1].split("\n")[0]
    assert len(evidence) == 21 and evidence.endswith("…")


def test_repeated_and_empty_proposals_are_dropped_without_evaluating(monkeypatch):
    target, calls = make_target(monkeypatch)
    worker = ScriptedWorker(["<INS>SOLVED</INS>", "<INS>SOLVED</INS>", "<INS></INS>"])

    algo = algorithm(target, worker, max_steps=3)
    asyncio.run(algo.evolve())

    # Baseline plus the single novel instruction; the repeat and the empty
    # reply produce no candidate and no target execution.
    assert len(algo._history) == 2
    assert len(calls) == 4  # Two train tasks, twice.


def test_several_candidates_in_one_step_branch_from_the_same_parent(monkeypatch):
    target, calls = graded_target(monkeypatch, {"WEAK": 0.5, "STRONG": 1.0})
    original = target.snapshot
    worker = ScriptedWorker(["<INS>WEAK</INS>", "<INS>STRONG</INS>"])

    algo = algorithm(target, worker, num_candidates=2)
    final = asyncio.run(algo.evolve())

    assert [item["score"] for item in algo._history] == [0.0, 0.5, 1.0]
    # Both candidates descend from the step's parent: the incumbent does not
    # move mid-step, so the stronger one is not built on top of the weaker.
    assert [
        algo._snapshots[item["snapshot_id"]].parent_id for item in algo._history[1:]
    ] == [original.id] * 2
    assert final.files["prompts/system.md"].content == b"STRONG\n"


def test_evidence_follows_the_best_candidate_found_within_a_step(monkeypatch):
    """A later candidate that only ties must not take over the evidence.

    `_best()` uses max(), which keeps the first maximum, so the evidence must
    use a strict comparison to stay consistent with the instruction that will
    actually be promoted.
    """
    calls = []

    async def run(self, prompt, working_dir=None):
        text = self.snapshot.files["prompts/system.md"].content.decode()
        marker = "TIED" if "TIED" in text else "FIRST" if "FIRST" in text else "base"
        calls.append(marker)
        # FIRST and TIED score identically, but each trajectory names the
        # instruction that produced it, so the evidence is traceable.
        return Trajectory(
            output="right" if marker != "base" else "no", messages=({"ran": marker},)
        )

    monkeypatch.setattr(MiniAgent, "_run", run)
    target = MiniAgent({"llm": {"model_name": "offline-target"}})
    worker = ScriptedWorker(
        ["<INS>FIRST</INS>", "<INS>TIED</INS>", "<INS>third</INS>", "<INS>fourth</INS>"]
    )

    algo = algorithm(target, worker, max_steps=2, num_candidates=2)
    final = asyncio.run(algo.evolve())

    assert [item["score"] for item in algo._history] == [0.0, 1.0, 1.0, 0.0, 0.0]
    # The tie is broken toward FIRST, both for promotion...
    assert final.files["prompts/system.md"].content == b"FIRST\n"
    # ...and for the evidence, which must stay on FIRST's own run. A >=
    # comparison would hand it to TIED and desynchronise the two.
    assert algo._best()["snapshot_id"] == algo._history[1]["snapshot_id"]
    produced = {
        message["ran"]
        for item in algo._leader
        for message in item.messages
        if "ran" in message
    }
    assert produced == {"FIRST"}


def test_duplicates_within_one_step_are_dropped_before_evaluation(monkeypatch):
    target, calls = make_target(monkeypatch)
    # The same instruction three times in a single step.
    worker = ScriptedWorker(["<INS>SOLVED</INS>"] * 3)

    algo = algorithm(target, worker, num_candidates=3)
    asyncio.run(algo.evolve())

    assert len(algo._history) == 2  # Baseline plus one distinct instruction.
    assert len(calls) == 4  # Two train tasks for the baseline, two for it.


@pytest.mark.parametrize(
    "config,message",
    [
        ({"max_steps": 0}, "max_steps must be an integer"),
        ({"num_candidates": 1.5}, "num_candidates must be an integer"),
        ({"seed": "42"}, "seed must be an integer"),
        ({"score_threshold": float("nan")}, "score_threshold must be finite"),
    ],
)
def test_configuration_is_checked_before_any_execution(monkeypatch, config, message):
    target, calls = make_target(monkeypatch)
    with pytest.raises(ValueError, match=message):
        algorithm(target, ScriptedWorker([]), **config)
    assert not calls


def test_an_empty_train_split_is_rejected(monkeypatch):
    class NoTraining(MemoryBenchmark):
        def load(self):
            super().load()
            self._splits = {**self._splits, "train": ()}
            return self._splits

    target, _ = make_target(monkeypatch)
    with pytest.raises(ValueError, match="non-empty train split"):
        OPRO(
            {},
            target=target,
            worker=ScriptedWorker([]),
            benchmark=NoTraining(),
        )


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_each_target_names_its_own_instruction_file(cls):
    # The declaration lives with the adapter, so OPRO never needs the harness
    # name and a run needs no knowledge of the file layout.
    assert cls.instruction_file == PATHS[cls]


@pytest.mark.parametrize(
    "declared,message",
    [
        (None, "declares no instruction_file"),
        ("", "declares no instruction_file"),
        # In no component OPRO may evolve, so not something to rewrite.
        ("skills/main.md", "outside its prompt component"),
        ("../escape.md", "invalid snapshot file path"),
    ],
)
def test_an_unusable_declared_instruction_file_is_rejected(
    monkeypatch, declared, message
):
    """The declaration is the only source, so OPRO checks it rather than trusting it."""
    target, calls = make_target(monkeypatch)
    monkeypatch.setattr(MiniAgent, "instruction_file", declared)

    with pytest.raises(ValueError, match=message):
        algorithm(target, ScriptedWorker([]))
    assert not calls


def _scored(text, score, snapshot):
    return {"text": text, "score": score, "snapshot_id": snapshot.id}
