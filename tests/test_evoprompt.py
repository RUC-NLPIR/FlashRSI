import asyncio
import json
import random
from dataclasses import replace

import pytest

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms import EvoPrompt
from flashrsi.algorithms.evoprompt import _top_k
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
                "train": (Task("train-only", "train-only", "right"),),
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


def tagged(text):
    return f"Here is the new prompt:\n<prompt>{text}</prompt>\n"


def algorithm(target, worker, **config):
    return EvoPrompt(
        {"population_size": 2, "max_steps": 1, "selection": "random", **config},
        target=target,
        worker=worker,
        benchmark=MemoryBenchmark(),
    )


def run_dir(algo, tmp_path):
    algo._run_dir = tmp_path / "run"
    for name in ("snapshots", "trajectories", "working"):
        (algo._run_dir / name).mkdir(parents=True)
    return algo._run_dir


def seed_population(algo, snapshot, members):
    """Start a generation from fixed (text, score) pairs on a real snapshot.

    _ga commits children from their parent, so a member needs a usable
    snapshot; only the text and score vary between these cases.
    """
    algo._path = "prompts/system.md"
    algo._snapshots = {snapshot.id: snapshot}
    algo._population = [
        {"snapshot_id": snapshot.id, "text": text, "score": score}
        for text, score in members
    ]


def decisions(directory):
    return [
        json.loads(path.read_text())
        for path in sorted((directory / "trajectories").glob("*-decision.json"))
    ]


# -- the loop --------------------------------------------------------------


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_same_algorithm_rewrites_each_native_instruction_path(monkeypatch, cls):
    target, calls = make_target(monkeypatch, cls)
    original = target.snapshot
    # One paraphrase to fill the population, then two crossover children.
    worker = ScriptedWorker([tagged("a try"), tagged("SOLVED"), tagged("also weak")])

    final = asyncio.run(algorithm(target, worker).evolve())

    assert isinstance(final, Snapshot)
    assert target.snapshot.id == final.id != original.id
    # The prompt is the file's whole content, not an appended fragment.
    assert final.files[PATHS[cls]].content == b"SOLVED\n"
    assert {p: f for p, f in final.files.items() if f.component != "prompt"} == {
        p: f for p, f in original.files.items() if f.component != "prompt"
    }
    # Dev only: neither train nor test reaches the target or the Worker.
    assert {prompt for prompt, _ in calls} == {"dev-only"}
    assert "test-only" not in worker.prompts[0]
    assert "train-only" not in worker.prompts[0]
    assert worker.prompts[0].splitlines()[0] == "[EvoPrompt: paraphrase]"
    assert worker.prompts[1].splitlines()[0] == "[EvoPrompt: crossover]"
    assert PATHS[cls] in worker.prompts[0]


def test_claude_code_starts_from_an_absent_instruction_file(monkeypatch):
    target, _ = make_target(monkeypatch, ClaudeCode)
    # Claude Code's seed carries no CLAUDE.md; the empty baseline is its native
    # prompt, and the population still has a member zero to cross from.
    assert "CLAUDE.md" not in target.snapshot.files
    worker = ScriptedWorker([tagged("a try"), tagged("SOLVED"), tagged("weak")])

    algo = algorithm(target, worker)
    final = asyncio.run(algo.evolve())

    assert algo._baseline == 0.0
    assert final.files["CLAUDE.md"].content == b"SOLVED\n"


def test_the_current_version_never_moves_during_the_search(monkeypatch):
    target, _ = make_target(monkeypatch)
    original = target.snapshot
    worker = ScriptedWorker(
        [tagged("SOLVED")] + [tagged(f"weak {i}") for i in range(4)]
    )
    algo = algorithm(target, worker, max_steps=2)

    # Record when the selected version moves, against how far the search got.
    updates = []
    update = type(target).update

    def spy(self, snapshot):
        updates.append((len(worker.prompts), snapshot.id))
        update(self, snapshot)

    monkeypatch.setattr(type(target), "update", spy)

    final = asyncio.run(algo.evolve())

    # Both generations ran, and the one update happened only after them: every
    # member was therefore scored against the same baseline.
    assert len(worker.prompts) == 5
    assert updates == [(5, final.id)]
    assert final.id != original.id
    assert final.files["prompts/system.md"].content == b"SOLVED\n"


def test_a_search_without_improvement_keeps_the_original_version(monkeypatch):
    target, _ = make_target(monkeypatch)
    original = target.snapshot
    worker = ScriptedWorker([tagged("no"), tagged("still no"), tagged("nope")])

    final = asyncio.run(algorithm(target, worker).evolve())

    assert final.id == target.snapshot.id == original.id


def test_the_seed_instruction_is_member_zero_and_is_not_recommitted(monkeypatch):
    """Patching the seed to its own text would be a candidate that changes nothing."""
    target, calls = make_target(monkeypatch)
    seed = target.snapshot
    text = seed.files["prompts/system.md"].content.decode()
    # The paraphrase returns the seed's own text back.
    worker = ScriptedWorker([tagged(text.strip())])

    algo = algorithm(target, worker)
    asyncio.run(algo._initialize(seed))

    # Both members are the seed snapshot itself, scored exactly once.
    assert [member["snapshot_id"] for member in algo._population] == [seed.id, seed.id]
    assert [prompt for prompt, _ in calls] == ["dev-only"]


def test_an_unusable_reply_keeps_the_parent_without_spending_an_evaluation(monkeypatch):
    """An empty operator result is not a new member; it costs no dev pass."""
    target, calls = make_target(monkeypatch)
    worker = ScriptedWorker(["<prompt></prompt>", "<prompt></prompt>", tagged("z")])

    algo = algorithm(target, worker)
    asyncio.run(algo.evolve())

    # Baseline, plus only the one child that actually carried new text.
    assert [prompt for prompt, _ in calls].count("dev-only") == 2
    assert [member["score"] for member in algo._population] == [0.0, 0.0]


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

    with pytest.raises(RuntimeError, match="failed: provider exploded"):
        asyncio.run(algorithm(target, Failing()).evolve())


def test_only_the_rewritten_file_is_named_to_the_operators(monkeypatch):
    """Other prompt files in the same component are neither shown nor touched."""
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker([tagged("a"), tagged("SOLVED"), tagged("b")])
    # MiniAgent's prompt component also holds prompts/extract.md, which serves
    # the evidence summariser and is not the agent's instructions.
    other = target.snapshot.files["prompts/extract.md"]

    algo = algorithm(target, worker)
    final = asyncio.run(algo.evolve())

    assert "prompts/system.md" in worker.prompts[0].splitlines()[1]
    assert "prompts/extract.md" not in worker.prompts[0]
    assert final.files["prompts/extract.md"] == other
    assert algo._path == "prompts/system.md"


# -- GA --------------------------------------------------------------------


def test_ga_crosses_two_parents_and_quotes_both_verbatim(monkeypatch):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker([tagged("second member"), tagged("child"), tagged("other")])

    algo = algorithm(target, worker)
    asyncio.run(algo.evolve())

    crossover = worker.prompts[1]
    assert "Prompt 1:" in crossover and "Prompt 2:" in crossover
    assert "second member" in crossover


def test_ga_topk_keeps_the_population_size_when_children_collapse(monkeypatch):
    """Deduplicating on text is what makes this top-k rather than a plain sort."""
    target, _ = make_target(monkeypatch)
    # Every child collapses onto one identical prompt.
    worker = ScriptedWorker([tagged("seed two")] + [tagged("same")] * 4)

    algo = algorithm(target, worker, max_steps=2)
    asyncio.run(algo.evolve())

    assert len(algo._population) == 2
    assert len({member["text"] for member in algo._population}) == 2


def test_ga_standard_survivors_keep_the_children_even_when_worse(monkeypatch):
    target, _ = make_target(monkeypatch)
    # A winning seed member, then two children that lose to it.
    worker = ScriptedWorker([tagged("SOLVED"), tagged("weak one"), tagged("weak two")])

    algo = algorithm(target, worker, survivor_selection="standard")
    final = asyncio.run(algo.evolve())

    # The winner was not carried into the next population...
    assert [member["text"] for member in algo._population] == [
        "weak one\n",
        "weak two\n",
    ]
    # ...so the promotion at the end finds no improvement to make.
    assert final.id == target.snapshot.id
    assert max(member["score"] for member in algo._population) == 0.0


def test_ga_topk_rescues_a_winning_parent_from_losing_children(monkeypatch):
    """The same schedule under topk: the parent survives its children."""
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker([tagged("SOLVED"), tagged("weak one"), tagged("weak two")])

    algo = algorithm(target, worker, survivor_selection="topk")
    final = asyncio.run(algo.evolve())

    assert "SOLVED\n" in [member["text"] for member in algo._population]
    assert final.files["prompts/system.md"].content == b"SOLVED\n"


def test_ga_tournament_selection_prefers_the_fitter_of_two(monkeypatch):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(["<prompt>child</prompt>"] * 2)
    algo = algorithm(target, worker, selection="tournament", population_size=2)
    seed_population(algo, target.snapshot, [("weak", 0.0), ("strong", 1.0)])

    asyncio.run(algo._ga(random.Random(0), 0))

    # A binary tournament over a two-member pool always returns the fitter, so
    # every crossover prompt quotes "strong" and never "weak".
    assert all("strong" in prompt for prompt in worker.prompts)
    assert not any("weak" in prompt for prompt in worker.prompts)


def test_ga_wheel_weights_by_fitness_and_can_repeat_a_parent(monkeypatch):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(["<prompt>child</prompt>"] * 2)
    algo = algorithm(target, worker, selection="wheel", population_size=2)
    seed_population(algo, target.snapshot, [("weak", 0.0), ("strong", 1.0)])

    asyncio.run(algo._ga(random.Random(0), 0))

    # Only the fitter member has weight, so the wheel resamples it into both
    # slots -- which is what lets one member be drawn as both parents.
    assert all(
        prompt.count("strong") == 2 and "weak" not in prompt
        for prompt in worker.prompts
    )


# -- DE --------------------------------------------------------------------


def test_de_still_evolves_when_every_paraphrase_is_unusable(monkeypatch):
    """A population whose slots all carry the same snapshot must still evolve.

    `_member` keeps the parent's snapshot and fitness when an operator returns
    nothing usable, so several slots can describe identical files. Donors are
    drawn by position and each slot is its own record, so neither the sampling
    nor top-k's padding can collapse on those duplicates.
    """
    target, _ = make_target(monkeypatch)
    # Every paraphrase fails, so all four slots carry the seed's own snapshot.
    worker = ScriptedWorker(["<prompt></prompt>"] * 3 + [tagged("SOLVED")] + [""] * 3)

    algo = algorithm(target, worker, variant="de", population_size=4)
    final = asyncio.run(algo.evolve())

    # One snapshot across several slots, but no slot aliases another's member.
    assert len({id(member) for member in algo._population}) == 4
    assert len(algo._population) == 4
    # The generation still ran, and the one winning trial was still adopted.
    assert final.files["prompts/system.md"].content == b"SOLVED\n"


def test_an_unusable_reply_keeps_the_parents_snapshot_as_its_own_record(monkeypatch):
    """Carrying a parent forward must not alias it into two population slots.

    top-k pads back to size from the ranked pool by excluding what it already
    took, so an aliased member would drop the fitter prompt's every copy at once
    and pad with a weaker one instead.
    """
    target, _ = make_target(monkeypatch)
    algo = algorithm(target, ScriptedWorker([]))
    seed = {"snapshot_id": target.snapshot.id, "text": "seed", "score": 1.0}

    carried = asyncio.run(algo._member(seed, "", label="child"))

    assert carried is not seed
    assert carried["snapshot_id"] == seed["snapshot_id"]
    assert (carried["text"], carried["score"]) == ("seed", 1.0)


def test_de_replaces_only_the_target_a_trial_was_built_from(monkeypatch):
    target, _ = make_target(monkeypatch)
    # Three paraphrases seed a population of four, then one trial per target;
    # only the first trial wins.
    worker = ScriptedWorker(
        [tagged(f"seed {i}") for i in range(3)]
        + [tagged("SOLVED"), tagged("weak a"), tagged("weak b"), tagged("weak c")]
    )

    algo = algorithm(target, worker, variant="de", population_size=4)
    final = asyncio.run(algo.evolve())

    texts = [member["text"] for member in algo._population]
    # Exactly one target was displaced; the three losing trials left theirs.
    assert texts.count("SOLVED\n") == 1
    assert "weak a\n" not in texts and "weak b\n" not in texts
    assert final.files["prompts/system.md"].content == b"SOLVED\n"


def test_de_builds_each_trial_from_three_distinct_donors(monkeypatch):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(
        [tagged(f"seed {i}") for i in range(3)]
        + [tagged(f"trial {i}") for i in range(4)]
    )

    algo = algorithm(target, worker, variant="de", population_size=4)
    asyncio.run(algo.evolve())

    mutate = worker.prompts[3]
    assert mutate.splitlines()[0] == "[EvoPrompt: mutate]"
    # Prompt 0 is the target, 1 and 2 the difference donors, 3 the base vector.
    for label in ("Basic Prompt:", "Prompt 1:", "Prompt 2:", "Prompt 3:"):
        assert label in mutate


def test_de_takes_the_global_best_as_its_base_vector(monkeypatch):
    """Upstream uses the best member unless --donor_random is set."""
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(
        [tagged("SOLVED"), tagged("seed b"), tagged("seed c")]
        + [tagged(f"trial {i}") for i in range(4)]
    )

    algo = algorithm(target, worker, variant="de", population_size=4)
    asyncio.run(algo.evolve())

    # The winning member is quoted as Prompt 3 in every trial of the generation.
    for prompt in worker.prompts[3:]:
        assert "Prompt 3: SOLVED" in prompt


def test_de_donor_random_takes_a_sampled_donor_as_the_base(monkeypatch):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(
        [tagged("SOLVED"), tagged("seed b"), tagged("seed c")]
        + [tagged(f"trial {i}") for i in range(4)]
    )

    algo = algorithm(target, worker, variant="de", population_size=4, donor_random=True)
    asyncio.run(algo.evolve())

    # The best member no longer anchors every trial.
    assert not all("Prompt 3: SOLVED" in prompt for prompt in worker.prompts[3:])


def test_de_keeps_a_target_whose_trial_echoed_its_own_text(monkeypatch):
    """The trial describes the same files, so it cannot beat the target."""
    target, calls = make_target(monkeypatch)
    seeds = [tagged(f"seed {i}") for i in range(3)]
    # Every trial echoes the text of the target it was built from.
    echo = [tagged("seed 0"), tagged("seed 1"), tagged("seed 2")]
    seed_text = target.snapshot.files["prompts/system.md"].content.decode().strip()
    worker = ScriptedWorker(seeds + [tagged(seed_text)] + echo)

    algo = algorithm(target, worker, variant="de", population_size=4)
    final = asyncio.run(algo.evolve())

    # Pairwise replacement needs a strict improvement, and an echo ties, so the
    # population is unchanged and nothing is promoted.
    assert [member["text"] for member in algo._population] == [
        seed_text + "\n",
        "seed 0\n",
        "seed 1\n",
        "seed 2\n",
    ]
    assert final.id == target.snapshot.id
    # The four echoed trials never cost a dev pass of their own.
    assert [prompt for prompt, _ in calls].count("dev-only") == 4


# -- records ---------------------------------------------------------------


def test_each_generation_and_the_promotion_are_recorded(monkeypatch, tmp_path):
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker([tagged("a"), tagged("SOLVED"), tagged("b")])
    algo = algorithm(target, worker)
    directory = run_dir(algo, tmp_path)

    final = asyncio.run(algo.evolve())

    generation, promote = decisions(directory)
    assert generation["kind"] == "generation" and generation["variant"] == "ga"
    assert generation["step"] == 0
    assert [row["text"] for row in generation["candidates"]] == ["SOLVED\n", "b\n"]
    # A scored candidate is not marked, so the flag below means what it says.
    assert all("carried" not in row for row in generation["candidates"])
    assert promote["accepted"] is True and promote["candidate_id"] == final.id
    assert promote["score"] == 1.0 and promote["baseline_score"] == 0.0
    assert [row["score"] for row in promote["population"]] == [1.0, 0.0]
    assert Snapshot.load(directory / "snapshots" / f"{final.id}.json") == final


def test_a_carried_parent_is_marked_in_the_record(monkeypatch, tmp_path):
    """Otherwise an unusable operator output reads as a candidate that tied."""
    target, _ = make_target(monkeypatch)
    # The first child's crossover returns nothing usable; the second scores.
    worker = ScriptedWorker([tagged("a"), "<prompt></prompt>", tagged("b")])
    algo = algorithm(target, worker)
    directory = run_dir(algo, tmp_path)

    asyncio.run(algo.evolve())

    generation, _ = decisions(directory)
    carried, scored = generation["candidates"]
    assert carried["carried"] is True
    assert "carried" not in scored
    # Same score either way, which is exactly why the flag has to be there.
    assert carried["score"] == scored["score"] == 0.0


# -- population arithmetic -------------------------------------------------


def member_row(text, score):
    return {"snapshot_id": None, "text": text, "score": score}


def test_top_k_keeps_the_best_copy_of_each_distinct_prompt():
    pool = [member_row("a", 0.2), member_row("a", 0.9), member_row("b", 0.5)]

    assert [item["score"] for item in _top_k(pool, 2)] == [0.9, 0.5]


def test_top_k_pads_back_to_the_requested_size_with_duplicates():
    """The next generation still needs `size` members to draw parents from.

    Padding reaches past the copy it already took and returns the best
    remaining entry, so two slots carrying one prompt must be two records: an
    aliased member would drop the fitter prompt entirely and pad with a weaker.
    """
    pool = [member_row("a", 1.0), member_row("a", 0.5)]

    survivors = _top_k(pool, 3)

    assert len(survivors) == 3
    assert [item["score"] for item in survivors] == [1.0, 0.5, 1.0]


def test_wheel_falls_back_to_uniform_weights_when_every_fitness_is_zero(monkeypatch):
    """A freshly initialized population would otherwise make choices() raise."""
    target, _ = make_target(monkeypatch)
    worker = ScriptedWorker(["<prompt>child</prompt>"] * 2)
    algo = algorithm(target, worker, selection="wheel", population_size=2)
    seed_population(algo, target.snapshot, [("a", 0.0), ("b", 0.0)])

    asyncio.run(algo._ga(random.Random(0), 0))

    assert len(algo._population) == 2


# -- configuration ---------------------------------------------------------


@pytest.mark.parametrize(
    "config,message",
    [
        ({"variant": "pso"}, "variant must be one of"),
        ({"selection": "elitist"}, "selection must be one of"),
        ({"survivor_selection": "best"}, "survivor_selection must be one of"),
        ({"population_size": 1}, "population_size must be an integer >= 2"),
        ({"variant": "de", "population_size": 3}, "population_size >= 4"),
        ({"max_steps": 0}, "max_steps must be an integer >= 1"),
        ({"seed": "42"}, "seed must be an integer"),
        ({"donor_random": "yes"}, "donor_random must be a boolean"),
    ],
)
def test_configuration_is_checked_before_any_execution(monkeypatch, config, message):
    target, calls = make_target(monkeypatch)
    with pytest.raises(ValueError, match=message):
        algorithm(target, ScriptedWorker([]), **config)
    assert not calls


def test_the_upstream_tour_selection_name_is_accepted(monkeypatch):
    target, _ = make_target(monkeypatch)

    algo = algorithm(target, ScriptedWorker([]), selection="tour")

    # Canonicalized once, so the loop compares against one name and the saved
    # configuration records what actually ran.
    assert algo.config.selection == "tournament"


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_the_target_names_its_own_instruction_file(monkeypatch, cls):
    """EvoPrompt rewrites whatever file the harness declares as its own."""
    target, _ = make_target(monkeypatch, cls)
    worker = ScriptedWorker([tagged("a"), tagged("SOLVED"), tagged("b")])

    algo = algorithm(target, worker)
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
        # Outside the prompt component, so beyond what EvoPrompt may evolve.
        ("skills/main.md", "outside its prompt component"),
        ("../escape.md", "invalid snapshot file path"),
    ],
)
def test_an_unusable_declared_instruction_file_is_rejected(
    monkeypatch, declared, message
):
    """The declaration is the only source, so EvoPrompt checks rather than trusts it."""
    target, calls = make_target(monkeypatch)
    monkeypatch.setattr(type(target), "instruction_file", declared)

    with pytest.raises(ValueError, match=message):
        algorithm(target, ScriptedWorker([]))

    assert not calls


def test_an_empty_dev_split_is_rejected(monkeypatch):
    class Missing(MemoryBenchmark):
        def load(self):
            super().load()
            self._splits = {**self._splits, "dev": ()}
            return self._splits

    target, _ = make_target(monkeypatch)
    with pytest.raises(ValueError, match="non-empty dev split"):
        EvoPrompt({}, target=target, worker=ScriptedWorker([]), benchmark=Missing())
