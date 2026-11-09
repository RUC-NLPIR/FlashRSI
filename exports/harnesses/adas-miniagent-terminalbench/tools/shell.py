"""A bounded shell call in the native MiniAgent's task environment.

The implementation stays deliberately low-level: it never opens /dev/null
(some sandboxes deny that path), and it reads only output that is already
available instead of waiting for EOF from background services that inherited
stdout. The command's own process group is killed only on timeout.
"""

import asyncio
import json
import math
import os
import select
import signal
import subprocess
import time
from pathlib import Path

_OUTPUT_LIMIT = 32 * 1024


def _read_some(fd: int, output: bytearray) -> tuple[bool, bool]:
    """Read one available chunk into `output`. Returns (got_data, truncated)."""
    truncated = False
    try:
        chunk = os.read(fd, 64 * 1024)
    except BlockingIOError:
        return False, truncated
    if not chunk:
        return False, truncated
    remaining = _OUTPUT_LIMIT - len(output)
    output.extend(chunk[:remaining])
    truncated = len(chunk) > remaining
    return True, truncated


def _run(command: str, directory: Path, timeout: float) -> dict:
    process = subprocess.Popen(
        ["/bin/sh", "-c", command],
        cwd=str(directory),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        bufsize=0,
    )

    # Give the child a clean EOF on stdin without touching /dev/null.
    if process.stdin is not None:
        try:
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError, RuntimeError, OSError):
            pass

    stdout = process.stdout
    fd = stdout.fileno()
    os.set_blocking(fd, False)

    output = bytearray()
    truncated = False
    timed_out = False
    deadline = time.monotonic() + timeout

    def kill_group() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def drain(max_wait: float) -> None:
        """Collect bytes already buffered; never block until EOF from a child."""
        nonlocal truncated
        end = time.monotonic() + max_wait
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            try:
                readable, _, _ = select.select([fd], [], [], min(remaining, 0.05))
            except (InterruptedError, ValueError):
                break
            if fd not in readable:
                break
            got_data, was_truncated = _read_some(fd, output)
            truncated = truncated or was_truncated
            if not got_data:
                break

    try:
        while True:
            if process.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                readable, _, _ = select.select([fd], [], [], min(remaining, 0.2))
            except InterruptedError:
                continue
            except ValueError:
                break
            if fd in readable:
                _, was_truncated = _read_some(fd, output)
                truncated = truncated or was_truncated

        if timed_out:
            kill_group()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            kill_group()
            process.wait()

        drain(0.2)
    finally:
        try:
            stdout.close()
        except (OSError, ValueError):
            pass

    return {
        "exit_code": process.returncode,
        "output": output.decode("utf-8", errors="replace"),
        "timed_out": timed_out,
        "truncated": truncated,
    }


async def call(args, ctx) -> str:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    timeout = args.get("timeout", 60)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    cwd = args.get("cwd", ".")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("cwd must be a non-empty path")

    working_dir = getattr(ctx, "working_dir", None)
    base = Path(working_dir) if working_dir is not None else Path.cwd()
    directory = (base / Path(cwd)).resolve(strict=True)

    result = await asyncio.to_thread(_run, command, directory, float(timeout))
    return json.dumps(result, ensure_ascii=False)
