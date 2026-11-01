"""Deterministic local context compaction used before provider calls."""

from __future__ import annotations

import json

from .models import content_text


def estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for message in messages:
        text = content_text(message.get("content"))
        calls = message.get("tool_calls")
        if calls:
            text += json.dumps(calls, ensure_ascii=False, separators=(",", ":"))
        total += max(1, len(text) // 4)
    return total


def compact(
    messages: list[dict], *, max_tokens: int, keep_recent: int = 8
) -> list[dict]:
    if estimate_tokens(messages) <= max_tokens or len(messages) <= keep_recent + 1:
        return list(messages)
    head = messages[0] if messages and messages[0].get("role") == "system" else None
    start = max(0, len(messages) - keep_recent)
    # A tool result is only valid after its assistant tool-call envelope.  Keep
    # the complete envelope (and its user turn) when the recent window would
    # otherwise begin in the middle of a tool exchange.
    while start > 0:
        current = messages[start]
        if current.get("role") == "tool":
            start -= 1
            continue
        if current.get("role") == "assistant" and current.get("tool_calls"):
            start -= 1
            continue
        break
    tail = messages[start:]
    middle_end = start
    middle = messages[1:middle_end] if head else messages[:middle_end]
    summary = "\n".join(
        f"{m.get('role')}: {content_text(m.get('content'))[:400]}" for m in middle
    )
    summary_message = {
        "role": "system",
        "content": "[OpenClaw compacted prior context]\n" + summary,
    }
    result = ([head] if head else []) + [summary_message] + tail
    while estimate_tokens(result) > max_tokens and len(summary_message["content"]) > 64:
        summary_message["content"] = summary_message["content"][
            : max(64, len(summary_message["content"]) // 2)
        ]
    # If the summary plus the recent window still exceeds the budget, discard
    # the oldest complete turn from the recent window.  Removing from the end
    # can leave an assistant tool-call envelope without its matching tool
    # result (or vice versa), which makes the next provider request invalid.
    while estimate_tokens(result) > max_tokens and len(tail) > 1:
        if tail[0].get("role") == "assistant" and tail[0].get("tool_calls"):
            tail.pop(0)
            while tail and tail[0].get("role") == "tool":
                tail.pop(0)
        else:
            tail.pop(0)
        result = ([head] if head else []) + [summary_message] + tail
    return result
