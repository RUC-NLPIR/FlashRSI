import json
import sys


def decide(event):
    # Reinforce the searchqa output contract immediately after the Skill tool
    # loads, while leaving every other hook event unchanged.
    if event.get("hook_event_name") == "PostToolUse" and event.get("tool_name") == "Skill":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    "Return only the short answer from the supplied context. "
                    "Identify the exact requested slot and return the shortest "
                    "contiguous context phrase that fills it. Copy that phrase "
                    "exactly as written, preserving its full surface form: do not "
                    "paraphrase, normalize, convert word forms, or add extra "
                    "qualifiers, class nouns, markdown, explanation, or tokens. "
                    "For category/type questions return only the bare label as "
                    "written in the context; for named entities return the exact "
                    "proper-name phrase as written; for numbers and ordinals "
                    "return the exact surface form used in the context."
                ),
            }
        }
    return {}


if __name__ == "__main__":
    event = json.load(sys.stdin)
    print(json.dumps(decide(event)))
