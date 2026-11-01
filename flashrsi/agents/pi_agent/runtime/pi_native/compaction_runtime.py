"""Transactional compaction shared by manual, threshold and overflow paths."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Mapping

from .compaction import (
    SUMMARIZATION_SYSTEM_PROMPT,
    content_text,
    estimate_projected_tokens,
    estimate_tokens,
    format_file_operations,
    is_context_overflow,
    is_recoverable_length,
    is_retryable_summary_error,
    prepare_compaction,
    should_compact,
    summary_prompt,
)
from .session import Session

SummaryCall = Callable[[list[dict[str, Any]], int], Awaitable[dict[str, Any]]]


class _SummaryAborted(Exception):
    """A provider abort response is distinct from cancellation of our task."""


class CompactionRuntime:
    def __init__(
        self,
        session: Session,
        options: Mapping[str, Any],
        context_window: int,
        model_max_tokens: int,
        events: list[dict[str, Any]],
        summarize: SummaryCall,
        cancel_event: asyncio.Event | None = None,
        retry_policy: Mapping[str, Any] | None = None,
    ):
        self.session, self.options = session, options
        self.context_window, self.model_max_tokens = context_window, model_max_tokens
        self.events, self.summarize = events, summarize
        self.cancel_event = cancel_event
        self.overflow_attempted = False
        self.retry_policy = retry_policy or {"enabled": False}
        self.active_reason = "manual"

    async def _produce_summary(self, conversation):
        attempts = (
            self.retry_policy.get("maxRetries", 0)
            if self.retry_policy.get("enabled")
            else 0
        )
        retried = False
        try:
            for attempt in range(attempts + 1):
                try:
                    response = await self.summarize(conversation, self.model_max_tokens)
                except Exception as exc:
                    response = {
                        "stopReason": "error",
                        "errorMessage": str(exc),
                        "content": [],
                    }
                if (
                    response.get("stopReason") != "error"
                    or attempt >= attempts
                    or not is_retryable_summary_error(
                        str(response.get("errorMessage") or "")
                    )
                ):
                    return response
                delay = min(
                    self.retry_policy.get("baseDelayMs", 2000) * (2**attempt),
                    self.retry_policy.get("maxAgentDelayMs", 60000),
                )
                retried = True
                self.events.append(
                    {
                        "type": "summarization_retry_scheduled",
                        "attempt": attempt + 1,
                        "maxAttempts": attempts,
                        "delayMs": delay,
                        "errorMessage": response.get("errorMessage", "Unknown error"),
                    }
                )
                await asyncio.sleep(delay / 1000)
                self.events.append(
                    {
                        "type": "summarization_retry_attempt_start",
                        "source": "compaction",
                        "reason": self.active_reason,
                    }
                )
        finally:
            if retried:
                self.events.append({"type": "summarization_retry_finished"})

    def threshold(self) -> bool:
        return self.context_window > 0 and should_compact(
            estimate_projected_tokens(self.session.projection(), self.session.branch())[
                "tokens"
            ],
            self.context_window,
            self.options,
        )

    def recovery(self, message: Mapping[str, Any]) -> bool:
        return bool(
            self.options["enabled"]
            and (
                is_context_overflow(message, self.context_window)
                or is_recoverable_length(message, self.model_max_tokens)
            )
        )

    async def recover(self, message: Mapping[str, Any], entry_id: str) -> bool:
        if not self.recovery(message) or message.get("stopReason") == "aborted":
            return False
        if message.get("stopReason") == "stop":
            await self.compact("overflow")
            return False
        if self.overflow_attempted:
            self._end(
                "overflow",
                error=(
                    "Context overflow recovery failed after one compact-and-retry attempt. "
                    "Try reducing context or switching to a larger-context model."
                    if is_context_overflow(message, self.context_window)
                    else "Truncated response recovery failed after one compact-and-retry attempt."
                ),
            )
            return False
        self.overflow_attempted = True
        result = await self.compact("overflow", will_retry=True, omit_entry_id=entry_id)
        return result is not None

    def _end(
        self,
        reason: str,
        result: dict[str, Any] | None = None,
        *,
        aborted: bool = False,
        retry: bool = False,
        error: str | None = None,
    ) -> None:
        value = {
            "type": "compaction_end",
            "reason": reason,
            "result": result,
            "aborted": aborted,
            "willRetry": retry,
        }
        if error:
            value["errorMessage"] = error
        self.events.append(value)

    async def _summary(
        self,
        messages: list[dict[str, Any]],
        previous: str | None,
        focus: str | None,
        prefix: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise asyncio.CancelledError
        conversation = [
            {"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": summary_prompt(
                    messages, previous, focus, turn_prefix=prefix
                ),
            },
        ]
        if self.cancel_event is None:
            response = await self._produce_summary(conversation)
        else:
            task = asyncio.create_task(self._produce_summary(conversation))
            cancelled = asyncio.create_task(self.cancel_event.wait())
            try:
                done, _ = await asyncio.wait(
                    (task, cancelled), return_when=asyncio.FIRST_COMPLETED
                )
                if cancelled in done and self.cancel_event.is_set():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise asyncio.CancelledError
                response = await task
            finally:
                task.cancel()
                cancelled.cancel()
                await asyncio.gather(task, cancelled, return_exceptions=True)
        label = "Turn prefix summarization" if prefix else "Summarization"
        reason = response.get("stopReason")
        if reason == "aborted":
            raise _SummaryAborted
        if reason == "error":
            raise RuntimeError(
                f"{label} failed: {response.get('errorMessage') or 'Unknown error'}"
            )
        if reason == "length":
            raise RuntimeError(
                f"{label} failed: generation hit the token cap and the summary is incomplete"
            )
        if any(
            block.get("type") == "toolCall" for block in response.get("content", [])
        ):
            raise RuntimeError(f"{label} attempted to call a tool")
        return content_text(response.get("content", [])), response.get("usage", {})

    async def compact(
        self,
        reason: str,
        *,
        focus: str | None = None,
        will_retry: bool = False,
        omit_entry_id: str | None = None,
    ) -> dict[str, Any] | None:
        self.active_reason = reason
        # Construct the recovery omission in a draft. Both the failed response
        # and all history remain visible on summary failure/cancellation.
        branch = self.session.branch()
        if omit_entry_id:
            branch = branch + [
                {
                    "type": "context_edit",
                    "id": "compaction-recovery-draft",
                    "parentId": branch[-1]["id"] if branch else None,
                    "targetId": omit_entry_id,
                    "replacement": None,
                }
            ]
        preparation = prepare_compaction(branch, self.options)
        if not preparation:
            if reason == "manual":
                self.events.append({"type": "compaction_start", "reason": reason})
                error = (
                    "Already compacted"
                    if branch and branch[-1].get("type") == "compaction"
                    else "Nothing to compact (session too small)"
                )
                self._end(reason, error=error)
            return None
        self.events.append({"type": "compaction_start", "reason": reason})
        try:
            history = preparation["messagesToSummarize"]
            previous = preparation.get("previousSummary")
            usages = []
            if preparation["isSplitTurn"] and preparation["turnPrefixMessages"]:
                history_text = previous if previous is not None else "No prior history."
                if history:
                    history_text, usage = await self._summary(history, previous, focus)
                    usages.append(usage)
                prefix_text, usage = await self._summary(
                    preparation["turnPrefixMessages"], None, focus, True
                )
                usages.append(usage)
                summary = (
                    history_text
                    + "\n\n---\n\n**Turn Context (split turn):**\n\n"
                    + prefix_text
                )
            else:
                summary, usage = await self._summary(history, previous, focus)
                usages.append(usage)
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise asyncio.CancelledError
            details = preparation["fileOps"]
            summary += format_file_operations(details)
            usage = {
                key: sum(value.get(key, 0) for value in usages)
                for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens")
            }
            usage["cost"] = {
                key: sum(value.get("cost", {}).get(key, 0) for value in usages)
                for key in ("input", "output", "cacheRead", "cacheWrite", "total")
            }
            result = {
                "summary": summary,
                "firstKeptEntryId": preparation["firstKeptEntryId"],
                "tokensBefore": preparation["tokensBefore"],
                "usage": usage,
                "details": details,
            }
            if omit_entry_id:
                omission = self.session.append(
                    "context_edit", targetId=omit_entry_id, replacement=None
                )
                if result["firstKeptEntryId"] == "compaction-recovery-draft":
                    result["firstKeptEntryId"] = omission["id"]
            self.session.append_compaction(result)
            result["estimatedTokensAfter"] = sum(
                estimate_tokens(m) for m in self.session.messages()
            )
            self._end(reason, result, retry=will_retry)
            return result
        except _SummaryAborted:
            self._end(reason, aborted=True)
            return None
        except asyncio.CancelledError:
            self._end(reason, aborted=True)
            # Explicit cancellation is local to compaction; cancelling the
            # enclosing asyncio task continues to propagate normally.
            if self.cancel_event is not None and self.cancel_event.is_set():
                return None
            raise
        except Exception as exc:
            prefix = (
                "Context overflow recovery failed: "
                if reason == "overflow"
                else "Auto-compaction failed: "
                if reason == "threshold"
                else ""
            )
            self._end(reason, error=prefix + str(exc))
            return None
