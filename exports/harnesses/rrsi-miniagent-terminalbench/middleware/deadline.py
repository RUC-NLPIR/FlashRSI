"""Wall-clock deadline reminders.

The surrounding MiniAgent runner enforces a fixed wall-clock budget (900s in the
standard task environment). Long setup/analysis phases can consume that budget
before the required deliverable is written. This middleware injects escalating,
time-aware user messages between LLM turns so the model is prompted to commit a
minimal deliverable early and to stop exploratory work as the deadline nears.

The budget is configurable through MINIAGENT_DEADLINE_SECONDS so the same
mechanism works for differently-sized runners without hard-coding a task value.
"""

from __future__ import annotations

import os

_BUDGET_SECONDS = float(os.environ.get("MINIAGENT_DEADLINE_SECONDS", "900"))

# Each level is (fraction_of_budget_elapsed, reminder). Levels are monotonic and
# deliberately stop at ~88% so we never push a late-but-successful run past the
# hard deadline with an extra LLM turn.
_LEVELS = [
    (
        0.50,
        "Time check: about half the wall-clock budget has elapsed. If you have "
        "not yet produced the required deliverable (file, fix, or configuration), "
        "produce a minimal valid version now, verify it, and refine it afterward.",
    ),
    (
        0.75,
        "Only about a quarter of the wall-clock budget remains. Stop open-ended "
        "setup and analysis; commit the best candidate to the required path or "
        "apply the required fix/configuration, then validate it with the exact "
        "required command or format.",
    ),
    (
        0.88,
        "Deadline imminent (under two minutes). Do not start new long-running "
        "installs or builds. Ensure the required artifact or change exists and is "
        "valid; if it is missing, create or apply it now and verify it before "
        "answering.",
    ),
]


async def before_llm(messages, ctx):
    """Append the next deadline reminder when a new time threshold is crossed."""
    state = ctx.state.setdefault("deadline", {})
    last_level = state.get("last_level", -1)

    elapsed = ctx.elapsed_s
    level = -1
    for idx, (fraction, _text) in enumerate(_LEVELS):
        if elapsed >= _BUDGET_SECONDS * fraction:
            level = idx

    if level <= last_level:
        return messages

    state["last_level"] = level
    reminder = _LEVELS[level][1]
    messages.append({"role": "user", "content": reminder})
    ctx.trace.event(
        "deadline_reminder",
        level=level,
        elapsed_s=elapsed,
        remaining_s=max(0.0, _BUDGET_SECONDS - elapsed),
    )
    return messages
