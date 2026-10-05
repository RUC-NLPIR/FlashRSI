"""Optional directory skills preserve the native flat-skill default."""

import asyncio
from types import SimpleNamespace

import pytest

from flashrsi.agents import MiniAgent
from flashrsi.agents.miniagent.runtime import workspace
from flashrsi.agents.miniagent.tools.read_skill import call


@pytest.fixture
def native_workspace(tmp_path):
    seed = MiniAgent({"llm": {"model_name": "unused"}}).snapshot
    for path, entry in seed.files.items():
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(entry.content)
    return tmp_path


def add_skill(root):
    path = root / "skills/probe/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nname: probe\ndescription: Check evidence when applicable\n"
        "flashrsi:\n  source_task_ids: [train-0]\n---\n"
        "PROCEDURE_BODY\n```python\nprint('checked')\n```\n"
    )


def test_directory_skill_is_loaded_only_after_native_tool_call(native_workspace):
    root = native_workspace
    baseline = workspace.load(root)
    assert "read_skill" not in baseline.tool_names
    add_skill(root)
    bundle = workspace.load(root)
    assert "Check evidence when applicable" in bundle.system_prompt
    assert "PROCEDURE_BODY" not in bundle.system_prompt
    assert "source_task_ids" not in bundle.system_prompt
    assert baseline.system_prompt in bundle.system_prompt
    ctx = SimpleNamespace(workspace=bundle)
    body = asyncio.run(bundle.extra_tools["read_skill"]({"skill": "probe"}, ctx))
    assert "PROCEDURE_BODY" in body and "```python" in body
    assert "source_task_ids" not in body


def test_directory_skill_removal_clears_catalog_and_reader(native_workspace):
    config = (native_workspace / "agent.yaml").read_bytes()
    add_skill(native_workspace)
    assert "read_skill" in workspace.load(native_workspace).tool_names
    (native_workspace / "skills/probe/SKILL.md").unlink()
    bundle = workspace.load(native_workspace)
    assert "read_skill" not in bundle.tool_names
    assert "Available skill: probe" not in bundle.system_prompt
    assert (native_workspace / "agent.yaml").read_bytes() == config


def test_directory_cannot_shadow_flat_skill(native_workspace):
    add_skill(native_workspace)
    (native_workspace / "skills/probe.md").write_text("Unrelated native skill")
    with pytest.raises(ValueError, match="shadows"):
        workspace.load(native_workspace)


def test_discovered_skills_require_native_reader_resources(native_workspace):
    add_skill(native_workspace)
    (native_workspace / "tools/read_skill.py").unlink()
    with pytest.raises(FileNotFoundError, match="read_skill"):
        workspace.load(native_workspace)


@pytest.mark.parametrize("name", [None, "unknown", "../outside", "", "probe/../probe"])
def test_read_skill_is_limited_to_discovered_workspace_skills(native_workspace, name):
    add_skill(native_workspace)
    ctx = SimpleNamespace(workspace=SimpleNamespace(root=native_workspace))
    with pytest.raises(ValueError, match="discovered workspace skill"):
        asyncio.run(call({"skill": name}, ctx))
