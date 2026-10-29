"""Task inputs and provider identity remain reachable through the fixed adapter."""

import asyncio
import json

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex
from flashrsi.agents.codex import _settings


@pytest.mark.parametrize("disabled", [False, True])
def test_project_instructions_and_skills_are_native_task_inputs(
    disabled, parity_source, upstream_codex, tmp_path
):
    project = tmp_path / "project"
    task = project / "nested"
    task.mkdir(parents=True)
    (project / "TASK_ROOT").touch()
    (project / "AGENTS.md").write_text("ROOT_TASK_INSTRUCTIONS\n")
    (task / "AGENTS.override.md").write_text("NESTED_TASK_INSTRUCTIONS\n")
    skill = project / ".agents/skills/task-probe/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: task-probe\ndescription: TASK_SKILL_DESCRIPTION\n---\n"
        "TASK_SKILL_PROCEDURE: write task evidence before finishing.\n"
    )
    config = parity_source / "config.toml"
    prefix = 'project_root_markers = ["TASK_ROOT"]\n'
    if disabled:
        prefix += (
            "project_doc_max_bytes = 0\n"
            "[[skills.config]]\n"
            f"path = {json.dumps(str(skill))}\nenabled = false\n"
        )
    config.write_text(prefix + config.read_text())
    observed = []
    with _responses_server() as replay:
        for label, binary in (("native", upstream_codex), ("python", None)):
            replay.reset([(200, _events())])
            options = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "timeout": 30,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
            }
            if binary:
                options["cli_path"] = binary
            result = asyncio.run(
                Codex(options).run("Use $task-probe to finish.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert not replay.steps and not replay.errors
            request = replay.requests[0]
            contents = json.dumps(request["body"])
            for marker in (
                "ROOT_TASK_INSTRUCTIONS",
                "NESTED_TASK_INSTRUCTIONS",
                "TASK_SKILL_DESCRIPTION",
                "TASK_SKILL_PROCEDURE",
            ):
                assert (marker in contents) is not disabled, marker
            assert "PARITY_VERSIONED_INSTRUCTIONS" in contents
            observed.append(_normalize(request, tmp_path))
            (tmp_path / f"{label}-integration.json").write_text(
                json.dumps(observed[-1], ensure_ascii=False, indent=2)
            )
    assert observed[0] == observed[1]


@pytest.mark.parametrize(
    "llm,expected",
    [
        ({}, "OpenAI"),
        ({"base_url": "https://api.openai.com/v1/"}, "OpenAI"),
        ({"base_url": "https://example.openai.azure.com/openai/v1"}, "Azure"),
        ({"base_url": "http://127.0.0.1:1234/v1"}, "FlashRSI endpoint"),
        (
            {"base_url": "http://127.0.0.1:1234/v1", "provider_name": "OpenAI"},
            "OpenAI",
        ),
    ],
)
def test_provider_identity_preserves_native_task_mechanism_selection(
    llm, expected, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    settings, _, _ = _settings(
        {"llm": {"model_name": "gpt-5.4", "api_key": "fake-key", **llm}},
        home,
        tmp_path,
    )
    assert settings["model_providers.flashrsi.name"] == expected


@pytest.mark.parametrize("name", ["", "  ", False, 1])
def test_invalid_provider_identity_is_explicit(name, tmp_path):
    with pytest.raises(ValueError, match="provider_name"):
        _settings(
            {
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "fake-key",
                    "provider_name": name,
                }
            },
            tmp_path,
            tmp_path,
        )


@pytest.mark.parametrize("case", ["nested", "root_cycle"])
def test_host_skill_isolation_matches_native_discovery(
    case, parity_source, upstream_codex, tmp_path, monkeypatch
):
    host = tmp_path / "host"
    root = host / ".agents/skills"
    root.parent.mkdir(parents=True)
    if case == "root_cycle":
        root.symlink_to(root, target_is_directory=True)
    else:
        for relative, name in (("outer", "outer"), ("outer/assets/nested", "nested")):
            path = root / relative / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"---\nname: host-{name}\ndescription: HOST_{name.upper()}_SKILL\n---\n"
                "This host installation is outside the selected harness.\n"
            )
    monkeypatch.setenv("HOME", str(host))
    task = tmp_path / "task"
    task.mkdir()
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset([(200, _events())])
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "timeout": 30,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run("Finish directly.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert not replay.steps and not replay.errors
            request = replay.requests[0]
            assert "HOST_OUTER_SKILL" not in json.dumps(request)
            assert "HOST_NESTED_SKILL" not in json.dumps(request)
            observed.append(_normalize(request, tmp_path))
    assert observed[0] == observed[1]
