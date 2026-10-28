"""Native-file curation, shared evaluation and portable Snapshot contracts."""

import asyncio
import json
from dataclasses import replace

import pytest
import yaml
from algorithm_helpers import MemoryBenchmark

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.algorithms import EvoHarness
from flashrsi.core import Agent, Algorithm, Snapshot, Task, Trajectory

MEMORY = json.dumps(
    {
        "lesson": "Verify evidence",
        "trigger": "Evidence questions",
        "evidence": "Skipped verification",
        "scope_hint": "QA",
    }
)
PATH = "skills/verify/SKILL.md"


def skill(content="WIN", *, level="topic", sources=("train-0",)):
    meta = {
        "name": "verify",
        "description": "Verify supplied evidence on evidence-backed questions",
        "flashrsi": {
            "algorithm": "evo_harness",
            "level": level,
            "source_task_ids": list(sources),
        },
    }
    return "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n" + content + "\n"


class FileWorker(Agent):
    name = "file_worker"
    description = "Scripted native directory editor."

    def __init__(self, replies):
        super().__init__({"type": "agent", "llm": {"model_name": "offline-worker"}})
        self.replies = iter(replies)
        self.prompts = []

    async def _run(self, prompt, working_dir=None):
        self.prompts.append(prompt)
        reply = next(self.replies)
        if working_dir is None:
            return Trajectory(output=reply)
        for path, content in reply.items():
            file = working_dir / path
            if content is None:
                file.chmod(0o644)
                file.unlink()
            else:
                file.parent.mkdir(parents=True, exist_ok=True)
                # Replace like an editor using atomic writes: commit must still
                # reject changes to resources exported read-only.
                if file.exists():
                    file.chmod(0o644)
                    file.unlink()
                file.write_text(content, newline="\n")
        return Trajectory(output="Curated native skills.")


class Scores(MemoryBenchmark):
    def grade(self, results):
        return tuple(
            replace(row, metrics={"accuracy": float(row.output)}) for row in results
        )


def setup(
    monkeypatch,
    replies,
    *,
    cls=MiniAgent,
    bench=None,
    score=None,
    env_runner=None,
    **config,
):
    calls = []

    async def run(self, prompt, working_dir=None):
        procedures = algo._skills(self.snapshot)
        text = "\n".join(row["content"] for row in procedures.values())
        calls.append((prompt, text, self.snapshot.id))
        return Trajectory(
            output=str(score(prompt, text) if score else float("WIN" in text)),
            messages=({"role": "tool", "content": "Observed verification failure"},),
        )

    monkeypatch.setattr(cls, "_run", run)
    target = cls(
        {
            "llm": {"model_name": "offline-target", "api_key": "target-secret"},
        }
    )
    target._env_runner = env_runner
    algo = EvoHarness(
        {"batch_size": 1, **config},
        target=target,
        worker=FileWorker(replies),
        benchmark=bench or Scores(),
    )
    return algo, calls


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_final_snapshot_uses_shared_evaluation_and_restored_agent(
    monkeypatch, tmp_path, cls
):
    algo, calls = setup(monkeypatch, [MEMORY, {PATH: skill()}, {}], cls=cls)
    algo._run_dir = tmp_path
    for folder in ("snapshots", "trajectories", "working"):
        (tmp_path / folder).mkdir()
    seed = algo.target.snapshot
    final = asyncio.run(algo.evolve())
    assert EvoHarness._evaluate is Algorithm._evaluate
    assert [prompt for prompt, _, _ in calls] == ["train-0", "train-1"]
    assert not calls[0][1] and calls[1][1] == "WIN"
    assert algo._skills(final)[PATH]["level"] == "topic"
    assert all(
        final.files[path] == entry
        for path, entry in seed.files.items()
        if entry.component not in {"skill", "config"}
    )
    assert seed.files.get("skills/main.md") == final.files.get("skills/main.md")
    assert not any(
        "dev-only" in p or "test-only" in p or "RunConfig" in p or "target-secret" in p
        for p in algo.worker.prompts
    )
    assert "Observed verification failure" in algo.worker.prompts[0]
    requests = len(algo.worker.prompts)
    evaluated = asyncio.run(algo._evaluate(final, algo.benchmark.test, label="test"))
    restored = cls(algo.target.config)
    restored.update(Snapshot.load(tmp_path / "snapshots" / f"{final.id}.json"))
    ordinary = algo.benchmark.grade(asyncio.run(restored.rollout(algo.benchmark.test)))
    assert evaluated.score == ordinary[0].metrics["accuracy"] == 1
    assert len(algo.worker.prompts) == requests
    assert calls[-1][1:] == calls[-2][1:]
    record = json.loads(
        next((tmp_path / "trajectories").glob("*-test.json")).read_text()
    )
    assert record["snapshot_id"] == final.id
    assert not list((tmp_path / "trajectories").glob("*-selection.json"))
    decisions = [
        json.loads(p.read_text())
        for p in sorted((tmp_path / "trajectories").glob("*-decision.json"))
    ]
    assert decisions[-1]["online_score"] == 0.5
    assert decisions[-1]["online_tasks"] == 2


def test_batch_keeps_one_version_and_compiles_both_levels(monkeypatch):
    bench = Scores()
    bench.load()
    bench._splits["train"] = tuple(Task(f"train-{i}", f"train-{i}") for i in range(3))
    general = skill(
        "GENERAL", level="general", sources=("train-0", "train-1", "train-2")
    ).replace("name: verify", "name: shared")
    algo, calls = setup(
        monkeypatch,
        [MEMORY] * 3 + [{PATH: skill()}, {"skills/shared/SKILL.md": general}],
        bench=bench,
        batch_size=3,
    )
    final = asyncio.run(algo.evolve())
    assert len({version for _, _, version in calls}) == 1
    assert {row["level"] for row in algo._skills(final).values()} == {
        "general",
        "topic",
    }
    assert "WIN" in algo.worker.prompts[-1]


def test_success_never_reflects(monkeypatch):
    algo, calls = setup(monkeypatch, [], score=lambda p, t: 1)
    seed = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == seed.id
    assert len(calls) == 2 and not algo.worker.prompts


def test_keeps_regression_and_does_not_validate_dev(monkeypatch):
    algo, calls = setup(
        monkeypatch,
        [MEMORY, {PATH: skill("BAD")}, {}, MEMORY, {}, {}],
        score=lambda p, t: 0.1 if "BAD" in t else 0.5,
    )
    final = asyncio.run(algo.evolve())
    assert "BAD" in calls[-1][1] and b"BAD" in final.files[PATH].content
    assert all(p != "dev-only" for p, _, _ in calls)


def test_step_limit_and_empty_dev(monkeypatch):
    bench = Scores()
    bench.load()
    bench._splits["dev"] = ()
    algo, calls = setup(monkeypatch, [MEMORY, {}, {}], bench=bench, max_steps=1)
    asyncio.run(algo.evolve())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "files,config,problem",
    [
        ({PATH: skill(sources=("test-only",))}, {}, "cite"),
        ({PATH: skill("too long")}, {"max_skill_chars": 3}, "max_skill_chars"),
        ({PATH: skill()}, {"max_library_chars": 10}, "max_library_chars"),
        ({PATH: skill(level="general")}, {}, "requested level"),
        ({"skills/main.md": "Unrelated replacement"}, {}, "unmanaged"),
        ({"prompts/system.md": "Replacement"}, {}, "hidden component"),
    ],
)
def test_invalid_directory_edit_is_declined(
    monkeypatch, tmp_path, files, config, problem
):
    algo, _ = setup(monkeypatch, [MEMORY, files, {}], max_steps=1, **config)
    algo._run_dir = tmp_path
    for folder in ("snapshots", "trajectories", "working"):
        (tmp_path / folder).mkdir()
    seed = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == seed.id
    rows = [
        json.loads(p.read_text())
        for p in (tmp_path / "trajectories").glob("*-declined.json")
    ]
    assert problem in rows[0]["problem"]


def test_general_revision_does_not_inherit_old_support(monkeypatch):
    algo, _ = setup(
        monkeypatch,
        [MEMORY, {}, {PATH: skill("NEW RULE", level="general")}],
        max_steps=1,
    )
    seeded = algo._candidate(
        algo.target.snapshot,
        {PATH: skill("OLD RULE", level="general", sources=("old-a", "old-b", "old-c"))},
    )
    algo.target.update(seeded)
    final = asyncio.run(algo.evolve())
    assert final.id == seeded.id
    assert algo._skills(final)[PATH]["source_task_ids"] == [
        "old-a",
        "old-b",
        "old-c",
    ]


def test_revision_support_only_describes_current_content(monkeypatch):
    algo, _ = setup(monkeypatch, [MEMORY, {PATH: skill("CORRECTED")}, {}], max_steps=1)
    seeded = algo._candidate(
        algo.target.snapshot, {PATH: skill("OLD", sources=("old-task",))}
    )
    algo.target.update(seeded)
    final = asyncio.run(algo.evolve())
    assert algo._skills(final)[PATH]["source_task_ids"] == ["train-0"]
    assert final.parent_id == seeded.id


def test_unchanged_checkout_does_not_create_adopted_version(monkeypatch):
    algo, _ = setup(monkeypatch, [MEMORY, {}, {}], max_steps=1)
    seed = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == seed.id


def test_worker_failure_propagates(monkeypatch):
    algo, _ = setup(monkeypatch, [])

    async def failed(prompt, working_dir=None):
        return Trajectory(status="error", error_message="worker unavailable")

    algo.worker._run = failed
    with pytest.raises(RuntimeError, match="worker unavailable"):
        asyncio.run(algo.evolve())


def test_skill_code_blocks_survive_native_files(monkeypatch):
    body = "WIN\n```python\nassert answer == observation\n```"
    algo, calls = setup(
        monkeypatch, ["```json\n" + MEMORY + "\n```", {PATH: skill(body)}, {}]
    )
    final = asyncio.run(algo.evolve())
    assert algo._skills(final)[PATH]["content"] == body
    assert calls[-1][1] == body


@pytest.mark.parametrize(
    "tasks,problem",
    [((), "non-empty"), ((Task("same", "a"), Task("same", "b")), "unique")],
)
def test_invalid_stream_fails_at_start(monkeypatch, tasks, problem):
    bench = Scores()
    bench.load()
    bench._splits["train"] = tasks
    with pytest.raises(ValueError, match=problem):
        setup(monkeypatch, [], bench=bench)


def test_text_worker_fails_at_start(monkeypatch):
    from flashrsi.agents import LLM

    algo, _ = setup(monkeypatch, [])
    with pytest.raises(ValueError, match="file-editing Worker"):
        EvoHarness(
            {},
            target=algo.target,
            worker=LLM({"llm": {"model_name": "unused"}}),
            benchmark=Scores(),
        )


def test_removing_provenance_cannot_leave_an_untracked_native_skill(
    monkeypatch, tmp_path
):
    algo, _ = setup(
        monkeypatch,
        [MEMORY, {PATH: "---\nname: verify\ndescription: Untracked\n---\nWIN"}, {}],
        max_steps=1,
    )
    seed = algo.target.snapshot
    with seed.check_out() as directory:
        path = directory / PATH
        path.parent.mkdir(parents=True)
        path.write_text(skill("OLD"), newline="\n")
        seed = seed.commit(directory)
    algo.target.update(seed)
    algo._run_dir = tmp_path
    for folder in ("snapshots", "trajectories", "working"):
        (tmp_path / folder).mkdir()
    assert asyncio.run(algo.evolve()).id == seed.id
    assert (
        "provenance"
        in next((tmp_path / "trajectories").glob("*-declined.json")).read_text()
    )


@pytest.mark.parametrize("wrapped", [False, True])
def test_reflection_preserves_code_snippets_in_memory(monkeypatch, wrapped):
    memory = json.loads(MEMORY)
    memory["evidence"] = "Failed assertion:\n```python\nassert checked\n```"
    reply = json.dumps(memory)
    if wrapped:
        reply = "Here is the memory:\n```json\n" + reply + "\n```"
    algo, _ = setup(monkeypatch, [reply, {PATH: skill()}, {}], max_steps=1)
    assert PATH in asyncio.run(algo.evolve()).files
    assert "assert checked" in algo.worker.prompts[1]


@pytest.mark.parametrize("reply", ["invalid", "[]", "{}"])
def test_invalid_reflection_is_declined_without_compilation(monkeypatch, reply):
    algo, _ = setup(monkeypatch, [reply], max_steps=1)
    seed = algo.target.snapshot
    assert asyncio.run(algo.evolve()).id == seed.id
    assert len(algo.worker.prompts) == 1
