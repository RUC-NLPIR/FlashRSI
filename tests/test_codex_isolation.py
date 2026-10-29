"""Isolate task configuration while retaining native task instruction inputs."""

import asyncio
import json
import shutil
import subprocess
import sys

import pytest
from test_codex_native import _config, _source
from test_codex_native import codex_binary as codex_binary
from test_codex_native import responses_server as responses_server

from flashrsi.agents import Codex


def test_native_git_root_stays_untrusted_when_task_is_nested(
    responses_server, codex_binary, tmp_path
):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is required to exercise native project-root discovery")
    project = tmp_path / "target-repo"
    task = project / "nested/work"
    task.mkdir(parents=True)
    subprocess.run([git, "init", "-q", str(project)], check=True, capture_output=True)
    target_hook = tmp_path / "target-hook-ran"
    snapshot_hook = tmp_path / "snapshot-hook-ran"
    (project / ".codex").mkdir()
    (project / ".codex/config.toml").write_text(
        'developer_instructions = "TARGET_PROJECT_CONTEXT"\n'
        "[features]\nhooks = true\n"
        "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
        'type = "command"\n'
        "command = " + json.dumps(f'echo target > "{target_hook}"') + "\n"
    )
    source = _source(tmp_path / "snapshot")
    hook = source / "hooks/session.py"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        f"import pathlib\npathlib.Path({str(snapshot_hook)!r}).write_text('snapshot')\n"
    )
    native = (
        'developer_instructions = "SNAPSHOT_CONTEXT"\n'
        "[features]\nplugins = false\nhooks = true\n"
        "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
        'type = "command"\n'
        "command = "
        + json.dumps(f'"{sys.executable}" "$CODEX_HOME/hooks/session.py"')
        + "\n"
        + f"[projects.{json.dumps(str(project.resolve()))}]\n"
        + 'trust_level = "trusted"\n'
    )
    (source / "config.toml").write_text(native)
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))
    baseline = agent.snapshot

    result = asyncio.run(agent.run("Answer directly.", working_dir=task))

    assert result.status == "finished", result.error_message
    request = json.dumps(responses_server.requests[-1]["body"])
    assert "SNAPSHOT_CONTEXT" in request
    assert "TARGET_PROJECT_CONTEXT" not in request
    assert snapshot_hook.read_text() == "snapshot"
    assert not target_hook.exists()
    assert agent.snapshot is baseline
    assert (source / "config.toml").read_text() == native


@pytest.mark.parametrize("directory", [".codex", ".agents"])
def test_native_ancestor_skill_discovery_respects_untrusted_project_config(
    responses_server, codex_binary, tmp_path, directory
):
    project = tmp_path / "target-project"
    task = project / "nested/work"
    task.mkdir(parents=True)
    external = tmp_path / "ambient-skill"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    external.mkdir()
    (external / "SKILL.md").write_text(
        "---\nname: ambient-probe\ndescription: TARGET_AMBIENT_SKILL\n---\n"
        "This skill belongs to the task project.\n"
    )
    ambient = project / directory / "skills"
    ambient.mkdir(parents=True)
    (ambient / "probe").symlink_to(external, target_is_directory=True)
    source = _source(tmp_path / "snapshot")
    selected = source / "skills/selected/SKILL.md"
    selected.parent.mkdir(parents=True)
    selected.write_text(
        "---\nname: selected\ndescription: SNAPSHOT_SELECTED_SKILL\n---\n"
        "Use the selected version's procedure.\n"
    )
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))

    result = asyncio.run(agent.run("Answer directly.", working_dir=task))

    assert result.status == "finished", result.error_message
    request = json.dumps(responses_server.requests[-1]["body"])
    assert "SNAPSHOT_SELECTED_SKILL" in request
    assert "TARGET_AMBIENT_SKILL" in request
    assert "TARGET_AMBIENT_SKILL" in (external / "SKILL.md").read_text()
