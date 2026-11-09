"""Final-answer gate for AppWorld tasks.

Keeps the agent from stopping on an incomplete or unsupported answer. It
remembers the full text of recent AppWorld tool results in `ctx.state`, uses a
cheap heuristic on the shell's own `TASK_COMPLETED` line, and enforces that the
most recent completion signal is `true` before the answer can be accepted. When
that requirement is met, it optionally asks a small side-LLM verifier to either
accept the answer or send the main agent back for one more evidence-gathering
turn.
"""

from __future__ import annotations

import json
import re

_MAX_RESULTS = 6
_MAX_HISTORY_IN_PROMPT = 4
_CODE_PREVIEW_CHARS = 600
_RESULT_PREVIEW_CHARS = 1200

_STATE_KEY = "verify_final"

# Matches the line this workspace's appworld_execute tool actually prints
# (e.g. `TASK_COMPLETED: true`). Anchoring avoids confusing a `task_completed`
# value printed inside stdout with the shell's own completion flag.
_TASK_COMPLETED_LINE_RE = re.compile(
    r"(?im)^\s*TASK_COMPLETED\s*:\s*[\"']?(true|false)[\"']?\s*$"
)


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a side-LLM reply, if any."""
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


async def after_tool(name, args, result, ctx):
    """Remember full AppWorld results so the final gate can inspect them."""
    if name != "appworld_execute":
        return result

    state = getattr(ctx, "state", None)
    if state is None:
        return result
    bucket = state.setdefault(_STATE_KEY, {})
    results = bucket.setdefault("results", [])
    results.append({"args": args or {}, "result": result or ""})
    if len(results) > _MAX_RESULTS:
        results = results[-_MAX_RESULTS:]
        bucket["results"] = results
    return result


def _stored_results(ctx) -> list:
    state = getattr(ctx, "state", None)
    if not state:
        return []
    bucket = state.get(_STATE_KEY) or {}
    return bucket.get("results") or []


def _history_text(ctx) -> str:
    """Summarize recent AppWorld activity for the verifier."""
    stored = _stored_results(ctx)
    if stored:
        recent = stored[-_MAX_HISTORY_IN_PROMPT:]
        parts: list[str] = []
        for i, item in enumerate(recent, 1):
            parts.append(f"Call {i}: appworld_execute")
            code = (item.get("args") or {}).get("code", "")
            if isinstance(code, str) and code.strip():
                parts.append("Code: " + code[:_CODE_PREVIEW_CHARS].replace("\n", "\\n"))
            result = item.get("result", "") or ""
            if result:
                parts.append("Result: " + result[:_RESULT_PREVIEW_CHARS])
        return "\n\n".join(parts)

    records = getattr(ctx, "tool_history", []) or []
    recent = records[-_MAX_HISTORY_IN_PROMPT:]
    if not recent:
        return "(no tool calls yet)"

    parts = []
    for i, rec in enumerate(recent, 1):
        name = getattr(rec, "requested_name", "?")
        parts.append(f"Call {i}: {name}")
        args = getattr(rec, "requested_args", {}) or {}
        if name == "appworld_execute":
            code = args.get("code", "")
            if isinstance(code, str) and code.strip():
                parts.append("Code: " + code[:_CODE_PREVIEW_CHARS].replace("\n", "\\n"))
        preview = getattr(rec, "result_preview", "") or ""
        if preview:
            parts.append("Result: " + preview[:_RESULT_PREVIEW_CHARS])
    return "\n\n".join(parts)


def _result_completed_value(result: str) -> bool | None:
    """Return the shell's completion flag as a bool, or None if not present."""
    if not result:
        return None

    # Prefer the exact `TASK_COMPLETED: <bool>` line emitted by our tool.
    matches = _TASK_COMPLETED_LINE_RE.findall(result)
    if matches:
        return matches[-1].lower() == "true"

    # Fallback for raw/compact shell JSON that was not reformatted.
    if re.search(r"task_completed[\"']?\s*:\s*[\"']?true", result, re.I):
        return True
    if re.search(r"task_completed[\"']?\s*:\s*[\"']?false", result, re.I):
        return False
    return None


def _latest_completion(ctx) -> bool | None:
    """Return the most recent explicit completion signal, if any."""
    stored = _stored_results(ctx)
    if stored:
        for item in reversed(stored):
            completed = _result_completed_value(item.get("result", "") or "")
            if completed is not None:
                return completed
        return None

    records = getattr(ctx, "tool_history", []) or []
    for rec in reversed(records):
        if getattr(rec, "requested_name", "") != "appworld_execute":
            continue
        completed = _result_completed_value(getattr(rec, "result_preview", "") or "")
        if completed is not None:
            return completed
    return None


def _task_completed_false(ctx) -> bool:
    """Heuristic: the most recent AppWorld result explicitly says not done."""
    return _latest_completion(ctx) is False


def _task_completed_true(ctx) -> bool:
    """True only when the most recent AppWorld result explicitly says done."""
    return _latest_completion(ctx) is True


async def before_final(answer: str, ctx):
    """Return accept/continue after checking whether the answer is ready."""
    answer = (answer or "").strip()
    if not answer:
        return {"action": "accept"}

    if _task_completed_false(ctx):
        return {
            "action": "continue",
            "feedback": (
                "The AppWorld environment reports TASK_COMPLETED=false. "
                "Do not finalize yet. If you have already performed all of the "
                "requested actions, mark the task complete by calling "
                "`apis.supervisor.complete_task()` (with `answer=` only if the "
                "task asks for a value), then wait for a result whose "
                "TASK_COMPLETED line is true. Otherwise continue working: "
                "inspect the relevant APIs/state, print the exact values needed "
                "by the question, and try again."
            ),
        }

    if not _task_completed_true(ctx):
        return {
            "action": "continue",
            "feedback": (
                "I do not see a recent AppWorld tool result with "
                "TASK_COMPLETED=true, so the task is not provably finished. "
                "Do not finalize yet. Call `apis.supervisor.complete_task()` "
                "(with `answer=<exact value>` only if the task asks for a "
                "value), then wait for a tool result whose TASK_COMPLETED line "
                "is true. If the last action was not the final action, keep "
                "working and verify the exact values before marking complete."
            ),
        }

    history = _history_text(ctx)
    prompt = (
        "You are a strict verifier for an AppWorld task agent. Decide whether "
        "the proposed final answer is ready to submit.\n\n"
        f"QUESTION:\n{getattr(ctx, 'question', '')}\n\n"
        f"PROPOSED FINAL ANSWER:\n{answer}\n\n"
        f"RECENT TOOL ACTIVITY:\n{history}\n\n"
        "Return a single JSON object with keys `action` and `feedback`.\n"
        "- action=\"accept\" if the answer directly and fully answers the "
        "question, is consistent with the observed tool outputs, and has no "
        "obvious missing required detail.\n"
        "- action=\"continue\" if the answer is incomplete, vague, unsupported, "
        "or likely wrong. In `feedback`, give one short, specific instruction "
        "telling the agent exactly what to print/verify next.\n"
        "Only choose continue for a concrete missing detail or inconsistency; "
        "do not demand perfection. If the answer is already adequate, accept it."
    )

    verdict = await ctx.side_text(prompt, purpose="verify_final", max_tokens=300)
    data = _extract_json(verdict or "")
    if not data:
        return {"action": "accept"}

    action = str(data.get("action", "accept")).lower()
    feedback = str(data.get("feedback", "") or "").strip()
    if action == "continue" and feedback:
        return {"action": "continue", "feedback": feedback}
    return {"action": "accept"}
