"""Task-local host for the original Hermes incomplete Responses state machine.

The caller supplies an already constructed assistant message. The original core
owns transcript changes, visible deduplication, checkpoint merging, retry limits,
nudges and one-shot output-budget escalation. No provider fallback is configured.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from ._vendor.continuation_core import (
    InterimVisibleText,
    continue_codex_incomplete,
)
from .policy import strip_think_blocks


@dataclass
class ContinuationDecision:
    continue_turn: bool
    result: dict[str, Any] | None
    max_output_tokens: int | None = None
    reasoning_off: bool = False
    emitted: list[dict[str, Any]] = field(default_factory=list)


class _Host(InterimVisibleText):
    api_mode = "codex_responses"
    quiet_mode = True
    show_commentary = True

    def __init__(self, state, assistant_message, configured_cap):
        self._codex_incomplete_retries = state.incomplete_retries
        self._codex_reasoning_only_streak = state.reasoning_only_streak
        self._ephemeral_reasoning_off = False
        self._ephemeral_max_output_tokens = None
        self.max_tokens = configured_cap
        self._message = assistant_message
        self.emitted = []

    def _build_assistant_message(self, assistant_message, finish_reason):
        message = copy.deepcopy(self._message)
        message.setdefault("role", "assistant")
        message["finish_reason"] = finish_reason
        return message

    def _strip_think_blocks(self, text):
        return strip_think_blocks(None, text)

    def _emit_interim_assistant_message(self, message):
        self.emitted.append(copy.deepcopy(message))

    def _try_activate_fallback(self, **kwargs):
        return False

    def _emit_diagnostic_wait(self, text):
        pass

    def _persist_session(self, messages, conversation_history):
        pass


@dataclass
class ContinuationState:
    """Keep one state per user turn; reset after a complete response/tool progress.

    Three partial replies exhaust the aggregate budget. Consecutive reasoning-only
    replies use their own three-response streak, so a partial followed by internal
    reasoning can continue beyond the aggregate third response, as in upstream.
    """

    incomplete_retries: int = 0
    reasoning_only_streak: int = 0

    def reset(self) -> None:
        self.incomplete_retries = self.reasoning_only_streak = 0

    def step(
        self,
        messages: list[dict[str, Any]],
        assistant_message: dict[str, Any],
        *,
        configured_cap: int | None = None,
        usage: dict[str, Any] | None = None,
        response_status: str | None = None,
        incomplete_reason: str | None = None,
        api_call_count: int = 0,
    ) -> ContinuationDecision:
        """Mutate messages and return the original continue/terminal verdict.

        Response status/reason describe the raw Responses object, before adapter
        normalization. An ``incomplete`` adapter verdict alone does not prove the
        output budget was exhausted and therefore does not enable escalation.
        Returned cap and reasoning overrides apply to the next request only.
        """
        host = _Host(self, assistant_message, configured_cap)
        result = continue_codex_incomplete(
            host,
            SimpleNamespace(**assistant_message),
            "incomplete",
            messages=messages,
            conversation_history=None,
            api_call_count=api_call_count,
            response=SimpleNamespace(
                status=response_status,
                incomplete_details={"reason": incomplete_reason},
                usage=usage,
            ),
        )
        self.incomplete_retries = host._codex_incomplete_retries
        self.reasoning_only_streak = host._codex_reasoning_only_streak
        return ContinuationDecision(
            continue_turn=result is None,
            result=result,
            max_output_tokens=host._ephemeral_max_output_tokens,
            reasoning_off=host._ephemeral_reasoning_off,
            emitted=host.emitted,
        )
