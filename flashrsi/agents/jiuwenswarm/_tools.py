"""Expose tools from the selected Snapshot through the native Process SDK."""

import asyncio
import json
import os
import signal
from pathlib import Path


def load_tools(root: Path):
    definitions = []
    scripts = {}
    for directory in sorted(root.glob("*/")):
        manifest = directory / "tool.json"
        script = directory / "run.py"
        if not manifest.is_file() or not script.is_file():
            raise ValueError(f"tools/{directory.name} requires tool.json and run.py")
        definition = json.loads(manifest.read_text(encoding="utf-8"))
        if definition.get("name") != directory.name:
            raise ValueError(f"{manifest.name} name must match tools/{directory.name}")
        definitions.append(definition)
        scripts[directory.name] = script
    return definitions, scripts


async def run_tool(script, arguments, *, python, cwd, env):
    process = await asyncio.create_subprocess_exec(
        python,
        "-I",
        "-B",
        "-Xutf8",
        str(script),
        cwd=cwd,
        env=env,
        start_new_session=os.name == "posix",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate(json.dumps(arguments).encode())
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace")[-2000:].strip()
            raise RuntimeError(
                f"{script.parent.name} exited {process.returncode}: {detail}"
            )
        return json.loads(stdout)
    finally:
        # The SDK cancels its callback on deadline. Release the process and any
        # children before the task workspace and Snapshot checkout disappear.
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.returncode is None:
            killer = await asyncio.create_subprocess_exec(
                "taskkill.exe",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
            if process.returncode is None:
                process.kill()
        await process.wait()
