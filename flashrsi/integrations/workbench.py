"""Expose native WorkBench tools to either harness and score on the host."""

import ast
import asyncio
import hashlib
import importlib.util
import json
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory

from flashrsi._records import _redact
from flashrsi.benchmarks.workbench import DATABASE_FILES, REVISION


class _Session:
    """One child process owns one native thread-local database for one task."""

    def __init__(self, upstream, data, directory):
        for name in DATABASE_FILES:
            destination = directory / "data" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(data / name, destination)
        names = {"PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "TMP", "TEMP"}
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-X",
                "utf8",
                str(Path(__file__).with_name("_workbench_process.py")),
            ],
            cwd=directory,
            env={k: v for k, v in os.environ.items() if k.upper() in names},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        self.responses = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.description = self.request({"upstream": str(upstream)})["tools"]
        except BaseException:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            self.responses.put(line)
        self.responses.put(None)

    def request(self, value):
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()
        try:
            line = self.responses.get(timeout=120)
        except queue.Empty:
            self.process.kill()
            raise RuntimeError("WorkBench native tool/scorer timed out") from None
        if line is None:
            raise RuntimeError("WorkBench native tool/scorer process stopped")
        return json.loads(line)

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()


def _serve(session, token, records):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if (
                self.path != "/"
                or self.headers.get("Authorization") != "Bearer " + token
            ):
                self.send_error(403)
                return
            value = {}
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 65536:
                    raise ValueError("Invalid WorkBench request size")
                value = json.loads(self.rfile.read(size))
                # The target can only call tools. Grading is never a bridge API.
                result = session.request(
                    {
                        "operation": "call",
                        "name": value["name"],
                        "arguments": value["arguments"],
                    }
                )
            except Exception as exc:
                result = {"error": f"WorkBench tool failed ({type(exc).__name__})"}
            records.append(
                {"type": "WorkBenchTool", "request": value, "response": result}
            )
            body = json.dumps(result, ensure_ascii=True).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    # Upstream state is thread-local: requests must stay on this server thread,
    # and the native state itself always stays on the child process's main thread.
    return HTTPServer(("127.0.0.1", 0), Handler)


def bind(agent, benchmark):
    if sys.version_info < (3, 12):
        raise ValueError("Pinned WorkBench requires Python >=3.12")
    if any(importlib.util.find_spec(m) is None for m in ("pandas", "numpy")):
        raise ValueError("Install flashrsi-lite[workbench]")
    if (
        agent.name == "miniagent"
        and os.name != "posix"
        and not agent.config.get("source_dir")
    ):
        raise ValueError(
            "WorkBench with bundled MiniAgent requires POSIX; use Claude Code or a compatible source_dir"
        )
    if (
        agent.name == "claude_code"
        and agent.config.get("permission_mode") != "bypassPermissions"
        and not any(
            t == "Bash" or t.startswith("Bash(")
            for t in agent.config.get("allowed_tools", ["Read", "Glob", "Grep"])
        )
    ):
        raise ValueError("WorkBench requires Claude Code allowed_tools to include Bash")

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("WorkBench requires a loaded benchmark Task")
        if any(
            hashlib.sha256((benchmark._data_root / name).read_bytes()).hexdigest()
            != benchmark._file_checksums[name]
            for name in DATABASE_FILES
        ):
            raise ValueError("WorkBench native database changed after load")
        token, records = token_urlsafe(32), []
        with (
            TemporaryDirectory(prefix="flashrsi-workbench-host-") as host,
            TemporaryDirectory(prefix="flashrsi-workbench-task-") as work,
        ):
            session = await asyncio.to_thread(
                _Session, benchmark._upstream_root, benchmark._data_root, Path(host)
            )
            server = _serve(session, token, records)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            result = None
            scores = {}
            try:
                client = Path(work) / "workbench.py"
                shutil.copyfile(
                    Path(__file__).with_name("_workbench_client.py"), client
                )
                command = shlex.join(
                    [
                        Path(sys.executable).as_posix(),
                        "-X",
                        "utf8",
                        client.as_posix(),
                        "--bridge",
                        f"http://127.0.0.1:{server.server_port}/",
                        "--token",
                        token,
                    ]
                )
                prompt = (
                    "Today's date is Thursday, 2023-11-30 and the current time is 00:00:00.\n"
                    + task.question
                    + "\n\nWorkBench tools (use your shell tool):\n"
                    + command
                    + " TOOL_NAME 'JSON_OBJECT_OF_STRING_KEYWORD_ARGUMENTS'\n\n"
                    + session.description
                )
                result = await target.run(prompt, working_dir=Path(work))
            finally:
                await asyncio.to_thread(server.shutdown)
                server.server_close()
                thread.join(timeout=2)
                # No target requests can race the final host-only scorer.
                try:
                    if result is not None and result.status == "finished":
                        try:
                            scores = await asyncio.to_thread(
                                session.request,
                                {
                                    "operation": "grade",
                                    "reference": ast.literal_eval(
                                        benchmark._rows_by_id[task.task_id]["outcome"]
                                    ),
                                },
                            )
                        except Exception as exc:
                            scores = {
                                "error": f"Native scorer failed ({type(exc).__name__})"
                            }
                finally:
                    session.close()
            messages = tuple(
                m
                for m in result.messages
                if m.get("type") not in ("WorkBenchVerifier", "WorkBenchTool")
            ) + tuple(records)
            if result.status == "finished":
                if "error" in scores:
                    result = replace(
                        result,
                        status="error",
                        error_message="WorkBench native scoring failed: "
                        + scores["error"],
                    )
                else:
                    messages += (
                        {
                            "type": "WorkBenchVerifier",
                            "task_id": task.task_id,
                            "task_checksum": task.metadata["task_checksum"],
                            "data_checksum": benchmark._data_checksum,
                            "snapshot_id": target.snapshot.id,
                            "revision": REVISION,
                            "ground_truth_version": "v2",
                            "actions": scores["actions"],
                            "metrics": scores["metrics"],
                        },
                    )
            return replace(
                result,
                messages=_redact(messages, [token]),
                output=_redact(result.output, [token]),
                usage=_redact(result.usage, [token]),
                error_message=_redact(result.error_message, [token]),
            )

    agent._env_runner = run
