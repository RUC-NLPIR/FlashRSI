import asyncio
import json
import os
import re
import sys
from pathlib import Path

# The Stop hook must never trap the agent in a loop: if Claude Code says another
# stop hook is already active, allow the stop to proceed.
MAX_RERUN_QUERIES = 2
EXECUTE_TIMEOUT_SECONDS = 1.5

# Read-only AppWorld method names.  These identify transcript queries that can
# safely be replayed against the live app state.
_READ_CALL_RE = re.compile(
    r"\b(?:get|list|search|find|query|check|inspect|show|lookup|read|fetch|"
    r"retrieve|count|verify|validate|is|has|api_docs)_?\w*\s*\(",
    re.IGNORECASE,
)

# Strongly mutating method names.  Queries containing these are never replayed,
# because a second execution could change the world (for example, sending an
# email twice).  Unknown non-read calls are treated as mutating as well.
_MUTATE_CALL_RE = re.compile(
    r"\b(?:send|create|delete|remove|add|update|modify|schedule|pay|transfer|"
    r"submit|post|register|unregister|cancel|complete|approve|reject|decline|"
    r"reply|respond|mark|save|write|insert|replace|drop|truncate|execute|run|"
    r"move|copy|rename|archive|publish|unpublish|restore|activate|deactivate|"
    r"like|unlike|follow|unfollow|friend|unfriend|rate|review|comment|share|"
    r"sync|import|export|load|flush|commit|rollback|grant|revoke|enable|disable|"
    r"accept|launch|install|uninstall|reset)\w*\s*\(",
    re.IGNORECASE,
)

# An explicit expected condition.  A bare print of a state object is observation,
# not verification; we require the agent to compare or assert an expected
# post-condition so completion cannot be accepted from a narrative summary.
_COMPARISON_RE = re.compile(r"(==|!=|<=|>=|\bin\b|<|>)")

# The documented supervisor completion call is the agent's signal, not an
# observed post-condition.  Do not let it hide the last real state-changing
# action when we look for verification queries that ran after that action.
_FINALIZATION_RE = re.compile(r"\b(?:complete_task|finish_task|mark_completed)\s*\(", re.IGNORECASE)


def _iter_dicts(obj):
    """Yield every dict in an arbitrary JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_dicts(value)


def _stringify_content(content):
    """Return a stable string for a transcript tool_result content value."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if text is not None:
                    parts.append(str(text))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    if isinstance(content, (dict, int, float, bool)):
        return json.dumps(content, sort_keys=True)
    return str(content)


def _normalize_output(text):
    if text is None:
        return ""
    if not isinstance(text, str):
        text = _stringify_content(text)
    return text.strip()


def _is_finalization(code):
    return bool(_FINALIZATION_RE.search(code or ""))


def _is_read_like(code):
    """True for an explicit, replayable read-only post-condition check."""
    code = code or ""
    if not code.strip():
        return False
    if _is_finalization(code):
        return False
    if _MUTATE_CALL_RE.search(code):
        return False
    # An assert is a post-condition check even when it uses a variable assigned
    # by an earlier read-only call.
    if "assert" in code:
        return True
    # Otherwise require a live read plus an explicit expected-condition check.
    if _COMPARISON_RE.search(code) and _READ_CALL_RE.search(code):
        return True
    return False


def _is_read_only_code(code):
    """Read-only verification query: replayable against the live app."""
    return _is_read_like(code)


def _has_mutating_code(code):
    """State-changing call? Finalization is excluded from this classification."""
    code = code or ""
    if not code.strip():
        return False
    if _is_finalization(code):
        return False
    if _MUTATE_CALL_RE.search(code):
        return True
    # Anything that is neither an explicit read/assert nor a known read call is
    # conservatively treated as state-changing.  This prevents replaying code
    # that depends on earlier variables or performs an unknown action.
    return not _is_read_like(code)


def _output_is_truthy(text):
    """Best-effort success interpretation of a verification query's output."""
    low = _normalize_output(text).lower()
    if low in ("", "none", "null", "false", "0", "[]", "{}", "no", "n/a"):
        return False
    if "traceback" in low or "assertionerror" in low or "error" in low:
        return False
    return True


def _extract_calls_and_results(transcript_path):
    """Return (calls, results, user_texts) from a Claude Code transcript."""
    calls = []
    results = {}
    user_texts = []

    with open(transcript_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # User instruction / follow-up text (not tool results).
            if isinstance(data, dict) and data.get("type") == "user":
                message = data.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        text = content.strip()
                        if text:
                            user_texts.append(text)

            for item in _iter_dicts(data):
                if not isinstance(item, dict):
                    continue

                # Assistant tool call.  Claude Code may prefix the MCP tool name
                # with the server name, e.g. mcp__appworld__appworld_execute.
                if item.get("type") == "tool_use":
                    name = item.get("name") or ""
                    if name != "appworld_execute" and not name.endswith("appworld_execute"):
                        continue
                    inp = item.get("input") or {}
                    code = inp.get("code")
                    if isinstance(code, str) and code.strip():
                        calls.append(
                            {
                                "id": item.get("id"),
                                "code": code,
                            }
                        )
                    continue

                # Tool result.  Claude Code uses tool_use_id; older transcripts
                # may use toolUseId / tool_use_id / id.
                if item.get("type") == "tool_result" or (
                    "tool_use_id" in item or "toolUseId" in item
                ):
                    tool_id = (
                        item.get("tool_use_id")
                        or item.get("toolUseId")
                        or item.get("id")
                    )
                    if tool_id:
                        results[str(tool_id)] = _stringify_content(
                            item.get("content")
                        )

    return calls, results, user_texts


def _execute_live(cwd, code):
    """Run code in the persistent AppWorld shell and return its raw output.

    This mirrors the read-only path used by servers/appworld.py without touching
    controller grading or any other MCP surface.
    """
    candidates = []
    event_cwd = Path(cwd) if cwd else None
    if event_cwd is not None:
        candidates.append(event_cwd / "appworld-connection.json")
    candidates.append(Path(os.getcwd()) / "appworld-connection.json")

    connection_path = None
    for candidate in candidates:
        if candidate.exists():
            connection_path = candidate
            break
    if connection_path is None:
        raise RuntimeError("appworld-connection.json not found in the task directory")

    socket = json.loads(connection_path.read_text())["socket"]

    async def _run():
        reader, writer = await asyncio.open_unix_connection(
            socket, limit=8 * 1024 * 1024
        )
        try:
            writer.write(
                (json.dumps({"operation": "execute", "code": code}) + "\n").encode()
            )
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), EXECUTE_TIMEOUT_SECONDS)
            return line.decode().strip()
        finally:
            writer.close()
            await writer.wait_closed()

    return asyncio.run(_run())


def _verification_passes(code, recorded, live):
    """Return (passed, detail)."""
    recorded_norm = _normalize_output(recorded)
    live_norm = _normalize_output(live)

    if "Traceback" in live_norm or "AssertionError" in live_norm:
        return False, f"live query failed with: {live_norm[:400]}"
    if "Traceback" in recorded_norm or "AssertionError" in recorded_norm:
        return False, f"transcript query failed with: {recorded_norm[:400]}"

    # An assertion is an explicit post-condition check.  A clean live re-run is
    # enough; it does not need to produce identical text.
    if "assert" in code:
        return True, "assertion passed in the live app"

    # A comparison check should produce a truthy result when the post-condition
    # holds.  If the transcript already showed a false/empty result for this
    # check, the agent finished with a failing verification.
    if _COMPARISON_RE.search(code):
        if not _output_is_truthy(live):
            return False, f"live check returned a false/empty result: {live_norm[:300]!r}"
        if recorded is not None and not _output_is_truthy(recorded):
            return False, (
                "transcript check returned a false/empty result: "
                f"{recorded_norm[:300]!r}"
            )
        return True, "live app satisfied the expected condition"

    # Fallback for any remaining read-only query: require the live state to
    # match the state the agent already observed in the transcript.
    if recorded is None:
        return False, "no recorded result was available to compare against the live app"
    if recorded_norm == live_norm:
        return True, "live state matched the transcript verification result"
    return False, (
        "live state differs from transcript: transcript recorded "
        f"{recorded_norm[:300]!r}, live app returned {live_norm[:300]!r}"
    )


def decide(event):
    if not isinstance(event, dict):
        return {}

    # Identity for events explicitly routed to another hook stage.
    hook_event_name = event.get("hook_event_name")
    if hook_event_name not in (None, "", "Stop"):
        return {}

    # Never trap Claude Code in a stop loop.
    if event.get("stop_hook_active"):
        return {}

    transcript_path = event.get("transcript_path")
    cwd = event.get("cwd") or os.getcwd()

    if transcript_path:
        transcript = Path(transcript_path)
        if not transcript.is_absolute():
            transcript = Path(cwd) / transcript
        transcript_path = str(transcript)

    if not transcript_path or not Path(transcript_path).exists():
        return {
            "decision": "block",
            "reason": (
                "No readable transcript was available to the completion check. "
                "Before finishing, run a read-only verification query (for example, "
                "print or assert the current app state) and confirm that the live "
                "state satisfies the task instruction."
            ),
        }

    try:
        calls, results, user_texts = _extract_calls_and_results(transcript_path)
    except Exception as error:  # noqa: BLE001 - transcript may be partial/locked
        return {
            "decision": "block",
            "reason": (
                "The completion check could not read the task transcript "
                f"({error}). Run a read-only verification query and confirm the "
                "live app state before finishing."
            ),
        }

    if not calls:
        return {
            "decision": "block",
            "reason": (
                "No appworld_execute calls were found in the transcript, so the "
                "required post-conditions have not been observed. Run a read-only "
                "verification query against the live app and confirm the current "
                "state matches the task instruction before finishing."
            ),
        }

    # Verification queries must be read-only and must have run after the last
    # real state-changing action (supervisor finalization is ignored).
    last_mutating_index = None
    for index, call in enumerate(calls):
        if _has_mutating_code(call["code"]):
            last_mutating_index = index

    candidates = []
    for index, call in enumerate(calls):
        if last_mutating_index is not None and index <= last_mutating_index:
            continue
        if not _is_read_only_code(call["code"]):
            continue
        if "api_docs" in call["code"]:
            continue
        candidates.append(call)

    if not candidates:
        return {
            "decision": "block",
            "reason": (
                "No explicit read-only verification was found after the last "
                "action. Do not finish on a narrative 'Done' or the supervisor "
                "status: run a live check that compares the current app state to "
                "the expected post-condition (for example, "
                "print(len(apis.example.get_items()) == 1) or "
                "assert apis.example.get_status() == 'done') and then stop again."
            ),
        }

    # Prefer explicit assert-based post-condition checks.  They are the
    # strongest verification and avoid false mismatches from dynamic text in
    # print-based queries.
    assertion_candidates = [call for call in candidates if "assert" in call["code"]]
    replay_candidates = assertion_candidates or candidates
    replay_candidates = replay_candidates[-MAX_RERUN_QUERIES:]

    for call in replay_candidates:
        try:
            live = _execute_live(cwd, call["code"])
        except Exception as error:  # noqa: BLE001 - live verification unavailable
            return {
                "decision": "block",
                "reason": (
                    "Unable to re-run a read-only verification query against the "
                    f"live app ({error}). Verify the current app state explicitly "
                    "and confirm it matches the instruction before finishing."
                ),
            }

        passed, detail = _verification_passes(
            call["code"], results.get(str(call["id"])), live
        )
        if not passed:
            snippet = call["code"].strip().replace("\n", " ")[:220]
            return {
                "decision": "block",
                "reason": (
                    "Observed post-conditions do not match. Re-running "
                    f"verification query ({snippet!r}) gave {detail}. Do not end "
                    "the run yet; inspect the live state, correct any mismatch, "
                    "and re-run a passing read-only verification before finishing."
                ),
            }

    return {}


if __name__ == "__main__":
    event = json.load(sys.stdin)
    print(json.dumps(decide(event)))
