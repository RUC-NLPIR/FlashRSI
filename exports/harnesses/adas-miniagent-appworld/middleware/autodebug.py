"""Automatic error-recovery middleware for AppWorld tool calls.

When an `appworld_execute` call returns a Python traceback, the agent has two
bad options: spend another full LLM turn staring at the traceback, or finalize
without evidence. This middleware instead asks a small side LLM for one short
read-only diagnostic snippet and injects it as an additional tool call in the
same turn. The main model sees the diagnostic result at the start of its next
turn, so common mistakes (unknown API, wrong argument shape, missing attribute)
are diagnosed without wasting the main loop's budget or repeating a
side-effecting action.

The repair is conservative:
  * generated snippets are read-only inspection, never retries of sends/writes;
  * it never diagnoses a diagnostic (injected calls are not re-injected);
  * it is limited to a small number of attempts per run;
  * it does nothing when the shell already reports `TASK_COMPLETED: true`;
  * if the side LLM cannot produce JSON or produces the same code, no
    injection happens.
"""

from __future__ import annotations

import json
import re
from typing import Any

_STATE_KEY = "autodebug"
_MAX_INJECTIONS = 5
_MAX_CODE_CHARS = 1600
_MAX_RESULT_CHARS = 2400

_TRACEBACK_RE = re.compile(r"Traceback\s*\(most recent call last\):", re.I)
_TASK_COMPLETED_TRUE_RE = re.compile(
    r"(?im)^\s*TASK_COMPLETED\s*:\s*[\"']?true[\"']?\s*$"
)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _state(ctx: Any) -> dict:
    state = getattr(ctx, "state", None)
    if state is None:
        return {}
    return state.setdefault(_STATE_KEY, {})


async def after_tool(name: str, args: dict, result: str, ctx):
    """Detect tracebacks and queue a single read-only diagnostic call."""
    if name != "appworld_execute":
        return result

    if getattr(ctx, "_in_injected_call", False):
        return result
    if getattr(ctx, "_pending_injections", None):
        return result

    code = (args or {}).get("code", "")
    if not isinstance(code, str) or not code.strip():
        return result

    result_text = result or ""
    if not _TRACEBACK_RE.search(result_text):
        return result
    if _TASK_COMPLETED_TRUE_RE.search(result_text):
        return result

    state = _state(ctx)
    count = int(state.get("count", 0))
    if count >= _MAX_INJECTIONS:
        return result

    last_failed = state.get("last_failed_code", "")
    if code.strip() == last_failed:
        # Already attempted (and failed) to diagnose this exact snippet.
        return result

    prompt = (
        "You are a debugging assistant for a persistent Python AppWorld "
        "environment. The `apis` object is already available and variables "
        "persist across calls. Below are the original task, the code that just "
        "raised a traceback, and the shell result.\n\n"
        f"TASK:\n{getattr(ctx, 'question', '')}\n\n"
        f"FAILED CODE:\n{code[:_MAX_CODE_CHARS]}\n\n"
        f"SHELL RESULT:\n{result_text[:_MAX_RESULT_CHARS]}\n\n"
        "Propose one short, READ-ONLY `appworld_execute` code snippet to run "
        "next. It must inspect the failing objects and print the exact values "
        "needed to understand the error (for example: print(dir(apis)), "
        "print(type(obj)), print(obj), or a safe read/get operation). Do NOT "
        "retry any side-effecting operation such as send/write/pay/delete/"
        "purchase. The snippet must be complete and runnable in the persistent "
        "shell, and it must print the values you need.\n"
        'Return exactly one JSON object with a `code` string key, for example:\n'
        '{"code": "print(dir(apis))"}'
    )

    verdict = await ctx.side_text(prompt, purpose="autodebug", max_tokens=600)
    data = _extract_json(verdict or "")
    if not data:
        return result

    new_code = str(data.get("code", "") or "").strip()
    if not new_code:
        return result
    if new_code == code.strip():
        return result

    state["count"] = count + 1
    state["last_failed_code"] = code.strip()
    return {
        "result": result_text,
        "inject": [{"name": "appworld_execute", "args": {"code": new_code}}],
    }
