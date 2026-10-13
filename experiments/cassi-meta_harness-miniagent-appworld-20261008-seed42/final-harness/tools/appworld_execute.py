"""MiniAgent workspace tool: execute code in the official AppWorld shell.

This wrapper adds preflight guards that keep the model from wasting its
limited AppWorld executions on known-bad inputs, and annotates shell
responses with the execution count so the model can budget the hard cap.
"""

import asyncio
import json
import re
from pathlib import Path

_BLOCKED_DISALLOWED_IMPORT = re.compile(
    r"(?m)^\s*(?:from\s+|\bimport\s+)(apis|sys|os|inspect|io|socket|traceback|statistics)\b"
)
_BLOCKED_DISALLOWED_USE = re.compile(
    r"\b(?:os\.(?:listdir|walk)|inspect\.|sys\.|traceback\.|io\.|socket\.|statistics\.|builtins\.open|open\s*\(|__closure__|__globals__|__dict__|__code__|__mro__|__defaults__|__kwdefaults__|cell_contents|request_tracker)\b"
)
_COMPLETE_WITH_ANSWER = re.compile(r"\bcomplete_task\s*\(\s*answer\s*=")
_NUMERIC_ANSWER_STR_RE = re.compile(
    r"(complete_task\s*\(\s*answer\s*=\s*)(['\"])\s*(\$?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*\2"
)

# AppWorld list/search endpoints that are commonly paginated.  We use a broad
# net on purpose: the note is only a reminder and never blocks execution.
_PAGINATED_ENDPOINT_RE = re.compile(
    r"\bapis\.[A-Za-z_][A-Za-z0-9_]*\.(?:"
    r"show_[A-Za-z0-9_]*(?:library|feed|transactions|contacts|threads|inbox|outbox|archived|messages|alarms|notifications|projects|tasks|notes|recommendations|reviews|playlists|songs|albums)"
    r"|search_[A-Za-z0-9_]+"
    r"|show_liked_[A-Za-z0-9_]+"
    r")\s*\("
)

_ENOUGH_SONGS_RE = re.compile(r"enough\s+songs", re.IGNORECASE)

_PAGINATION_NOTE = (
    " [Pagination reminder: AppWorld list/search endpoints return only one page "
    "and often default to 5 results. If you need a complete set, loop with "
    "page_index/page_limit until an empty page is returned.]"
)

_ENOUGH_SONGS_NOTE = (
    " [Selection hint: 'enough songs' means the number of bulleted exercises "
    "for today in this note. Prefer the first topically relevant playlist with "
    "at least that many songs, then play it and complete the task.]"
)


def _extract_instruction(question: str) -> str:
    """Best-effort extraction of the AppWorld task instruction from ctx.question.

    ``ctx.question`` is the full user prompt used by this harness, e.g.
    "Complete this AppWorld task by executing Python with the appworld_execute
    tool.\\n{... \\"instruction\\": \\"...\\", ...}".  Keep this resilient: if it
    is already a JSON object with an instruction key, use that.
    """
    if not question:
        return ""
    try:
        data = json.loads(question)
        if isinstance(data, dict) and isinstance(data.get("instruction"), str):
            return data["instruction"]
    except Exception:
        pass

    match = re.search(
        r'"instruction"\s*:\s*"(.*?)"\s*,\s*"supervisor"', question, re.DOTALL
    )
    if match:
        return match.group(1)
    return ""


def _is_answer_task(instruction: str) -> bool:
    """Return True when a task is asking for an answer.

    AppWorld's supervisor.complete_task accepts an ``answer`` only for these
    tasks.  Action/imperative tasks must call ``complete_task()`` or
    ``complete_task(status='success')`` without an answer.
    """
    text = instruction.strip()
    if not text:
        return True  # If we cannot classify, do not block the call.
    if "?" in text:
        return True
    first = text.split()[0].lower() if text.split() else ""
    return first in {"what", "how", "name", "which", "who", "when", "where", "why"}


def _normalize_complete_task_answer(code: str) -> str:
    """Rewrite numeric/currency string answers to numeric literals.

    AppWorld expects ``answer`` to be concise and in the natural type for the
    question.  For money/count totals the grader expects e.g. ``314`` or
    ``786.0`` rather than ``"$314"`` or ``"786"``.
    """
    def repl(match: re.Match) -> str:
        prefix = match.group(1)
        number = match.group(4).replace(",", "")
        if not number:
            return match.group(0)
        # Do not strip leading zeros from values that look like codes/IDs.
        if not match.group(3) and number.startswith("0") and len(number) > 1:
            return match.group(0)
        try:
            value = float(number) if "." in number else int(number)
        except ValueError:
            return match.group(0)
        return f"{prefix}{value}"

    return _NUMERIC_ANSWER_STR_RE.sub(repl, code)


def _preflight(code: str, instruction: str) -> str | None:
    """Return a helpful rejection message when a call is known to be wasted.

    Returning a string means "do not send this to the AppWorld shell".  This
    preserves the shell's hard execution budget for useful calls.
    """
    import_match = _BLOCKED_DISALLOWED_IMPORT.search(code)
    if import_match:
        module = import_match.group(1)
        if module == "apis":
            return (
                "Execution blocked before AppWorld shell: `apis` is already a "
                "global object. Do not import it; call it directly, e.g. "
                "print(apis.api_docs.app_descriptions())."
            )
        return (
            f"Execution blocked before AppWorld shell: `{module}` is not "
            "allowed in AppWorld. Do not introspect the Python runtime or "
            "filesystem with builtins; use apis.api_docs.* to inspect APIs and "
            "apis.file_system.* / apis.<app>.* for application data."
        )

    if _BLOCKED_DISALLOWED_USE.search(code):
        return (
            "Execution blocked before AppWorld shell: this builtin/introspection "
            "call is not allowed in AppWorld. Use apis.api_docs.show_api_doc to "
            "learn an API, and apis.file_system.show_directory/show_file for "
            "files instead of os.*/open(). Do not inspect __closure__, "
            "__globals__, __dict__, request_tracker, or other runtime internals."
        )

    if _COMPLETE_WITH_ANSWER.search(code) and not _is_answer_task(instruction):
        return (
            "Execution blocked before AppWorld shell: this task is an action "
            "task, not a question, so apis.supervisor.complete_task() must not "
            "pass `answer`. Call apis.supervisor.complete_task() or "
            "complete_task(status='success') instead, then provide a brief "
            "final answer in your own message."
        )

    return None


def _should_add_pagination_note(code: str) -> bool:
    """Return True when code calls a list endpoint without explicit pagination."""
    if "page_index" in code or "page_limit" in code:
        return False
    return bool(_PAGINATED_ENDPOINT_RE.search(code))


async def call(args, ctx):
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a non-empty string")

    state = ctx.state.setdefault("appworld_execute", {})
    call_no = int(state.get("calls", 0)) + 1
    state["calls"] = call_no

    if "complete_task" in code:
        state["complete_task_seen"] = True

    instruction = _extract_instruction(getattr(ctx, "question", "") or "")
    rejection = _preflight(code, instruction)
    if rejection is not None:
        return json.dumps(
            {
                "output": rejection,
                "task_completed": False,
                "blocked": True,
                "execution_count": call_no,
            },
            ensure_ascii=False,
        )

    code = _normalize_complete_task_answer(code)
    add_pagination_note = _should_add_pagination_note(code)
    add_enough_songs_note = bool(_ENOUGH_SONGS_RE.search(instruction)) and (
        "show_note" in code
        or "search_notes" in code
        or "duration_mins" in code
    )

    connection_path = ctx.working_dir / "appworld-connection.json"
    endpoint = json.loads(Path(connection_path).read_text())["socket"]

    reader, writer = await asyncio.open_unix_connection(
        endpoint, limit=8 * 1024 * 1024
    )
    try:
        writer.write(
            (json.dumps({"operation": "execute", "code": code}) + "\n").encode()
        )
        await writer.drain()
        line = (await reader.readline()).decode().strip()
    finally:
        writer.close()
        await writer.wait_closed()

    try:
        data = json.loads(line)
        if not isinstance(data, dict):
            return line
        if data.get("task_completed"):
            state["task_completed"] = True
        output = str(data.get("output", ""))
        if "Maximum number of executions" in output:
            output += (
                " [AppWorld execution limit reached. Do not retry more code; "
                "compose your final answer or call complete_task only if it is "
                "still possible.]"
            )
        if add_pagination_note:
            output += _PAGINATION_NOTE
        if add_enough_songs_note:
            output += _ENOUGH_SONGS_NOTE
        data["output"] = output
        data["execution_count"] = call_no
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return f"{line} [execution_count={call_no}]"
