"""Exercise the native Codex CLI and resource discovery against localhost."""

import asyncio
import gzip
import importlib.util
import inspect
import json
import shutil
import sys
import textwrap
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from flashrsi.agents import Codex
from flashrsi.core import Task


def _events(text="Paris", *, call=None, namespace=None, response_id="resp_local"):
    item = {
        "type": "message",
        "id": "msg_" + response_id,
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }
    if call is not None:
        name, arguments = call
        item = {
            "type": "function_call",
            "id": "fc_" + response_id,
            "call_id": "call_" + response_id,
            "name": name,
            "arguments": json.dumps(arguments),
        }
        if namespace is not None:
            item["namespace"] = namespace
    events = [
        {"type": "response.created", "response": {"id": response_id}},
        {"type": "response.output_item.done", "item": item},
        {
            "type": "response.completed",
            "response": {
                "id": response_id,
                "usage": {
                    "input_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 5},
                    "output_tokens": 3,
                    "output_tokens_details": {"reasoning_tokens": 1},
                    "total_tokens": 23,
                },
            },
        },
    ]
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()


@pytest.fixture
def codex_binary():
    # An ambient desktop Codex may be a different revision or a UI entry point.
    # Native parity must exercise the explicitly pinned distribution.
    package = pytest.importorskip("codex_cli_bin")
    return str(package.bundled_codex_path())


@pytest.fixture
def responses_server(monkeypatch, tmp_path):
    # A custom provider and explicit fake key keep all model requests local.
    monkeypatch.setenv("CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG", "1")

    class LocalModel:
        def __init__(self):
            self.requests = []
            self.errors = []

        def reply(self, request):
            return _events(response_id=f"resp_{len(self.requests)}")

    model = LocalModel()
    model.source_dir = _source(tmp_path / "native-default")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if self.path.endswith("/models"):
                content = json.dumps(
                    {"object": "list", "data": [{"id": "gpt-5", "object": "model"}]}
                ).encode()
                self._send(200, "application/json", content)
            else:
                self._send(404, "application/json", b"{}")

        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                if self.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                request = {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(raw),
                }
                model.requests.append(request)
                if not self.path.endswith("/responses"):
                    raise AssertionError(f"unexpected request: {self.path}")
                content = model.reply(request)
                self._send(200, "text/event-stream", content)
            except Exception as error:
                model.errors.append(error)
                self._send(500, "application/json", b'{"error":"local test failure"}')

        def _send(self, status, content_type, content):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    model.base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield model
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not model.errors


def _config(server, binary, **overrides):
    return {
        "llm": {
            "model_name": "gpt-5",
            "api_key": "local-codex-test-key",
            "base_url": server.base_url,
        },
        "cli_path": binary,
        "source_dir": server.source_dir,
        "timeout": 30,
        **overrides,
    }


def _source(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        Path(inspect.getfile(Codex)).parent,
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "runtime"),
    )
    # These tests cover local snapshot resources. Plugin network discovery has
    # a separate test suite and must not contact remote catalogs here.
    (source / "config.toml").write_text(
        "[features]\nplugins = false\nremote_plugin = false\n"
    )
    return source


def _shell_call(body, command):
    names = {tool.get("name") for tool in body["tools"]}
    if "exec_command" in names:
        return "exec_command", {"cmd": command, "yield_time_ms": 1000}
    if "shell_command" in names:
        return "shell_command", {"command": command}
    if "shell" in names:
        return "shell", {"command": ["sh", "-c", command]}
    raise AssertionError(f"native shell tool missing: {names}")


def test_native_cli_answers_and_preserves_usage(responses_server, codex_binary):
    config = _config(responses_server, codex_binary)
    if importlib.util.find_spec("codex_cli_bin") is not None:
        config.pop("cli_path")
    agent = Codex(config)
    (result,) = asyncio.run(agent.rollout([Task("capital", "Capital of France?")]))

    assert result.status == "finished", result.error_message
    assert result.output == "Paris"
    assert result.task.task_id == "capital"
    assert result.messages[0]["type"] == "RunConfig"
    completion_type = (
        "turn.completed" if config.get("cli_path") else "flashrsi.core.completed"
    )
    assert any(message.get("type") == completion_type for message in result.messages)
    assert result.usage["prompt_tokens"] == 20
    assert result.usage["completion_tokens"] == 3
    assert result.usage["prompt_tokens_details"]["cached_tokens"] == 5
    assert responses_server.requests
    assert all(
        request["authorization"] == "Bearer local-codex-test-key"
        for request in responses_server.requests
    )
    trace = json.dumps([dict(message) for message in result.messages])
    assert "local-codex-test-key" not in trace


def test_candidate_resources_reach_native_prompt_without_activation(
    responses_server, codex_binary, tmp_path
):
    source = _source(tmp_path)
    (source / "AGENTS.md").write_text("BASELINE_INSTRUCTION_PROBE")
    skill = source / "skills/probe/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: probe\ndescription: BASELINE_SKILL_PROBE\n---\nSkill procedure.\n"
    )
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))
    agent.set_scope({"prompt": "rw", "skill": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        (directory / "AGENTS.md").write_text("CANDIDATE_INSTRUCTION_PROBE")
        (directory / "skills/probe/SKILL.md").write_text(
            "---\nname: probe\ndescription: CANDIDATE_SKILL_PROBE\n---\nSkill procedure.\n"
        )
        candidate = baseline.commit(directory)

    (result,) = asyncio.run(
        agent.rollout([Task("probe", "Answer directly.")], snapshot=candidate)
    )
    assert result.status == "finished", result.error_message
    request = json.dumps(responses_server.requests[-1]["body"])
    assert "CANDIDATE_INSTRUCTION_PROBE" in request
    assert "CANDIDATE_SKILL_PROBE" in request
    assert "BASELINE_INSTRUCTION_PROBE" not in request
    assert "BASELINE_SKILL_PROBE" not in request
    assert agent.snapshot is baseline
    assert result.messages[0]["snapshot_id"] == candidate.id

    result = asyncio.run(agent.run("Answer directly."))
    assert result.status == "finished", result.error_message
    request = json.dumps(responses_server.requests[-1]["body"])
    assert "BASELINE_INSTRUCTION_PROBE" in request
    assert "BASELINE_SKILL_PROBE" in request
    assert "CANDIDATE_INSTRUCTION_PROBE" not in request


def test_native_worker_edits_target_and_keeps_own_version(
    responses_server, codex_binary, tmp_path
):
    target = tmp_path / "edit-target"
    target.mkdir()
    resource = target / "skill.md"
    resource.write_text("initial procedure")

    def reply(request):
        body = request["body"]
        if resource.read_text() == "UPDATED_NATIVE_SKILL":
            return _events("edited", response_id="resp_done")
        command = "printf UPDATED_NATIVE_SKILL > skill.md"
        return _events(call=_shell_call(body, command), response_id="resp_edit")

    responses_server.reply = reply
    worker = Codex(
        _config(responses_server, codex_binary, sandbox="danger-full-access")
    )
    original = worker.snapshot
    result = asyncio.run(worker.run("Improve skill.md", working_dir=target))

    assert result.status == "finished", result.error_message
    assert result.output == "edited"
    assert resource.read_text() == "UPDATED_NATIVE_SKILL"
    assert worker.snapshot is original
    assert len(responses_server.requests) == 2
    assert any(
        message.get("item", {}).get("type") == "command_execution"
        for message in result.messages
    )


def test_skillopt_runner_evolves_native_codex_target_with_native_worker(
    responses_server, codex_binary, tmp_path
):
    from flashrsi.config import load_config
    from flashrsi.core import Snapshot
    from flashrsi.runner import _run

    marker = "NATIVE_RUNNER_EVIDENCE_SKILL"
    proposal = {
        "reasoning": "Read the evidence before answering.",
        "edits": [
            {
                "op": "append",
                "path": "skills/evidence/SKILL.md",
                "content": (
                    "---\nname: evidence\ndescription: "
                    + marker
                    + "\n---\nUse the supplied context to check the answer.\n"
                ),
                "source_type": "failure",
                "support_count": 1,
            }
        ],
    }

    def reply(request):
        if request["authorization"] == "Bearer local-worker-key":
            text = json.dumps(proposal)
        else:
            assert request["authorization"] == "Bearer local-codex-test-key"
            text = "Paris" if marker in json.dumps(request["body"]) else "Rome"
        return _events(text, response_id=f"resp_{len(responses_server.requests)}")

    responses_server.reply = reply
    data = tmp_path / "questions.json"
    data.write_text(
        json.dumps(
            [
                {
                    "id": f"question-{index}",
                    "question": "Capital of France?",
                    "context": "Paris is the capital of France.",
                    "answers": ["Paris"],
                }
                for index in range(5)
            ]
        )
    )
    target_config = _config(responses_server, codex_binary)
    worker_config = _config(responses_server, codex_binary)
    worker_config["llm"]["api_key"] = "local-worker-key"
    config = load_config(
        overrides={
            "run": {"output_dir": str(tmp_path / "runs")},
            "benchmark": {"name": "searchqa", "data_path": str(data)},
            "agent": {"name": "codex", **target_config},
            "algorithm": {
                "name": "skillopt",
                "num_epochs": 1,
                "max_steps": 1,
                "batch_size": 1,
                "reflection_minibatch_size": 1,
                "edit_budget": 1,
                "worker": {"type": "agent", "name": "codex", **worker_config},
            },
        }
    )

    run_dir, summary = asyncio.run(_run(config))

    assert summary["status"] == "finished"
    assert summary["test_score"] == 1.0
    assert summary["test_tasks"] == 1
    final = Snapshot.load(run_dir / "snapshots" / f"{summary['snapshot_id']}.json")
    assert marker.encode() in final.files["skills/evidence/SKILL.md"].content
    records = [
        json.loads(path.read_text())
        for path in (run_dir / "trajectories").glob("*.json")
    ]
    (decision,) = [record for record in records if record.get("kind") == "fast"]
    assert decision["accepted"] is True
    assert decision["baseline_score"] == 0.0
    assert decision["score"] == 1.0
    assert decision["candidate_id"] == final.id
    assert final.parent_id == decision["parent_id"]
    (test_record,) = [
        json.loads(path.read_text())
        for path in (run_dir / "trajectories").glob("*-test.json")
    ]
    assert test_record["snapshot_id"] == final.id
    assert all(item["output"] == "Paris" for item in test_record["trajectories"])
    assert (run_dir / "snapshots" / "worker.json").is_file()
    assert any(
        record.get("trajectory", {})
        .get("messages", [{}])[0]
        .get("config", {})
        .get("name")
        == "codex"
        for record in records
    )
    saved = "".join(path.read_text() for path in run_dir.rglob("*") if path.is_file())
    assert "local-codex-test-key" not in saved
    assert "local-worker-key" not in saved


def test_native_session_hook_executes_candidate_without_activating_it(
    responses_server, codex_binary, tmp_path
):
    source = _source(tmp_path)
    log = tmp_path / "hook-executions.jsonl"
    hook = source / "hooks/session.py"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        "import json, pathlib, sys\n"
        "event = json.load(sys.stdin)\n"
        f"with pathlib.Path({str(log)!r}).open('a') as output:\n"
        "    output.write(json.dumps({'version': 'baseline', 'event': event}) + '\\n')\n"
    )
    (source / "config.toml").write_text(
        "[features]\nplugins = false\nremote_plugin = false\nhooks = true\n"
        "[[hooks.SessionStart]]\n"
        "[[hooks.SessionStart.hooks]]\n"
        'type = "command"\n'
        f'command = \'"{sys.executable}" "$CODEX_HOME/hooks/session.py"\'\n'
        "timeout = 5\n"
    )
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))
    assert agent.snapshot.files["hooks/session.py"].component == "hook"
    agent.set_scope({"hook": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        path = directory / "hooks/session.py"
        path.write_text(path.read_text().replace("'baseline'", "'candidate'"))
        candidate = baseline.commit(directory)

    (result,) = asyncio.run(
        agent.rollout([Task("hook", "Answer directly.")], snapshot=candidate)
    )
    assert result.status == "finished", result.error_message
    assert agent.snapshot is baseline
    result = asyncio.run(agent.run("Answer directly."))
    assert result.status == "finished", result.error_message
    executions = [json.loads(line) for line in log.read_text().splitlines()]
    assert [entry["version"] for entry in executions] == ["candidate", "baseline"]
    assert all(
        entry["event"]["hook_event_name"] == "SessionStart" for entry in executions
    )
    assert (
        baseline.files["hooks/session.py"].content
        != candidate.files["hooks/session.py"].content
    )


@pytest.mark.parametrize(
    "read_only", [True, False], ids=["read-only", "approved-write"]
)
def test_native_mcp_server_runs_from_snapshot_and_returns_tool_result(
    responses_server, codex_binary, tmp_path, read_only
):
    source = _source(tmp_path)
    log = tmp_path / "mcp-execution.json"
    protocol_log = tmp_path / "mcp-protocol.jsonl"
    server = source / "servers/probe.py"
    server.parent.mkdir(parents=True)
    server.write_text(
        textwrap.dedent(
            f"""\
            import json, os, pathlib, sys

            for line in sys.stdin:
                with pathlib.Path({str(protocol_log)!r}).open('a') as output:
                    output.write(line)
                request = json.loads(line)
                if 'id' not in request:
                    continue
                method = request['method']
                if method == 'initialize':
                    result = {{
                        'protocolVersion': '2024-11-05',
                        'capabilities': {{'tools': {{}}}},
                        'serverInfo': {{'name': 'snapshot-probe', 'version': '1'}},
                    }}
                elif method == 'tools/list':
                    result = {{'tools': [{{
                        'name': 'echo',
                        'description': 'Return the supplied native MCP evidence.',
                        'annotations': {{'readOnlyHint': {read_only!r}}},
                        'inputSchema': {{'type': 'object', 'properties': {{
                            'message': {{'type': 'string'}}
                        }}, 'required': ['message']}},
                    }}]}}
                elif method == 'tools/call':
                    if not {read_only!r}:
                        pathlib.Path('mcp-created.txt').write_text('NATIVE_MCP_WRITE')
                    pathlib.Path({str(log)!r}).write_text(json.dumps({{
                        'cwd': str(pathlib.Path.cwd()),
                        'script': str(pathlib.Path(__file__).resolve()),
                        'resource_home': os.environ.get('CODEX_HOME'),
                        'task_dir': os.environ.get('FLASHRSI_TASK_DIR'),
                        'params': request['params'],
                    }}))
                    result = {{'content': [{{'type': 'text', 'text':
                        'NATIVE_MCP_TOOL_RESULT:' + request['params']['arguments']['message']
                    }}], 'isError': False}}
                else:
                    result = {{}}
                print(json.dumps({{'jsonrpc': '2.0', 'id': request['id'], 'result': result}}), flush=True)
            """
        )
    )
    (source / "config.toml").write_text(
        "[features]\nplugins = false\nremote_plugin = false\n"
        "[mcp_servers.probe]\n"
        f"command = {json.dumps(sys.executable)}\n"
        'args = ["servers/probe.py"]\n'
        'env_vars = ["CODEX_HOME", "FLASHRSI_TASK_DIR"]\n'
        "startup_timeout_sec = 10\n"
        "tool_timeout_sec = 5\n"
        + ("" if read_only else 'default_tools_approval_mode = "approve"\n')
    )

    def reply(request):
        if len(responses_server.requests) > 1:
            return _events("MCP complete", response_id="resp_mcp_done")
        tools = request["body"]["tools"]
        assert any(tool.get("name") == "mcp__probe" for tool in tools), tools
        return _events(
            call=("echo", {"message": "from snapshot"}),
            namespace="mcp__probe",
            response_id="resp_mcp_call",
        )

    responses_server.reply = reply
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))
    assert agent.snapshot.files["servers/probe.py"].component == "tool"
    task = tmp_path / "mcp-task"
    task.mkdir()
    result = asyncio.run(agent.run("Use the probe MCP server.", working_dir=task))

    protocol = protocol_log.read_text() if protocol_log.exists() else "not started"
    assert result.status == "finished", (
        f"{result.error_message}\nMCP protocol: {protocol}\n"
        f"Model requests: {len(responses_server.requests)}"
    )
    assert result.output == "MCP complete"
    assert log.is_file(), responses_server.requests[-1]["body"]["input"]
    execution = json.loads(log.read_text())
    assert execution["params"]["name"] == "echo"
    assert execution["params"]["arguments"] == {"message": "from snapshot"}
    assert Path(execution["script"]).parent.parent == Path(execution["resource_home"])
    assert Path(execution["cwd"]) == Path(execution["task_dir"]) == task.resolve()
    created = task / "mcp-created.txt"
    if read_only:
        assert not created.exists()
    else:
        assert created.read_text() == "NATIVE_MCP_WRITE"
    assert "NATIVE_MCP_TOOL_RESULT:from snapshot" in json.dumps(
        responses_server.requests[-1]["body"]
    )
    assert any(
        message.get("item", {}).get("type") == "mcp_tool_call"
        for message in result.messages
    )


def test_native_tools_read_selected_skill_body(
    responses_server, codex_binary, tmp_path
):
    source = _source(tmp_path)
    skill = source / "skills/probe/SKILL.md"
    skill.parent.mkdir(parents=True)
    marker = "NATIVE_SKILL_BODY_ONLY_42"
    skill.write_text(
        "---\nname: probe\ndescription: Read this procedure for the body test.\n---\n"
        + marker
        + "\n"
    )

    def reply(request):
        if len(responses_server.requests) == 1:
            assert marker not in json.dumps(request["body"])
            return _events(
                call=_shell_call(
                    request["body"], 'cat "$CODEX_HOME/skills/probe/SKILL.md"'
                ),
                response_id="resp_skill_read",
            )
        assert marker in json.dumps(request["body"])
        return _events("Skill read", response_id="resp_skill_done")

    responses_server.reply = reply
    agent = Codex(
        _config(
            responses_server,
            codex_binary,
            source_dir=source,
            sandbox="danger-full-access",
        )
    )
    result = asyncio.run(agent.run("Follow the probe skill procedure."))

    assert result.status == "finished", result.error_message
    assert result.output == "Skill read"
    assert len(responses_server.requests) == 2
    assert any(
        marker in message.get("item", {}).get("aggregated_output", "")
        for message in result.messages
    )


def test_native_custom_subagent_loads_snapshot_role(
    responses_server, codex_binary, tmp_path
):
    source = _source(tmp_path)
    role = source / "agents/researcher.toml"
    role.parent.mkdir(parents=True)
    marker = "NATIVE_RESEARCHER_ROLE_INSTRUCTIONS"
    role.write_text(f'developer_instructions = "{marker}"\n')
    (source / "config.toml").write_text(
        "[features]\nplugins = false\nremote_plugin = false\n"
        "[features.multi_agent_v2]\nenabled = true\n"
        "[agents.researcher]\n"
        'description = "Research the delegated native test task."\n'
        'config_file = "agents/researcher.toml"\n'
    )
    child_requests = []

    def reply(request):
        body = request["body"]
        serialized = json.dumps(body)
        if marker in serialized:
            child_requests.append(body)
            return _events("CHILD_NATIVE_COMPLETE", response_id="resp_child_done")
        if "call_resp_spawn" not in serialized:
            assert any(tool.get("name") == "collaboration" for tool in body["tools"])
            return _events(
                call=(
                    "spawn_agent",
                    {
                        "task_name": "native_researcher",
                        "agent_type": "researcher",
                        "fork_turns": "none",
                        "message": "NATIVE_CHILD_TASK: report the role evidence.",
                    },
                ),
                namespace="collaboration",
                response_id="resp_spawn",
            )
        if "call_resp_wait" not in serialized:
            return _events(
                call=("wait_agent", {"timeout_ms": 10000}),
                namespace="collaboration",
                response_id="resp_wait",
            )
        return _events("Parent complete", response_id="resp_parent_done")

    responses_server.reply = reply
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))
    assert agent.snapshot.files["agents/researcher.toml"].component == "agent"
    result = asyncio.run(agent.run("Delegate the evidence task to researcher."))

    assert result.status == "finished", result.error_message
    assert result.output == "Parent complete"
    assert len(child_requests) == 1
    assert "NATIVE_CHILD_TASK" in json.dumps(child_requests[0])
    assert marker not in json.dumps(responses_server.requests[0]["body"])
    assert any(
        message.get("item", {}).get("type") == "collab_tool_call"
        and message["item"]["status"] == "completed"
        for message in result.messages
    )


def test_native_invalid_skill_is_visible_in_success_diagnostics(
    responses_server, codex_binary, tmp_path
):
    source = _source(tmp_path)
    skill = source / "skills/missing-description/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: missing-description\n---\nInvalid skill body.\n")
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))

    result = asyncio.run(agent.run("Answer directly."))

    assert result.status == "finished", result.error_message
    assert result.output == "Paris"
    diagnostics = "\n".join(
        message["text"]
        for message in result.messages
        if message["type"] == "CodexDiagnostics"
    )
    assert "failed to load skill" in diagnostics
    assert "description" in diagnostics
    assert "missing-description/SKILL.md" in diagnostics
    assert responses_server.requests


def test_native_unknown_config_fails_before_model_request(
    responses_server, codex_binary, tmp_path
):
    source = _source(tmp_path)
    config = source / "config.toml"
    config.write_text("unknown_flashrsi_option = true\n" + config.read_text())
    agent = Codex(_config(responses_server, codex_binary, source_dir=source))

    result = asyncio.run(agent.run("Answer directly."))

    assert result.status == "error"
    assert "unknown_flashrsi_option" in result.error_message
    assert not responses_server.requests
    assert any(message["type"] == "CodexDiagnostics" for message in result.messages)
