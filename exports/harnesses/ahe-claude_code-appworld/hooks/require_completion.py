"""Stop hook that keeps an AppWorld run from ending before the documented
supervisor completion API has actually been invoked.

This hook is fail-open only when it cannot obtain any usable evidence: if the
input cannot be parsed, or neither a transcript path nor a
``last_assistant_message`` is available, it approves the stop so a healthy run
can never be broken by the hook itself.

When evidence is available and no ``supervisor.complete_task(...)`` call is
found, the hook blocks the stop and returns a concrete reason for the model to
keep working. The reason distinguishes two general non-completion states:

* the transcript contains only read-only AppWorld calls (no observable
  world-state change), or
* some state-changing call exists but ``supervisor.complete_task(...)`` has not
  been called.

It intentionally does **not** gate the block on the CLI's ``stop_hook_active``
flag: the Claude Code SDK does not currently propagate that flag to plugin Stop
hooks, so it can be ``false`` even for an ordinary, blockable turn end. The CLI's
own block cap and turn limit still bound retries.
"""

import json
import re
import sys
from pathlib import Path

# Match an actual invocation such as ``apis.supervisor.complete_task(...)`` or
# ``supervisor.complete_task(...)``, but not documentation lookups like
# ``show_api_doc(app_name="supervisor", api_name="complete_task")``.
_COMPLETION_CALL = re.compile(r"(?:apis\.)?supervisor\.complete_task\s*\(")

# A read-only AppWorld API call queries data but does not change world state.
# Mutating calls are everything else: follow_artist, create_transaction,
# update_alarm, delete_account, login, complete_task, and so on.
_READ_ONLY_CALL = re.compile(
    r"apis\.[A-Za-z_]\w*\.(?:show_|get_|search_|list_|find_|query_|read_)\w*\s*\("
)
_MUTATING_CALL = re.compile(
    r"apis\.[A-Za-z_]\w*\.(?!show_|get_|search_|list_|find_|query_|read_)\w+\s*\("
)

_TOOL_USE_TYPES = {
    "ToolUseBlock",
    "tool_use",
    "tool_use_block",
    "toolUse",
    "ToolUse",
}


def _extract_code(value):
    """Return the Python code string from a tool-use record, if one exists."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str):
            return code
        for key in ("input", "arguments", "tool_input"):
            child = value.get(key)
            if isinstance(child, str):
                return child
            if isinstance(child, dict):
                code = _extract_code(child)
                if code:
                    return code
    return None


def _walk(value, pattern, found):
    """Walk JSON records and search tool-use code blocks for ``pattern``."""
    if isinstance(value, dict):
        record_type = value.get("type")
        if record_type in _TOOL_USE_TYPES:
            code = _extract_code(value)
            if code and pattern.search(code):
                found.append(True)
        for child in value.values():
            _walk(child, pattern, found)
    elif isinstance(value, list):
        for child in value:
            _walk(child, pattern, found)


def _text_has_pattern(value, pattern):
    """Search assistant text (a string or nested text blocks) for ``pattern``."""
    if isinstance(value, str):
        return bool(pattern.search(value))
    if isinstance(value, dict):
        return any(_text_has_pattern(child, pattern) for child in value.values())
    if isinstance(value, list):
        return any(_text_has_pattern(child, pattern) for child in value)
    return False


def _transcript_has_pattern(transcript_path, pattern):
    """Return True/False, or None when the transcript is missing/unreadable."""
    path = Path(transcript_path)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    # The transcript is normally JSONL; accept a single JSON array as well.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    found = []
    if isinstance(data, (dict, list)):
        _walk(data, pattern, found)
    else:
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            _walk(record, pattern, found)
    return any(found)


def _approve():
    print(json.dumps({"decision": "approve"}), flush=True)


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}), flush=True)


def main():
    try:
        request = json.load(sys.stdin)
    except Exception:
        _approve()
        return

    if not isinstance(request, dict):
        _approve()
        return

    transcript_path = request.get("transcript_path") or request.get("transcript")
    last_message = request.get("last_assistant_message") or ""

    has_completion = None
    has_mutation = None
    if transcript_path:
        has_completion = _transcript_has_pattern(transcript_path, _COMPLETION_CALL)
        has_mutation = _transcript_has_pattern(transcript_path, _MUTATING_CALL)

    if has_completion is None and last_message:
        has_completion = _text_has_pattern(last_message, _COMPLETION_CALL)
    if has_mutation is None and last_message:
        has_mutation = _text_has_pattern(last_message, _MUTATING_CALL)

    if has_completion:
        _approve()
        return

    if has_completion is None:
        # No usable evidence about the run; fail open rather than risk breaking
        # a healthy session that happens to use an unexpected input shape.
        _approve()
        return

    if has_mutation:
        _block(
            "Do not end the run yet: no apis.supervisor.complete_task(...) call "
            "was found in the transcript, even though state-changing AppWorld "
            "calls were made. AppWorld grades final world state, so perform any "
            "remaining required world-state changes, then call "
            'print(apis.supervisor.complete_task(status="success")) and wait for '
            "its result before ending your turn."
        )
    else:
        _block(
            "Do not end the run yet: no apis.supervisor.complete_task(...) call "
            "and no state-changing AppWorld call were found in the transcript. "
            "AppWorld grades final world state, so a final text answer alone will "
            "fail. Query only as much as you need, then perform the required "
            "world-state change(s), then call "
            'print(apis.supervisor.complete_task(status="success")) and wait for '
            "its result before ending your turn."
        )


if __name__ == "__main__":
    main()
