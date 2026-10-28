"""Execute native extensions and tool cleanup through the default core bridge.

Assertions use actual hook effects, MCP results sent back to the model and OS
process state, independently of the CLI's presentation-specific event shapes.
"""

import asyncio
import json
import os
import shlex
import signal
import struct
import sys
import textwrap
from contextlib import suppress
from pathlib import Path

import pytest
from test_codex_core_parity import _normalize
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_native import _config, _events, _shell_call, _source
from test_codex_native import responses_server as responses_server

from flashrsi.agents import Codex
from flashrsi.core import Task

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="Native extension fixtures require POSIX shell and tools"
)


def _core_config(server, **overrides):
    config = _config(server, None, **overrides)
    config.pop("cli_path")
    return config


def _custom_events(name, input_text, response_id):
    events = [
        {"type": "response.created", "response": {"id": response_id}},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "custom_tool_call",
                "id": "ctc_" + response_id,
                "call_id": "call_" + response_id,
                "name": name,
                "input": input_text,
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": response_id,
                "usage": {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23},
            },
        },
    ]
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()


@pytest.fixture(autouse=True)
def local_model_only(monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def test_core_session_hook_executes_selected_candidate(responses_server, tmp_path):
    source = _source(tmp_path)
    log = tmp_path / "core-hook.jsonl"
    hook = source / "hooks/session.py"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        "import json,pathlib,sys\n"
        "event=json.load(sys.stdin)\n"
        f"with pathlib.Path({str(log)!r}).open('a') as output:\n"
        "    output.write(json.dumps({'version':'BASELINE', 'event':event})+'\\n')\n"
        "print(json.dumps({'hookSpecificOutput':{"
        "'hookEventName':event['hook_event_name'],"
        "'additionalContext':'CORE_HOOK_BASELINE_'+event['hook_event_name']}}))\n"
    )
    command = f'command=\'"{sys.executable}" "$CODEX_HOME/hooks/session.py"\'\n'
    (source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\nhooks=true\n"
        "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
        'type="command"\n' + command + "timeout=5\n"
        "[[hooks.UserPromptSubmit]]\n[[hooks.UserPromptSubmit.hooks]]\n"
        'type="command"\n' + command + "timeout=5\n"
    )
    agent = Codex(_core_config(responses_server, source_dir=source))
    agent.set_scope({"hook": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        path = directory / "hooks/session.py"
        path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)

    (result,) = asyncio.run(
        agent.rollout(
            [Task("hook", "Answer the supplied response.")], snapshot=candidate
        )
    )
    assert result.status == "finished", result.error_message
    candidate_request = json.dumps(responses_server.requests[-1]["body"])
    for event_name in ("SessionStart", "UserPromptSubmit"):
        assert "CORE_HOOK_CANDIDATE_" + event_name in candidate_request
    assert "CORE_HOOK_BASELINE" not in candidate_request
    assert agent.snapshot.id == baseline.id

    result = asyncio.run(agent.run("Answer the supplied response."))
    assert result.status == "finished", result.error_message
    baseline_request = json.dumps(responses_server.requests[-1]["body"])
    for event_name in ("SessionStart", "UserPromptSubmit"):
        assert "CORE_HOOK_BASELINE_" + event_name in baseline_request
    executions = [json.loads(line) for line in log.read_text().splitlines()]
    assert [entry["version"] for entry in executions] == [
        "CANDIDATE",
        "CANDIDATE",
        "BASELINE",
        "BASELINE",
    ]
    assert [entry["event"]["hook_event_name"] for entry in executions] == [
        "SessionStart",
        "UserPromptSubmit",
    ] * 2
    for entry in executions:
        if entry["event"]["hook_event_name"] == "UserPromptSubmit":
            assert entry["event"]["prompt"] == "Answer the supplied response."
    assert "CORE_HOOK_BASELINE" in hook.read_text()


def test_core_notify_preserves_upstream_client_and_payload(
    responses_server, upstream_codex, tmp_path
):
    source = _source(tmp_path)
    task = tmp_path / "notify-task"
    task.mkdir()
    log = tmp_path / "notify.json"
    script = (
        "import pathlib,sys;"
        f"target=pathlib.Path({str(log)!r});"
        "staging=target.with_suffix('.tmp');"
        "staging.write_text(sys.argv[-1]);staging.replace(target)"
    )
    (source / "config.toml").write_text(
        f"notify={json.dumps([sys.executable, '-c', script])}\n"
        "[features]\nplugins=false\nremote_plugin=false\n"
    )
    observed = []
    for binary in (upstream_codex, None):
        log.unlink(missing_ok=True)
        responses_server.requests.clear()
        config = _core_config(responses_server, source_dir=source)
        if binary is not None:
            config["cli_path"] = binary

        async def scenario():
            result = await Codex(config).run("Notify with the native client.", task)
            assert result.status == "finished", result.error_message
            async with asyncio.timeout(5):
                while not log.exists():
                    await asyncio.sleep(0.01)
            return result, json.loads(log.read_text())

        result, payload = asyncio.run(scenario())
        assert payload["type"] == "agent-turn-complete"
        assert payload["client"] == "codex_exec"
        assert payload["input-messages"] == ["Notify with the native client."]
        assert payload["last-assistant-message"] == result.output
        assert Path(payload["cwd"]) == task
        observed.append(
            _normalize(
                {
                    "notify": payload,
                    "requests": responses_server.requests,
                    "usage": dict(result.usage),
                },
                tmp_path,
            )
        )
    for label, trace in zip(("upstream", "core"), observed, strict=True):
        (tmp_path / f"notify-{label}.json").write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1]


def test_core_external_clock_matches_upstream_rejection(
    responses_server, upstream_codex, tmp_path
):
    source = _source(tmp_path)
    (source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\n"
        "[features.current_time_reminder]\nenabled=true\n"
        'clock_source="external"\nreminder_interval_seconds=0\n'
    )
    expected = (
        "Fatal error: failed to read current time: current-time request failed: "
        "code=-32000 message=external current time is not supported in exec mode"
    )
    observed = []
    for binary in (upstream_codex, None):
        responses_server.requests.clear()
        config = _core_config(responses_server, source_dir=source)
        if binary is not None:
            config["cli_path"] = binary
        result = asyncio.run(Codex(config).run("Read the configured external clock."))
        assert result.status == "error"
        assert result.error_message.splitlines()[0] == expected
        assert not responses_server.requests
        assert result.output == ""
        assert dict(result.usage) == {}
        observed.append(
            {
                "status": result.status,
                "error": result.error_message.splitlines()[0],
                "output": result.output,
                "usage": dict(result.usage),
                "requests": responses_server.requests.copy(),
            }
        )
    assert observed[0] == observed[1]


def test_core_startup_warning_matches_upstream_without_failing_turn(
    responses_server, upstream_codex, tmp_path
):
    source = _source(tmp_path)
    (source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\n"
        '[otel.span_attributes]\n""="missing-key"\n'
    )
    expected = (
        "Ignoring invalid `otel.span_attributes` config: "
        "configured span attribute key must not be empty"
    )
    observed = []
    for binary in (upstream_codex, None):
        responses_server.requests.clear()
        config = _core_config(responses_server, source_dir=source)
        if binary is not None:
            config["cli_path"] = binary
        result = asyncio.run(Codex(config).run("Answer despite the startup warning."))
        assert result.status == "finished", result.error_message
        assert result.output == "Paris"
        assert result.error_message is None
        # CLI wraps ConfigWarning in item.completed; the core retains Warning.
        # Both must preserve the native warning text in the public trajectory.
        warnings = []
        for event in result.messages:
            if binary is None:
                payload = event.get("msg", {})
                if payload.get("type") == "warning":
                    warnings.append(payload["message"])
            elif event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "error":
                    warnings.append(item["message"])
        warnings = [message for message in warnings if message.startswith(expected)]
        assert warnings == [expected], result.messages
        observed.append(
            _normalize(
                {
                    "warnings": warnings,
                    "requests": responses_server.requests,
                    "output": result.output,
                    "usage": dict(result.usage),
                },
                tmp_path,
            )
        )
    assert observed[0] == observed[1]


@pytest.mark.parametrize("read_only", [True, False], ids=["read", "approved-write"])
def test_core_mcp_result_reaches_the_model(responses_server, tmp_path, read_only):
    source = _source(tmp_path)
    log = tmp_path / "core-mcp.json"
    server = source / "servers/probe.py"
    server.parent.mkdir(parents=True)
    server.write_text(
        textwrap.dedent(
            f"""\
            import json,os,pathlib,sys

            for line in sys.stdin:
                request=json.loads(line)
                if 'id' not in request:
                    continue
                if request['method']=='initialize':
                    result={{
                        'protocolVersion':'2024-11-05','capabilities':{{'tools':{{}}}},
                        'serverInfo':{{'name':'core-probe','version':'1'}},
                    }}
                elif request['method']=='tools/list':
                    result={{'tools':[{{
                        'name':'echo','description':'Return the supplied core evidence.',
                        'annotations':{{'readOnlyHint':{read_only!r}}},
                        'inputSchema':{{'type':'object','properties':{{
                            'message':{{'type':'string'}}
                        }},'required':['message']}},
                    }}]}}
                elif request['method']=='tools/call':
                    pathlib.Path({str(log)!r}).write_text(json.dumps({{
                        'cwd':str(pathlib.Path.cwd()),
                        'script':str(pathlib.Path(__file__).resolve()),
                        'home':os.environ['CODEX_HOME'],
                        'task':os.environ['FLASHRSI_TASK_DIR'],
                        'params':request['params'],
                    }}))
                    if not {read_only!r}:
                        pathlib.Path('core-mcp-created.txt').write_text('CORE_MCP_WRITE')
                    result={{'content':[{{'type':'text','text':
                        'CORE_MCP_RESULT:'+request['params']['arguments']['message']
                    }}],'isError':False}}
                else:
                    result={{}}
                print(json.dumps({{'jsonrpc':'2.0','id':request['id'],'result':result}}),flush=True)
            """
        )
    )
    (source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\n"
        "[mcp_servers.probe]\n"
        f"command={json.dumps(sys.executable)}\n"
        'args=["servers/probe.py"]\n'
        'env_vars=["CODEX_HOME","FLASHRSI_TASK_DIR"]\n'
        "startup_timeout_sec=10\ntool_timeout_sec=5\n"
        + ("" if read_only else 'default_tools_approval_mode="approve"\n')
    )

    def reply(request):
        if len(responses_server.requests) == 1:
            assert any(
                tool.get("name") == "mcp__probe" for tool in request["body"]["tools"]
            )
            return _events(
                call=("echo", {"message": "selected core snapshot"}),
                namespace="mcp__probe",
                response_id="resp_core_mcp_call",
            )
        assert "CORE_MCP_RESULT:selected core snapshot" in json.dumps(request["body"])
        return _events("Core MCP complete", response_id="resp_core_mcp_done")

    responses_server.reply = reply
    task = tmp_path / "mcp-task"
    task.mkdir()
    agent = Codex(_core_config(responses_server, source_dir=source))
    result = asyncio.run(agent.run("Use the probe MCP tool.", working_dir=task))
    assert result.status == "finished", result.error_message
    assert result.output == "Core MCP complete"
    assert len(responses_server.requests) == 2
    execution = json.loads(log.read_text())
    assert execution["params"]["arguments"] == {"message": "selected core snapshot"}
    assert Path(execution["script"]).parent.parent == Path(execution["home"])
    assert Path(execution["cwd"]) == Path(execution["task"]) == task.resolve()
    created = task / "core-mcp-created.txt"
    if read_only:
        assert not created.exists()
    else:
        assert created.read_text() == "CORE_MCP_WRITE"


def test_core_custom_subagent_executes_selected_role(responses_server, tmp_path):
    source = _source(tmp_path)
    role = source / "agents/researcher.toml"
    role.parent.mkdir(parents=True)
    marker = "CORE_RESEARCHER_ROLE_INSTRUCTIONS"
    role.write_text(f'developer_instructions="{marker}"\n')
    (source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\n"
        "[features.multi_agent_v2]\nenabled=true\n"
        '[agents.researcher]\ndescription="Research the delegated evidence."\n'
        'config_file="agents/researcher.toml"\n'
    )
    child_requests = []

    def reply(request):
        body = request["body"]
        serialized = json.dumps(body)
        if marker in serialized:
            child_requests.append(body)
            return _events("CHILD_CORE_COMPLETE", response_id="resp_core_child")
        if "call_resp_core_spawn" not in serialized:
            assert any(tool.get("name") == "collaboration" for tool in body["tools"])
            return _events(
                call=(
                    "spawn_agent",
                    {
                        "task_name": "core_researcher",
                        "agent_type": "researcher",
                        "fork_turns": "none",
                        "message": "CORE_CHILD_TASK: return the role evidence.",
                    },
                ),
                namespace="collaboration",
                response_id="resp_core_spawn",
            )
        if "call_resp_core_wait" not in serialized:
            return _events(
                call=("wait_agent", {"timeout_ms": 10000}),
                namespace="collaboration",
                response_id="resp_core_wait",
            )
        assert "CHILD_CORE_COMPLETE" in serialized
        return _events("Core parent complete", response_id="resp_core_parent")

    responses_server.reply = reply
    agent = Codex(_core_config(responses_server, source_dir=source))
    result = asyncio.run(agent.run("Delegate the evidence task to researcher."))
    assert result.status == "finished", result.error_message
    assert result.output == "Core parent complete"
    assert len(child_requests) == 1
    assert "CORE_CHILD_TASK" in json.dumps(child_requests[0])
    assert marker not in json.dumps(responses_server.requests[0]["body"])


def test_core_mcp_elicitation_matches_noninteractive_upstream(
    responses_server, upstream_codex, tmp_path
):
    source = _source(tmp_path)
    log = tmp_path / "elicitation.jsonl"
    server = source / "servers/question.py"
    server.parent.mkdir(parents=True)
    server.write_text(
        f"LOG={str(log)!r}\n"
        + textwrap.dedent(
            """\
            import json,pathlib,sys

            pending=None
            def send(message):
                print(json.dumps(message),flush=True)

            for line in sys.stdin:
                request=json.loads(line)
                if 'method' not in request:
                    with pathlib.Path(LOG).open('a') as log:
                        log.write(json.dumps(request)+'\\n')
                    action=request.get('result',{}).get('action','MISSING')
                    send({'jsonrpc':'2.0','id':pending,'result':{
                        'content':[{'type':'text','text':'CORE_ELICITATION:'+action}],
                        'isError':False,
                    }})
                    continue
                if 'id' not in request:
                    continue
                method=request['method']
                if method=='initialize':
                    result={
                        'protocolVersion':'2025-06-18','capabilities':{'tools':{}},
                        'serverInfo':{'name':'elicitation-probe','version':'1'},
                    }
                elif method=='tools/list':
                    result={'tools':[{
                        'name':'question','description':'Ask for optional evidence.',
                        'annotations':{'readOnlyHint':True},
                        'inputSchema':{'type':'object','properties':{}},
                    }]}
                elif method=='tools/call':
                    pending=request['id']
                    send({'jsonrpc':'2.0','id':'probe-question','method':'elicitation/create',
                        'params':{'message':'Supply optional evidence.',
                            'requestedSchema':{'type':'object','properties':{
                                'evidence':{'type':'string'}
                            },'required':['evidence']},
                        },
                    })
                    continue
                else:
                    result={}
                send({'jsonrpc':'2.0','id':request['id'],'result':result})
            """
        )
    )
    (source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\n"
        "[mcp_servers.probe]\n"
        f"command={json.dumps(sys.executable)}\n"
        'args=["servers/question.py"]\n'
        "startup_timeout_sec=10\ntool_timeout_sec=5\n"
    )

    def reply(request):
        if len(responses_server.requests) == 1:
            return _events(
                call=("question", {}),
                namespace="mcp__probe",
                response_id="resp_elicitation_call",
            )
        return _events("Elicitation complete", response_id="resp_elicitation_done")

    responses_server.reply = reply
    task = tmp_path / "elicitation-task"
    task.mkdir()
    observed = []
    for binary in (upstream_codex, None):
        responses_server.requests.clear()
        config = _core_config(responses_server, source_dir=source)
        if binary is not None:
            config["cli_path"] = binary
        result = asyncio.run(
            Codex(config).run("Call the optional evidence tool.", task)
        )
        assert result.status == "finished", result.error_message
        assert result.output == "Elicitation complete"
        assert len(responses_server.requests) == 2
        assert "CORE_ELICITATION:decline" in json.dumps(
            responses_server.requests[-1]["body"]
        )
        observed.append(_normalize(responses_server.requests, tmp_path))
    answers = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(answers) == 2
    assert all(answer["result"]["action"] == "decline" for answer in answers)
    for label, trace in zip(("upstream", "core"), observed, strict=True):
        (tmp_path / f"elicitation-{label}.json").write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1]


def test_core_code_mode_matches_upstream_execution(
    responses_server, upstream_codex, tmp_path
):
    source = _source(tmp_path)
    (source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\n"
        "[features.code_mode]\nenabled=true\n"
        "[features.code_mode_host]\nenabled=true\ndisable_in_process_fallback=true\n"
    )

    def reply(request):
        if len(responses_server.requests) != 1:
            return _events("Code mode complete", response_id="resp_code_done")
        assert any(tool.get("name") == "exec" for tool in request["body"]["tools"])
        events = [
            {"type": "response.created", "response": {"id": "resp_code_exec"}},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "custom_tool_call",
                    "id": "ctc_code_exec",
                    "call_id": "call_code_exec",
                    "name": "exec",
                    "input": "text(6 * 7);",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_code_exec",
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 3,
                        "total_tokens": 23,
                    },
                },
            },
        ]
        return "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        ).encode()

    responses_server.reply = reply
    task = tmp_path / "code-mode-task"
    task.mkdir()
    observed = []
    for binary in (upstream_codex, None):
        responses_server.requests.clear()
        config = _core_config(
            responses_server, source_dir=source, sandbox="danger-full-access"
        )
        if binary is not None:
            config["cli_path"] = binary
        result = asyncio.run(
            Codex(config).run("Execute the supplied JavaScript.", task)
        )
        assert result.status == "finished", result.error_message
        assert result.output == "Code mode complete"
        assert len(responses_server.requests) == 2
        outputs = [
            item
            for item in responses_server.requests[-1]["body"]["input"]
            if item.get("type") == "custom_tool_call_output"
        ]
        assert len(outputs) == 1
        assert "42" in json.dumps(outputs[0]["output"])
        assert "Error:" not in json.dumps(outputs[0]["output"])
        observed.append(_normalize(responses_server.requests, tmp_path))
    for label, trace in zip(("upstream", "core"), observed, strict=True):
        (tmp_path / f"code-mode-{label}.json").write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1]


def test_core_apply_patch_matches_upstream_edit_and_requests(
    responses_server, upstream_codex, tmp_path
):
    source = _source(tmp_path)
    task = tmp_path / "patch-task"
    task.mkdir()
    edited = task / "proof.txt"
    patch = "*** Begin Patch\n*** Add File: proof.txt\n+CORE_NATIVE_PATCH_PAYLOAD\n*** End Patch\n"

    def reply(request):
        if len(responses_server.requests) == 1:
            return _custom_events("apply_patch", patch, "resp_native_patch")
        return _events("Patch complete", response_id="resp_patch_done")

    responses_server.reply = reply
    observed = []
    for binary in (upstream_codex, None):
        edited.unlink(missing_ok=True)
        responses_server.requests.clear()
        config = _core_config(responses_server, source_dir=source)
        if binary is not None:
            config["cli_path"] = binary
        result = asyncio.run(Codex(config).run("Apply the supplied patch.", task))
        assert result.status == "finished", result.error_message
        assert result.output == "Patch complete"
        assert len(responses_server.requests) == 2
        assert any(
            tool.get("name") == "apply_patch"
            for tool in responses_server.requests[0]["body"]["tools"]
        )
        assert edited.read_text() == "CORE_NATIVE_PATCH_PAYLOAD\n"
        assert "proof.txt" in json.dumps(responses_server.requests[-1]["body"])
        observed.append(
            _normalize(
                {"requests": responses_server.requests, "usage": dict(result.usage)},
                tmp_path,
            )
        )
    for label, trace in zip(("upstream", "core"), observed, strict=True):
        (tmp_path / f"apply-patch-{label}.json").write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1]


def test_core_tiff_view_image_matches_upstream_payload(
    responses_server, upstream_codex, tmp_path
):
    source = _source(tmp_path)
    task = tmp_path / "image-task"
    task.mkdir()
    image = task / "probe.tiff"
    width, height = 16, 12
    pixels = bytes(
        channel
        for y in range(height)
        for x in range(width)
        for channel in (x * 13, y * 19, 127)
    )
    # One uncompressed RGB TIFF strip, constructed without an imaging dependency.
    bits_offset = 8 + 2 + 10 * 12 + 4
    tags = [
        (256, 4, 1, width),
        (257, 4, 1, height),
        (258, 3, 3, bits_offset),
        (259, 3, 1, 1),
        (262, 3, 1, 2),
        (273, 4, 1, bits_offset + 6),
        (277, 3, 1, 3),
        (278, 4, 1, height),
        (279, 4, 1, len(pixels)),
        (284, 3, 1, 1),
    ]
    original = (
        struct.pack("<2sHIH", b"II", 42, 8, len(tags))
        + b"".join(struct.pack("<HHII", *tag) for tag in tags)
        + struct.pack("<IHHH", 0, 8, 8, 8)
        + pixels
    )
    image.write_bytes(original)

    def reply(request):
        if len(responses_server.requests) == 1:
            return _events(
                call=("view_image", {"path": str(image)}), response_id="resp_tiff_view"
            )
        return _events("Image complete", response_id="resp_tiff_done")

    responses_server.reply = reply
    observed = []
    for binary in (upstream_codex, None):
        responses_server.requests.clear()
        config = _core_config(
            responses_server, source_dir=source, sandbox="danger-full-access"
        )
        if binary is not None:
            config["cli_path"] = binary
        result = asyncio.run(
            Codex(config).run("Inspect the supplied TIFF image.", task)
        )
        assert result.status == "finished", result.error_message
        assert result.output == "Image complete"
        assert len(responses_server.requests) == 2
        images = [
            part
            for item in responses_server.requests[-1]["body"]["input"]
            for part in item.get("output", [])
            if isinstance(part, dict) and part.get("type") == "input_image"
        ]
        assert len(images) == 1, [
            item
            for item in responses_server.requests[-1]["body"]["input"]
            if item.get("type") == "function_call_output"
        ]
        assert images[0]["image_url"].startswith("data:image/")
        observed.append(_normalize(responses_server.requests, tmp_path))
    assert image.read_bytes() == original
    for label, trace in zip(("upstream", "core"), observed, strict=True):
        (tmp_path / f"tiff-{label}.json").write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1]


@pytest.mark.skipif(os.name != "posix", reason="Native tool sessions require POSIX")
@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_core_interrupt_closes_independent_tool_session(
    responses_server, tmp_path, mode
):
    task = tmp_path / "task"
    task.mkdir()
    pidfile = task / "core-tool-process.json"
    script = (
        "import json,os,time;from pathlib import Path;"
        "Path('core-tool-process.json').write_text(json.dumps({"
        "'pid':os.getpid(),'pgid':os.getpgid(0),"
        "'parent_pgid':os.getpgid(os.getppid()),"
        "'home':os.environ['CODEX_HOME']}));"
        "time.sleep(45)"
    )
    command = shlex.quote(sys.executable) + " -c " + shlex.quote(script)

    def reply(request):
        name, arguments = _shell_call(request["body"], command)
        arguments["yield_time_ms"] = 10000
        return _events(call=(name, arguments), response_id="resp_core_sleep")

    responses_server.reply = reply
    agent = Codex(
        _core_config(
            responses_server,
            timeout=5 if mode == "timeout" else 30,
            sandbox="danger-full-access",
        )
    )

    async def scenario():
        running = asyncio.create_task(
            agent.run("Run the tool and wait.", working_dir=task)
        )
        try:
            if mode == "timeout":
                result = await asyncio.wait_for(running, timeout=12)
                assert result.status == "error"
                assert "timed out" in result.error_message
            else:
                async with asyncio.timeout(10):
                    while not pidfile.exists():
                        await asyncio.sleep(0.02)
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(running, timeout=8)
        finally:
            if not running.done():
                running.cancel()
                with suppress(asyncio.CancelledError):
                    await running

    try:
        asyncio.run(scenario())
        child = json.loads(pidfile.read_text())
        assert child["pgid"] != child["parent_pgid"]
        with pytest.raises(ProcessLookupError):
            os.kill(child["pid"], 0)
        assert not Path(child["home"]).exists()
    finally:
        if pidfile.exists():
            child = json.loads(pidfile.read_text())
            with suppress(ProcessLookupError):
                os.kill(child["pid"], signal.SIGKILL)
