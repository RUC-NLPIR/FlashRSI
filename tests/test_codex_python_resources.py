"""Python Codex resource behavior against real local processes and pinned data."""

import asyncio
import inspect
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

import pytest
from codex_test_support import responses_server as responses_server

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core import resources as module
from flashrsi.agents.codex.python_core.hooks import HookBlocked, HookStopped
from flashrsi.agents.codex.python_core.resources import Resources


class Router:
    def __init__(self):
        self.tools = {}
        self.metadata = {}

    def register(self, name, spec, handler, **metadata):
        self.tools[name] = (spec, handler)
        self.metadata[name] = metadata


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "snapshot"
    shutil.copytree(
        Path(inspect.getfile(module)).parent / "resource_assets",
        home / "python_core/resource_assets",
    )
    shutil.copy2(
        Path(inspect.getfile(Codex)).parent / "components.yaml",
        home / "components.yaml",
    )
    (home / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\n"
    )
    return home


def _resource(home, tmp_path, settings=None, environment=None):
    cwd = tmp_path / "task"
    cwd.mkdir(exist_ok=True)
    events = []
    settings = {
        "model": "gpt-5",
        "approval_policy": "never",
        "sandbox_mode": "danger-full-access",
        "project_doc_max_bytes": 0,
        "features": {"plugins": False},
        **(settings or {}),
    }
    environment = {
        **os.environ,
        "HOME": str(tmp_path / "isolated-home"),
        **(environment or {}),
    }
    return Resources(home, cwd, settings, events.append, environment), Router(), events


def _text(items):
    return "\n".join(
        content["text"]
        for item in items
        for content in item.get("content", [])
        if content.get("type") == "input_text"
    )


def _skill(
    home,
    name="probe",
    description="SELECTED_SKILL",
    body="Skill procedure",
    metadata=None,
):
    path = home / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}\n")
    if metadata:
        (path.parent / "agents").mkdir()
        (path.parent / "agents/openai.yaml").write_text(metadata)
    return path


def test_bundled_assets_and_selected_skill_contents(home, tmp_path):
    selected = _skill(home)
    _skill(
        home,
        "explicit",
        "HIDDEN_EXPLICIT",
        metadata="policy:\n  allow_implicit_invocation: false\n",
    )
    resources, router, _ = _resource(home, tmp_path)

    async def run():
        initial = await resources.start(router)
        catalog = _text(initial)
        assert all(
            f"- {name}:" in catalog
            for name in (
                "imagegen",
                "openai-docs",
                "plugin-creator",
                "skill-creator",
                "skill-installer",
                "probe",
            )
        )
        assert "HIDDEN_EXPLICIT" not in catalog
        assert "### How to use skills" not in catalog
        prompt, injected = await resources.before_prompt("Use $probe and $explicit.")
        assert prompt == "Use $probe and $explicit."
        assert (
            f"<path>{selected.resolve()}</path>\n{selected.read_text()}\n</skill>"
            in _text(injected)
        )
        assert "HIDDEN_EXPLICIT" in _text(injected)
        await resources.close()

    asyncio.run(run())


def test_snapshot_bundled_asset_mutation_is_observed(home, tmp_path):
    asset = home / "python_core/resource_assets/system_skills/imagegen/SKILL.md"
    asset.write_text(
        asset.read_text().replace(
            "Generate or edit raster images", "CANDIDATE_SYSTEM_DESCRIPTION"
        )
    )
    resources, router, _ = _resource(home, tmp_path)

    async def run():
        assert "CANDIDATE_SYSTEM_DESCRIPTION" in _text(await resources.start(router))
        assert "CANDIDATE_SYSTEM_DESCRIPTION" in _text(
            (await resources.before_prompt("Use $imagegen"))[1]
        )
        await resources.close()

    asyncio.run(run())


def test_agents_hierarchy_override_fallback_and_byte_limit(home, tmp_path):
    (home / "AGENTS.md").write_text("GLOBAL\n")
    root = tmp_path / "repo"
    cwd = root / "nested/deep"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("ROOT\n")
    (root / "nested/AGENTS.md").write_text("WRONG")
    (root / "nested/AGENTS.override.md").write_text("OVERRIDE\n")
    (cwd / "GUIDE.md").write_text("FALLBACK\n")
    resources, _, _ = _resource(
        home,
        tmp_path,
        {"project_doc_max_bytes": 16, "project_doc_fallback_filenames": ["GUIDE.md"]},
    )
    resources.cwd = cwd
    text = _text([resources._agents()])
    assert (
        text
        == f"# AGENTS.md instructions for {cwd}\n\n<INSTRUCTIONS>\nGLOBAL\n\n--- project-doc ---\n\nROOT\n\n\nOVERRIDE\n\n\nFA\n</INSTRUCTIONS>"
    )


def test_disabled_skill_and_ambiguous_plain_name_are_not_injected(home, tmp_path):
    skill = _skill(home)
    other = home / "skills/second/SKILL.md"
    other.parent.mkdir()
    other.write_text(skill.read_text())
    resources, router, _ = _resource(home, tmp_path)

    async def run():
        await resources.start(router)
        assert not (await resources.before_prompt("$probe"))[1]
        assert "<skill>" in _text(
            (await resources.before_prompt(f"[$probe]({skill})"))[1]
        )
        await resources.close()

    asyncio.run(run())


def _hook_command(home, script):
    path = home / "hooks/probe.py"
    path.parent.mkdir(exist_ok=True)
    path.write_text(script)
    return f'{shlex.quote(sys.executable)} "$CODEX_HOME/hooks/probe.py"'


def test_hooks_execute_snapshot_context_in_order_and_notify(home, tmp_path):
    log = tmp_path / "hooks.jsonl"
    command = _hook_command(
        home,
        "import json,os,pathlib,sys,time\npayload=json.load(sys.stdin)\n"
        + f"with pathlib.Path({str(log)!r}).open('a') as file: file.write(json.dumps({{'payload':payload,'home':os.environ['CODEX_HOME'],'cwd':os.getcwd()}})+'\\n')\n"
        + "print(json.dumps({'hookSpecificOutput':{'hookEventName':payload['hook_event_name'],'additionalContext':'CONTEXT_'+payload['hook_event_name']}}))\n",
    )
    notify = tmp_path / "notify.json"
    settings = {
        "features": {"hooks": True, "plugins": False},
        "hooks": {
            event: [{"hooks": [{"type": "command", "command": command}]}]
            for event in ("SessionStart", "UserPromptSubmit")
        },
        "notify": [
            sys.executable,
            "-c",
            f"import pathlib,sys;pathlib.Path({str(notify)!r}).write_text(sys.argv[-1])",
        ],
        "_session_id": "session",
        "_thread_id": "thread",
        "_turn_id": "turn",
    }
    resources, router, _ = _resource(home, tmp_path, settings)

    async def run():
        assert _text(await resources.start(router)).endswith("CONTEXT_SessionStart")
        assert (
            _text((await resources.before_prompt("Original prompt"))[1])
            == "CONTEXT_UserPromptSubmit"
        )
        assert await resources.after_turn("Completed", "finished") == []
        await resources.close()

    asyncio.run(run())
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [call["payload"]["hook_event_name"] for call in calls] == [
        "SessionStart",
        "UserPromptSubmit",
    ]
    assert calls[0]["payload"] == {
        "session_id": "session",
        "transcript_path": None,
        "cwd": str(tmp_path / "task"),
        "hook_event_name": "SessionStart",
        "model": "gpt-5",
        "permission_mode": "bypassPermissions",
        "source": "startup",
    }
    assert calls[1]["payload"]["prompt"] == "Original prompt"
    assert all(call["home"] == str(home) for call in calls)
    assert json.loads(notify.read_text()) == {
        "type": "agent-turn-complete",
        "thread-id": "thread",
        "turn-id": "turn",
        "cwd": str(tmp_path / "task"),
        "client": "codex_exec",
        "input-messages": ["Original prompt"],
        "last-assistant-message": "Completed",
    }


@pytest.mark.parametrize(
    "output,expected",
    [
        ('print(\'{"continue":false,"stopReason":"HALT"}\')', "HALT"),
        ("import sys;print('BLOCKED',file=sys.stderr);sys.exit(2)", "BLOCKED"),
    ],
)
def test_prompt_hook_blocks_before_model(home, tmp_path, output, expected):
    command = _hook_command(home, output)
    resources, router, _ = _resource(
        home,
        tmp_path,
        {
            "features": {"hooks": True, "plugins": False},
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": command}]}
                ]
            },
        },
    )

    async def run():
        await resources.start(router)
        with pytest.raises((HookBlocked, HookStopped), match=expected):
            await resources.before_prompt("Prompt")
        await resources.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "read_only,approve,expected",
    [(True, False, True), (False, False, False), (False, True, True)],
)
def test_mcp_real_stdio_discovery_call_approval_and_elicitation(
    home, tmp_path, read_only, approve, expected
):
    log = tmp_path / "mcp.jsonl"
    script = home / "servers/probe.py"
    script.parent.mkdir()
    script.write_text(
        "import json,pathlib,sys,os\npending=None\ndef send(value): print(json.dumps(value),flush=True)\nfor line in sys.stdin:\n request=json.loads(line)\n"
        + f" with pathlib.Path({str(log)!r}).open('a') as file: file.write(json.dumps(request)+'\\n')\n"
        + " if 'method' not in request:\n  send({'jsonrpc':'2.0','id':pending,'result':{'content':[{'type':'text','text':'ELICITATION:'+request['result']['action']}],'isError':False}})\n  continue\n if 'id' not in request: continue\n method=request['method']\n if method=='initialize': result={'protocolVersion':'2025-06-18','serverInfo':{'name':'probe','version':'1'},'capabilities':{'tools':{}}}\n elif method=='tools/list':\n"
        + f"  result={{'tools':[{{'name':'echo','description':'Echo','inputSchema':{{'type':'object','properties':{{'value':{{'type':'string'}}}},'required':['value']}},'annotations':{{'readOnlyHint':{read_only!r}}}}}]}}\n"
        + " elif method=='tools/call':\n  pending=request['id']\n  send({'jsonrpc':'2.0','id':'ask','method':'elicitation/create','params':{'message':'Optional evidence','requestedSchema':{'type':'object','properties':{}}}})\n  continue\n else: result={}\n send({'jsonrpc':'2.0','id':request['id'],'result':result})\n"
    )
    config = {
        "command": sys.executable,
        "args": ["servers/probe.py"],
        "env_vars": ["CODEX_HOME"],
    }
    if approve:
        config["default_tools_approval_mode"] = "approve"
    resources, router, _ = _resource(
        home,
        tmp_path,
        {"sandbox_mode": "workspace-write", "mcp_servers": {"probe": config}},
    )

    async def run():
        await resources.start(router)
        spec, call = router.tools["mcp__probe__echo"]
        assert spec == {
            "type": "namespace",
            "name": "mcp__probe",
            "description": "Tools in the mcp__probe namespace.",
            "tools": [
                {
                    "type": "function",
                    "name": "echo",
                    "description": "Echo",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                    "strict": False,
                }
            ],
        }
        result = await call({"value": "selected"})
        assert router.metadata["mcp__probe__echo"] == {
            "parallel": read_only,
            "deferred": True,
            "search_text": "mcp__probeecho echo echo probe Echo value",
            "source_info": {"name": "probe", "description": None},
        }
        assert result["success"] is expected
        if expected:
            assert '"text":"ELICITATION:decline"' in result["output"]
        else:
            assert result["output"] == "user rejected MCP tool call"
        await resources.close()

    asyncio.run(run())
    requests = [json.loads(line) for line in log.read_text().splitlines()]
    assert requests[0]["method"] == "initialize"
    assert requests[1]["method"] == "notifications/initialized"
    assert (
        any(request.get("method") == "tools/call" for request in requests) is expected
    )


def test_plugin_candidate_skill_and_hook_are_loaded(home, tmp_path):
    root = home / "plugins/cache/demo/plugin/local"
    (root / ".codex-plugin").mkdir(parents=True)
    (root / ".codex-plugin/plugin.json").write_text('{"name":"example"}')
    skill = root / "skills/probe/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: probe\ndescription: PLUGIN_SKILL_CANDIDATE\n---\nPlugin procedure\n"
    )
    (root / "hooks").mkdir()
    (root / "hooks/hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{shlex.quote(sys.executable)} -c 'import os;print(os.environ[\"PLUGIN_ROOT\"])'",
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    resources, router, _ = _resource(
        home,
        tmp_path,
        {
            "features": {"hooks": True, "plugins": True},
            "plugins": {"plugin@demo": {"enabled": True}},
        },
    )

    async def run():
        initial = await resources.start(router)
        assert "- example:probe: PLUGIN_SKILL_CANDIDATE" in _text(initial)
        assert _text(initial).endswith(str(root))
        assert "Plugin procedure" in _text(
            (await resources.before_prompt("$example:probe"))[1]
        )
        await resources.close()

    asyncio.run(run())


def test_mcp_resource_pagination_read_and_partial_server_failure(home, tmp_path):
    script = home / "resource_server.py"
    script.write_text(
        """import json,sys
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request: continue
    method=request['method']
    params=request.get('params') or {}
    if method=='initialize':
        result={'protocolVersion':'2025-06-18','serverInfo':{'name':'resources','version':'1'},'capabilities':{}}
    elif len(sys.argv)>1:
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'not supported'}}),flush=True)
        continue
    elif method=='resources/list':
        if params.get('cursor')=='second': result={'resources':[{'uri':'probe://second','name':'Second'}]}
        else: result={'resources':[{'uri':'probe://first','name':'First'}],'nextCursor':'second'}
    elif method=='resources/templates/list':
        result={'resourceTemplates':[{'uriTemplate':'probe://{name}','name':'Probe'}]}
    elif method=='resources/read':
        result={'contents':[{'uri':params['uri'],'mimeType':'text/plain','text':'SELECTED_RESOURCE'}]}
    else: result={}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
"""
    )
    resources, router, events = _resource(
        home,
        tmp_path,
        {
            "mcp_servers": {
                "probe": {"command": sys.executable, "args": [str(script)]},
                "broken": {"command": sys.executable, "args": [str(script), "fail"]},
            }
        },
    )

    async def run():
        await resources.start(router)
        _, listing = router.tools["list_mcp_resources"]
        result = json.loads((await listing({}))["output"])
        assert result == {
            "resources": [
                {"server": "probe", "uri": "probe://first", "name": "First"},
                {"server": "probe", "uri": "probe://second", "name": "Second"},
            ]
        }
        result = json.loads((await listing({"server": " probe "}))["output"])
        assert result["server"] == "probe" and result["nextCursor"] == "second"
        result = json.loads(
            (await listing({"server": "probe", "cursor": " second "}))["output"]
        )
        assert result["resources"][0]["uri"] == "probe://second"
        with pytest.raises(ValueError, match="cursor can only"):
            await listing({"cursor": "second"})
        _, templates = router.tools["list_mcp_resource_templates"]
        assert json.loads((await templates({}))["output"]) == {
            "resourceTemplates": [
                {"server": "probe", "uriTemplate": "probe://{name}", "name": "Probe"}
            ]
        }
        _, read = router.tools["read_mcp_resource"]
        result = json.loads(
            (await read({"server": "probe", "uri": "probe://first"}))["output"]
        )
        assert result == {
            "server": "probe",
            "uri": "probe://first",
            "contents": [
                {
                    "uri": "probe://first",
                    "mimeType": "text/plain",
                    "text": "SELECTED_RESOURCE",
                }
            ],
        }
        await resources.close()

    asyncio.run(run())
    assert (
        sum("MCP server 'broken'" in event.get("message", "") for event in events) == 2
    )


@pytest.mark.parametrize("behavior", ["allow", "deny"])
def test_permission_request_hook_controls_mcp_call(home, tmp_path, behavior):
    script = home / "permission_server.py"
    script.write_text(
        """import json,sys
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request: continue
    if request['method']=='initialize': result={'protocolVersion':'2025-06-18','serverInfo':{'name':'probe','version':'1'},'capabilities':{'tools':{}}}
    elif request['method']=='tools/list': result={'tools':[{'name':'write','inputSchema':{'type':'object','properties':{}}}]}
    elif request['method']=='tools/call': result={'content':[{'type':'text','text':'CALLED'}]}
    else: result={}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
"""
    )
    command = _hook_command(
        home,
        "import json,sys\npayload=json.load(sys.stdin)\n"
        "assert payload['tool_name']=='mcp__probe__write'\n"
        "assert payload['tool_input']=={'selected':True}\n"
        f"print(json.dumps({{'hookSpecificOutput':{{'hookEventName':'PermissionRequest','decision':{{'behavior':{behavior!r},'message':'DENIED_BY_HOOK'}}}}}}))\n",
    )
    resources, router, _ = _resource(
        home,
        tmp_path,
        {
            "sandbox_mode": "workspace-write",
            "features": {"hooks": True, "plugins": False},
            "hooks": {
                "PermissionRequest": [
                    {
                        "matcher": "mcp__probe__write",
                        "hooks": [{"type": "command", "command": command}],
                    }
                ]
            },
            "mcp_servers": {
                "probe": {"command": sys.executable, "args": [str(script)]}
            },
        },
    )

    async def run():
        await resources.start(router)
        _, call = router.tools["mcp__probe__write"]
        result = await call({"selected": True})
        assert result["success"] is (behavior == "allow")
        assert ("CALLED" if behavior == "allow" else "DENIED_BY_HOOK") in result[
            "output"
        ]
        await resources.close()

    asyncio.run(run())


def test_hook_and_notify_spawn_failure_warn_and_continue(home, tmp_path):
    resources, router, events = _resource(
        home,
        tmp_path,
        {
            "features": {"hooks": True, "plugins": False},
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": "echo context"}]}
                ]
            },
            "notify": [str(home / "missing-notify")],
        },
        {"SHELL": str(home / "missing-shell")},
    )

    async def run():
        await resources.start(router)
        assert await resources.after_turn("Completed", "finished") == []
        await resources.close()

    asyncio.run(run())
    warnings = [
        event.get("message", "") for event in events if event["type"] == "warning"
    ]
    assert any("failed to start SessionStart hook" in text for text in warnings)
    assert any("failed to start notify" in text for text in warnings)


def test_pretool_unsupported_continue_is_ignored_and_posttool_replaces_feedback(
    home, tmp_path
):
    command = _hook_command(home, 'print(\'{"continue":false,"stopReason":"HALT"}\')')
    resources, _, events = _resource(
        home,
        tmp_path,
        {
            "hooks": {
                event: [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": command}],
                    }
                ]
                for event in ("PreToolUse", "PostToolUse")
            }
        },
    )

    async def run():
        arguments = {"command": "echo selected"}
        rewritten, _ = await resources.hooks.before_tool("Bash", arguments, "call")
        assert rewritten == arguments
        output, _ = await resources.hooks.after_tool(
            "Bash", arguments, "output", "call"
        )
        assert output == "HALT"
        await resources.close()

    asyncio.run(run())
    assert any(
        "unsupported continue:false" in event.get("message", "") for event in events
    )


def test_stop_continue_false_preserves_answer_and_skips_notify(home, tmp_path):
    command = _hook_command(home, 'print(\'{"continue":false,"stopReason":"Enough"}\')')
    resources, router, events = _resource(
        home,
        tmp_path,
        {
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": command}]}]},
            "notify": [str(home / "missing-notify")],
        },
    )

    async def run():
        await resources.start(router)
        assert await resources.after_turn("Completed answer", "finished") == []
        await resources.close()

    asyncio.run(run())
    assert not any(
        "failed to start notify" in event.get("message", "") for event in events
    )


def test_unsupported_configured_resources_fail_explicitly(home, tmp_path):
    with pytest.raises(ValueError, match="not installed"):
        _resource(
            home,
            tmp_path,
            {
                "features": {"plugins": True},
                "plugins": {"missing@test": {"enabled": True}},
            },
        )
    _resource(
        home,
        tmp_path,
        {"features": {"hooks": True}, "hooks": {"SubagentStart": [{"hooks": []}]}},
    )


def test_stop_hook_returns_native_xml_continuation_and_tracks_active(home, tmp_path):
    command = _hook_command(
        home,
        "import json,sys\npayload=json.load(sys.stdin)\nprint(json.dumps({} if payload['stop_hook_active'] else {'decision':'block','reason':'Do the next <step> & report.'}))\n",
    )
    resources, router, _ = _resource(
        home,
        tmp_path,
        {
            "features": {"hooks": True, "plugins": False},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": command}]}]},
        },
    )

    async def run():
        await resources.start(router)
        continuation = await resources.after_turn("First output", "finished")
        assert continuation == [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f'<hook_prompt hook_run_id="stop:0:{home}/config.toml">Do the next &lt;step&gt; &amp; report.</hook_prompt>',
                    }
                ],
            }
        ]
        assert await resources.after_turn("Second output", "finished") == []
        await resources.close()

    asyncio.run(run())


def test_invalid_hook_json_warns_and_does_not_inject(home, tmp_path):
    command = _hook_command(
        home,
        'print(\'{"unexpected":true,"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"MUST_NOT_APPEAR"}}\')',
    )
    resources, router, events = _resource(
        home,
        tmp_path,
        {
            "features": {"hooks": True, "plugins": False},
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": command}]}
                ]
            },
        },
    )

    async def run():
        await resources.start(router)
        assert (await resources.before_prompt("Prompt"))[1] == []
        await resources.close()

    asyncio.run(run())
    assert any(
        event.get("type") == "warning"
        and "invalid UserPromptSubmit JSON output" in event["message"]
        for event in events
    )


def test_json_hook_context_preserves_whitespace_and_spills_full_output(home, tmp_path):
    text = "  Context with whitespace\n"
    command = _hook_command(
        home,
        f"print({json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': text}})!r})",
    )
    resources, router, _ = _resource(
        home,
        tmp_path,
        {
            "features": {"hooks": True, "plugins": False},
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": command,
                                "additionalContextLimit": 0,
                            }
                        ]
                    }
                ]
            },
        },
    )

    async def run():
        await resources.start(router)
        assert _text((await resources.before_prompt("Prompt"))[1]) == text
        long = "HEAD" + "x" * 12000 + "TAIL"
        spilled = resources.hooks._spill(long, 100)
        path = Path(spilled.split("Full hook output saved to: ", 1)[1])
        assert path.read_text() == long
        assert "tokens truncated" in spilled
        path.unlink()
        await resources.close()

    asyncio.run(run())


def test_skill_usage_flag_and_utf8_body_limit(home, tmp_path):
    path = _skill(home, body="界" * 4000)
    resources, router, events = _resource(
        home,
        tmp_path,
        {
            "_model_info": {
                "include_skills_usage_instructions": True,
                "context_window": 272000,
            }
        },
    )

    async def run():
        assert "### How to use skills" in _text(await resources.start(router))
        text = _text((await resources.before_prompt("$probe"))[1])
        body = text.split(f"<path>{path}</path>\n", 1)[1].removesuffix("\n</skill>")
        assert len(body.encode()) <= 8000
        assert path.read_text().startswith(body)
        await resources.close()

    asyncio.run(run())
    assert any("truncated" in event.get("message", "") for event in events)
