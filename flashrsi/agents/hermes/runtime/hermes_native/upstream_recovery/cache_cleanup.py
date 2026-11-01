from __future__ import annotations
from typing import Any
from .cache_boundary import find_stable_prefix

def _has_part_marker(content: Any) -> bool:
    return isinstance(content, list) and any(isinstance(part, dict) and "cache_control" in part for part in content)


def strip_anthropic_cache_control(api_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove ``cache_control`` markers and undo decoration-produced list shapes (in place).

    Used before re-decorating after a mid-turn failover. Flattening to a string is restricted
    to the exact shapes :func:`apply_anthropic_cache_control` produces from string content
    (single text part, two-part system split, two-part skill split) so the ``""``-join is
    byte-exact. Marker removal is copy-on-write on part dicts: parts can alias caller-held
    lists and stripping must never rewrite the stored transcript.
    """
    for msg in api_messages:
        if not isinstance(msg, dict):
            continue
        msg.pop("cache_control", None)
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        role = msg.get("role")
        user_pair = role == "user" and len(content) == 2 and all(isinstance(p, dict) for p in content)
        # The skill split is the only decoration marking the FIRST part of a user message, so the
        # marked shape identifies it even after the prefix registry evicted the entry.
        first_part_marked = user_pair and "cache_control" in content[0] and "cache_control" not in content[1]
        if _has_part_marker(content):
            content = msg["content"] = [
                {k: v for k, v in part.items() if k != "cache_control"}
                if isinstance(part, dict) and "cache_control" in part else part for part in content
            ]
        plain_text_parts = content and all(
            isinstance(part, dict) and part.get("type", "text") == "text"
            and isinstance(part.get("text"), str) and set(part.keys()) <= {"type", "text"} for part in content
        )
        if not plain_text_parts:
            continue
        joined = "".join(part["text"] for part in content)
        # An UNMARKED split (outside the marker window) only the registry tells from a genuine
        # two-part user message.
        skill_split = first_part_marked or (user_pair and find_stable_prefix(joined) == content[0]["text"])
        if len(content) == 1 or (role == "system" and len(content) == 2) or skill_split:
            msg["content"] = joined
    return api_messages
