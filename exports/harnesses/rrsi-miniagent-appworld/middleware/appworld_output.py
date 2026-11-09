"""Flatten AppWorld ``execute`` shell results for the main model.

The shell tool returns a JSON envelope and ``appworld_client.py execute``
prints a second JSON envelope inside it.  The model has to read through
double-escaped text before it can see the actual AppWorld output, which burns
context and makes postcondition verification and completion markers harder to
spot.

This ``after_tool`` hook unwraps those two envelopes for AppWorld execute
commands so state reads, error messages, and the ``task_completed`` flag are
immediately visible.  It is deliberately conservative:

* only ``shell`` calls containing ``appworld_client.py execute`` are touched;
* shell-level timeouts and truncation are left untouched;
* malformed JSON is left untouched;
* the flattened result still contains the shell exit code (when non-zero) and
  an explicit ``[task_completed=...]`` marker.

The hook is placed after the completion guard in ``agent.yaml`` so completion
detection still sees the raw result before it is flattened.
"""

from __future__ import annotations

import json
from typing import Any

_EXECUTE_MARKER = "appworld_client.py execute"


def _is_appworld(ctx) -> bool:
    question = getattr(ctx, "question", "") or ""
    if "AppWorld tools are available" in question:
        return True
    return (
        "Supervisor:" in question
        and "Current simulated datetime:" in question
    )


def _get_command(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    command = args.get("command", "")
    return command if isinstance(command, str) else ""


def _flatten_execute_result(result: Any) -> str | None:
    if not isinstance(result, str):
        return None
    try:
        outer = json.loads(result)
    except Exception:
        return None
    if not isinstance(outer, dict):
        return None
    if outer.get("timed_out") or outer.get("truncated"):
        return None

    raw_output = outer.get("output", "")
    if not isinstance(raw_output, str) or not raw_output.strip():
        return None

    try:
        inner = json.loads(raw_output)
    except Exception:
        return None
    if not isinstance(inner, dict):
        return None

    core = inner.get("output", "")
    if not isinstance(core, str):
        core = str(core)
    task_completed = inner.get("task_completed")

    parts: list[str] = []
    if outer.get("exit_code") != 0:
        parts.append(f"[shell exit_code={outer['exit_code']}]")
    parts.append(core.strip() if core.strip() else "(no output)")
    parts.append(f"[task_completed={task_completed}]")
    return "\n".join(parts)


async def after_tool(name: str, args: dict, result: Any, ctx) -> Any:
    if name != "shell" or not _is_appworld(ctx):
        return None
    command = _get_command(args)
    if not command or _EXECUTE_MARKER not in command:
        return None
    flattened = _flatten_execute_result(result)
    if flattened is None:
        return None
    return {"result": flattened}
