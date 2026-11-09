import json
import sys


# PreToolUse is the tool-interaction boundary. Only these read-only,
# supplied-context tools are allowed to run; anything else would let the model
# reach outside the supplied context (e.g. WebSearch or Bash).
_SAFE_PRE_TOOLS = frozenset({"Skill", "Read", "Glob", "Grep"})
_PRE_TOOL_DENIAL_REASON = (
    "Use only the supplied context; external tools are not allowed."
)


def decide(event):
    """Handle PreToolUse/PostToolUse hook events.

    PreToolUse denies every tool outside the fixed read-only, supplied-context
    set. PostToolUse remains permissive so it never grants new permissions.
    Stop events are handled exclusively by the completion hook, so this hook
    leaves them alone.
    """
    if not isinstance(event, dict):
        return {}

    hook_event_name = event.get("hook_event_name")

    if hook_event_name == "PreToolUse":
        tool_name = event.get("tool_name")
        if not isinstance(tool_name, str) or tool_name not in _SAFE_PRE_TOOLS:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _PRE_TOOL_DENIAL_REASON,
                }
            }

    return {}


if __name__ == "__main__":
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError, ValueError):
        event = {}
    print(json.dumps(decide(event)))
