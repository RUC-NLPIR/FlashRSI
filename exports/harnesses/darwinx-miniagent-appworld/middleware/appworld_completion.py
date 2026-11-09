"""Guardedly record an AppWorld answer when the model finishes without doing so.

This middleware only uses the kernel's ``before_final`` hook, which runs for a
*voluntary* final answer (the model emitted text and no tool calls). It never
runs on the forced-answer path, because the kernel does not invoke
``before_final`` hooks there.

Why this is safe for already-solved trajectories:
  * The LLM prompt, tool schemas, and normal tool-call flow are unchanged.
  * The hook returns ``None`` immediately when a prior tool call already
    contained ``supervisor.complete_task``, so it never re-submits or
    overwrites an answer the model already recorded.
  * The hook returns ``None`` immediately when the answer is empty.
  * Any error during the extra completion call is swallowed and traced; the
    final answer text returned to the caller is never modified.
"""

from __future__ import annotations

import asyncio
from typing import Any

_AUTO_COMPLETE_TIMEOUT_S = 30.0


def _already_completed(ctx: Any) -> bool:
    """Return True if any prior AppWorld call already invoked complete_task."""
    for record in getattr(ctx, "tool_history", None) or []:
        args = getattr(record, "requested_args", None) or {}
        code = args.get("code")
        if isinstance(code, str) and "complete_task" in code:
            return True
    return False


def _trace(ctx: Any, event: str, **payload: Any) -> None:
    try:
        trace = getattr(ctx, "trace", None)
        if trace is not None and hasattr(trace, "event"):
            trace.event(event, **payload)
    except Exception:
        pass


async def before_final(answer: str, ctx: Any) -> None:
    """Auto-record an unrecorded final answer in the AppWorld supervisor."""
    text = (answer or "").strip()
    if not text:
        return None

    if _already_completed(ctx):
        return None

    tool = None
    try:
        tool = (getattr(ctx, "workspace", None).extra_tools or {}).get(
            "appworld_execute"
        )
    except Exception:
        tool = None
    if tool is None:
        return None

    # repr() produces a valid Python string literal for the exact answer text.
    code = "apis.supervisor.complete_task(answer=" + repr(text) + ")"
    _trace(
        ctx,
        "appworld_auto_complete",
        answer_length=len(text),
        code_length=len(code),
    )

    try:
        await asyncio.wait_for(tool({"code": code}, ctx), timeout=_AUTO_COMPLETE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - a failure here must not break the run
        _trace(ctx, "appworld_auto_complete_error", error=str(exc))
    return None
