"""Bridge shell-capable agents to isolated ALFWorld text sessions."""

import asyncio
import hashlib
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
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory

from flashrsi._records import _redact
from flashrsi.benchmarks.alfworld import TEXTWORLD_VERSION, VERSION


class _Session:
    def __init__(self, setup, directory):
        names = {"PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "HOME"}
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-X",
                "utf8",
                str(Path(__file__).with_name("_alfworld_process.py")),
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
        self.error = None
        try:
            self.initial = self.request(setup)
        except BaseException:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            self.responses.put(line)
        self.responses.put(None)

    def request(self, value):
        try:
            self.process.stdin.write(json.dumps(value) + "\n")
            self.process.stdin.flush()
            line = self.responses.get(timeout=120)
            if line is None:
                raise RuntimeError("Native process stopped")
            return json.loads(line)
        except Exception as exc:
            self.error = f"ALFWorld process failed ({type(exc).__name__})"
            raise RuntimeError(self.error) from None

    def close(self):
        # EOF lets the child close the native environment before exiting.
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdout.close()


def _serve(session, token, records):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(120)
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 65536:
                    raise ValueError("Invalid request size")
                # Drain bounded request bodies before closing rejected requests;
                # unread bytes can reset the connection before the 403 arrives.
                body = self.rfile.read(size)
            except (ValueError, OSError):
                self.send_error(400)
                return
            if (
                self.path != "/"
                or self.headers.get("Authorization") != "Bearer " + token
            ):
                self.send_error(403)
                return
            action = None
            try:
                value = json.loads(body)
                # The target cannot reset, grade, or select a different game.
                if not isinstance(value, dict) or set(value) != {"action"}:
                    raise ValueError("Only action is accepted")
                action = value["action"]
                result = session.request({"operation": "step", "action": action})
            except Exception as exc:
                result = {"error": f"ALFWorld action failed ({type(exc).__name__})"}
            records.append(
                {"type": "ALFWorldStep", "action": action, "response": result}
            )
            body = json.dumps(result, ensure_ascii=True).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return HTTPServer(("127.0.0.1", 0), Handler)


def _check_runtime():
    if os.name != "posix" or not (3, 11) <= sys.version_info < (3, 13):
        raise ValueError(
            "ALFWorld text requires Linux/WSL/macOS with Python 3.11 or 3.12"
        )
    for package, required in (("alfworld", VERSION), ("textworld", TEXTWORLD_VERSION)):
        try:
            installed = version(package)
        except PackageNotFoundError:
            installed = None
        if installed != required:
            raise ValueError(
                f"Install flashrsi-lite[alfworld]: requires {package}=={required}"
            )


def bind(agent, benchmark):
    _check_runtime()
    if (
        agent.name == "claude_code"
        and agent.config.get("permission_mode") != "bypassPermissions"
        and not any(
            t == "Bash" or t.startswith("Bash(")
            for t in agent.config.get("allowed_tools", ["Read", "Glob", "Grep"])
        )
    ):
        raise ValueError("ALFWorld requires Claude Code allowed_tools to include Bash")

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("ALFWorld requires a loaded benchmark Task")
        game, checksum = benchmark._games[task.task_id]
        game_bytes = game.read_bytes()
        if hashlib.sha256(game_bytes).hexdigest() != checksum:
            raise ValueError("ALFWorld native game changed after load")
        token, records = token_urlsafe(32), []
        with (
            TemporaryDirectory(prefix="flashrsi-alfworld-host-") as host,
            TemporaryDirectory(prefix="flashrsi-alfworld-task-") as work,
        ):
            gamefile = Path(host) / "game.tw-pddl"
            gamefile.write_bytes(game_bytes)
            setup = {
                "gamefile": str(gamefile),
                "max_steps": benchmark.max_steps,
                "seed": benchmark.config.get("seed", 0),
                "admissible_commands": benchmark.admissible_commands,
            }
            session = await asyncio.to_thread(_Session, setup, host)
            server = None
            result, score = None, {}
            try:
                server = _serve(session, token, records)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                client = Path(work) / "alfworld.py"
                shutil.copyfile(Path(__file__).with_name("_alfworld_client.py"), client)
                command = shlex.join(
                    [
                        Path(sys.executable).as_posix(),
                        "-X",
                        "utf8",
                        client.as_posix(),
                        "--bridge",
                        f"http://127.0.0.1:{server.server_port}/",
                        "--token=" + token,
                    ]
                )
                prompt = (
                    task.question
                    + "\n\nInitial environment observation:\n"
                    + json.dumps(session.initial, ensure_ascii=False)
                    + "\n\nUse your shell tool to submit one environment action:\n"
                    + command
                    + " 'ACTION'\n"
                    + f"At most {benchmark.max_steps} environment steps. "
                    "Use the native text commands (e.g. look, inventory, help). "
                    "Stop when done is true. Your final text does not change the environment."
                )
                result = await target.run(prompt, working_dir=Path(work))
            finally:
                if server is not None:
                    await asyncio.to_thread(server.shutdown)
                    server.server_close()
                    thread.join(timeout=2)
                try:
                    if result is not None and result.status == "finished":
                        if session.error:
                            score = {"error": session.error}
                        else:
                            try:
                                score = await asyncio.to_thread(
                                    session.request, {"operation": "grade"}
                                )
                            except RuntimeError as exc:
                                score = {"error": str(exc)}
                finally:
                    session.close()
            messages = tuple(
                m
                for m in result.messages
                if m.get("type") not in ("ALFWorldVerifier", "ALFWorldStep")
            ) + tuple(records)
            if result.status == "finished":
                if "error" in score:
                    result = replace(
                        result, status="error", error_message=score["error"]
                    )
                else:
                    messages += (
                        {
                            "type": "ALFWorldVerifier",
                            "task_id": task.task_id,
                            "task_checksum": task.metadata["task_checksum"],
                            "game_sha256": checksum,
                            "version": VERSION,
                            "textworld_version": TEXTWORLD_VERSION,
                            "max_steps": benchmark.max_steps,
                            "seed": setup["seed"],
                            "admissible_commands": benchmark.admissible_commands,
                            **score,
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
