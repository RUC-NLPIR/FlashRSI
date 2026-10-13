"""Tool-interaction guard for the ModularRSI harness.

Injects a short, targeted reminder into the conversation when the agent is at
risk of a self-referential verification failure or an irreversible,
destructive mutation:

  * (a) runs an equivalence / verification command (diff, cmp, comm,
        sha256sum, SQL EXCEPT / UNION ALL / INTERSECT, ...),
  * (b) copies or mutates an input artifact (cp, .clone, CREATE INDEX,
        VACUUM, INSERT, UPDATE, ALTER, ...),
  * (c) runs an irreversible / destructive command (git history rewrite via
        filter-branch / filter-repo / rebase / commit --amend / reset --hard /
        push --force / reflog expire / gc --prune / update-ref -d, or deletion
        of .git internals / backups / original inputs via rm -rf / shred /
        truncate),
  * (d) a tool response indicates the command did not actually run or finish
        (denied, not permitted, timed out, killed, terminated).

The reminder is injected as ``additionalContext`` and never blocks the tool.
Non-tool hook events (e.g. Stop) are silent no-ops that honor
``stop_hook_active`` to avoid recursion.
"""

import json
import re
import sys

_EQUIVALENCE_REMINDER = (
    "Equivalence guard: verify equivalence byte-for-byte against the pristine, "
    "unmodified task input -- never against a copy you created or altered "
    "yourself. 'Semantics-preserving' mutations (e.g. adding indexes) can "
    "silently reorder rows for any result without a complete deterministic "
    "ORDER BY, so sort BOTH sides with an explicit total ordering that fully "
    "resolves ties before comparing. A timed-out or killed run is not an "
    "authoritative reference."
)

_DESTRUCTIVE_REMINDER = (
    "Destructive-action guard: this command is irreversible or destructive "
    "(a git history rewrite, or deletion of .git internals / backups / "
    "original inputs). Make a recoverable backup of the affected state FIRST, "
    "before running it. Verify the acceptance criterion against the pristine, "
    "unmodified input -- never against a copy you created or altered."
)

_NOT_RUN_REMINDER = (
    "Command-execution guard: the command was denied or did not actually run "
    "to completion (denied / not permitted / timed out / killed / terminated). "
    "Do not assume its effect took place: re-check the actual on-disk state "
    "before claiming success."
)

# (a) equivalence / verification commands
_EQUIVALENCE_PATTERNS = [
    r"\bdiff\b",
    r"\bcmp\b",
    r"\bcomm\b",
    r"\bsha256sum\b",
    r"\bsha1sum\b",
    r"\bmd5sum\b",
    r"\bcksum\b",
    r"\bsdiff\b",
    r"\bEXCEPT\b",
    r"\bUNION\s+ALL\b",
    r"\bINTERSECT\b",
]

# (b) copy / mutate an input artifact
_MUTATION_PATTERNS = [
    r"\bcp\b",
    r"\.clone\b",
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b",
    r"\bVACUUM\b",
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bALTER\b",
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bREINDEX\b",
    r"\bATTACH\b",
    r"\bCREATE\s+TABLE\b",
]

# (c) irreversible / destructive commands
_DESTRUCTIVE_PATTERNS = [
    r"git\s+filter-branch\b",
    r"filter-repo\b",
    r"git\s+rebase\b",
    r"commit\s+--amend\b",
    r"reset\s+--hard\b",
    r"push\s+[^\n]*--force(?:-with-lease)?\b",
    r"reflog\s+expire\b",
    r"gc\s+--prune\b",
    r"update-ref\s+[^\n]*-d\b",
    r"\brm\s+[^\n]*-[a-z]*[rf][a-z]*[rf][a-z]*\b",  # rm -rf / -fr / -Rf ...
    r"\bshred\b",
    r"\btruncate\b",
]

# (d) signals that a command did not actually run or finish
_NOT_RUN_PATTERNS = [
    r"\bdenied\b",
    r"not\s+permitted",
    r"permission\s+denied",
    r"not\s+allowed",
    r"\bunauthorized\b",
    r"\bforbidden\b",
    r"\brejected\b",
    r"timed?\s*-?\s*out",
    r"\btimeout\b",
    r"exceeded",
    r"\bkilled\b",
    r"\binterrupted\b",
    r"SIGKILL",
    r"SIGTERM",
    r"\bterminated\b",
]

_EQUIVALENCE_RE = re.compile(
    "|".join(_EQUIVALENCE_PATTERNS + _MUTATION_PATTERNS), re.IGNORECASE
)
_DESTRUCTIVE_RE = re.compile("|".join(_DESTRUCTIVE_PATTERNS), re.IGNORECASE)
_NOT_RUN_RE = re.compile("|".join(_NOT_RUN_PATTERNS), re.IGNORECASE)


def _text(value):
    """Flatten a hook field into a searchable string."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            return command
        return json.dumps(value)
    if value is None:
        return ""
    return str(value)


def _context(event_name, reminder):
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": reminder,
        }
    }


def decide(event):
    if not isinstance(event, dict):
        return {}

    # Honor stop_hook_active: never emit output while a Stop hook is already
    # re-entering, which would otherwise recurse.
    if event.get("stop_hook_active"):
        return {}

    name = event.get("hook_event_name")
    if name not in ("PreToolUse", "PostToolUse"):
        # Stop and any other non-tool hook event: silent no-op.
        return {}

    try:
        if name == "PreToolUse":
            command = _text(event.get("tool_input"))
            if command and _DESTRUCTIVE_RE.search(command):
                return _context(name, _DESTRUCTIVE_REMINDER)
            if command and _EQUIVALENCE_RE.search(command):
                return _context(name, _EQUIVALENCE_REMINDER)
        else:  # PostToolUse
            response = _text(event.get("tool_response"))
            if response and _NOT_RUN_RE.search(response):
                return _context(name, _NOT_RUN_REMINDER)
    except Exception:
        return {}

    return {}


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    print(json.dumps(decide(payload)))
