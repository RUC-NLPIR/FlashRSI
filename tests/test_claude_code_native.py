"""Exercise the real Claude SDK, bundled CLI, skills and tools against localhost."""

import asyncio
import inspect
import json
import os
import shutil
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.benchmarks import SearchQA
from flashrsi.config import load_config
from flashrsi.core import Snapshot, Task

pytest.importorskip(
    "claude_agent_sdk", reason="Native Claude integration needs the claude-code extra"
)


def _message_events(body, text="Paris", *, tool=None, message_id="msg_local"):
    """Return the native Anthropic streaming protocol, including tool inputs."""
    message = {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": body["model"],
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 20, "output_tokens": 0},
    }
    block = {"type": "text", "text": ""}
    delta = {"type": "text_delta", "text": text}
    if tool:
        name, arguments = tool
        block = {
            "type": "tool_use",
            "id": f"tool_{message_id}",
            "name": name,
            "input": {},
        }
        delta = {"type": "input_json_delta", "partial_json": json.dumps(arguments)}
    events = [
        {"type": "message_start", "message": message},
        {"type": "content_block_start", "index": 0, "content_block": block},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {
                "stop_reason": "tool_use" if tool else "end_turn",
                "stop_sequence": None,
            },
            "usage": {"output_tokens": 3},
        },
        {"type": "message_stop"},
    ]
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()


def test_parent_cloud_provider_switches_do_not_redirect_configured_endpoint(
    anthropic_server, monkeypatch
):
    switches = (
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_ANTHROPIC_AWS",
        "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
        "CLAUDE_CODE_USE_MANTLE",
        "CLAUDE_CODE_USE_GATEWAY",
    )
    for name in switches:
        monkeypatch.setenv(name, "1")
    trajectory = asyncio.run(
        ClaudeCode(_config(anthropic_server, tools=[])).run("Answer directly")
    )
    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Paris"
    assert anthropic_server.requests
    assert all(
        request["api_key"] == "local-claude-test-key"
        for request in anthropic_server.requests
    )
    assert all(os.environ[name] == "1" for name in switches)


@pytest.fixture
def anthropic_server(tmp_path, monkeypatch):
    # Keep the real CLI's persistent state and optional background traffic out of
    # the developer's Claude installation. Only the local API receives prompts.
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_TERMINAL_TITLE", "1")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    for name in (
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    ):
        monkeypatch.delenv(name, raising=False)

    class LocalModel:
        def __init__(self):
            self.requests = []
            self.errors = []

        def reply(self, request):
            return _message_events(request["body"])

    model = LocalModel()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            try:
                request = {
                    "path": self.path,
                    "api_key": self.headers.get("x-api-key"),
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    ),
                }
                if "count_tokens" in self.path:
                    content = json.dumps({"input_tokens": 20}).encode()
                    content_type = "application/json"
                else:
                    model.requests.append(request)
                    content = model.reply(request)
                    content_type = "text/event-stream"
                status = 200
            except Exception as error:
                model.errors.append(error)
                status, content_type = 500, "application/json"
                content = json.dumps(
                    {"type": "error", "error": {"message": "test server error"}}
                ).encode()
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
    model.base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield model
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not model.errors


def _config(server, **overrides):
    return {
        "llm": {
            "model_name": "claude-sonnet-4-6",
            "api_key": "local-claude-test-key",
            "base_url": server.base_url,
        },
        "timeout": 30,
        **overrides,
    }


def _copy_source(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        Path(inspect.getfile(ClaudeCode)).parent,
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return source


def _write_skill(source, content):
    skill = source / "skills/probe/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: probe\ndescription: Read the test evidence.\n---\n" + content + "\n"
    )
    return skill


def _trace_text(trajectory):
    return json.dumps([dict(message) for message in trajectory.messages])


def test_real_sdk_answers_searchqa_and_preserves_native_usage(
    anthropic_server, tmp_path
):
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
                for index in range(3)
            ]
        )
    )
    config = load_config(
        overrides={
            "benchmark": {"data_path": data},
            "agent": _config(anthropic_server, tools=[]),
            "algorithm": {"worker": {"llm": {"model_name": "unused"}}},
        }
    )
    benchmark = SearchQA(config)
    benchmark.load()
    agent = ClaudeCode(config.agent)
    (trajectory,) = asyncio.run(agent.rollout(benchmark.dev))
    (graded,) = benchmark.grade((trajectory,))

    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Paris"
    assert trajectory.task is benchmark.dev[0]
    assert graded.metrics == {"exact_match": 1, "f1": 1}
    assert trajectory.usage["input_tokens"] == 20
    assert trajectory.usage["output_tokens"] == 3
    assert trajectory.usage["model_usage"]["claude-sonnet-4-6"]["inputTokens"] == 20
    assert trajectory.usage["total_cost_usd"] > 0
    assert {item["type"] for item in trajectory.messages} >= {
        "AssistantMessage",
        "ResultMessage",
    }
    assert "local-claude-test-key" not in _trace_text(trajectory)
    assert len(anthropic_server.requests) == 1
    request = anthropic_server.requests[0]
    assert request["path"].startswith("/v1/messages")
    assert request["api_key"] == "local-claude-test-key"
    assert request["body"]["model"] == "claude-sonnet-4-6"
    assert "Capital of France?" in json.dumps(request["body"]["messages"])
    assert "flashrsi:solve" not in json.dumps(request["body"])
    run_input = next(
        message for message in trajectory.messages if message["type"] == "RunInput"
    )
    assert run_input["system_prompt"] == {
        "type": "preset",
        "preset": "claude_code",
    }


def test_real_skill_candidate_is_loaded_without_selecting_it(
    anthropic_server, tmp_path
):
    source = _copy_source(tmp_path)
    skill = _write_skill(source, "BASELINE_SKILL_MARKER")

    def reply(request):
        body = request["body"]
        messages = json.dumps(body["messages"])
        tool = None
        if "CANDIDATE_SKILL_MARKER" in messages:
            text = "candidate"
        elif "BASELINE_SKILL_MARKER" in messages:
            text = "baseline"
        else:
            text = ""
            tool = ("Skill", {"skill": "flashrsi:probe"})
        return _message_events(
            body,
            text,
            tool=tool,
            message_id=f"msg_{len(anthropic_server.requests)}",
        )

    anthropic_server.reply = reply
    agent = ClaudeCode(_config(anthropic_server, source_dir=source, tools=["Skill"]))
    agent.set_scope({"skill": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        path = directory / "skills/probe/SKILL.md"
        path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)
    saved = tmp_path / "candidate.json"
    candidate.save(saved)

    (trial,) = asyncio.run(
        agent.rollout([Task("trial", "question")], snapshot=Snapshot.load(saved))
    )
    assert trial.status == "finished", trial.error_message
    assert trial.output == "candidate"
    assert agent.snapshot is baseline
    assert "CANDIDATE_SKILL_MARKER" in _trace_text(trial)
    assert asyncio.run(agent.run("question")).output == "baseline"
    agent.update(candidate)
    assert asyncio.run(agent.run("question")).output == "candidate"
    assert "BASELINE_SKILL_MARKER" in skill.read_text()


def test_real_worker_edits_miniagent_using_its_own_plugin(anthropic_server, tmp_path):
    source = _copy_source(tmp_path)
    instructions = source / "CLAUDE.md"
    instructions.write_text("WORKER_INSTRUCTION_MARKER\n")
    _write_skill(source, "WORKER_SKILL_MARKER")
    worker = ClaudeCode(
        _config(anthropic_server, source_dir=source, tools=["Skill", "Read", "Write"])
    )
    worker_baseline = worker.snapshot
    target = MiniAgent({"llm": {"model_name": "unused"}})
    target.set_scope({"skill": "rw"})
    target_baseline = target.snapshot

    with target_baseline.check_out() as directory:
        target_skill = directory / "skills/main.md"
        # A task checkout may itself look like a Claude project. It must remain
        # editing data rather than replace this Worker's prompt and skills.
        (directory / "CLAUDE.md").write_text("TARGET_INSTRUCTION_MARKER")
        conflicting = directory / ".claude/skills/conflict/SKILL.md"
        conflicting.parent.mkdir(parents=True)
        conflicting.write_text(
            "---\nname: conflict\ndescription: TARGET_SKILL_MARKER\n---\n"
            "TARGET_SKILL_MARKER\n"
        )
        (directory / ".claude/settings.json").write_text(
            json.dumps({"env": {"ANTHROPIC_API_KEY": "target-unwanted-key"}})
        )

        def reply(request):
            body = request["body"]
            encoded = json.dumps(body)
            assert "WORKER_INSTRUCTION_MARKER" in encoded
            assert "TARGET_INSTRUCTION_MARKER" not in encoded
            assert "TARGET_SKILL_MARKER" not in encoded
            assert request["api_key"] == "local-claude-test-key"
            messages = json.dumps(body["messages"])
            if "WORKER_SKILL_MARKER" not in messages:
                tool = ("Skill", {"skill": "flashrsi:probe"})
            elif "Read" not in [
                block.get("name")
                for message in body["messages"]
                for block in message["content"]
                if isinstance(block, dict)
            ]:
                tool = ("Read", {"file_path": str(target_skill)})
            elif target_skill.read_text() != "updated skill\n":
                tool = (
                    "Write",
                    {"file_path": str(target_skill), "content": "updated skill\n"},
                )
            else:
                tool = None
            return _message_events(
                body,
                "edited",
                tool=tool,
                message_id=f"msg_{len(anthropic_server.requests)}",
            )

        anthropic_server.reply = reply
        trajectory = asyncio.run(
            worker.run("Improve skills/main.md", working_dir=directory)
        )
        assert trajectory.status == "finished", trajectory.error_message
        assert trajectory.output == "edited"
        assert target_skill.read_text() == "updated skill\n"
        # Remove this test's unrelated conflict files before committing the
        # MiniAgent checkout, whose manifest intentionally excludes them.
        (directory / "CLAUDE.md").unlink()
        shutil.rmtree(directory / ".claude")
        candidate = target_baseline.commit(directory)

    assert worker.snapshot is worker_baseline
    assert target.snapshot is target_baseline
    assert candidate.files["skills/main.md"].content == b"updated skill\n"
    assert len(anthropic_server.requests) == 4
    trace = _trace_text(trajectory)
    assert "ToolUseBlock" in trace and "ToolResultBlock" in trace
    assert "WORKER_SKILL_MARKER" in trace
    assert "target-unwanted-key" not in trace
    assert "TARGET_SKILL_MARKER" not in trace


def test_real_custom_subagent_uses_selected_snapshot_and_ignores_target_agents(
    anthropic_server, tmp_path
):
    source = _copy_source(tmp_path)
    definition = source / "agents/reviewer.md"
    definition.parent.mkdir(exist_ok=True)
    definition.write_text(
        "---\nname: reviewer\ndescription: Review supporting evidence.\n"
        "model: inherit\n---\nBASELINE_CUSTOM_AGENT_MARKER\n"
    )
    agent = ClaudeCode(
        _config(
            anthropic_server,
            source_dir=source,
            tools=["Agent"],
            allowed_tools=["Agent"],
        )
    )
    agent.set_scope({"agent": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        path = directory / "agents/reviewer.md"
        path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)

    def reply(request):
        body = request["body"]
        instructions = json.dumps(body.get("system"))
        messages = json.dumps(body["messages"])
        tool = None
        if "CUSTOM_AGENT_MARKER" in instructions:
            # The parent's first result must not terminate this native child.
            time.sleep(0.1)
            text = (
                "CANDIDATE_REVIEW_EVIDENCE"
                if "CANDIDATE_CUSTOM_AGENT_MARKER" in instructions
                else "BASELINE_REVIEW_EVIDENCE"
            )
        elif "CANDIDATE_REVIEW_EVIDENCE" in messages:
            text = "candidate reviewed"
        elif "BASELINE_REVIEW_EVIDENCE" in messages:
            text = "baseline reviewed"
        elif any(
            block.get("name") == "Agent"
            for message in body["messages"]
            for block in message["content"]
            if isinstance(block, dict)
        ):
            text = "Review delegated"
        else:
            text = ""
            tool = (
                "Agent",
                {
                    "subagent_type": "flashrsi:reviewer",
                    "description": "Review supporting evidence",
                    "prompt": "Collect native review evidence",
                    "run_in_background": True,
                },
            )
        return _message_events(
            body,
            text,
            tool=tool,
            message_id=f"msg_{len(anthropic_server.requests)}",
        )

    anthropic_server.reply = reply
    (trial,) = asyncio.run(
        agent.rollout([Task("trial", "Delegate review")], snapshot=candidate)
    )
    assert trial.status == "finished", trial.error_message
    assert trial.output == "candidate reviewed"
    assert agent.snapshot is baseline

    target = tmp_path / "target"
    conflict = target / ".claude/agents/reviewer.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text(
        "---\nname: reviewer\ndescription: TARGET_AGENT_MARKER\n---\n"
        "TARGET_AGENT_MARKER\n"
    )
    current = asyncio.run(agent.run("Delegate review", working_dir=target))
    assert current.status == "finished", current.error_message
    assert current.output == "baseline reviewed"
    assert "BASELINE_CUSTOM_AGENT_MARKER" in definition.read_text()
    assert "TARGET_AGENT_MARKER" not in json.dumps(anthropic_server.requests)

    for trajectory, evidence in (
        (trial, "CANDIDATE_REVIEW_EVIDENCE"),
        (current, "BASELINE_REVIEW_EVIDENCE"),
    ):
        parent_call = next(
            block
            for message in trajectory.messages
            if message["type"] == "AssistantMessage"
            for block in message["content"]
            if block["type"] == "ToolUseBlock" and block["name"] == "Agent"
        )
        assert any(
            message["type"] == "AssistantMessage"
            and message.get("parent_tool_use_id") == parent_call["id"]
            and any(
                block["type"] == "TextBlock" and block["text"] == evidence
                for block in message["content"]
            )
            for message in trajectory.messages
        )
