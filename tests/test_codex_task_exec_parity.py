"""Task-level comparison of the pinned native and Python interactive harnesses.

The same localhost Responses script drives both implementations. Session and
chunk identifiers are mapped by identity; prompts, schemas, arguments, output
bytes, exit status, token usage and task files remain in the comparison.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import sys

from test_codex_core_parity import (
    _events,
    _normalize,
    _responses_server,
)
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex

_SESSION = re.compile(r"Process running with session ID (\d+)")
_CHUNK = re.compile(r"(?m)^Chunk ID: (\S+)$")
_ANSWER = "Processed three values; total 16; report.json independently verified."
_WORKER = """import json
import pathlib
import sys

print("READY_FOR_INPUT", flush=True)
payload = json.loads(sys.stdin.readline())
print("INPUT_ACCEPTED", flush=True)
assert sys.stdin.readline() == "finish\\n", "expected explicit finish input"
report = {
    "label": payload["label"].upper(),
    "count": len(payload["values"]),
    "total": sum(payload["values"]),
}
pathlib.Path("report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\\n")
print("REPORT_WRITTEN", flush=True)
"""


def _outputs(body):
    return [
        item["output"]
        for item in body["input"]
        if item.get("type") == "function_call_output"
    ]


class _InteractiveScript(list):
    """Use the existing replay server while binding returned process handles."""

    def __init__(self, replay, task):
        self.replay = replay
        self.task = task
        self.session_id = None
        python = shlex.quote(sys.executable)
        self.start = {
            "cmd": python + " -u worker.py",
            "workdir": str(task),
            "shell": "/bin/sh",
            "login": False,
            "tty": True,
            "yield_time_ms": 250,
            "max_output_tokens": 2000,
        }
        verification = 'import json,pathlib; report=json.loads(pathlib.Path("report.json").read_text()); assert report=={"label":"BLUE","count":3,"total":16},report; print("VERIFIED label=BLUE count=3 total=16")'
        self.verify = {
            "cmd": python + " -c " + shlex.quote(verification),
            "workdir": str(task),
            "shell": "/bin/sh",
            "login": False,
            "yield_time_ms": 1000,
            "max_output_tokens": 2000,
        }
        super().__init__(
            [
                self._start,
                self._write,
                self._poll,
                self._release,
                self._verify,
                self._finish,
            ]
        )

    def pop(self, index=0):
        step = super().pop(index)
        return 200, step(self.replay.requests[-1]["body"])

    def _start(self, body):
        assert not _outputs(body)
        return _events(call=("exec_command", self.start), response_id="resp_start")

    def _write(self, body):
        output = _outputs(body)[-1]
        assert "READY_FOR_INPUT" in output, output
        match = _SESSION.search(output)
        assert match, output
        self.session_id = int(match.group(1))
        return _events(
            call=(
                "write_stdin",
                {
                    "session_id": self.session_id,
                    "chars": '{"label":"blue","values":[3,5,8]}\n',
                    "yield_time_ms": 250,
                    "max_output_tokens": 2000,
                },
            ),
            response_id="resp_write",
        )

    def _poll(self, body):
        output = _outputs(body)[-1]
        assert "INPUT_ACCEPTED" in output, output
        assert f"Process running with session ID {self.session_id}" in output
        return _events(
            call=(
                "write_stdin",
                {
                    "session_id": self.session_id,
                    "chars": "",
                    "yield_time_ms": 5000,
                    "max_output_tokens": 2000,
                },
            ),
            response_id="resp_poll",
        )

    def _release(self, body):
        output = _outputs(body)[-1]
        assert f"Process running with session ID {self.session_id}" in output, output
        assert "REPORT_WRITTEN" not in output
        assert not (self.task / "report.json").exists()
        return _events(
            call=(
                "write_stdin",
                {
                    "session_id": self.session_id,
                    "chars": "finish\n",
                    "yield_time_ms": 30000,
                    "max_output_tokens": 2000,
                },
            ),
            response_id="resp_release",
        )

    def _verify(self, body):
        output = _outputs(body)[-1]
        assert "REPORT_WRITTEN" in output and "Process exited with code 0" in output, (
            output
        )
        return _events(call=("exec_command", self.verify), response_id="resp_verify")

    def _finish(self, body):
        output = _outputs(body)[-1]
        assert "VERIFIED label=BLUE count=3 total=16" in output, output
        assert "Process exited with code 0" in output
        return _events(text=_ANSWER, response_id="resp_answer")


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


def test_exec_normalization_preserves_schema_and_handle_relationships(tmp_path):
    schema = {"type": "number", "description": "Identifier of the running process."}
    trace = {
        "tools": [{"parameters": {"properties": {"session_id": schema}}}],
        "output": "Chunk ID: abc123\nProcess running with session ID 12345\nOriginal token count: 17\nOutput:\nanswer=42",
        "arguments": json.dumps({"session_id": 12345, "chars": "input\n"}),
        "later": "Chunk ID: def456\nProcess running with session ID 54321\nOutput:\nerror=17",
    }
    result = _normalize_exec_trace(trace, tmp_path)
    assert result["tools"][0]["parameters"]["properties"]["session_id"] == schema
    assert "Process running with session ID <SESSION:0>" in result["output"]
    assert json.loads(result["arguments"])["session_id"] == "<SESSION:0>"
    assert "Process running with session ID <SESSION:1>" in result["later"]
    assert "Original token count: 17\nOutput:\nanswer=42" in result["output"]
    assert result["later"].endswith("Output:\nerror=17")


def test_interactive_exec_task_matches_pinned_native_end_to_end(
    parity_source, upstream_codex, tmp_path
):
    (parity_source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\nshell_snapshot=false\nunified_exec=true\n"
    )
    task = tmp_path / "interactive-task"
    task.mkdir()
    traces = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            for path in task.iterdir():
                path.unlink()
            (task / "worker.py").write_text(_WORKER)
            replay.reset([])
            replay.steps = _InteractiveScript(replay, task)
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
                    'Run worker.py interactively. Send {"label":"blue","values":[3,5,8]}, poll to confirm it is still waiting, then send finish to release the report and independently verify all report fields before answering.',
                    working_dir=task,
                )
            )
            assert not replay.errors, (replay.errors, result.error_message)
            assert not replay.steps, result.error_message
            assert len(replay.requests) == 6
            assert all(
                request["authorization"] == "Bearer local-parity-test-key"
                for request in replay.requests
            )
            assert result.status == "finished" and result.output == _ANSWER, (
                result.error_message
            )
            assert result.usage["prompt_tokens"] == 120
            assert result.usage["completion_tokens"] == 18
            assert len(_outputs(replay.requests[-1]["body"])) == 5
            files = {
                str(path.relative_to(task)): path.read_text()
                for path in sorted(task.rglob("*"))
                if path.is_file()
            }
            assert json.loads(files["report.json"]) == {
                "label": "BLUE",
                "count": 3,
                "total": 16,
            }
            traces.append(
                _normalize_exec_trace(
                    {
                        "requests": replay.requests,
                        "tool_outputs": _outputs(replay.requests[-1]["body"]),
                        "status": result.status,
                        "output": result.output,
                        "usage": dict(result.usage),
                        "files": files,
                    },
                    tmp_path,
                )
            )
    paths = [
        tmp_path / "interactive-upstream.json",
        tmp_path / "interactive-python.json",
    ]
    for path, trace in zip(paths, traces, strict=True):
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True))
    assert traces[0] == traces[1], f"Full normalized task traces: {paths}"
