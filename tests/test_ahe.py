"""AHE decisions use scripted edits; harness loading is tested separately."""

import asyncio
import json
from dataclasses import replace

import pytest
from test_opro import MemoryBenchmark

from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.algorithms import AHE
from flashrsi.algorithms.ahe._manifest import Manifest, ManifestError, attribute
from flashrsi.core import Agent, Snapshot, Task, Trajectory

# The edited file drives the target's score, so a run reads as: which marker is
# in the harness right now, and which tasks does that marker answer.
_MARKER = "skills/main.md"
_SEED = (
    MiniAgent({"llm": {"model_name": "offline"}})
    .snapshot.files[_MARKER]
    .content.decode()
)


class EditingWorker(Agent):
    """A Worker that edits the checkout, the way an Agent Worker does.

    A script entry is either a plain string -- the reply to a text call, such
    as a debugger pass -- or ``(files, manifest)`` for an editing call: files to
    write into the directory, and the manifest the Worker claims for them. A
    manifest given as a string is sent verbatim, which is how a malformed reply
    is expressed.
    """

    name = "editing"
    description = "Finite offline Worker that writes files in working_dir."

    def __init__(self, script):
        super().__init__({"llm": {"model_name": "offline-worker"}, "type": "agent"})
        self.script = iter(script)
        self.prompts = []

    async def _run(self, prompt, working_dir=None):
        self.prompts.append(prompt)
        entry = next(self.script)
        if working_dir is None:
            return Trajectory(output=entry)
        files, manifest = entry
        for path, content in files.items():
            destination = working_dir / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                destination.unlink()
            else:
                destination.write_text(content)
        if isinstance(manifest, str):
            return Trajectory(output=manifest)
        return Trajectory(
            output=f"Edited.\n<MANIFEST>{json.dumps(manifest)}</MANIFEST>"
        )


def manifest(paths, fixes=(), risks=()):
    return {
        "failure_evidence": ["train-0 failed"],
        "root_cause": "the harness never verifies",
        "targeted_fix": "add a verification rule",
        "changes": [
            {"path": path, "fix_tasks": list(fixes), "risk_tasks": list(risks)}
            for path in paths
        ],
    }


class Scores(MemoryBenchmark):
    """Two train tasks whose scores depend on which markers the harness holds.

    ``SEED`` stands for the seed file's own content, so a table can express a
    task the starting harness already answers.
    """

    def __init__(self, table=None):
        super().__init__()
        # marker -> the task_ids it answers correctly.
        self.table = table if table is not None else {"FIX0": {"train-0"}}

    def grade(self, results):
        return tuple(
            replace(item, metrics={"accuracy": float(item.output)}) for item in results
        )


def setup(monkeypatch, script, *, cls=MiniAgent, table=None, **config):
    calls = []
    benchmark = Scores(table)

    async def run(self, prompt, working_dir=None):
        path = self.files_dir / _MARKER
        text = path.read_text() if path.exists() else ""
        calls.append((prompt, text, self.snapshot.id))
        passing = set()
        for marker, tasks in benchmark.table.items():
            if marker in text or (marker == "SEED" and text == _SEED):
                passing |= tasks
        return Trajectory(output=str(float(prompt in passing)))

    monkeypatch.setattr(cls, "_run", run)
    target = cls({"llm": {"model_name": "offline-target"}})
    worker = EditingWorker(script)
    algo = AHE(
        {"max_steps": 1, "use_debugger": False, **config},
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


# -- the edit is kept, and its verdict goes to the next Evolve Agent --


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_the_worker_edits_the_checkout_and_the_edit_is_adopted(monkeypatch, cls):
    """Both harnesses hand over their own directory; AHE names no path."""
    algo, calls = setup(
        monkeypatch,
        [({_MARKER: "FIX0 verify\n"}, manifest([_MARKER], fixes=["train-0"]))],
        cls=cls,
    )
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    assert final.id == algo.target.snapshot.id != original.id
    assert final.parent_id == original.id
    assert final.files[_MARKER].content == b"FIX0 verify\n"
    # Everything else is byte-for-byte the seed: the Worker edited one file.
    assert {p: f for p, f in final.files.items() if p != _MARKER} == {
        p: f for p, f in original.files.items() if p != _MARKER
    }
    assert algo._previous["changes"][0]["verdict"] == "EFFECTIVE"
    assert algo._previous["tasks"]["train-0"]["flip"] == "fail_to_pass"
    # Training only: dev and test never reach the target or the Worker.
    assert {prompt for prompt, _, _ in calls} == {"train-0", "train-1"}
    assert all("dev-only" not in prompt for prompt in algo.worker.prompts)
    assert all("test-only" not in prompt for prompt in algo.worker.prompts)
    assert all("RunConfig" not in prompt for prompt in algo.worker.prompts)


def test_an_ineffective_edit_is_kept_and_its_verdict_reaches_the_next_agent(
    monkeypatch,
):
    """There is no score gate: the next Evolve Agent is the decision."""
    algo, _ = setup(
        monkeypatch,
        [
            ({_MARKER: "NOTHING\n"}, manifest([_MARKER], fixes=["train-0"])),
            ({_MARKER: "FIX0\n"}, manifest([_MARKER], fixes=["train-0"])),
        ],
        max_steps=2,
    )
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    # The first edit scored nothing and was adopted anyway.
    assert final.files[_MARKER].content == b"FIX0\n"
    assert final.parent_id != original.id
    second = algo.worker.prompts[1]
    assert '"verdict": "INEFFECTIVE"' in second
    # The next agent is asked to consider a rollback, so it is shown what it
    # would be rolling back to -- its checkout only holds the edited version.
    assert "rollback_sources" in second
    assert _SEED.splitlines()[0] in second
    assert algo._previous["changes"][0]["verdict"] == "EFFECTIVE"


def test_an_unpredicted_regression_is_reported_separately(monkeypatch):
    """A regression nobody declared is the manifest missing something."""
    algo, _ = setup(
        monkeypatch,
        [({_MARKER: "FIX0\n"}, manifest([_MARKER], fixes=["train-0"]))],
        table={"SEED": {"train-1"}, "FIX0": {"train-0"}},
    )

    asyncio.run(algo.evolve())

    assert algo._previous["unattributed_regressions"] == ["train-1"]
    # The change still delivered what it promised, so it is not HARMFUL.
    assert algo._previous["changes"][0]["verdict"] == "EFFECTIVE"


def test_the_decision_record_carries_the_verdicts_and_the_snapshot_is_saved(
    monkeypatch, tmp_path
):
    algo, _ = setup(
        monkeypatch,
        [({_MARKER: "FIX0\n"}, manifest([_MARKER], fixes=["train-0"]))],
    )
    directory = run_dir(algo, tmp_path)

    final = asyncio.run(algo.evolve())

    (decision,) = decisions(directory)
    assert decision["kind"] == "keep" and decision["accepted"] is True
    assert decision["parent_score"] == 0.0 and decision["candidate_score"] == 0.5
    assert decision["candidate_id"] == final.id
    assert decision["changes"][0]["verdict"] == "EFFECTIVE"
    assert decision["manifest"]["root_cause"] == "the harness never verifies"
    assert Snapshot.load(directory / "snapshots" / f"{final.id}.json") == final
    assert not list((directory / "working").iterdir())


# -- an edit that cannot be held to a prediction is not a candidate --


@pytest.mark.parametrize(
    "reply, problem",
    [
        (manifest(["skills/other.md"], fixes=["train-0"]), "manifest declares"),
        ("Edited, no manifest here.", "not valid JSON"),
        ("<MANIFEST>{not json}</MANIFEST>", "not valid JSON"),
        (
            {**manifest([_MARKER]), "root_cause": "  "},
            "root_cause must be a non-empty string",
        ),
    ],
)
def test_an_unfalsifiable_edit_is_declined_without_ending_the_run(
    monkeypatch, tmp_path, reply, problem
):
    algo, _ = setup(
        monkeypatch,
        [
            ({_MARKER: "FIX0\n"}, reply),
            ({_MARKER: "FIX0\n"}, manifest([_MARKER], fixes=["train-0"])),
        ],
        max_steps=2,
    )
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    declined, adopted = decisions(directory)
    assert declined["kind"] == "decline" and declined["accepted"] is False
    assert problem in declined["problem"]
    assert declined["parent_id"] == original.id
    # The run continued, and the next step produced a real candidate.
    assert adopted["accepted"] is True and final.id != original.id
    # The declined reason is fed back to the next Evolve Agent.
    assert "declined_edits" in algo.worker.prompts[1]
    assert problem.split()[0] in algo.worker.prompts[1]


def test_an_unchanged_checkout_is_declined(monkeypatch, tmp_path):
    algo, _ = setup(monkeypatch, [({}, manifest([]))])
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    assert final.id == original.id
    (decision,) = decisions(directory)
    assert decision["problem"] == "the harness was left unchanged"


def test_a_file_outside_every_component_rule_is_refused(monkeypatch, tmp_path):
    """Lite classifies by the target's rules; an unplaceable path is not a candidate."""
    algo, _ = setup(monkeypatch, [({"nowhere.md": "FIX0\n"}, manifest(["nowhere.md"]))])
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    assert final.id == original.id
    (decision,) = decisions(directory)
    assert "rejected edit" in decision["problem"]


def test_a_new_file_inside_a_component_is_committed_and_classified(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        [({"skills/added.md": "FIX0\n"}, manifest(["skills/added.md"], ["train-0"]))],
    )

    final = asyncio.run(algo.evolve())

    assert final.files["skills/added.md"].component == "skill"
    assert final.files["skills/added.md"].content == b"FIX0\n"


# -- budget, evidence and startup checks --


def test_the_target_score_ends_the_search_before_any_worker_call(monkeypatch):
    algo, calls = setup(
        monkeypatch,
        [],
        table={"SEED": {"train-0", "train-1"}},
        target_score=1.0,
    )
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    assert final.id == original.id
    assert algo.worker.prompts == []
    assert len(calls) == 2  # The baseline rollout only.


def test_the_debugger_reads_failures_first_and_then_synthesizes(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        [
            "one report",
            "the overview",
            ({_MARKER: "FIX0\n"}, manifest([_MARKER], fixes=["train-0"])),
        ],
        table={"SEED": {"train-1"}, "FIX0": {"train-0", "train-1"}},
        use_debugger=True,
        debugger_max_tasks=1,
    )

    asyncio.run(algo.evolve())

    stages = [prompt.splitlines()[0] for prompt in algo.worker.prompts]
    assert stages == ["[AHE: debug]", "[AHE: overview]", "[AHE: evolve]"]
    # The cap spends the one debugger call on the failing task.
    assert "train-0" in algo.worker.prompts[0]
    assert "train-1" not in algo.worker.prompts[0]
    assert "one report" in algo.worker.prompts[1]
    assert "the overview" in algo.worker.prompts[2]


def test_a_text_worker_is_refused_at_startup(monkeypatch):
    """AHE needs a Worker that edits a directory, so the run never begins."""
    calls = []

    async def run(self, prompt, working_dir=None):
        calls.append(prompt)
        return Trajectory(output="0")

    monkeypatch.setattr(MiniAgent, "_run", run)
    with pytest.raises(ValueError, match="worker.type"):
        AHE(
            {},
            target=MiniAgent({"llm": {"model_name": "offline-target"}}),
            worker=LLM({"type": "llm", "llm": {"model_name": "offline-worker"}}),
            benchmark=Scores(),
        )
    assert calls == []


def test_duplicate_train_task_ids_are_refused_at_startup(monkeypatch):
    class Duplicated(Scores):
        def load(self):
            self._splits = {
                "train": (Task("same", "same"), Task("same", "same")),
                "dev": (),
                "test": (),
            }
            return self._splits

    async def run(self, prompt, working_dir=None):
        return Trajectory(output="0")

    monkeypatch.setattr(MiniAgent, "_run", run)
    with pytest.raises(ValueError, match="unique task_id"):
        AHE(
            {},
            target=MiniAgent({"llm": {"model_name": "offline-target"}}),
            worker=EditingWorker([]),
            benchmark=Duplicated(),
        )


def test_an_empty_train_split_is_refused_at_startup(monkeypatch):
    class Empty(Scores):
        def load(self):
            self._splits = {"train": (), "dev": (), "test": ()}
            return self._splits

    async def run(self, prompt, working_dir=None):
        return Trajectory(output="0")

    monkeypatch.setattr(MiniAgent, "_run", run)
    with pytest.raises(ValueError, match="non-empty train"):
        AHE(
            {},
            target=MiniAgent({"llm": {"model_name": "offline-target"}}),
            worker=EditingWorker([]),
            benchmark=Empty(),
        )


# -- the manifest protocol on its own --


def test_a_whole_diff_prediction_is_applied_to_every_changed_file():
    parsed = Manifest.parse(
        json.dumps(
            {
                "failure_evidence": ["e"],
                "root_cause": "r",
                "targeted_fix": "t",
                "predicted_impact": {"fix_tasks": ["a"], "risk_tasks": ["b"]},
            }
        ),
        ["one.md", "two.md"],
    )
    assert [change.path for change in parsed.changes] == ["one.md", "two.md"]
    assert all(change.fixes == ("a",) for change in parsed.changes)
    assert all(change.risks == ("b",) for change in parsed.changes)


def test_a_per_file_entry_inherits_the_overall_prediction_when_silent():
    parsed = Manifest.parse(
        json.dumps(
            {
                "failure_evidence": ["e"],
                "root_cause": "r",
                "targeted_fix": "t",
                "predicted_impact": {"fix_tasks": ["a"]},
                "changes": [{"path": "one.md"}, {"path": "two.md", "fix_tasks": []}],
            }
        ),
        ["one.md", "two.md"],
    )
    assert parsed.changes[0].fixes == ("a",)
    # An explicit empty list is a prediction, not a silence.
    assert parsed.changes[1].fixes == ()


def test_a_missing_declaration_for_an_edited_file_is_refused():
    with pytest.raises(ManifestError, match="the edit changed"):
        Manifest.parse(
            json.dumps(
                {
                    "failure_evidence": ["e"],
                    "root_cause": "r",
                    "targeted_fix": "t",
                    "changes": [{"path": "one.md"}],
                }
            ),
            ["one.md", "two.md"],
        )


@pytest.mark.parametrize(
    "before, after, flip",
    [
        ({"t": 0.0}, {"t": 1.0}, "fail_to_pass"),
        ({"t": 1.0}, {"t": 0.0}, "pass_to_fail"),
        ({"t": 0.4}, {"t": 0.6}, "unchanged"),
    ],
)
def test_attribution_names_what_moved(before, after, flip):
    assert attribute(before, after)["t"]["flip"] == flip


# -- committing a directory a Worker edited itself --------------------------


def test_runtime_artifacts_the_worker_left_do_not_cost_the_iteration(
    monkeypatch, tmp_path
):
    """Importing an edited module writes __pycache__, which commit refuses."""
    algo, _ = setup(
        monkeypatch,
        [
            (
                {
                    _MARKER: "FIX0\n",
                    "skills/__pycache__/cached.pyc": "\x00",
                    "skills/notes.log": "tool output",
                    "skills/.env": "SECRET=value",
                },
                manifest([_MARKER], fixes=["train-0"]),
            )
        ],
    )
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    # The edit landed, and the artifacts beside it changed nothing else.
    assert final.files[_MARKER].content == b"FIX0\n"
    assert set(final.files) == set(original.files)
    assert Snapshot.load(directory / "snapshots" / f"{final.id}.json") == final


def test_an_edit_that_leaked_a_runtime_credential_is_refused(monkeypatch, tmp_path):
    """The bytes came from a process this algorithm does not control."""
    monkeypatch.setenv("FLASHRSI_TEST_API_KEY", "runtime-secret-value")
    algo, _ = setup(
        monkeypatch,
        [({_MARKER: "leaks runtime-secret-value\n"}, manifest([_MARKER]))],
    )
    directory = run_dir(algo, tmp_path)
    original = algo.target.snapshot

    final = asyncio.run(algo.evolve())

    assert final.id == original.id
    (decision,) = decisions(directory)
    assert decision["kind"] == "decline"
    assert "runtime credential" in decision["problem"]
    # Only the baseline was ever versioned; the leaking candidate was not.
    assert [p.stem for p in (directory / "snapshots").iterdir()] == [original.id]
    assert not list((directory / "working").iterdir())
