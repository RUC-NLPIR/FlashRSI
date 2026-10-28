"""ADAS decisions use scripted designs; harness loading is tested separately."""

import asyncio
import json
from dataclasses import replace

import pytest
from algorithm_helpers import MemoryBenchmark

from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.algorithms import ADAS
from flashrsi.core import Agent, Trajectory

# The edited file drives the target's score, so a run reads as: which marker is
# in the harness right now, and which dev tasks does that marker answer.
_MARKER = "skills/main.md"
# A phrase from the seed skill, so a table can express a task the starting
# harness already answers. Read from the file rather than written out, so a
# renamed heading changes the marker instead of silently scoring the seed zero.
_SEED_MARKER = (
    MiniAgent({"llm": {"model_name": "offline"}})
    .snapshot.files[_MARKER]
    .content.decode()
    .splitlines()[0]
)


class DesigningWorker(Agent):
    """A Worker that edits the checkout, the way a real meta agent does.

    A script entry is ``(files, account)``: files to write into the directory,
    and the design description the Worker claims for them. Every ADAS Worker
    call is an edit call, so unlike AHE's there is no text-reply branch. An
    account given as ``None`` sends a reply with no ``<DESIGN>`` block, which is
    how an unbracketed reply is expressed.
    """

    name = "designing"
    description = "Finite offline Worker that writes files in working_dir."

    def __init__(self, script):
        super().__init__({"llm": {"model_name": "offline-worker"}, "type": "agent"})
        self.script = iter(script)
        self.prompts = []

    async def _run(self, prompt, working_dir=None):
        self.prompts.append(prompt)
        files, account = next(self.script)
        for path, content in files.items():
            destination = working_dir / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                destination.unlink()
            else:
                destination.write_text(content, newline="\n")
        if account is None:
            return Trajectory(output="Edited, but said nothing about the design.")
        return Trajectory(output=f"Done.\n<DESIGN>{account}</DESIGN>")


class Scores(MemoryBenchmark):
    """Dev tasks whose scores depend on which marker the harness holds.

    ADAS admits designs on dev, so the table is keyed by dev task ids. Three
    dev tasks let a design score a third, two thirds or all of the split, which
    a pass/fail target cannot express.
    """

    def __init__(self, table=None):
        super().__init__()
        # marker -> the dev task_ids it answers correctly.
        self.table = table if table is not None else {"D1": {"dev-0"}}

    def load(self):
        if self._splits is None:
            self._splits = {
                "train": (),
                "dev": tuple(_task(f"dev-{i}") for i in range(3)),
                "test": (_task("test-only"),),
            }
        return self._splits

    def grade(self, results):
        return tuple(
            replace(item, metrics={"accuracy": float(item.output)}) for item in results
        )


def _task(task_id):
    from flashrsi.core import Task

    return Task(task_id, task_id, "right")


def setup(monkeypatch, script, *, cls=MiniAgent, table=None, **config):
    calls = []
    benchmark = Scores(table)

    async def run(self, prompt, working_dir=None):
        # Read the whole skill directory, so a design that adds a file counts
        # the same as one that edits the existing one.
        text = "".join(
            path.read_text()
            for path in sorted((self.files_dir / "skills").rglob("*"))
            if path.is_file()
        )
        calls.append((prompt, text, self.snapshot.id))
        passing = set()
        for marker, tasks in benchmark.table.items():
            if marker in text:
                passing |= tasks
        return Trajectory(output=str(float(prompt in passing)))

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline-target"}})
    worker = DesigningWorker(script)
    algo = ADAS(
        {"max_steps": 1, "num_reflections": 0, **config},
        target=target,
        worker=worker,
        benchmark=benchmark,
    )
    return algo, calls


def decisions(run_dir):
    return [
        json.loads(path.read_text())
        for path in sorted((run_dir / "trajectories").glob("*-decision.json"))
    ]


def run_dir(algo, tmp_path):
    algo._run_dir = tmp_path
    for name in ("snapshots", "trajectories", "working"):
        (tmp_path / name).mkdir(exist_ok=True)
    return tmp_path


# -- admission is by score, and the archive keeps what did not improve --


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_an_improving_design_is_promoted(monkeypatch, tmp_path, cls):
    algo, _ = setup(
        monkeypatch,
        [({_MARKER: "D1\n"}, "answers dev-0")],
        cls=cls,
        table={"D1": {"dev-0"}},
    )
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    assert final.id != original.id
    assert final.files[_MARKER].content == b"D1\n"
    admit, promote = decisions(directory)
    assert admit["kind"] == "admit" and admit["accepted"] is True
    assert (admit["parent_score"], admit["candidate_score"]) == (0.0, 1 / 3)
    # The whole archive is recorded with the promotion, seed included.
    assert promote["kind"] == "promote" and promote["accepted"] is True
    assert [row["account"] for row in promote["archive"]] == [
        "the harness this run started from",
        "answers dev-0",
    ]
    # Lineage is the Snapshot's own, not a second copy in the archive row.
    assert final.parent_id == original.id


def test_a_worse_design_enters_the_archive_but_is_not_promoted(monkeypatch, tmp_path):
    """A low score is information: it is kept so the next round can read it."""
    algo, _ = setup(
        monkeypatch,
        # Overwriting the seed skill drops the marker the seed scored on.
        [({_MARKER: "WORSE\n"}, "a design that loses")],
        table={_SEED_MARKER: {"dev-0", "dev-1"}, "WORSE": {"dev-0"}},
    )
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    assert final.id == original.id  # The incumbent did not move.
    admit, promote = decisions(directory)
    assert (admit["parent_score"], admit["candidate_score"]) == (2 / 3, 1 / 3)
    assert admit["kind"] == "admit" and admit["accepted"] is False
    assert promote["accepted"] is False
    # Kept anyway: the archive carries the design and what it scored.
    assert promote["archive"][1] == {
        "account": "a design that loses",
        "score": 1 / 3,
    }


def test_the_best_design_is_promoted_even_when_a_later_one_regressed(
    monkeypatch, tmp_path
):
    algo, _ = setup(
        monkeypatch,
        [
            ({_MARKER: "GOOD\n"}, "the good one"),
            ({_MARKER: "BAD\n"}, "a step backwards"),
        ],
        table={"GOOD": {"dev-0", "dev-1"}, "BAD": {"dev-2"}},
        max_steps=2,
    )
    directory = run_dir(algo, tmp_path)

    final = asyncio.run(algo.evolve())

    assert final.files[_MARKER].content == b"GOOD\n"
    first, second, promote = decisions(directory)
    assert (first["accepted"], second["accepted"]) == (True, False)
    # The regression was measured against the leader, not against the seed.
    assert second["parent_score"] == 2 / 3
    assert second["parent_id"] == first["candidate_id"]
    assert [row["score"] for row in promote["archive"]] == [0.0, 2 / 3, 1 / 3]


# -- the archive is what the meta agent reads --


def test_the_meta_agent_is_shown_every_measured_design(monkeypatch, tmp_path):
    algo, _ = setup(
        monkeypatch,
        [
            ({_MARKER: "FIRST\n"}, "the first idea"),
            ({_MARKER: "SECOND\n"}, "the second idea"),
        ],
        table={"FIRST": {"dev-0"}, "SECOND": {"dev-0", "dev-1"}},
        max_steps=2,
    )
    run_dir(algo, tmp_path)

    asyncio.run(algo.evolve())

    first, second = algo.worker.prompts
    assert [prompt.splitlines()[0] for prompt in (first, second)] == [
        "[ADAS: propose]",
        "[ADAS: propose]",
    ]
    # The first proposal sees only the seed; the second sees the seed and the
    # design that came out of the first, with the score it earned.
    assert "the first idea" not in first
    assert "the first idea" in second
    assert "0.3333333333333333" in second
    # The component rules travel with the prompt, because commit enforces them.
    assert "skills/**" in first


def test_reflection_revises_the_same_checkout_before_it_is_measured(
    monkeypatch, tmp_path
):
    algo, _ = setup(
        monkeypatch,
        [
            ({_MARKER: "DRAFT\n"}, "a first draft"),
            ({_MARKER: "REVISED\n"}, "revised after review"),
        ],
        table={"DRAFT": {"dev-0"}, "REVISED": {"dev-0", "dev-1"}},
        num_reflections=1,
    )
    directory = run_dir(algo, tmp_path)

    final = asyncio.run(algo.evolve())

    propose, reflect = algo.worker.prompts
    assert propose.splitlines()[0] == "[ADAS: propose]"
    assert reflect.splitlines()[0] == "[ADAS: reflect]"
    # The reflection is shown the account it is revising.
    assert "a first draft" in reflect
    # Only the revised files are committed, and only one candidate was scored.
    assert final.files[_MARKER].content == b"REVISED\n"
    admit, _ = decisions(directory)
    assert admit["candidate_score"] == 2 / 3
    assert admit["account"] == "revised after review"


def test_zero_reflections_skips_the_review_pass(monkeypatch, tmp_path):
    algo, _ = setup(
        monkeypatch,
        [({_MARKER: "D1\n"}, "one pass only")],
        num_reflections=0,
    )
    run_dir(algo, tmp_path)

    asyncio.run(algo.evolve())

    assert [prompt.splitlines()[0] for prompt in algo.worker.prompts] == [
        "[ADAS: propose]"
    ]


# -- a refused design costs one step, not the experiment --


@pytest.mark.parametrize(
    ("files", "problem"),
    [
        ({"nowhere.md": "D1\n"}, "rejected design"),
        ({}, "the harness was left unchanged"),
    ],
)
def test_a_refused_design_is_declined_without_ending_the_run(
    monkeypatch, tmp_path, files, problem
):
    algo, _ = setup(
        monkeypatch,
        [(files, "an unusable design"), ({_MARKER: "D1\n"}, "a usable one")],
        max_steps=2,
    )
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    declined, admitted, promote = decisions(directory)
    assert declined["kind"] == "decline" and declined["accepted"] is False
    assert problem in declined["problem"]
    assert declined["parent_id"] == original.id
    # Nothing was measured, so nothing entered the archive: two steps ran but
    # the archive holds only the seed and the one design that was scored.
    assert len(promote["archive"]) == 2
    # The run continued, and the next step produced a real candidate.
    assert admitted["accepted"] is True and final.id != original.id
    # Each record names the loop iteration it happened on: a decline does not
    # shift the ones after it, which it would if the step came from the
    # archive position.
    assert (declined["step"], admitted["step"]) == (0, 1)
    # The declined reason is carried into the promotion record.
    assert problem in promote["declined_designs"][0]["problem"]


def test_a_new_file_inside_a_component_is_committed_and_classified(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        [({"skills/added.md": "D1\n"}, "a design in a new file")],
        table={"D1": {"dev-0"}},
    )

    final = asyncio.run(algo.evolve())

    assert final.files["skills/added.md"].component == "skill"
    assert final.files["skills/added.md"].content == b"D1\n"


def test_an_unbracketed_reply_is_still_a_design(monkeypatch, tmp_path):
    """The edit is the design; the account is prose, so a whole reply will do."""
    algo, _ = setup(monkeypatch, [({_MARKER: "D1\n"}, None)])
    directory = run_dir(algo, tmp_path)

    final = asyncio.run(algo.evolve())

    assert final.files[_MARKER].content == b"D1\n"
    admit, _ = decisions(directory)
    assert admit["account"] == ("Edited, but said nothing about the design.")


# -- startup checks --


def test_a_text_worker_is_refused_at_startup(monkeypatch):
    """ADAS needs a Worker that edits a directory, so the run never begins."""
    calls = []

    async def run(self, prompt, working_dir=None):
        calls.append(prompt)
        return Trajectory(output="0")

    monkeypatch.setattr(MiniAgent, "_run", run)
    with pytest.raises(ValueError, match="worker.type"):
        ADAS(
            {},
            target=MiniAgent({"llm": {"model_name": "offline-target"}}),
            worker=LLM({"type": "llm", "llm": {"model_name": "offline-worker"}}),
            benchmark=Scores(),
        )
    assert calls == []


def test_an_empty_dev_split_is_refused_at_startup(monkeypatch):
    class NoDev(Scores):
        def load(self):
            self._splits = {"train": (_task("train-0"),), "dev": (), "test": ()}
            return self._splits

    async def run(self, prompt, working_dir=None):
        return Trajectory(output="0")

    monkeypatch.setattr(MiniAgent, "_run", run)
    with pytest.raises(ValueError, match="non-empty dev split"):
        ADAS(
            {},
            target=MiniAgent({"llm": {"model_name": "offline-target"}}),
            worker=DesigningWorker([]),
            benchmark=NoDev(),
        )


@pytest.mark.parametrize(
    ("config", "field"),
    [
        ({"max_steps": 0}, "max_steps"),
        ({"num_reflections": -1}, "num_reflections"),
        ({"max_evidence_chars": 0}, "max_evidence_chars"),
    ],
)
def test_parameter_ranges_are_checked(monkeypatch, config, field):
    async def run(self, prompt, working_dir=None):
        return Trajectory(output="0")

    monkeypatch.setattr(MiniAgent, "_run", run)
    with pytest.raises(ValueError, match=field):
        ADAS(
            config,
            target=MiniAgent({"llm": {"model_name": "offline-target"}}),
            worker=DesigningWorker([]),
            benchmark=Scores(),
        )


# -- the archive's own rules --


def test_a_design_that_only_ties_does_not_move_the_incumbent(monkeypatch, tmp_path):
    """An equal score is not evidence for moving off the incumbent."""
    algo, _ = setup(
        monkeypatch,
        # TIE answers exactly the two dev tasks the seed already answers.
        [({_MARKER: "TIE\n"}, "a design that merely ties")],
        table={_SEED_MARKER: {"dev-0", "dev-1"}, "TIE": {"dev-0", "dev-1"}},
    )
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    assert final.id == original.id
    admit, promote = decisions(directory)
    assert admit["parent_score"] == admit["candidate_score"] == 2 / 3
    assert admit["accepted"] is False and promote["accepted"] is False
    # It is still archived -- the next round should be able to see it tied.
    assert [row["account"] for row in promote["archive"]][1] == (
        "a design that merely ties"
    )
