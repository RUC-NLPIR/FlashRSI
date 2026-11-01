"""Async host for Hermes's independent per-request retry/recovery budget.

The classifier, delay parsing, jitter, overload schedule, and post-exhaustion
ladder policies are the original pinned Python. The host uses cancellable async
waits; provider credentials and routes are supplied explicitly by the role.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from .upstream_loop import retry_utils
from .upstream_loop.auto_recovery import ladder_eligible, ladder_wait_seconds
from .upstream_loop.error_classifier import (
    RETRYABLE_CLIENT_REASONS,
    FailoverReason,
    classify_api_error,
)
from .upstream_loop.recovery import _TRANSIENT_TRANSPORT_ERRORS
from .upstream_loop.recovery_reasons import (
    _RATE_LIMIT_REASONS,
    _TRANSPORT_FAILURE_REASONS,
)
from .upstream_loop.urls import base_url_host_matches


class InvalidResponseError(ValueError):
    """Successful HTTP envelope with an unusable assistant response."""


class ProviderError(RuntimeError):
    """Keep the structured provider body at the SDK-free HTTP boundary."""

    def __init__(self, response, body):
        self.response = response
        self.status_code = response.status_code
        self.body = body
        self.message = str(body)
        super().__init__(self.message)


def _integer(value, default, minimum):
    try:
        return max(int(value), minimum)
    except (TypeError, ValueError):
        return default


async def sleep(seconds):
    # asyncio cancellation interrupts waits immediately, with no worker left
    # behind to issue a request after the role has timed out.
    await asyncio.sleep(seconds)


class RetryBudget:
    def __init__(
        self,
        settings,
        route,
        event_sink,
        *,
        activate_fallback=None,
        rebuild_transport=None,
        recovery=None,
    ):
        section = settings.get("agent") or {}
        if not isinstance(section, dict):
            section = {}
        section = {
            **section,
            **{
                name: settings[name]
                for name in ("api_max_retries", "auto_recovery_cycles")
                if name in settings
            },
        }
        self.maximum = _integer(section.get("api_max_retries", 3), 3, 1)
        self.cycles = _integer(section.get("auto_recovery_cycles", 5), 5, 0)
        self.route = route
        self.emit = event_sink
        self.attempts = 0
        self.cycles_used = 0
        self.activate_fallback = activate_fallback
        self.rebuild_transport = rebuild_transport
        self.primary_recovered = False
        self.recovery = recovery

    async def recover(
        self, error, *, approx_tokens=0, context_length=200000, num_messages=0
    ):
        if self.recovery is not None and self.recovery.before(error):
            return True
        invalid = isinstance(error, InvalidResponseError)
        verdict = classify_api_error(
            error,
            provider=self.route.get("provider", ""),
            model=self.route.get("model_name", ""),
            base_url=self.route.get("base_url", ""),
            api_key=self.route.get("api_key"),
            approx_tokens=approx_tokens,
            context_length=context_length,
            num_messages=num_messages,
        )
        if self.recovery is not None and self.recovery.after(error, verdict):
            return True
        self.attempts += 1
        zai_overload = retry_utils.is_zai_coding_overload_error(
            base_url=self.route.get("base_url"),
            model=self.route.get("model_name"),
            error=error,
        )
        if zai_overload:
            self.maximum = max(
                self.maximum, retry_utils.zai_coding_overload_retry_ceiling()
            )
        local_validation = isinstance(error, (ValueError, TypeError)) and not invalid
        spent = self.recovery is not None and (
            (verdict.reason == FailoverReason.reasoning_mandatory and self.recovery.retry_state.reasoning_mandatory_retry_attempted)
            or (verdict.reason == FailoverReason.image_too_large and self.recovery.retry_state.image_shrink_retry_attempted)
        )
        terminal = not invalid and (
            local_validation or spent
            or (
                not verdict.retryable and verdict.reason not in RETRYABLE_CLIENT_REASONS
            )
        )
        if verdict.should_compress:
            return False
        # No implicit credential discovery exists in this role runtime. Once
        # original credential-pool recovery is unavailable, upstream eagerly
        # switches rate limits / invalid envelopes, and transport after one retry.
        eager_fallback = (
            invalid
            or verdict.is_auth
            or verdict.reason in _RATE_LIMIT_REASONS
            or (verdict.reason in _TRANSPORT_FAILURE_REASONS and self.attempts >= 2)
        ) and not verdict.error_context.get("usage_window")
        if self.activate_fallback and (
            eager_fallback
            or (terminal and (verdict.should_fallback or local_validation or spent))
        ):
            if self.activate_fallback(verdict.reason):
                return True
        if terminal:
            return False
        if self.attempts >= self.maximum:
            # Recreate one poisoned HTTP connection pool before the fallback
            # walk, matching try_recover_primary_transport's original gates.
            if (
                self.rebuild_transport is not None
                and not self.primary_recovered
                and type(error).__name__ in _TRANSIENT_TRANSPORT_ERRORS
                and not base_url_host_matches(
                    self.route.get("base_url", ""), "openrouter.ai"
                )
                and self.route.get("provider", "").lower()
                not in {"nous", "nous-portal", "nousresearch"}
            ):
                self.primary_recovered = True
                await self.rebuild_transport()
                delay = min(3 + self.attempts, 8)
                self.attempts = 0
                self.emit(
                    {
                        "type": "api_retry",
                        "reason": "primary_transport_recovery",
                        "delay_seconds": delay,
                    }
                )
                await sleep(delay)
                return True
            if self.activate_fallback and self.activate_fallback(verdict.reason):
                return True
            host = SimpleNamespace(
                _auto_recovery_cycles=self.cycles,
                _current_streamed_assistant_text="",
                _has_content_after_think_block=bool,
            )
            if (
                invalid
                or not ladder_eligible(host, verdict)
                or self.cycles_used >= self.cycles
            ):
                return False
            self.cycles_used += 1
            delay = ladder_wait_seconds(self.cycles_used, error)
            self.attempts = 0
            kind = "auto_recovery"
        else:
            kind = "invalid_response" if invalid else verdict.reason.value
            retry_after = retry_utils.provider_retry_after_seconds(error)
            if retry_after is not None and not invalid:
                delay = min(retry_after, retry_utils.RETRY_AFTER_CAP_S)
            else:
                delay = retry_utils.jittered_backoff(
                    self.attempts,
                    base_delay=5.0 if invalid else 2.0,
                    max_delay=120.0 if invalid else 60.0,
                )
                if verdict.reason == FailoverReason.rate_limit or zai_overload:
                    delay, _ = retry_utils.adaptive_rate_limit_backoff(
                        self.attempts,
                        base_url=self.route.get("base_url"),
                        model=self.route.get("model_name"),
                        error=error,
                        default_wait=delay,
                    )
        self.emit(
            {
                "type": "api_retry",
                "reason": kind,
                "attempt": self.attempts,
                "max_attempts": self.maximum,
                "auto_recovery_cycle": self.cycles_used,
                "delay_seconds": delay,
            }
        )
        await sleep(delay)
        return True
