"""Open harness adapter: execute the selected source and skill files."""

import asyncio
import sys

from flashrsi.core import Agent, Trajectory


class ProcessAgent(Agent):
    name = "example_process"
    description = "Execute the selected version's Python source and skill."

    async def _run(self, prompt, working_dir=None):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            str(self.files_dir / "runtime/main.py"),
            prompt,
            cwd=working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, error = await process.communicate()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        return Trajectory(
            output=output.decode().strip(),
            status="finished" if process.returncode == 0 else "error",
            error_message=error.decode() or "process failed"
            if process.returncode
            else None,
        )
