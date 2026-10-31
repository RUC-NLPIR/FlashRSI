"""Reject reviewer counterexamples at the native-file commit boundary."""

import asyncio
import json

import pytest
import yaml
from test_evo_harness import PATH, setup, skill

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.agents.miniagent.runtime.workspace import load
from flashrsi.core import Snapshot

MEMORIES = [
    {
        "task_id": "train-0",
        "lesson": "Check",
        "evidence": "Skipped check",
        "trigger": "QA",
        "scope_hint": "topic",
    }
]


@pytest.fixture
def editor(monkeypatch, tmp_path):
    def create(*, cls=MiniAgent, seed_files=None):
        algo, _ = setup(monkeypatch, [], cls=cls)
        if seed_files:
            algo.target.update(algo._candidate(algo.target.snapshot, seed_files))
        algo._run_dir = tmp_path
        for folder in ("snapshots", "trajectories", "working"):
            (tmp_path / folder).mkdir(exist_ok=True)
        return algo

    return create


def compile_edit(algo, files, *, level="topic"):
    algo.worker.replies = iter([files])
    return asyncio.run(algo._compile(algo.target.snapshot, MEMORIES, level, 1))


def declined(algo, files, problem, *, level="topic"):
    seed = algo.target.snapshot
    assert compile_edit(algo, files, level=level).id == seed.id
    assert algo.target.snapshot.id == seed.id
    record = json.loads(
        sorted((algo._run_dir / "trajectories").glob("*-declined.json"))[-1].read_text()
    )
    assert problem in record["problem"]


@pytest.mark.parametrize("mutation", ["prompt", "tools", "middleware", "remove-main"])
def test_configuration_only_edits_cannot_change_native_behavior(editor, mutation):
    algo = editor()
    data = yaml.safe_load(algo.target.snapshot.files["agent.yaml"].content)
    if mutation == "prompt":
        data["prompts"]["system"] = "prompts/extract.md"
    elif mutation == "tools":
        data["tools"] = []
    elif mutation == "middleware":
        data["middlewares"] = ["unexpected"]
    else:
        data["skills"] = []
    declined(
        algo,
        {"agent.yaml": yaml.safe_dump(data)},
        "outside allowed components (config)",
    )


def test_valid_skill_cannot_hide_unrelated_config_changes(editor):
    algo = editor()
    declined(
        algo,
        {
            PATH: skill(),
            "agent.yaml": "middlewares: [unexpected]\n",
        },
        "outside allowed components (config)",
    )


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_native_skill_cannot_be_taken_over_by_adding_provenance(editor, cls):
    algo = editor(
        cls=cls,
        seed_files={
            PATH: "---\nname: verify\ndescription: Native procedure\n---\nKEEP"
        },
    )
    declined(algo, {PATH: skill("REPLACED")}, "unmanaged")


@pytest.mark.parametrize("cls", [MiniAgent, ClaudeCode])
def test_raw_frontmatter_change_cannot_edit_other_level(editor, cls):
    old = skill("GENERAL", level="general", sources=("old-a", "old-b", "old-c"))
    algo = editor(cls=cls, seed_files={PATH: old})
    declined(
        algo,
        {
            PATH: old.replace(
                "name: verify", "disable-model-invocation: true\nname: verify"
            )
        },
        "requested level",
    )


def test_same_level_metadata_change_requires_fresh_evidence(editor):
    old = skill("OLD", sources=("old-task",))
    algo = editor(seed_files={PATH: old})
    declined(
        algo,
        {PATH: old.replace("name: verify", "allowed-tools: []\nname: verify")},
        "cite",
    )


def test_skill_creation_and_deletion_need_no_configuration_edit(editor, tmp_path):
    algo = editor()
    original_config = algo.target.snapshot.files["agent.yaml"]
    seeded = compile_edit(algo, {PATH: skill()})
    assert PATH in seeded.files
    ordinary = MiniAgent(algo.target.config)
    ordinary.update(seeded)
    with ordinary.snapshot.check_out() as directory:
        assert "Available skill: verify" in load(directory).system_prompt
    final = compile_edit(algo, {PATH: None})
    assert final.id != seeded.id and PATH not in final.files
    assert final.files["agent.yaml"] == original_config
    saved = tmp_path / "final.json"
    final.save(saved)
    restored = MiniAgent(algo.target.config)
    restored.update(Snapshot.load(saved))
    with restored.snapshot.check_out() as directory:
        bundle = load(directory)
        assert "Available skill: verify" not in bundle.system_prompt
        assert "read_skill" not in bundle.tool_names


def test_automatic_discovery_target_configuration_stays_frozen(editor):
    algo = editor(cls=ClaudeCode)
    declined(
        algo,
        {"settings.json": '{"permissions": {"allow": ["Bash(*)"]}}'},
        "outside allowed components (config)",
    )
    assert PATH in compile_edit(algo, {PATH: skill()}).files


def test_algorithm_does_not_branch_on_target_name(editor):
    algo = editor()
    algo.target.name = "unregistered-native-harness"
    assert PATH in compile_edit(algo, {PATH: skill()}).files


def test_new_directory_skill_cannot_shadow_existing_flat_native_skill(editor):
    algo = editor()
    declined(algo, {"skills/main/SKILL.md": skill()}, "shadow native")
