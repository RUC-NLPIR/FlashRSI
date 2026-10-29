"""Replay identical local model responses through upstream Codex and its core.

The comparison keeps complete model instructions, tool schemas and conversation
history. Only timestamps, UUIDs and absolute temporary paths are normalized.
Passing these cases establishes parity for these traces, not all Codex behavior.
"""

from __future__ import annotations

import asyncio
import gzip
import importlib.metadata
import inspect
import json
import re
import shutil
import threading
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from flashrsi.agents import Codex

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_RUN_HOME = re.compile(r"/[^\s<>\"'\\]*/flashrsi-codex-[^/\s<>\"'\\]+")
_ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def _normalize(value, temporary_root):
    identities = {}

    def identity(match):
        key = match.group(0)
        return identities.setdefault(key, f"<UUID:{len(identities)}>")

    def visit(item):
        if isinstance(item, dict):
            return {
                key: "<TIME>" if key == "turn_started_at_unix_ms" else visit(value)
                for key, value in sorted(item.items())
            }
        if isinstance(item, list):
            return [visit(value) for value in item]
        if not isinstance(item, str):
            return item
        item = item.replace(str(temporary_root.resolve()), "<FIXTURE>")
        item = _RUN_HOME.sub("<RUN>", item)
        item = _UUID.sub(identity, item)
        item = _ISO_TIME.sub("<TIME>", item)
        item = re.sub(r'("turn_started_at_unix_ms"\s*:\s*)\d+', r'\1"<TIME>"', item)
        return re.sub(r"(Wall time:? )\d+(?:\.\d+)?( seconds)", r"\1<TIME>\2", item)

    return visit(value)


def _events(text="PARITY_ANSWER", *, call=None, response_id="resp_answer"):
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


class _Replay:
    def __init__(self):
        self.requests = []
        self.errors = []
        self.steps = []

    def reset(self, steps):
        self.requests.clear()
        self.errors.clear()
        self.steps = list(steps)


@contextmanager
def _responses_server():
    replay = _Replay()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send(404, "application/json", b"{}")

        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                if self.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                replay.requests.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "body": json.loads(raw),
                    }
                )
                assert self.path == "/v1/responses"
                assert replay.steps, "Codex sent an unscripted model request"
                status, content = replay.steps.pop(0)
                self.send(
                    status,
                    "text/event-stream" if status == 200 else "application/json",
                    content,
                )
            except Exception as error:
                replay.errors.append(error)
                self.send(400, "application/json", b'{"error":"parity replay failed"}')

        def send(self, status, content_type, content):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Retry-After", "0")
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
    replay.base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield replay
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def upstream_codex():
    package = pytest.importorskip("codex_cli_bin")
    assert importlib.metadata.version("openai-codex-cli-bin") == "0.147.0"
    return str(package.bundled_codex_path())


@pytest.fixture
def parity_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG", "1")
    # Keep optional catalog traffic offline while model traffic stays local.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    source = tmp_path / "source"
    shutil.copytree(
        Path(inspect.getfile(Codex)).parent,
        source,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "target", ".git", "runtime"
        ),
    )
    (source / "config.toml").write_text(
        "[features]\nplugins = false\nremote_plugin = false\nunified_exec = false\n"
    )
    (source / "AGENTS.md").write_text("PARITY_VERSIONED_INSTRUCTIONS\n")
    skill = source / "skills/parity/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: parity\ndescription: PARITY_VERSIONED_SKILL\n---\n"
        "Use the supplied replay evidence.\n"
    )
    return source


def _script(case):
    answer = (200, _events())
    if case == "answer":
        return [answer]
    if case in {"tool_success", "tool_failure"}:
        command = "printf 'PARITY_TOOL_OUTPUT\\n'"
        if case == "tool_failure":
            command = "printf 'PARITY_TOOL_ERROR\\n' >&2; exit 17"
        call = ("shell_command", {"command": command})
        return [(200, _events(call=call, response_id="resp_tool")), answer]
    if case == "unknown_tool":
        call = ("missing_parity_tool", {"probe": "PARITY_UNKNOWN_TOOL"})
        return [(200, _events(call=call, response_id="resp_tool")), answer]
    if case == "http_retry":
        error = b'{"error":{"type":"server_error","message":"PARITY_RETRY"}}'
        return [(503, error), answer]
    assert case == "http_failure"
    error = b'{"error":{"type":"invalid_request_error","message":"PARITY_REQUEST_REJECTED"}}'
    return [(400, error)]


@pytest.mark.parametrize(
    "case",
    [
        "answer",
        "tool_success",
        "tool_failure",
        "unknown_tool",
        "http_retry",
        "http_failure",
    ],
)
def test_extracted_core_matches_upstream_requests_and_results(
    case, parity_source, upstream_codex, tmp_path
):
    task = tmp_path / "task"
    task.mkdir()
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset(_script(case))
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "timeout": 60,
                "sandbox": "danger-full-access",
            }
            if binary is not None:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Follow the scripted parity responses.", working_dir=task
                )
            )
            assert not replay.errors
            assert not replay.steps, (
                result.error_message or "Codex failed to consume the response script"
            )
            assert replay.requests
            assert all(
                request["authorization"] == "Bearer local-parity-test-key"
                for request in replay.requests
            )
            body = json.dumps(replay.requests[0]["body"])
            assert "PARITY_VERSIONED_INSTRUCTIONS" in body
            assert "PARITY_VERSIONED_SKILL" in body
            if case == "http_failure":
                assert result.status == "error", result.error_message
                assert "PARITY_REQUEST_REJECTED" in result.error_message
            else:
                assert result.status == "finished", result.error_message
                assert result.output == "PARITY_ANSWER"
                calls = 2 if case.startswith("tool_") or case == "unknown_tool" else 1
                assert result.usage["prompt_tokens"] == 20 * calls
                assert result.usage["completion_tokens"] == 3 * calls
                assert (
                    result.usage["prompt_tokens_details"]["cached_tokens"] == 5 * calls
                )
            observed.append(
                _normalize(
                    {
                        "requests": replay.requests,
                        "status": result.status,
                        "output": result.output,
                        "usage": dict(result.usage),
                    },
                    tmp_path,
                )
            )
    traces = [tmp_path / "upstream-trace.json", tmp_path / "core-trace.json"]
    for path, trace in zip(traces, observed, strict=True):
        path.write_text(json.dumps(trace, indent=2, sort_keys=True))
    assert observed[0] == observed[1], f"Normalized traces: {traces}"


def test_parity_normalization_preserves_identity_and_semantic_differences(tmp_path):
    first = "00000000-0000-0000-0000-000000000001"
    second = "00000000-0000-0000-0000-000000000002"
    result = _normalize(
        {
            "ids": [first, second, first],
            "text": "Exit code: 17\nWall time: 0.02 seconds\nOutput:\nproof",
            "path": str(tmp_path / "selected/SKILL.md"),
            "turn_started_at_unix_ms": 12345,
        },
        tmp_path,
    )
    assert result["ids"] == ["<UUID:0>", "<UUID:1>", "<UUID:0>"]
    assert result["text"] == "Exit code: 17\nWall time: <TIME> seconds\nOutput:\nproof"
    assert result["path"] == "<FIXTURE>/selected/SKILL.md"
    assert result["turn_started_at_unix_ms"] == "<TIME>"
    assert _normalize(
        "Script completed\nWall time 2.3 seconds\nOutput:\n42", tmp_path
    ) == ("Script completed\nWall time <TIME> seconds\nOutput:\n42")
    assert _normalize({"exit_code": 17}, tmp_path) != _normalize(
        {"exit_code": 0}, tmp_path
    )
    assert _normalize({"instructions": "first"}, tmp_path) != _normalize(
        {"instructions": "second"}, tmp_path
    )
