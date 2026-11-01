from __future__ import annotations
from typing import Any, Optional
from ..upstream_compaction.responses_usage import normalize_usage

def repetition_copy(stopping: str, outcome: str, refusal: str) -> tuple[str, str, str]:
    """(log line, user copy, error) for a repetition-dominated abort; only the clauses naming
    where the turn stopped differ between the length path and the stop path."""
    return (
        f"🔁 Response dominated by repeated text — stopping {stopping}.",
        "⚠️ **Response Stopped — Repetition Detected**\n\nThe model fell into a repetition loop while "
        f"writing this response, {outcome}\n\n→ Switch to a different model with `/model`\n"
        "→ Or resend your message (your conversation history is preserved)",
        f"Model output entered a repetition loop{refusal} degenerate response.",
    )


_REPETITION_DOMINATED = repetition_copy(
    "instead of continuing a degenerate response",
    "so continuing would only produce more repeated text. The partial response was discarded.",
    " and was truncated mid-loop; refusing to continue a",
)


_CEILING_NO_TEXT = (
    "⚠️ **No visible answer was produced.** The model hit its output-token limit on every "
    "continuation attempt — its reasoning consumed the entire budget each time.\n\nTo fix this:\n"
    "→ Lower reasoning effort: `/reasoning low` or `/reasoning none`\n→ Or raise max_tokens for this model"
)


_MIN_CONTINUATION_HEADROOM = 512


_WINDOW_FILLED = (
    "⚠️ **Context window full.** The prompt used {prompt:,} of this model's {ctx:,}-token "
    "context window, leaving no room to answer in. This is a context-window limit, not an "
    "output-length limit.\n\nTo fix this:\n→ Compress the conversation with `/compress` or start "
    "a new session\n→ Or raise the model's context window (e.g. Ollama `num_ctx`)"
)


def _prompt_filled_window(agent: Any, response: Any) -> Optional[tuple[int, int]]:
    """``(prompt_tokens, context_length)`` when this response's usage shows the prompt left
    less than ``_MIN_CONTINUATION_HEADROOM`` in the window compression resolves for the
    model; ``None`` (keep continuing) when either number is unknown."""
    ctx = int(getattr(getattr(agent, "context_compressor", None), "context_length", 0) or 0)
    usage = getattr(response, "usage", None)
    if not (ctx and usage):
        return None
    prompt = normalize_usage(usage, provider=agent.provider, api_mode=agent.api_mode).prompt_tokens
    return (prompt, ctx) if prompt and ctx - prompt < _MIN_CONTINUATION_HEADROOM else None
