"""Exercise installed native plugin bundles from a candidate Snapshot."""

import asyncio
import json
import shlex
import sys
from pathlib import Path

import pytest
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_native import _config, _source
from test_codex_native import responses_server as responses_server

from flashrsi.agents import Codex
from flashrsi.core import Task


@pytest.mark.parametrize("backend", ["upstream", "core"])
def test_native_plugin_skill_and_hook_use_candidate_bundle(
    responses_server, upstream_codex, tmp_path, monkeypatch, backend
):
    # Native plugin discovery also refreshes its public catalog. Keep those
    # background requests offline while the model talks only to our fixture.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
        monkeypatch.setenv(name.lower(), "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    source = _source(tmp_path)
    relative_root = Path("plugins/cache/flashrsi/demo/local")
    plugin = source / relative_root
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin/plugin.json").write_text(
        json.dumps({"name": "demo", "description": "Snapshot plugin probe"})
    )
    skill = plugin / "skills/probe/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: probe\ndescription: BASELINE_PLUGIN_SKILL\n---\n"
        "Use the versioned plugin procedure.\n"
    )
    log = tmp_path / "plugin-hook-execution.json"
    hook = plugin / "hooks/context.py"
    hook.parent.mkdir()
    hook.write_text(
        "import json, os, pathlib, sys\n"
        "request = json.load(sys.stdin)\n"
        f"pathlib.Path({str(log)!r}).write_text(json.dumps({{\n"
        "    'home': os.environ['CODEX_HOME'],\n"
        "    'root': os.environ['PLUGIN_ROOT'],\n"
        "    'data': os.environ['PLUGIN_DATA'],\n"
        "    'cwd': os.getcwd(),\n"
        "    'event': request['hook_event_name'],\n"
        "}))\n"
        "print(json.dumps({'hookSpecificOutput': {\n"
        "    'hookEventName': 'SessionStart',\n"
        "    'additionalContext': 'BASELINE_PLUGIN_CONTEXT',\n"
        "}}))\n"
    )
    (plugin / "hooks/hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{shlex.quote(sys.executable)} "
                                    '"${PLUGIN_ROOT}/hooks/context.py"',
                                    "timeout": 5,
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    (source / "config.toml").write_text(
        "[features]\nplugins = true\nhooks = true\nremote_plugin = false\n"
        '[plugins."demo@flashrsi"]\nenabled = true\n'
    )

    config = _config(responses_server, upstream_codex, source_dir=source)
    if backend == "core":
        config.pop("cli_path")
    agent = Codex(config)
    agent.set_scope({"plugin": "rw"})
    baseline = agent.snapshot
    assert (
        baseline.files[(relative_root / "hooks/context.py").as_posix()].component
        == "plugin"
    )
    with baseline.check_out() as directory:
        for relative in ("hooks/context.py", "skills/probe/SKILL.md"):
            path = directory / relative_root / relative
            path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)

    (result,) = asyncio.run(
        agent.rollout([Task("plugin", "Answer directly.")], snapshot=candidate)
    )

    assert result.status == "finished", result.error_message
    request = json.dumps(responses_server.requests[-1]["body"])
    assert "CANDIDATE_PLUGIN_SKILL" in request
    assert "CANDIDATE_PLUGIN_CONTEXT" in request
    assert "BASELINE_PLUGIN_SKILL" not in request
    assert "BASELINE_PLUGIN_CONTEXT" not in request
    execution = json.loads(log.read_text())
    home = Path(execution["home"]).resolve()
    assert Path(execution["root"]).resolve() == home / relative_root
    assert Path(execution["data"]).resolve().is_relative_to(home / "plugins/data")
    assert not Path(execution["cwd"]).resolve().is_relative_to(home)
    assert execution["event"] == "SessionStart"
    assert not home.exists()
    assert agent.snapshot is baseline
    assert "BASELINE_PLUGIN_CONTEXT" in hook.read_text()
    assert result.messages[0]["snapshot_id"] == candidate.id
