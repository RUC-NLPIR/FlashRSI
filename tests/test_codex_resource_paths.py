"""Keep version-owned paths portable without guessing the meaning of argv words."""

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest
from test_codex import _agent, _requests
from test_codex import native_cli as native_cli
from test_codex import source as source
from test_codex_native import _config, _source
from test_codex_native import codex_binary as codex_binary
from test_codex_native import responses_server as responses_server

from flashrsi.agents import Codex
from flashrsi.core import Task


@pytest.mark.parametrize(
    "args",
    [
        ["-m", "servers"],
        ["--name", "servers"],
        ["-m", "servers.probe"],
        ["--name", "probe.py"],
    ],
)
def test_mcp_bare_words_are_not_resource_paths(source, native_cli, args):
    (source / "servers").mkdir()
    (source / "servers/probe.py").write_text("# Resource with a colliding name.\n")
    (source / "components.yaml").write_text(
        (source / "components.yaml").read_text() + "extra: [probe.py]\n"
    )
    (source / "probe.py").write_text(
        "# Root resource; use ./probe.py to refer to it.\n"
    )
    (source / "config.toml").write_text(
        '[mcp_servers.probe]\ncommand = "python3"\nargs = ' + json.dumps(args) + "\n"
    )

    result = asyncio.run(_agent(source, native_cli).run("question"))

    assert result.status == "finished", result.error_message
    assert _requests(native_cli)[0]["overrides"]["mcp_servers"]["probe"]["args"] == args


def test_mcp_explicit_paths_relocate_but_external_dependencies_do_not(
    source, native_cli, tmp_path
):
    (source / "servers").mkdir()
    script = source / "servers/probe.py"
    script.write_text("# MCP resource\n")
    external = tmp_path / "external.py"
    external.write_text("# External dependency\n")
    (source / "config.toml").write_text(
        "[mcp_servers.probe]\n"
        'command = "./servers/probe.py"\n'
        "args = " + json.dumps([str(script), "./servers", str(external)]) + "\n"
    )
    result = asyncio.run(_agent(source, native_cli).run("question"))

    assert result.status == "finished", result.error_message
    request = _requests(native_cli)[0]
    home = Path(request["home"])
    server = request["overrides"]["mcp_servers"]["probe"]
    assert server["command"] == str(home / "servers/probe.py")
    assert server["args"] == [
        str(home / "servers/probe.py"),
        str(home / "servers"),
        str(external),
    ]


def test_skill_disable_paths_follow_the_selected_home(source, native_cli, tmp_path):
    external = tmp_path / "external/SKILL.md"
    original = (
        "[[skills.config]]\npath = "
        + json.dumps(str(source / "skills/probe/SKILL.md"))
        + "\nenabled = false\n[[skills.config]]\npath = "
        + json.dumps(str(external))
        + "\nenabled = false\n"
    )
    (source / "config.toml").write_text(original)

    result = asyncio.run(_agent(source, native_cli).run("question"))

    assert result.status == "finished", result.error_message
    request = _requests(native_cli)[0]
    settings = request["overrides"]["skills"]["config"]
    assert settings[:2] == [
        {
            "path": str(Path(request["home"]) / "skills/probe/SKILL.md"),
            "enabled": False,
        },
        {"path": str(external), "enabled": False},
    ]
    assert request["resources"]["config.toml"] == original


def test_native_absolute_skill_setting_survives_copy_and_candidate_evaluation(
    responses_server, codex_binary, tmp_path
):
    source = _source(tmp_path)
    skill = source / "skills/probe/SKILL.md"
    skill.parent.mkdir(parents=True)
    marker = "ABSOLUTE_SKILL_DISABLE_REGRESSION"
    skill.write_text(f"---\nname: probe\ndescription: {marker}\n---\nProcedure.\n")
    native = (source / "config.toml").read_text()
    (source / "config.toml").write_text(
        native
        + f"[[skills.config]]\npath = {json.dumps(str(skill))}\nenabled = false\n"
    )
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))
    agent.set_scope({"config": "rw"})
    baseline = agent.snapshot

    result = asyncio.run(agent.run("Answer directly."))
    assert result.status == "finished", result.error_message
    assert marker not in json.dumps(responses_server.requests[-1]["body"])

    with baseline.check_out() as directory:
        path = directory / "config.toml"
        path.write_text(path.read_text().replace("enabled = false", "enabled = true"))
        candidate = baseline.commit(directory)
    (result,) = asyncio.run(
        agent.rollout([Task("probe", "Answer directly.")], snapshot=candidate)
    )
    assert result.status == "finished", result.error_message
    assert marker in json.dumps(responses_server.requests[-1]["body"])
    assert agent.snapshot is baseline
    assert baseline.files["config.toml"].content.endswith(b"enabled = false\n")


@pytest.mark.parametrize("invocation", ["module", "literal-option"])
def test_native_mcp_operands_keep_their_meaning(
    responses_server, codex_binary, tmp_path, invocation
):
    source = _source(tmp_path)
    (source / "servers").mkdir()
    (source / "servers/snapshot-resource.py").write_text(
        "# Unrelated versioned tool.\n"
    )
    task = tmp_path / "task"
    package = task / "servers"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    marker = task / "mcp-started.json"
    (package / "__main__.py").write_text(
        textwrap.dedent(
            """\
            import json, pathlib, sys
            assert sys.argv[1:] in ([], ['--name', 'servers']), sys.argv
            pathlib.Path('mcp-started.json').write_text(json.dumps(sys.argv))
            for line in sys.stdin:
                request = json.loads(line)
                if 'id' not in request:
                    continue
                if request['method'] == 'initialize':
                    result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                              'serverInfo': {'name': 'operand-probe', 'version': '1'}}
                elif request['method'] == 'tools/list':
                    result = {'tools': []}
                else:
                    result = {}
                print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
            """
        )
    )
    args = ["-m", "servers"]
    if invocation == "literal-option":
        args = [str(package / "__main__.py"), "--name", "servers"]
    with (source / "config.toml").open("a") as config:
        config.write(
            "[mcp_servers.probe]\n"
            f"command = {json.dumps(sys.executable)}\n"
            f"args = {json.dumps(args)}\n"
            "required = true\nstartup_timeout_sec = 5\n"
        )

    agent = Codex(_config(responses_server, codex_binary, source_dir=source))
    result = asyncio.run(agent.run("Answer directly.", working_dir=task))

    assert result.status == "finished", result.error_message
    assert marker.is_file()
    expected = args[2:] if invocation == "module" else args[1:]
    assert json.loads(marker.read_text())[1:] == expected
