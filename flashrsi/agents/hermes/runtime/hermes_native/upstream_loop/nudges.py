from __future__ import annotations


_CODEX_ACK_CONTINUATION_NUDGE = (
    "[System: Continue now. Execute the required tool calls and only send your final answer "
    "after completing the task.]"
)


_DEGENERATE_FINAL_NUDGE = (
    "[System: Your previous message ended the turn with a fragment that is not a usable answer. "
    "If the task is unfinished, continue it and then give the complete answer. If that fragment "
    "WAS your complete answer, send it again exactly as before.]"
)
