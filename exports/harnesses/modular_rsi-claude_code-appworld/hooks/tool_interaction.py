import ast
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import tokenize


# Tool names used by the AppWorld MCP bridge.  The Claude Code hook event uses
# the MCP-qualified name, but the unqualified name is accepted as a fallback so
# the guard still works if the harness ever changes its naming.
APPWORLD_TOOL_NAMES = {"mcp__appworld__appworld_execute", "appworld_execute"}

# AppWorld mutating verbs.  These are matched as method names (``.send(...)``)
# and, for the clearly API-like ones, as standalone call names too.
MUTATING_VERBS = {
    "create",
    "send",
    "update",
    "delete",
    "add",
    "remove",
    "follow",
    "like",
    "rate",
    "move",
    "play",
    "mark",
    "set",
}

# Regex fallback used only when the submitted snippet is not valid Python.
# ``(?:_\w+)?`` allows ``send_message``/``set_status`` while avoiding false
# positives such as ``settings`` or ``address``.
_MUTATING_METHOD_RE = re.compile(
    r"\.\s*(create|send|update|delete|add|remove|follow|like|rate|move|play|mark|set)(?:_\w+)?\s*\(",
    re.IGNORECASE,
)
_MUTATING_STANDALONE_RE = re.compile(
    r"(?<![\w.])(create|send|update|delete|add|remove|follow|like|rate|move|play|mark)(?:_\w+)?\s*\(",
    re.IGNORECASE,
)
_MUTATING_SET_RE = re.compile(r"(?<![\w.])(set_\w+)\s*\(", re.IGNORECASE)

_BARE_SUCCESS_RE = re.compile(
    r"^(execution\s+successful\.?|success(ful)?!?|successful\.?|ok\.?|done\.?|true\.?|ack\.?|acknowledged\.?)$",
    re.IGNORECASE,
)

# A file is kept per session so PreToolUse can remember the response produced
# by the previous identical appworld_execute submission.
_STATE_DIR = tempfile.gettempdir()
_STATE_FILE_PREFIX = "flashrsi_tool_interaction_state_"
_MAX_STATE_ENTRIES = 100
_PREVIEW_LIMIT = 300


def _normalize_code(code):
    """Return a stable representation of a submitted code snippet."""
    return re.sub(r"\s+", " ", code or "").strip()


def _code_key(normalized_code):
    """Return a compact, filesystem-safe key for a code snippet."""
    return hashlib.sha256(normalized_code.encode("utf-8")).hexdigest()


def _session_key(event):
    session_id = event.get("session_id") or event.get("sessionId") or ""
    transcript_path = event.get("transcript_path") or event.get("transcriptPath") or ""
    if session_id or transcript_path:
        return session_id or transcript_path
    # Real hook events always carry a session id or transcript path.  Fall back
    # to a process-specific key so direct unit tests do not leak state into one
    # another through the shared temporary directory.
    return f"default-session-{os.getpid()}"


def _state_path(event):
    digest = hashlib.sha256(_session_key(event).encode("utf-8")).hexdigest()[:24]
    return os.path.join(_STATE_DIR, f"{_STATE_FILE_PREFIX}{digest}.json")


def _load_state(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(path, state):
    # Keep the file bounded and use an atomic replacement so a crash mid-write
    # does not leave a corrupt state file behind.
    while len(state) > _MAX_STATE_ENTRIES:
        oldest = next(iter(state), None)
        if oldest is None:
            break
        state.pop(oldest, None)

    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(tmp_path, path)
    except Exception:
        pass


def _extract_text(tool_response):
    """Pull the human-readable text out of an MCP-style tool_response."""
    if tool_response is None:
        return ""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        content = tool_response.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text is not None:
                        parts.append(str(text))
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        text = tool_response.get("text")
        if text is not None:
            return str(text)
        result = tool_response.get("result")
        if result is not None:
            return str(result)
        error = tool_response.get("error")
        if error is not None:
            return str(error)
        return json.dumps(tool_response, default=str)
    return str(tool_response)


def _preview(text, limit=_PREVIEW_LIMIT):
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _is_bare_success(text):
    """Return True when the tool output carries no concrete state."""
    stripped = (text or "").strip()
    if stripped == "":
        return True
    if len(stripped) > 60:
        return False
    return bool(_BARE_SUCCESS_RE.match(stripped))


def _is_mutating_name(name, is_attribute):
    """Match method/function names against the AppWorld mutating verbs.

    ``set`` is only treated as mutating when it is clearly a method
    (``.set(...)`` or ``set_something(...)``); a bare Python ``set(...)``
    constructor is left alone.
    """
    name = (name or "").lower()
    for verb in MUTATING_VERBS:
        if name == verb:
            if verb == "set" and not is_attribute:
                continue
            return True
        if name.startswith(verb + "_"):
            return True
    return False


def _walk_calls(node):
    """Walk a parsed AST and report whether any call mutates AppWorld state."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if _is_mutating_name(func.attr, is_attribute=True):
                return True
        elif isinstance(func, ast.Name):
            if _is_mutating_name(func.id, is_attribute=False):
                return True

    for child in ast.iter_child_nodes(node):
        if _walk_calls(child):
            return True
    return False


def _strip_comments_and_strings(code):
    """Return code with strings/comments blanked, for regex fallback only."""
    try:
        lines = code.splitlines(keepends=True)
        offsets = []
        position = 0
        for line in lines:
            offsets.append(position)
            position += len(line)

        masked = list(code)
        tokens = tokenize.generate_tokens(io.StringIO(code).readline)
        for token in tokens:
            if token.type in (tokenize.STRING, tokenize.COMMENT):
                start = offsets[token.start[0] - 1] + token.start[1]
                end = offsets[token.end[0] - 1] + token.end[1]
                for index in range(start, min(end, len(masked))):
                    if masked[index] not in "\r\n":
                        masked[index] = " "
        return "".join(masked)
    except Exception:
        return code


def _contains_mutating_calls(code):
    """Return True when the submitted snippet calls a mutating AppWorld API."""
    if not code or not code.strip():
        return False
    try:
        tree = ast.parse(code)
    except Exception:
        cleaned = _strip_comments_and_strings(code)
        return bool(
            _MUTATING_METHOD_RE.search(cleaned)
            or _MUTATING_STANDALONE_RE.search(cleaned)
            or _MUTATING_SET_RE.search(cleaned)
        )
    return _walk_calls(tree)


def _looks_like_supervisor_completion(code):
    """Return True when the snippet appears to be the documented completion API.

    Completion calls are intentionally excluded from PostToolUse state
    re-inspection prompts: once the model has called the supervisor completion
    API, asking it to re-read AppWorld state is both too late and confusing.
    """
    if not code or not code.strip():
        return False
    lowered = code.lower()
    if "supervisor" in lowered and "complete" in lowered:
        return True
    if re.search(r"\b(complete_task|finish_task|submit_answer|task_completed)\s*\(", lowered):
        return True
    return False


def _pre_tool_use(state_path, normalized_code, original_code):
    state = _load_state(state_path)
    key = _code_key(normalized_code)
    entry = state.get(key)
    previous_count = entry.get("count", 0) if entry else 0
    previous_response = entry.get("last_response_preview", "") if entry else ""

    if previous_count == 0:
        # First submission: leave native behavior unchanged, but remember that
        # this exact snippet has now been attempted once.
        state[key] = {
            "count": 1,
            "last_response_preview": previous_response,
        }
        _save_state(state_path, state)
        return {}

    if previous_count == 1:
        # First resubmission: allow it, but inject the prior result and a
        # warning so the model has a chance to correct course.
        preview = _preview(previous_response)
        if preview:
            prior_text = (
                "The previous identical appworld_execute call returned:\n"
                '"""\n' + preview + '\n"""\n'
            )
        else:
            prior_text = "The previous identical appworld_execute call returned no output.\n"

        additional_context = (
            prior_text
            + "You are resubmitting identical AppWorld code. Do not repeat unchanged code. "
            "Inspect the previous output and choose a different next action that re-reads and "
            "reports the concrete AppWorld state (values, IDs, counts, or remaining state) "
            "before calling the supervisor completion API."
        )

        state[key] = {
            "count": 2,
            "last_response_preview": previous_response,
        }
        _save_state(state_path, state)

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "Identical AppWorld code was resubmitted; allowed once with a warning.",
                "additionalContext": additional_context,
            }
        }

    # Repeated identical submission beyond the warned retry: block the call so
    # the model is forced to inspect previous outputs and choose a different
    # next action instead of consuming the turn budget in a loop.
    preview = _preview(previous_response)
    reason = (
        "This identical appworld_execute code has been submitted repeatedly without a "
        "different next action. Inspect the previous outputs"
        + (f' (last output preview: "{preview}")' if preview else "")
        + " and choose a different action that reads and reports the concrete AppWorld "
        "state instead of repeating unchanged code."
    )

    state[key] = {
        "count": previous_count + 1,
        "last_response_preview": previous_response,
    }
    _save_state(state_path, state)

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _post_tool_use(state_path, normalized_code, original_code, tool_response):
    response_text = _extract_text(tool_response)

    # Record the response so the PreToolUse guard can show it if the same code
    # is submitted again.
    state = _load_state(state_path)
    key = _code_key(normalized_code)
    entry = state.get(key)
    if entry is None:
        entry = {"count": 0}
    entry["last_response_preview"] = _preview(response_text, 500)
    state[key] = entry
    _save_state(state_path, state)

    is_mutating = _contains_mutating_calls(original_code)
    is_bare = _is_bare_success(response_text)

    # A successful supervisor completion call is not a state mutation that
    # needs re-inspection; do not prompt for a re-read after it.
    if _looks_like_supervisor_completion(original_code) and not is_mutating:
        return {}

    if not (is_mutating or is_bare):
        return {}

    reasons = []
    if is_mutating:
        reasons.append("the submitted code appears to make state-mutating AppWorld API calls")
    if is_bare:
        reasons.append("the tool response is only a bare success/acknowledgement message")

    additional_context = (
        "This appworld_execute call requires state verification because "
        + " and ".join(reasons)
        + ". Do not mark the task complete yet, and do not treat the tool output alone "
        "as proof that the intended state change happened. Re-query the affected "
        "records, files, balances, or libraries via appworld_execute, then print the "
        "concrete returned IDs, counts, timestamps, and remaining state. Compare those "
        "values against the task requirement. Only call the supervisor completion API "
        "after that concrete state has been read back and verified."
    )

    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": additional_context,
        }
    }


def decide(event):
    try:
        hook_event_name = (
            event.get("hook_event_name")
            or event.get("hookEventName")
            or ""
        )
        tool_name = event.get("tool_name") or event.get("toolName") or ""

        if tool_name not in APPWORLD_TOOL_NAMES:
            return {}

        tool_input = event.get("tool_input") or event.get("toolInput") or {}
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except Exception:
                tool_input = {}
        if not isinstance(tool_input, dict):
            tool_input = {}

        original_code = tool_input.get("code")
        if not isinstance(original_code, str):
            return {}
        normalized_code = _normalize_code(original_code)
        if not normalized_code:
            return {}

        state_path = _state_path(event)

        if hook_event_name == "PreToolUse":
            return _pre_tool_use(state_path, normalized_code, original_code)
        if hook_event_name == "PostToolUse":
            tool_response = event.get("tool_response") or event.get("toolResponse")
            return _post_tool_use(
                state_path,
                normalized_code,
                original_code,
                tool_response,
            )

        return {}
    except Exception:
        # A hook failure must never take down the main agent loop.
        return {}


if __name__ == "__main__":
    try:
        event = json.load(sys.stdin)
    except Exception:
        print("{}")
    else:
        print(json.dumps(decide(event)))
