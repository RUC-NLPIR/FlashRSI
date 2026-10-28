"""Native PreToolUse policy for this optional file-only Worker profile."""

import json
import sys
from pathlib import Path


def rejection(payload):
    tool = payload["tool_name"]
    fields = {"Read": "file_path", "Write": "file_path", "Edit": "file_path"}
    if tool not in {*fields, "Glob", "Grep"}:
        return "This Worker only uses Read, Write, Edit, Glob and Grep."
    root = Path(payload["cwd"]).resolve()
    arguments = payload["tool_input"]
    raw = arguments[fields[tool]] if tool in fields else arguments.get("path") or "."
    path = Path(raw).expanduser()
    path = (root / path).resolve()
    if not path.is_relative_to(root):
        return "Access outside the current working directory is unavailable."
    if tool == "Glob":
        pattern = Path(arguments["pattern"])
        if pattern.anchor or ".." in pattern.parts:
            return "Use a relative Glob pattern within the current directory."
    return None


if __name__ == "__main__":
    try:
        reason = rejection(json.load(sys.stdin))
    except (KeyError, TypeError, ValueError, OSError):
        reason = "Cannot validate the tool input; access denied."
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny" if reason else "allow",
                    "permissionDecisionReason": reason
                    or "Within the current directory.",
                }
            }
        )
    )
