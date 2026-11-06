"""Expose only native text actions; the isolated target cannot access goals or reset."""

import asyncio
import json
import os
import queue
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from flashrsi.benchmarks.webshop import GOAL_ORDER_SHA256, REVISION
from flashrsi.integrations import _model_egress, _web_tools


class _Session:
    def __init__(self, python, setup, directory):
        names = {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "PATHEXT",
            "TMP",
            "TEMP",
            "HOME",
            "JAVA_HOME",
        }
        self.process = subprocess.Popen(
            [
                str(python),
                "-I",
                "-B",
                "-X",
                "utf8",
                str(Path(__file__).with_name("_webshop_process.py")),
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
            self.initial = self.request(setup, timeout=600)
            if "error" in self.initial:
                raise RuntimeError(self.initial["error"])
        except BaseException:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            self.responses.put(line)
        self.responses.put(None)

    def request(self, value, *, timeout=120):
        try:
            self.process.stdin.write(json.dumps(value) + "\n")
            self.process.stdin.flush()
            line = self.responses.get(timeout=timeout)
            if line is None:
                raise RuntimeError("Native process stopped")
            return json.loads(line)
        except Exception as exc:
            self.error = f"WebShop native process failed ({type(exc).__name__}); check native_python dependencies, full catalog and goal order"
            raise RuntimeError(self.error) from None

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()


def bind(agent, benchmark):
    _web_tools._check_target(agent, "WebShop")
    _model_egress._origins(agent.config)
    if not benchmark.native_python.is_file():
        raise ValueError(
            "WebShop native_python must point to the prepared upstream Python executable"
        )

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("WebShop requires a loaded benchmark Task")
        setup = {
            "native_root": str(benchmark.native_root),
            "goal_index": task.metadata["goal_index"],
            "goal_order_sha256": GOAL_ORDER_SHA256,
            "max_steps": benchmark.max_steps,
            "seed": benchmark.seed,
        }
        records = []
        with TemporaryDirectory(prefix="flashrsi-webshop-host-") as host:
            opening = asyncio.create_task(
                asyncio.to_thread(_Session, benchmark.native_python, setup, host)
            )
            try:
                session = await asyncio.shield(opening)
            except asyncio.CancelledError:
                try:
                    (await opening).close()
                finally:
                    raise

            def respond(raw):
                action = None
                try:
                    value = json.loads(raw)
                    if (
                        not isinstance(value, dict)
                        or set(value) != {"action"}
                        or not isinstance(value["action"], str)
                    ):
                        raise ValueError("Only action is accepted")
                    action = value["action"]
                    response = session.request({"operation": "step", "action": action})
                except Exception as exc:
                    response = {
                        "error": f"WebShop action failed ({type(exc).__name__})"
                    }
                records.append(
                    {"type": "WebShopStep", "action": action, "response": response}
                )
                return response

            try:
                prompt = (
                    task.question
                    + "\n\nInitial environment observation:\n"
                    + json.dumps(session.initial["public"], ensure_ascii=False)
                    + "\n\nUse your shell tool to submit one native action:\n"
                    + _web_tools._command(130)
                    + " step 'search[YOUR QUERY]'\n"
                    + "or replace the action with 'click[VISIBLE CLICKABLE]'. "
                    + f"At most {benchmark.max_steps} actions. Stop when done is true. "
                    + "Only environment actions affect the purchase; final answer text is not scored."
                )
                result = await _web_tools._run_with_relay(
                    target, prompt, respond, model_only=True
                )
                score = None
                if result.status == "finished":
                    score = (
                        {"error": session.error}
                        if session.error
                        else await asyncio.to_thread(
                            session.request, {"operation": "grade"}
                        )
                    )
            finally:
                session.close()
            messages = tuple(
                m
                for m in result.messages
                if m.get("type") not in ("WebShopVerifier", "WebShopStep")
            ) + tuple(records)
            if score is not None:
                if "error" in score:
                    result = replace(
                        result, status="error", error_message=score["error"]
                    )
                else:
                    messages += (
                        {
                            "type": "WebShopVerifier",
                            "task_id": task.task_id,
                            "task_checksum": task.metadata["task_checksum"],
                            "revision": REVISION,
                            "seed": benchmark.seed,
                            "max_steps": benchmark.max_steps,
                            **score,
                        },
                    )
            return replace(result, messages=messages)

    agent._env_runner = run
