"""Verify versioned extensions with the bundled CLI and local model replies."""

import asyncio
import json
import shlex
import sys

import pytest
from test_claude_code_native import _config, _copy_source, _message_events
from test_claude_code_native import anthropic_server as anthropic_server

from flashrsi.agents import ClaudeCode
from flashrsi.core import Task


def test_native_hook_and_settings_use_candidate_snapshot(anthropic_server, tmp_path):
    source = _copy_source(tmp_path)
    hook = source / "hooks/context.py"
    hook.write_text(
        "import json, os, sys\n"
        "request = json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {\n"
        "    'hookEventName': 'UserPromptSubmit',\n"
        "    'additionalContext': 'BASELINE_HOOK ' + "
        "os.environ['FLASHRSI_EXTENSION_SETTING'],\n"
        "}}))\n"
    )
    (source / "hooks/hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{shlex.quote(sys.executable)} "
                                    '"${CLAUDE_PLUGIN_ROOT}/hooks/context.py"',
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    (source / "settings.json").write_text(
        json.dumps({"env": {"FLASHRSI_EXTENSION_SETTING": "BASELINE_SETTING"}})
    )
    agent = ClaudeCode(_config(anthropic_server, source_dir=source, tools=[]))
    agent.set_scope({"hook": "rw", "config": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        for relative in ("hooks/context.py", "settings.json"):
            path = directory / relative
            path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)

    def reply(request):
        body = request["body"]
        content = json.dumps(body["messages"])
        if "CANDIDATE_HOOK CANDIDATE_SETTING" in content:
            text = "candidate extensions loaded"
        elif "BASELINE_HOOK BASELINE_SETTING" in content:
            text = "baseline extensions loaded"
        else:
            text = "extension context missing"
        return _message_events(body, text)

    anthropic_server.reply = reply
    (trial,) = asyncio.run(
        agent.rollout([Task("trial", "inspect")], snapshot=candidate)
    )
    assert trial.status == "finished", trial.error_message
    assert trial.output == "candidate extensions loaded"
    assert agent.snapshot is baseline
    current = asyncio.run(agent.run("inspect"))
    assert current.status == "finished", current.error_message
    assert current.output == "baseline extensions loaded"
    assert any(message["type"] == "HookEventMessage" for message in trial.messages)


def test_native_mcp_tool_uses_candidate_server_and_preserves_results(
    anthropic_server, tmp_path
):
    source = _copy_source(tmp_path)
    server = source / "servers/probe.py"
    server.parent.mkdir(exist_ok=True)
    server.write_text(
        """import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {
            'protocolVersion': request['params']['protocolVersion'],
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'flashrsi-test-probe', 'version': '1.0'},
        }
    elif method == 'tools/list':
        result = {'tools': [{
            'name': 'evidence', 'description': 'Read the versioned test evidence.',
            'inputSchema': {'type': 'object', 'properties': {}},
        }]}
    elif method == 'tools/call':
        result = {'content': [{'type': 'text', 'text': 'BASELINE_MCP_EVIDENCE'}]}
    elif method == 'ping':
        result = {}
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {
            'code': -32601, 'message': 'Method not found',
        }}), flush=True)
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}),
          flush=True)
"""
    )
    (source / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "probe": {
                        "command": sys.executable,
                        "args": ["${CLAUDE_PLUGIN_ROOT}/servers/probe.py"],
                    }
                }
            }
        )
    )
    agent = ClaudeCode(
        _config(
            anthropic_server,
            source_dir=source,
            tools=[],
            allowed_tools=["mcp__probe__*", "mcp__plugin_flashrsi_probe__*"],
        )
    )
    agent.set_scope({"tool": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        path = directory / "servers/probe.py"
        path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)

    def reply(request):
        body = request["body"]
        content = json.dumps(body["messages"])
        tool = None
        if "CANDIDATE_MCP_EVIDENCE" in content:
            text = "candidate tool loaded"
        elif "BASELINE_MCP_EVIDENCE" in content:
            text = "baseline tool loaded"
        else:
            names = [
                entry["name"]
                for entry in body.get("tools", [])
                if entry["name"].endswith("__evidence")
            ]
            assert len(names) == 1, names
            tool, text = (names[0], {}), ""
        return _message_events(
            body, text, tool=tool, message_id=f"msg_{len(anthropic_server.requests)}"
        )

    anthropic_server.reply = reply
    (trial,) = asyncio.run(
        agent.rollout([Task("trial", "inspect")], snapshot=candidate)
    )
    assert trial.status == "finished", trial.error_message
    assert trial.output == "candidate tool loaded"
    assert agent.snapshot is baseline
    current = asyncio.run(agent.run("inspect"))
    assert current.status == "finished", current.error_message
    assert current.output == "baseline tool loaded"
    trace = json.dumps([dict(message) for message in trial.messages])
    assert "ToolUseBlock" in trace and "ToolResultBlock" in trace
    assert "CANDIDATE_MCP_EVIDENCE" in trace


def test_native_command_and_forced_output_style_are_loaded_from_snapshot(
    anthropic_server, tmp_path
):
    source = _copy_source(tmp_path)
    command = source / "commands/probe.md"
    command.parent.mkdir(exist_ok=True)
    command.write_text(
        "---\ndescription: Inspect versioned command behavior.\n---\n"
        "BASELINE_COMMAND_CONTEXT\n"
    )
    style = source / "output-styles/probe.md"
    style.parent.mkdir(exist_ok=True)
    style.write_text(
        "---\nname: probe\ndescription: Inspect output style behavior.\n"
        "keep-coding-instructions: true\nforce-for-plugin: true\n---\nBASELINE_OUTPUT_STYLE_CONTEXT\n"
    )
    agent = ClaudeCode(_config(anthropic_server, source_dir=source, tools=["Skill"]))
    agent.set_scope({"prompt": "rw", "skill": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        for relative in ("commands/probe.md", "output-styles/probe.md"):
            path = directory / relative
            path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)

    def reply(request):
        body = request["body"]
        if "CANDIDATE_OUTPUT_STYLE_CONTEXT" not in json.dumps(body):
            return _message_events(body, "output style missing")
        content = json.dumps(body["messages"])
        if "CANDIDATE_COMMAND_CONTEXT" in content:
            text, tool = "candidate command and style loaded", None
        else:
            text, tool = "", ("Skill", {"skill": "flashrsi:probe"})
        return _message_events(
            body, text, tool=tool, message_id=f"msg_{len(anthropic_server.requests)}"
        )

    anthropic_server.reply = reply
    (trial,) = asyncio.run(
        agent.rollout([Task("trial", "inspect")], snapshot=candidate)
    )
    assert trial.status == "finished", trial.error_message
    assert trial.output == "candidate command and style loaded"
    assert agent.snapshot is baseline


@pytest.mark.parametrize(
    "relative",
    [".claude-plugin/plugin.json", "hooks/hooks.json", "settings.json"],
)
def test_malformed_native_extension_returns_error_trajectory(
    anthropic_server, tmp_path, relative
):
    source = _copy_source(tmp_path)
    agent = ClaudeCode(_config(anthropic_server, source_dir=source, tools=[]))
    agent.set_scope({"config": "rw", "hook": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        (directory / relative).write_text("{ invalid JSON")
        candidate = baseline.commit(directory)

    (trajectory,) = asyncio.run(
        agent.rollout(
            [Task("invalid-extension", "Inspect the configured extensions.")],
            snapshot=candidate,
        )
    )

    assert trajectory.status == "error", trajectory.output
    assert trajectory.output == ""
    assert trajectory.error_message
    run_input = next(
        message for message in trajectory.messages if message["type"] == "RunInput"
    )
    assert run_input["snapshot_id"] == candidate.id
    assert agent.snapshot is baseline
    if relative != "settings.json":
        assert any(
            message["type"] == "SystemMessage"
            and message["subtype"] == "init"
            and message["data"].get("plugin_errors")
            for message in trajectory.messages
        )
    assert (
        asyncio.run(agent.run("Inspect the baseline extensions.")).status == "finished"
    )


def test_failed_native_mcp_server_returns_error_trajectory(anthropic_server, tmp_path):
    source = _copy_source(tmp_path)
    (source / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "broken_probe": {
                        "command": sys.executable,
                        "args": ["-c", "raise SystemExit(2)"],
                    }
                }
            }
        )
    )
    agent = ClaudeCode(_config(anthropic_server, source_dir=source, tools=[]))

    trajectory = asyncio.run(agent.run("Inspect the configured extensions."))

    assert trajectory.status == "error", trajectory.output
    assert trajectory.output == ""
    assert "broken_probe" in trajectory.error_message
    assert any(
        message["type"] == "SystemMessage"
        and message["subtype"] == "init"
        and {"name": "broken_probe", "status": "failed"}
        in message["data"].get("mcp_servers", [])
        for message in trajectory.messages
    )


def test_deferred_native_tool_returns_error_and_preserves_pending_tool(
    anthropic_server, tmp_path
):
    source = _copy_source(tmp_path)
    (source / "hooks/defer.py").write_text(
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {\n"
        "    'hookEventName': 'PreToolUse',\n"
        "    'permissionDecision': 'defer',\n"
        "    'permissionDecisionReason': 'Waiting for external review',\n"
        "}}))\n"
    )
    (source / "hooks/hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Read",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{shlex.quote(sys.executable)} "
                                    '"${CLAUDE_PLUGIN_ROOT}/hooks/defer.py"',
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )
    probe = tmp_path / "pending.txt"
    probe.write_text("SHOULD_NOT_BE_READ")

    def reply(request):
        return _message_events(
            request["body"], tool=("Read", {"file_path": str(probe)})
        )

    anthropic_server.reply = reply
    agent = ClaudeCode(
        _config(
            anthropic_server,
            source_dir=source,
            tools=["Read"],
            allowed_tools=["Read"],
        )
    )

    trajectory = asyncio.run(agent.run("Read the pending file.", working_dir=tmp_path))

    assert trajectory.status == "error", trajectory.output
    assert trajectory.output == ""
    assert "defer" in trajectory.error_message.lower()
    results = [
        message for message in trajectory.messages if message["type"] == "ResultMessage"
    ]
    assert results[-1]["terminal_reason"] == "tool_deferred"
    assert results[-1]["deferred_tool_use"]["name"] == "Read"
    assert results[-1]["deferred_tool_use"]["input"]["file_path"] == str(probe)
    assert len(anthropic_server.requests) == 1


@pytest.mark.parametrize(
    "name",
    [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
    ],
)
def test_snapshot_settings_cannot_replace_runtime_connection_or_state(
    anthropic_server, tmp_path, name
):
    source = _copy_source(tmp_path)
    (source / "settings.json").write_text(
        json.dumps({"env": {name: "snapshot-runtime-override"}})
    )
    agent = ClaudeCode(_config(anthropic_server, source_dir=source, tools=[]))

    trajectory = asyncio.run(agent.run("Answer directly"))

    assert trajectory.status == "error"
    assert "settings.json.env" in trajectory.error_message
    assert name in trajectory.error_message
    assert "snapshot-runtime-override" not in trajectory.error_message
    assert not anthropic_server.requests


def test_malformed_mcp_retains_cli_parse_diagnostic(anthropic_server, tmp_path):
    source = _copy_source(tmp_path)
    (source / ".mcp.json").write_text("{ invalid JSON")
    trajectory = asyncio.run(
        ClaudeCode(_config(anthropic_server, source_dir=source, tools=[])).run("Answer")
    )

    assert trajectory.status == "error"
    assert "stderr" in trajectory.error_message
    assert "JSON" in trajectory.error_message
    assert not anthropic_server.requests
