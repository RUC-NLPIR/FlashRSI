"""Pre-flight short-answer format reminder.

When the user's request explicitly requires a bare short answer, this hook adds
a one-time reminder immediately before the first LLM call. It is deliberately
tiny and bounded: it only fires once per task (turn 1) and only when the exact
benchmark instruction is present, so it adds a small, fixed prompt cost and
never loops or re-rolls.

The primary model remains the sole author of the final answer; this hook only
makes the user's own output contract the most recent instruction before the
model's first attempt.
"""

from __future__ import annotations

from typing import Any


def _short_answer_requested(question: str) -> bool:
    return "return only the short answer" in (question or "").lower()


async def before_llm(messages: list[dict], ctx: Any) -> list[dict]:
    """Append a one-turn format reminder when the task demands a bare answer."""
    if ctx.turn != 1:
        return messages
    if not _short_answer_requested(ctx.question):
        return messages

    reminder = {
        "role": "user",
        "content": (
            "Format reminder: the user's request says \"Return only the short "
            "answer.\" Your final message must be exactly the requested answer "
            "phrase and nothing else. Copy the exact wording from the supplied "
            "context (spelling, capitalization, hyphens, and name extent). No "
            "sentence, lead-in, explanation, parenthetical, citation, markdown, "
            "quote, or trailing punctuation."
        ),
    }
    return messages + [reminder]
