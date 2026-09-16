"""Run the selected MiniAgent source in an independent Python process."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from flashrsi.core import Agent, Trajectory

_ENTRY = Path(__file__).with_name("_entry.py")


class MiniAgent(Agent):
    """Pass inputs to the selected harness and map its result to a Trajectory."""

    name = "miniagent"
    description = "A workspace-driven ReAct harness with optional file editing."

    async def _run(self, prompt: str, working_dir: Path | None = None) -> Trajectory:
        config = self.config
        model = config["model_name"]
        timeout = config.get("timeout", 300)
        # Use the harness's existing environment interface in this child only.
        api_key = config.get("api_key") or ""
        base_url = config.get("base_url") or ""
        env = {
            **os.environ,
            "FLASHRSI_MINIAGENT_API_KEY": api_key,
            "FLASHRSI_MINIAGENT_MODEL": model,
            "FLASHRSI_MINIAGENT_SIDE_MODEL": model,
            "FLASHRSI_MINIAGENT_BASE_URL": base_url,
            "FLASHRSI_MINIAGENT_SIDE_BASE_URL": base_url,
            "FLASHRSI_MINIAGENT_MAX_TOKENS": str(config.get("max_tokens", 4096)),
            "FLASHRSI_MINIAGENT_LLM_MAX_RETRIES": str(config.get("llm_max_retries", 1)),
            "FLASHRSI_MINIAGENT_REASONING": config.get("reasoning_effort") or "",
            "FLASHRSI_MINIAGENT_EXTRA_BODY": json.dumps(
                config.get("extra_body") or {}, default=dict
            ),
        }
        # files_dir belongs to Agent; logs and the task cwd belong to this run.
        with TemporaryDirectory(prefix="flashrsi-miniagent-") as temporary:
            root = Path(temporary)
            task_dir = working_dir or root / "task"
            if working_dir is None:
                task_dir.mkdir()
            # These are the native run() arguments, passed unchanged by _entry.py.
            request = {
                "question": prompt,
                "model": model,
                "max_turns": config.get("max_turns", 10),
                "workspace_dir": str(self.files_dir),
                "runs_root": str(root / "runs"),
            }
            if working_dir is not None:
                request["working_dir"] = str(working_dir)
            secrets = _secrets(env)
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-B",
                str(_ENTRY),
                cwd=task_dir,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(json.dumps(request).encode()), timeout=timeout
                )
            except TimeoutError:
                return Trajectory(
                    status="error",
                    error_message=f"MiniAgent timed out after {timeout:g}s",
                )
            finally:
                # Also reap children spawned by native tools before files_dir is
                # cleaned. Cancellation propagates after this awaited cleanup.
                await _stop(process)
            if process.returncode:
                detail = _redact(stderr.decode(errors="replace"), secrets)
                return Trajectory(
                    status="error",
                    error_message=f"MiniAgent process exited with {process.returncode}: "
                    + detail[-4000:].strip(),
                )
            # Native messages and usage are preserved; only the status is mapped.
            result = _redact(json.loads(stdout), secrets)
            success = result["stop_reason"] == "completed"
            return Trajectory(
                status="finished" if success else "error",
                output=result["answer"] if success else "",
                messages=result.get("messages", []),
                usage={"model_calls": result["usage"], "turns": result["turns"]},
                error_message=None if success else result["stop_reason"],
            )


async def _stop(process):
    """Finish all work using files_dir before Agent removes that directory."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.returncode is None:
        process.kill()
    await process.wait()


def _secrets(env):
    values = [
        value
        for key, value in env.items()
        if key.upper().endswith(("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
    ]
    return sorted(filter(None, values), key=len, reverse=True)


def _redact(value, secrets):
    """Redact subprocess text and decoded JSON without changing their structure."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {
            _redact(key, secrets): _redact(item, secrets) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    return value
