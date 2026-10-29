"""Recognize execution limits without masking infrastructure errors."""

import re


def budget_reason(result):
    if result.status != "error":
        return None
    verifier = next(
        (m for m in reversed(result.messages) if m.get("type") == "HarborVerifier"),
        None,
    )
    if verifier is not None:
        exception = verifier.get("exception_type")
        if exception not in (
            None,
            "NonZeroAgentExitCodeError",
            "AgentTimeoutError",
            "VerifierTimeoutError",
        ):
            return None
        if exception in ("AgentTimeoutError", "VerifierTimeoutError"):
            return "time_limit"
    error = (
        (result.error_message or "")
        .partition("\nClaude Code stderr (tail):\n")[0]
        .lower()
    )
    if error == "max_turns" or re.search(
        r"reached maximum number of turns\s*\(\d+\)", error
    ):
        return "turn_limit"
    if re.fullmatch(r"(?:miniagent|claude code) timed out after [0-9.]+s", error):
        return "time_limit"
    if any(
        text in error
        for text in (
            "output budget exhausted",
            "output token limit reached",
            "maximum context length",
            "context_length_exceeded",
            "prompt is too long",
        )
    ):
        return "token_limit"
    for message in result.messages:
        if message.get("type") == "NativeBudgetOutcome" and message.get("reason") in (
            "token_limit",
            "turn_limit",
            "time_limit",
        ):
            return message["reason"]
        if message.get("type") == "ChatCompletion" and any(
            choice.get("finish_reason") == "length"
            for choice in message.get("choices", ())
        ):
            return "token_limit"
        if (
            message.get("type") == "AssistantMessage"
            and message.get("error") == "max_output_tokens"
        ):
            return "token_limit"
        if (
            message.get("type") == "ResultMessage"
            and message.get("subtype") == "error_max_turns"
        ):
            return "turn_limit"
    return None
