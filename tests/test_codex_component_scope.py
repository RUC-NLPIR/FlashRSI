"""Component boundaries for the Codex Snapshot editing surface."""

from __future__ import annotations

from collections import Counter

import pytest

from flashrsi.agents import Codex


@pytest.fixture
def codex():
    return Codex({"llm": {"model_name": "local-component-test"}})


def test_codex_core_resources_have_evolution_components(codex):
    snapshot = codex.snapshot
    expected = {
        "python_core/loop.py": "code",
        "python_core/assets/prompt.md": "prompt",
        "python_core/assets/compact/prompt.md": "prompt",
        "python_core/resource_assets/system_skills/imagegen/SKILL.md": "skill",
        "python_core/tool_assets/agent_roles.json": "agent",
        "python_core/resource_assets/hook_schemas/session-start.command.output.schema.json": "hook",
        "python_core/code_mode_assets/exec.lark": "tool",
        "python_core/memory_assets/read_path.md": "memory",
        "python_core/assets/models.json": "config",
    }
    assert {path: snapshot.files[path].component for path in expected} == expected
    counts = Counter(entry.component for entry in snapshot.files.values())
    assert counts["code"] > 0
    for component in ("prompt", "skill", "agent", "hook", "tool", "memory", "config"):
        assert counts[component] > 0, component


def test_component_scope_checkout_exposes_only_selected_surfaces(codex):
    codex.set_scope({"prompt": "rw", "skill": "rw"})
    snapshot = codex.snapshot
    with snapshot.check_out() as directory:
        checked_out = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
        }
    expected = {
        path
        for path, entry in snapshot.files.items()
        if entry.component in {"prompt", "skill"}
    }
    assert checked_out == expected
    assert checked_out
    assert all(
        snapshot.files[path].component in {"prompt", "skill"} for path in checked_out
    )


def test_component_scope_allows_selected_resource_edits(codex):
    codex.set_scope({"prompt": "rw", "skill": "rw"})
    baseline = codex.snapshot
    with baseline.check_out() as directory:
        prompt = directory / "python_core/assets/prompt.md"
        skill = directory / "python_core/resource_assets/skills_prompt.json"
        prompt.write_bytes(prompt.read_bytes() + b"\nCOMPONENT_PROMPT_EDIT\n")
        skill.write_bytes(skill.read_bytes() + b"\n")
        candidate = baseline.commit(directory)
    assert baseline.changed_paths(candidate) == (
        "python_core/assets/prompt.md",
        "python_core/resource_assets/skills_prompt.json",
    )
    assert candidate.files["python_core/assets/prompt.md"].component == "prompt"
    assert (
        candidate.files["python_core/resource_assets/skills_prompt.json"].component
        == "skill"
    )
    assert codex.snapshot.id == baseline.id


def test_code_scope_edits_core_while_retaining_hidden_runtime(codex):
    codex.set_scope({"code": "rw"})
    baseline = codex.snapshot
    with baseline.check_out() as directory:
        visible = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
        }
        assert visible == {
            path for path, entry in baseline.files.items() if entry.component == "code"
        }
        loop = directory / "python_core/loop.py"
        loop.write_bytes(loop.read_bytes() + b"\nCODE_SCOPE_EDIT\n")
        candidate = baseline.commit(directory)

    assert baseline.changed_paths(candidate) == ("python_core/loop.py",)
    assert (
        candidate.files["python_core/tools.py"]
        == baseline.files["python_core/tools.py"]
    )


def test_component_scope_rejects_unselected_core_edits(codex):
    codex.set_scope({"prompt": "rw", "skill": "rw"})
    baseline = codex.snapshot
    with baseline.check_out() as directory:
        core_file = directory / "python_core/loop.py"
        core_file.parent.mkdir(parents=True, exist_ok=True)
        core_file.write_text("# attempted code edit\n")
        with pytest.raises(ValueError, match=r"hidden component: python_core/loop.py"):
            baseline.commit(directory)
