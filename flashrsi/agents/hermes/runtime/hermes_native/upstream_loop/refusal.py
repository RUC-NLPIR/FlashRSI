from __future__ import annotations


CONTENT_POLICY_NEXT_STEPS = (
    "Try rewording your message or removing sensitive attachments, or switch to another "
    "model with /model."
)


def content_policy_copy(*, label: str, summary: str) -> str:
    return (
        f"{label}'s safety filter refused this request, so the model didn't answer. "
        f"{CONTENT_POLICY_NEXT_STEPS}\n\nProvider said: {summary}"
    )
