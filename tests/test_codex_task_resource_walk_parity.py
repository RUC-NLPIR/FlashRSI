"""The pinned bounded filesystem inventory discovers nested task skills."""

import asyncio
import json

from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex


def _skill(path, name, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {marker}\n---\nBODY_{marker}\n")


def test_native_and_python_inventory_nested_skills_hidden_aliases_and_file_symlinks(
    parity_source, upstream_codex, tmp_path
):
    config_file = parity_source / "config.toml"
    config_file.write_text(
        'project_root_markers=["TASK_ROOT"]\n' + config_file.read_text()
    )
    task = tmp_path / "task"
    task.mkdir()
    (task / "TASK_ROOT").touch()
    root = task / ".agents/skills"
    _skill(root / "outer/SKILL.md", "outer-probe", "WALK_OUTER")
    _skill(root / "outer/assets/nested/SKILL.md", "nested-probe", "WALK_NESTED")
    _skill(root / ".hidden/SKILL.md", "hidden-visible", "WALK_HIDDEN_ALIAS")
    _skill(root / ".excluded/SKILL.md", "hidden-only", "WALK_HIDDEN_ONLY")
    (root / "visible-alias").symlink_to(root / ".hidden", target_is_directory=True)
    external = tmp_path / "external/SKILL.md"
    _skill(external, "file-alias", "WALK_FILE_SYMLINK")
    (root / "file-alias").mkdir()
    (root / "file-alias/SKILL.md").symlink_to(external)
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
                                {"command": "printf WALK_CHECKED > evidence"},
                            )
                        ),
                    ),
                    (200, _events("WALK_TASK_COMPLETED")),
                ]
            )
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "timeout": 30,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-walk-test-key",
                    "base_url": replay.base_url,
                },
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Use $nested-probe and $hidden-visible to write task evidence.",
                    working_dir=task,
                )
            )
            assert result.status == "finished", result.error_message
            assert result.output == "WALK_TASK_COMPLETED"
            assert not replay.steps and not replay.errors and len(replay.requests) == 2
            initial = json.dumps(replay.requests[0]["body"]["input"])
            for marker in ("WALK_OUTER", "BODY_WALK_NESTED", "BODY_WALK_HIDDEN_ALIAS"):
                assert marker in initial, (label, marker)
            assert "WALK_HIDDEN_ONLY" not in initial
            assert "WALK_FILE_SYMLINK" not in initial
            assert (task / "evidence").read_text() == "WALK_CHECKED"
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
            (tmp_path / f"{label}-skill-walk.json").write_text(
                json.dumps(trace, indent=2)
            )
            observed.append(trace)
    assert observed[0] == observed[1], f"Full skill-inventory task traces in {tmp_path}"
