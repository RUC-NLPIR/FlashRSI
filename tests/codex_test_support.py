"""Shared local replay helpers for Python Codex tests.

The production adapter is Python-only. This module contains deterministic HTTP
replay and snapshot helpers retained for tests that historically used parity
fixtures; it does not invoke or depend on a native executable.
"""

from __future__ import annotations

import gzip
import inspect
import json
import re
import shutil
import threading
import time as _time
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from flashrsi.agents import Codex

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)
_RUN_HOME = re.compile(r"/[^\s<>\"'\\]*/flashrsi-codex-[^/\s<>\"'\\]+")
_ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def _normalize(value, temporary_root):
    identities = {}

    def identity(match):
        key = match.group(0)
        return identities.setdefault(key, f"<UUID:{len(identities)}>")

    def clean(item):
        if isinstance(item, str):
            item = item.replace(str(temporary_root), "<TMP>")
            item = _RUN_HOME.sub("<RUNTIME_HOME>", item)
            item = _ISO_TIME.sub("<TIME>", item)
            return _UUID.sub(identity, item)
        if isinstance(item, list):
            return [clean(v) for v in item]
        if isinstance(item, dict):
            return {k: clean(v) for k, v in item.items()}
        return item

    return clean(value)


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
        self.auto = False

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
                if replay.steps:
                    status, content = replay.steps.pop(0)
                elif replay.auto:
                    status, content = (
                        200,
                        _events(response_id=f"resp_{len(replay.requests)}"),
                    )
                else:
                    raise AssertionError("Codex sent an unscripted model request")
                self.send(
                    status,
                    "text/event-stream" if status == 200 else "application/json",
                    content,
                )
            except Exception as error:
                replay.errors.append(error)
                self.send(400, "application/json", b'{"error":"replay failed"}')

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
    """Compatibility fixture; native execution was removed."""
    return None


@pytest.fixture
def parity_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG", "1")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    source = tmp_path / "source"
    shutil.copytree(
        Path(inspect.getfile(Codex)).parent,
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "target", ".git"),
    )
    (source / "config.toml").write_text(
        "[features]\nplugins = false\nremote_plugin = false\nunified_exec = false\n"
    )
    (source / "AGENTS.md").write_text("PYTHON_VERSIONED_INSTRUCTIONS\n")
    skill = source / "skills/parity/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: parity\ndescription: PYTHON_VERSIONED_SKILL\n---\n"
        "Use the supplied replay evidence.\n"
    )
    return source


# Legacy adapter helpers used by Python resource tests.


def _source(tmp_path):
    # pytest's ``tmp_path`` already exists; stage a fresh Snapshot below it.
    source = Path(tmp_path) / "source"
    shutil.copytree(
        Path(inspect.getfile(Codex)).parent,
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "target", ".git"),
    )
    (source / "config.toml").write_text(
        "[features]\nplugins = false\nremote_plugin = false\nunified_exec = false\n"
    )
    return source


def _config(server, binary=None, **overrides):
    config = {
        "llm": {
            "model_name": "gpt-5",
            "api_key": "local-codex-test-key",
            "base_url": server.base_url,
        },
        "source_dir": server.source_dir,
        "timeout": 30,
        **overrides,
    }
    return config


def _shell_call(body, command):
    names = {tool.get("name") for tool in body.get("tools", [])}
    if "exec_command" in names:
        return "exec_command", {"cmd": command, "yield_time_ms": 1000}
    if "shell_command" in names:
        return "shell_command", {"command": command}
    if "shell" in names:
        return "shell", {"command": ["sh", "-c", command]}
    raise AssertionError(f"Python shell tool missing: {names}")


# Interactive shell replay helpers used by Python-only task tests.
_SESSION = re.compile(r"Process running with session ID (\d+)")
_CHUNK = re.compile(r"(?m)^Chunk ID: (\S+)$")


def _normalize_exec_trace(value, temporary_root):
    sessions, chunks = {}, {}

    def session(value):
        return sessions.setdefault(str(value), f"<SESSION:{len(sessions)}>")

    def visit(item):
        if isinstance(item, dict):
            return {
                key: session(value)
                if key == "session_id" and type(value) is int
                else visit(value)
                for key, value in item.items()
            }
        if isinstance(item, list):
            return [visit(value) for value in item]
        if not isinstance(item, str):
            return item
        try:
            arguments = json.loads(item)
        except (ValueError, TypeError):
            arguments = None
        if isinstance(arguments, dict) and "session_id" in arguments:
            item = json.dumps(visit(arguments))
        item = _SESSION.sub(
            lambda match: "Process running with session ID " + session(match.group(1)),
            item,
        )
        return _CHUNK.sub(
            lambda match: (
                "Chunk ID: "
                + chunks.setdefault(match.group(1), f"<CHUNK:{len(chunks)}>")
            ),
            item,
        )

    return _normalize(visit(value), temporary_root)


class _SnapshotScript(list):
    def __init__(self, task, mode):
        self.task = task
        command = "printf 'snapshot-value=%s\\n' \"$RSI_SNAPSHOT_VALUE\""
        args = {"cmd" if mode in {"unified", "model-bash"} else "command": command}
        if mode == "model-bash":
            args["shell"] = "/bin/bash"
        if mode == "no-login":
            args["login"] = False
        if mode == "other-cwd":
            args["workdir"] = str(task / "other")
        if mode == "normalized-cwd":
            args["workdir"] = "does-not-exist/.."
        super().__init__(
            [
                (
                    200,
                    _events(
                        call=(
                            "exec_command"
                            if mode in {"unified", "model-bash"}
                            else "shell_command",
                            args,
                        )
                    ),
                ),
                (200, _events(text="SNAPSHOT_RESTORED")),
            ]
        )
        self.first = True

    def pop(self, index=0):
        if self.first:
            self.first = False
            marker = self.task / "snapshot-home"
            deadline = _time.monotonic() + 12
            while _time.monotonic() < deadline:
                try:
                    home = Path(marker.read_text())
                    ready = home.is_dir() and any(
                        (home / "shell_snapshots").glob("*.sh")
                    )
                except OSError:
                    ready = False
                if ready:
                    break
                _time.sleep(0.01)
            else:
                raise AssertionError("background shell snapshot did not finish")
        return super().pop(index)


@pytest.fixture
def responses_server(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG", "1")
    source = _source(tmp_path / "python-default")
    with _responses_server() as replay:
        replay.source_dir = source
        replay.auto = True
        yield replay
