"""AppWorld completion lifecycle guard.

This middleware makes the native completion protocol deterministic for AppWorld
tasks.  Three reported failure modes are handled:

1. The run ends without a real ``apis.supervisor.complete_task`` call.  The
   ``before_final`` hook continues the turn whenever an AppWorld task has not
   yet recorded a successful completion, and specifically recovers the common
   case where the model emitted DSML/tool-call markup as message text.

2. Action tasks call ``complete_task(answer='long prose')`` even though the
   supervisor docs require ``answer`` to be left at its default ``None`` for
   non-question tasks.  ``before_tool`` rewrites the command to drop the
   answer argument and executes the corrected call in the same turn.

3. ``after_tool`` records a successful completion only when the AppWorld
   execute result actually reports ``task_completed: true``, so a failed or
   skipped completion cannot satisfy the final gate.

In addition, ``before_tool`` has a one-shot pending-work guard for action
tasks whose instruction says "all pending": if the most recent AppWorld output
still reports ``PENDING: n`` with ``n > 0``, the first completion attempt is
skipped with actionable feedback.  The guard fires at most once per run so a
legitimate completion that follows a non-qualifying pending list can still go
through.

The module is deliberately generic: it keys on the AppWorld supervisor prompt
shape and the task text, never on task IDs or expected answers.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_EXECUTE_MARKER = "appworld_client.py execute"
_COMPLETE_MARKERS = (
    "apis.supervisor.complete_task",
    "supervisor.complete_task",
)
_DSML_MARKERS = (
    "<｜｜DSML｜｜",
    "<|DSML|",
    "<dsml",
    "<tool_calls>",
    "<function_calls>",
)
_QUESTION_STARTS = {"what", "which", "when", "where", "who", "why", "how"}
_ANSWER_KW_RE = re.compile(r"\banswer\s*=")
_PENDING_COUNT_RE = re.compile(r"\bPENDING\s*:\s*(\d+)", re.IGNORECASE)


def _is_appworld(ctx) -> bool:
    question = getattr(ctx, "question", "") or ""
    if "AppWorld tools are available" in question:
        return True
    return (
        "Supervisor:" in question
        and "Current simulated datetime:" in question
    )


def _instruction(question: str) -> str:
    question = question.strip()
    idx = question.find("\n\nSupervisor:")
    if idx != -1:
        question = question[:idx]
    return question.strip()


def _is_question_task(question: str) -> bool:
    """Return True when the supervisor expects a concise answer value.

    AppWorld question tasks begin with a question word (What/How/Which/...);
    action tasks are imperative.  We also accept a first-sentence '?' as a
    fallback so tasks such as d0b1f43_2 are classified correctly.
    """
    instr = _instruction(question)
    if not instr:
        return False
    first_word = instr.split()[0].strip().lower().rstrip("?.!:;")
    if first_word in _QUESTION_STARTS:
        return True
    first_sentence = instr.splitlines()[0].rstrip() if instr.splitlines() else instr
    return first_sentence.endswith("?")


def _get_command(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    command = args.get("command", "")
    return command if isinstance(command, str) else ""


def _state(ctx) -> dict:
    state = ctx.state.get("appworld")
    if not isinstance(state, dict):
        state = {}
        ctx.state["appworld"] = state
    return state


def _pending_count(result: Any) -> int:
    """Return the most recent ``PENDING: n`` count from an AppWorld result."""
    if not isinstance(result, str):
        return 0
    match = _PENDING_COUNT_RE.search(result)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def _find_call_bounds(text: str, start: int) -> tuple[int, int] | None:
    """Return (open_paren, close_paren) for the call starting at ``start``."""
    open_idx = text.find("(", start)
    if open_idx == -1:
        return None
    depth = 0
    single = False
    double = False
    escaped = False
    for j in range(open_idx, len(text)):
        ch = text[j]
        if single:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                single = False
            continue
        if double:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                double = False
            continue
        if ch == "'":
            single = True
            continue
        if ch == '"':
            double = True
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                return open_idx, j
    return None


def _call_has_nondefault_answer(call_text: str) -> bool:
    """True if the call supplies an answer that is not None/null."""
    for match in _ANSWER_KW_RE.finditer(call_text):
        tail = call_text[match.end() :]
        if re.match(r"\s*(?:None|null)\b", tail):
            continue
        return True
    return False


def _extract_answer_value(command: str) -> str | None:
    """Return the literal value passed to ``answer=`` in the first complete_task call."""
    for marker in _COMPLETE_MARKERS:
        idx = command.find(marker)
        if idx == -1:
            continue
        bounds = _find_call_bounds(command, idx + len(marker))
        if bounds is None:
            continue
        open_idx, close_idx = bounds
        call_text = command[open_idx + 1 : close_idx]
        match = re.search(
            r"\banswer\s*=\s*("
            r"'(?:\\.|[^'\\])*'"
            r"|\"(?:\\.|[^\"\\])*\""
            r"|[^,\n\)]+"
            r")",
            call_text,
            re.S,
        )
        if not match:
            return None
        raw = match.group(1).strip()
        if len(raw) >= 2 and raw[0] in ("'", '"'):
            try:
                return str(ast.literal_eval(raw))
            except Exception:
                return raw[1:-1]
        return raw
    return None


def _is_prose_question_answer(value: str) -> bool:
    """True when a question-task answer is too long to be the documented concise value."""
    return len(value) > 120 or "\n" in value or "\r" in value


def _fix_action_complete_task(command: str) -> str | None:
    """Return the command with the answer argument removed, if appropriate."""
    for marker in _COMPLETE_MARKERS:
        idx = command.find(marker)
        if idx == -1:
            continue
        bounds = _find_call_bounds(command, idx + len(marker))
        if bounds is None:
            continue
        open_idx, close_idx = bounds
        call_text = command[open_idx : close_idx + 1]
        if not _call_has_nondefault_answer(call_text):
            return None
        return command[:open_idx] + "()" + command[close_idx + 1 :]
    return None


def _result_says_completed(result: Any) -> bool:
    if not isinstance(result, str):
        return False
    try:
        outer = json.loads(result)
    except Exception:
        return False
    if not isinstance(outer, dict):
        return False
    if outer.get("timed_out") or outer.get("truncated"):
        return False
    if outer.get("exit_code") != 0:
        return False
    raw_output = outer.get("output", "")
    if not isinstance(raw_output, str) or not raw_output.strip():
        return False
    try:
        inner = json.loads(raw_output)
    except Exception:
        return False
    return isinstance(inner, dict) and inner.get("task_completed") is True


def _has_dsml(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker.lower() in lowered for marker in _DSML_MARKERS)


async def before_tool(name: str, args: dict, ctx) -> Any:
    if name != "shell" or not _is_appworld(ctx):
        return None
    command = _get_command(args)
    if not command or _EXECUTE_MARKER not in command or "complete_task" not in command:
        return None

    is_question = _is_question_task(ctx.question or "")

    # One-shot pending-work guard for "all pending" action tasks.  If the last
    # AppWorld result still shows a positive PENDING count, skip the first
    # completion attempt so the model has to look at the pending list again.
    if not is_question:
        instruction = _instruction(ctx.question or "")
        if "all pending" in instruction.lower():
            state = _state(ctx)
            if not state.get("pending_guard_blocked"):
                pending = _pending_count(state.get("last_execute_result"))
                if pending > 0:
                    state["pending_guard_blocked"] = True
                    ctx.trace.event(
                        "appworld_pending_guard_blocked",
                        pending=pending,
                    )
                    return {
                        "action": "skip",
                        "result": (
                            "The AppWorld supervisor.complete_task call was NOT "
                            "executed because the most recent AppWorld output "
                            f"still reports PENDING: {pending}. The task says "
                            "\"all pending\", so re-read the full pending list, "
                            "identify every pending item that matches the task's "
                            "target condition, apply the required action to each "
                            "one programmatically, and re-check that no qualifying "
                            "pending item remains before calling complete_task "
                            "again. If the remaining pending items are all outside "
                            "the target condition, briefly say why and retry "
                            "complete_task."
                        ),
                    }

    if is_question:
        value = _extract_answer_value(command)
        if value is None or value in ("", "None", "null") or _is_prose_question_answer(value):
            ctx.trace.event(
                "appworld_completion_answer_blocked",
                tool=name,
                length=len(value) if value else 0,
            )
            return {
                "action": "skip",
                "result": (
                    "The AppWorld supervisor.complete_task call was NOT executed "
                    "because the `answer` value is missing or too long/prose. The "
                    "supervisor docs require a concise answer: a number, a yes/no, or "
                    "a specific entity. Compute the concise canonical answer to the "
                    "task and call `apis.supervisor.complete_task(answer='<concise "
                    "answer>')` again."
                ),
            }
        return None

    fixed = _fix_action_complete_task(command)
    if fixed and fixed != command:
        ctx.trace.event("appworld_completion_answer_stripped", tool=name)
        return {"action": "redirect", "name": "shell", "args": {**args, "command": fixed}}
    return None


async def after_tool(name: str, args: dict, result: Any, ctx) -> Any:
    if name != "shell" or not _is_appworld(ctx):
        return None
    command = _get_command(args)
    if not command or _EXECUTE_MARKER not in command:
        return None

    state = _state(ctx)
    state["last_execute_command"] = command
    state["last_execute_result"] = result if isinstance(result, str) else str(result)

    if _result_says_completed(result):
        state["completed"] = True
        ctx.trace.event("appworld_completion_recorded")
    return None


async def before_final(answer: str, ctx) -> Any:
    if not _is_appworld(ctx):
        return None
    state = _state(ctx)
    completed = bool(state.get("completed"))
    if completed:
        return None

    if _has_dsml(answer):
        feedback = (
            "You ended with tool-call markup instead of a native tool call, so no "
            "supervisor completion call was executed. Issue a native `shell` tool "
            "call that runs the AppWorld execute Python block and calls "
            "`apis.supervisor.complete_task()`, then return a one-sentence final "
            "message. Do not put the command in message text or DSML markup."
        )
    elif _is_question_task(ctx.question or ""):
        feedback = (
            "This AppWorld question has not been submitted to the supervisor. "
            "Extract the concise answer from your final message and issue a native "
            "`shell` tool call that runs the AppWorld execute Python block with "
            "`apis.supervisor.complete_task(answer=<concise answer>)`. Then return a "
            "one-sentence final message."
        )
    else:
        feedback = (
            "This AppWorld task has not been marked complete. Issue a native `shell` "
            "tool call that runs the AppWorld execute Python block with "
            "`apis.supervisor.complete_task()`, then return a one-sentence final "
            "message. Do not return the command as message text."
        )
    return {"action": "continue", "feedback": feedback}
