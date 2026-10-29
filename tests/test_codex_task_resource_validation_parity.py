"""Pinned skill parsing and explicit selection in complete local replay tasks."""

import asyncio
import json

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex


@pytest.mark.parametrize(
    "case",
    [
        "unconfigured-mcp",
        "blank-name",
        "env-mention",
        "unicode-name",
        "hidden-catalog",
        "trimmed-name-selector",
        "directory-selector",
        "both-selectors",
        "later-enable-selector",
    ],
)
def test_native_and_python_apply_skill_rules_and_complete_the_same_task(
    case, parity_source, upstream_codex, tmp_path
):
    config_file = parity_source / "config.toml"
    config_file.write_text(config_file.read_text() + "shell_snapshot=false\n")
    name = "HOME" if case == "env-mention" else "parity"
    if case == "unicode-name":
        name = "界" * 64
    skill = parity_source / "skills/parity/SKILL.md"
    skill.write_text(
        "---\nname: "
        + ('"   "' if case == "blank-name" else name)
        + "\ndescription: RESOURCE_RULE_CATALOG\n---\nRESOURCE_RULE_BODY\n"
    )
    if case == "unconfigured-mcp":
        metadata = skill.parent / "agents/openai.yaml"
        metadata.parent.mkdir()
        metadata.write_text(
            "dependencies:\n  tools:\n    - type: mcp\n      value: not_configured\n"
        )
    skill_config = {
        "hidden-catalog": "include_instructions=false\n",
        "trimmed-name-selector": 'config=[{name=" parity ",enabled=false}]\n',
        "directory-selector": 'config=[{path="skills/parity",enabled=false}]\n',
        "both-selectors": 'config=[{path="skills/parity/SKILL.md",name="parity",enabled=false}]\n',
        "later-enable-selector": 'config=[{path="skills/parity/SKILL.md",enabled=false},{name="parity",enabled=true}]\n',
    }.get(case)
    if skill_config:
        config_file.write_text(config_file.read_text() + "[skills]\n" + skill_config)
    prompt = (
        f"Inspect $HOME and [$HOME]({skill}) without treating shell variables as skills."
        if case == "env-mention"
        else "Inspect the skill catalog and write evidence."
        if case == "unicode-name"
        else "Use $parity to write evidence and finish."
    )
    task = tmp_path / "task"
    task.mkdir()
    observed = []
    with _responses_server() as replay:
        for label, binary in (("native", upstream_codex), ("python", None)):
            (task / "evidence").unlink(missing_ok=True)
            replay.reset(
                [
                    (
                        200,
                        _events(
                            call=(
                                "shell_command",
                                {"command": "printf RESOURCE_RULE_CHECKED > evidence"},
                            )
                        ),
                    ),
                    (200, _events("RESOURCE_RULE_TASK_COMPLETED")),
                ]
            )
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "timeout": 30,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-resource-test-key",
                    "base_url": replay.base_url,
                },
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(Codex(config).run(prompt, working_dir=task))
            assert result.status == "finished", result.error_message
            assert result.output == "RESOURCE_RULE_TASK_COMPLETED"
            assert len(replay.requests) == 2 and not replay.steps and not replay.errors
            first_input = json.dumps(
                replay.requests[0]["body"]["input"], ensure_ascii=False
            )
            catalog = "\n".join(
                part["text"]
                for item in replay.requests[0]["body"]["input"]
                for part in item.get("content", [])
                if part.get("text", "").startswith("<skills_instructions>")
            )
            assert ("RESOURCE_RULE_CATALOG" in catalog) == (
                case not in {"hidden-catalog", "trimmed-name-selector"}
            )
            assert ("RESOURCE_RULE_BODY" in first_input) == (
                case not in {"env-mention", "unicode-name", "trimmed-name-selector"}
            )
            assert (task / "evidence").read_text() == "RESOURCE_RULE_CHECKED"
            trace = _normalize(
                {
                    "requests": replay.requests,
                    "status": result.status,
                    "output": result.output,
                    "usage": dict(result.usage),
                    "file": (task / "evidence").read_text(),
                },
                tmp_path,
            )
            (tmp_path / f"{label}-skill-rule-task.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2)
            )
            observed.append(trace)
    assert observed[0] == observed[1], f"Full skill-rule task traces in {tmp_path}"
