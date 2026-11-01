"""Execute native resource semantics against original Pi v1.4.0 records."""

import json
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.prompt_builder import (
    build_system_prompt_sections,
    diff_system_prompt_sections,
    render_sections,
)
from flashrsi.agents.pi_agent.runtime.pi_native.resources import (
    _load_skills,
    _parse_frontmatter,
    load_resources,
)

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures/pi_resources_upstream.json").read_text()
)
KEYS = {
    "selectedTools": "selected_tools",
    "hiddenTools": "hidden_tools",
    "toolSnippets": "tool_snippets",
    "toolGuidelines": "tool_guidelines",
    "promptGuidelines": "prompt_guidelines",
    "customPrompt": "custom_prompt",
    "appendSystemPrompt": "append_system_prompt",
    "contextFiles": "context_files",
}


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda case: case["name"])
def test_prompt_sections_match_executed_original(case, tmp_path):
    options = {KEYS.get(key, key): value for key, value in case["options"].items()}
    if "forceSystemPrompt" in options:
        bundle = load_resources(
            tmp_path, tmp_path, force_system_prompt=options["forceSystemPrompt"]
        )
        assert bundle.system_prompt == case["text"]
        assert bundle.system_sections is None
        return
    if "error" in case:
        with pytest.raises(ValueError, match=case["error"]):
            build_system_prompt_sections(**options, reference_root="<REFERENCE>")
        return
    result = build_system_prompt_sections(**options, reference_root="<REFERENCE>")
    assert result == case["state"]["sections"]
    assert render_sections(result) == case["text"]


@pytest.mark.parametrize("case", ORACLE["patches"])
def test_section_patch_matches_original(case):
    assert (
        diff_system_prompt_sections(case["previous"], case["current"])
        == case["expected"]
    )


@pytest.mark.parametrize("case", ORACLE["frontmatter"])
def test_yaml_core_and_body_match_original(case):
    metadata, body = _parse_frontmatter(case["raw"])
    assert {"frontmatter": metadata, "body": body} == case["expected"]


def test_skill_warnings_preserve_loaded_skills_and_strict_boolean(tmp_path):
    fixture = ORACLE["skills"]
    for name, text in fixture["files"].items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    diagnostics = []
    loaded = _load_skills(tmp_path, diagnostics)
    actual = [
        {
            "name": skill.name,
            "description": skill.description,
            "path": str(Path(skill.path).relative_to(tmp_path)),
            "disable_model_invocation": skill.disable_model_invocation,
        }
        for skill in loaded
    ]
    assert actual == fixture["expected"]
    assert diagnostics


def test_project_system_override_append_and_resource_precedence(tmp_path):
    snapshot = tmp_path / "snapshot"
    work = tmp_path / "task"
    snapshot.mkdir()
    (work / ".pi").mkdir(parents=True)
    (snapshot / "SYSTEM.md").write_text("snapshot system\n")
    (snapshot / "APPEND_SYSTEM.md").write_text("snapshot append\n")
    (work / ".pi/SYSTEM.md").write_text("project system\n")
    (work / ".pi/APPEND_SYSTEM.md").write_text("project append\n")
    bundle = load_resources(snapshot, work)
    assert bundle.system_sections["preamble"] == "project system\n"
    assert (
        bundle.system_sections["addendum"]
        == "<addendum>\nproject append\n\n</addendum>"
    )
    assert "tools" not in bundle.system_sections
    untrusted = load_resources(snapshot, work, project_trusted=False)
    assert untrusted.system_sections["preamble"] == "snapshot system\n"
    explicit = load_resources(
        snapshot, work, custom_system_prompt="explicit", append_system_prompt="override"
    )
    assert explicit.system_sections["preamble"] == "explicit"
    assert explicit.system_sections["addendum"] == "<addendum>\noverride\n</addendum>"


def test_pinned_documentation_paths_are_real_snapshot_resources():
    snapshot = Path(__file__).parents[1] / "flashrsi/agents/pi_agent"
    bundle = load_resources(snapshot, snapshot, selected_tools=[])
    reference = snapshot / "runtime/pi_native/reference"
    assert str(reference / "README.md") in bundle.system_prompt
    sources = json.loads((reference.parent / "PROMPT_SOURCES.json").read_text())
    import hashlib

    for name, expected in sources["reference_assets"].items():
        assert hashlib.sha256((reference / name).read_bytes()).hexdigest() == expected


def test_nested_linked_worktree_shadows_main_repository_instructions(tmp_path):
    main = tmp_path / "main"
    work = main / "worktrees/feature"
    git_dir = main / ".git/worktrees/feature"
    git_dir.mkdir(parents=True)
    work.mkdir(parents=True)
    (git_dir / "commondir").write_text("../..\n")
    (work / ".git").write_text(f"gitdir: {git_dir}\n")
    (main / "AGENTS.md").write_text("MAIN_CONTEXT_MUST_BE_SHADOWED")
    (work / "AGENTS.md").write_text("WORKTREE_CONTEXT")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    bundle = load_resources(snapshot, work)
    assert "WORKTREE_CONTEXT" in bundle.system_prompt
    assert "MAIN_CONTEXT_MUST_BE_SHADOWED" not in bundle.system_prompt
