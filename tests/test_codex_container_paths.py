"""Exercise native resource relocation through the serialized container entry."""

import asyncio
import inspect
import json
import shutil
import textwrap
from pathlib import Path

import pytest
import yaml
from test_codex_native import _source
from test_codex_native import responses_server as responses_server

from flashrsi.agents import Codex
from flashrsi.integrations import _container


@pytest.mark.parametrize("source_kind", ["relative", "default"])
def test_stage_records_resolved_host_source_without_changing_role_config(
    tmp_path, monkeypatch, source_kind
):
    pytest.importorskip("codex_cli_bin")
    harbor = pytest.importorskip("flashrsi.integrations.harbor")
    monkeypatch.chdir(tmp_path)
    config = {"llm": {"model_name": "gpt-5", "api_key": "test"}}
    if source_kind == "relative":
        source = _source(tmp_path)
        config["source_dir"] = "source"
    else:
        source = Path(inspect.getfile(Codex)).parent
    agent = Codex(config)
    directory = tmp_path / "staged"
    directory.mkdir()

    harbor._stage(directory, agent, agent.config, "Answer directly.")

    request = json.loads((directory / "request.json").read_text())
    staged_config = yaml.safe_load(request["config_yaml"])
    assert staged_config["source_dir"] == str(source.resolve())
    assert dict(agent.config) == config


@pytest.mark.parametrize("skill_enabled", [False, True])
def test_container_candidate_relocates_absolute_skill_and_mcp_paths(
    responses_server, tmp_path, monkeypatch, skill_enabled
):
    pytest.importorskip("codex_cli_bin")
    source = _source(tmp_path)
    skill = source / "skills/probe/SKILL.md"
    skill.parent.mkdir(parents=True)
    marker = "CONTAINER_SKILL_PATH_REGRESSION"
    skill.write_text(f"---\nname: probe\ndescription: {marker}\n---\nProcedure.\n")
    script = source / "servers/probe.py"
    script.parent.mkdir()
    script.write_text(
        textwrap.dedent(
            """\
            import json, pathlib, sys
            resource = pathlib.Path(__file__).with_name('resource.txt').read_text()
            pathlib.Path('mcp-started.txt').write_text(resource)
            for line in sys.stdin:
                request = json.loads(line)
                if 'id' not in request:
                    continue
                if request['method'] == 'initialize':
                    result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                              'serverInfo': {'name': 'container-path-probe', 'version': '1'}}
                elif request['method'] == 'tools/list':
                    result = {'tools': []}
                else:
                    result = {}
                print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
            """
        )
    )
    (source / "servers/resource.txt").write_text("BASELINE_MCP_RESOURCE")
    with (source / "config.toml").open("a") as native:
        native.write(
            f"[[skills.config]]\npath = {json.dumps(str(skill))}\nenabled = false\n"
            "[mcp_servers.probe]\ncommand = 'python3'\n"
            f"args = [{json.dumps(str(script))}]\n"
            "required = true\nstartup_timeout_sec = 5\n"
        )
    config = {
        "source_dir": str(source),
        "llm": {
            "model_name": "gpt-5",
            "api_key": "local-codex-test-key",
            "base_url": responses_server.base_url,
        },
        "timeout": 30,
    }
    baseline = Codex(config).snapshot
    with baseline.check_out() as directory:
        (directory / "servers/resource.txt").write_text("CANDIDATE_MCP_RESOURCE")
        if skill_enabled:
            path = directory / "config.toml"
            path.write_text(
                path.read_text().replace("enabled = false", "enabled = true")
            )
        candidate = baseline.commit(directory)
    snapshot_path = tmp_path / "snapshot.json"
    candidate.save(snapshot_path)
    request_path, output_path = tmp_path / "request.json", tmp_path / "output.json"
    request_path.write_text(
        json.dumps(
            {
                "agent_class": "flashrsi.agents.codex:Codex",
                "config_yaml": yaml.safe_dump(config),
                "snapshot_path": str(snapshot_path),
                "prompt": "Answer directly.",
            }
        )
    )
    # A container receives serialized resources, not the original host tree.
    shutil.rmtree(source)
    task = tmp_path / "task"
    task.mkdir()
    monkeypatch.chdir(task)

    assert asyncio.run(_container._run(request_path, output_path)) == 0

    result = json.loads(output_path.read_text())
    assert result["status"] == "finished", result["error_message"]
    assert result["output"] == "Paris"
    assert (task / "mcp-started.txt").read_text() == "CANDIDATE_MCP_RESOURCE"
    assert (
        marker in json.dumps(responses_server.requests[-1]["body"])
    ) == skill_enabled
    run_config = result["messages"][0]
    assert run_config["snapshot_id"] == candidate.id
    assert "source_dir" not in run_config["config"]
    assert "_container_source_dir" not in run_config["config"]
    assert not request_path.exists()
