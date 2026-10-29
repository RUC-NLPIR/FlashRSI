"""Awaitable Docker CLI calls with cancellation and process reaping."""

import asyncio
import subprocess


async def _docker(*args, timeout, check=True, binary=False):
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
    result = subprocess.CompletedProcess(
        args,
        process.returncode,
        stdout if binary else stdout.decode("utf-8"),
        stderr.decode("utf-8", errors="replace"),
    )
    if check and result.returncode:
        raise RuntimeError(
            f"Docker {args[0]} exited with {result.returncode}: {result.stderr[-4000:]}"
        )
    return result
