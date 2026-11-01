"""Original Hermes v0.22.5 incomplete Responses continuation helpers.

Only import paths and host/provider I/O boundaries differ; see
../CONTINUATION_SOURCES.json. Core function body is retained verbatim.
"""
from __future__ import annotations

import enum
from typing import Any, Optional

from ..message_content import flatten_message_text
from ..upstream_compaction.conversation_loop import _CODEX_INCOMPLETE_NUDGE
from ..upstream_compaction.message_metadata import append_message
from ..upstream_compaction.redact import redact_sensitive_text
from .truncation import boosted_output_cap




class FailoverReason(enum.Enum):
    """Why an API call failed — determines recovery strategy."""
    auth = "auth"                        # Transient auth (401/403) — refresh/rotate
    auth_permanent = "auth_permanent"    # Auth failed after refresh — abort
    billing = "billing"                  # 402 or confirmed credit exhaustion — rotate immediately
    rate_limit = "rate_limit"            # 429 or quota-based throttling — backoff then rotate
    upstream_rate_limit = "upstream_rate_limit"  # Aggregator's upstream model 429 — fallback model, key is healthy
    upstream_blocked = "upstream_blocked"  # 403 from a WAF/CDN/proxy in front of the provider — key is healthy, fallback
    overloaded = "overloaded"            # 503/529 — provider overloaded, backoff
    server_error = "server_error"        # 500/502 — internal server error, retry
    timeout = "timeout"                  # Connection/read timeout — rebuild client + retry
    ssl_cert_verification = "ssl_cert_verification"  # Deterministic TLS chain failure — fail fast with guidance
    context_overflow = "context_overflow"  # Context too large — compress, not failover
    payload_too_large = "payload_too_large"  # 413 — compress payload
    image_too_large = "image_too_large"   # Native image part exceeds provider's per-image limit — shrink and retry
    image_corrupt = "image_corrupt"       # Provider can't decode image bytes — strip and retry (shrinking won't help)
    model_not_found = "model_not_found"  # 404 or invalid model — fallback to different model
    provider_policy_blocked = "provider_policy_blocked"  # Aggregator account data/privacy policy excluded the only endpoint
    data_policy_denied = "data_policy_denied"  # Context holds a connector result needing a no-training model; none serves it
    content_policy_blocked = "content_policy_blocked"  # Provider safety filter rejected this prompt — deterministic per-request, don't retry unchanged
    model_entitlement = "model_entitlement"  # This account cannot use the requested model — rotate credential (model-scoped), else fall back
    incomplete_response = "incomplete_response"  # Codex/Responses turn stuck emitting reasoning only (no answer, no tool call) after replay + nudge — hand to a different provider
    format_error = "format_error"        # 400 bad request — abort or strip + retry
    role_alternation = "role_alternation"  # Strict chat template rejected adjacent same-role messages — merge them for this destination and retry
    invalid_encrypted_content = "invalid_encrypted_content"  # Responses replay blob rejected — strip replay state and retry
    multimodal_tool_content_unsupported = "multimodal_tool_content_unsupported"  # Provider rejected list-type content in tool messages (e.g. Xiaomi MiMo) — downgrade to text and retry
    reasoning_mandatory = "reasoning_mandatory"  # Route rejects reasoning: {enabled: false} — send the disable no more this session and retry

    # Provider-specific
    thinking_signature = "thinking_signature"  # Anthropic thinking block sig invalid
    long_context_tier = "long_context_tier"    # Anthropic "extra usage" tier gate
    oauth_long_context_beta_forbidden = "oauth_long_context_beta_forbidden"  # Anthropic OAuth rejects 1M beta — disable beta and retry
    llama_cpp_grammar_pattern = "llama_cpp_grammar_pattern"  # llama.cpp grammar rejects regex `pattern`/`format` — strip from tools and retry
    unknown = "unknown"


def partial_result(
    messages: list[dict[str, Any]], api_call_count: int, final_response: str,
    error: Optional[str] = None, *, failed: bool = False, compression_exhausted: bool = False,
) -> dict[str, Any]:
    """Typed incomplete-turn result (``partial`` unless ``failed``); ``error`` defaults to
    ``final_response``. ``compression_exhausted`` carries the #98722 typed bit the gateway
    consumes to reset/move future input to a clean session (see run_turn.py)."""
    result = {
        "final_response": final_response,
        "messages": messages,
        "api_calls": api_call_count,
        "completed": False,
        ("failed" if failed else "partial"): True,
        "error": final_response if error is None else error,
    }
    if compression_exhausted:
        result["compression_exhausted"] = True
    return result


_CODEX_REPLAY_KEYS = (
    "content", "reasoning", "reasoning_content", "reasoning_details",
    "codex_reasoning_items", "codex_message_items",
)


CODEX_FALLBACK_ACTIVATED = "codex_fallback_activated"


def continue_codex_incomplete(
    agent: Any, assistant_message: Any, finish_reason: str, *, messages: list[dict[str, Any]],
    conversation_history: Any, api_call_count: int, response: Any = None,
) -> Optional[Any]:
    """Codex Responses ``status=incomplete`` continuation (max 3 per turn).

    Appends the interim assistant message (deduped on visible content only — opaque
    provider state drifts per continuation; ``codex_reasoning_items`` are merged, not
    overwritten, because the earlier response holds the only native-compaction
    checkpoint) and, when a bare retry would be byte-identical, a user-role nudge — only
    after an assistant row, to preserve role alternation. Returns ``None`` to continue
    the turn loop, ``CODEX_FALLBACK_ACTIVATED`` when a reasoning-only stall was handed to
    the next fallback provider, or the terminal ``partial`` result once retries are exhausted.

    Reasoning-only stall ladder (#67321): a response with neither visible text nor a tool
    call advances ``_codex_reasoning_only_streak`` (a visible partial resets it; the aggregate
    ``_codex_incomplete_retries`` stays the cap for partials). Encrypted reasoning replays
    byte-for-byte, so after replay (1) and nudge (2) the third consecutive reasoning-only
    response goes to the configured fallback with the semantic ``incomplete_response`` reason
    instead of ending on the sentinel; when that response consumed the last iteration the
    fallback gets exactly one grace call (``_budget_grace_call`` is consumed by the next
    iteration, and the streak restarts from 0, so a second grace call is unreachable).

    When ``response`` hit ``max_output_tokens`` with no visible text (reasoning ate the
    whole budget), the next attempt goes out with reasoning off and a doubled output
    cap — the same one-shot overrides the chat-completions length path uses — because
    re-sending the identical budget and effort re-burns the budget identically (#90393)."""

    agent._codex_incomplete_retries += 1
    n = agent._codex_incomplete_retries

    interim_msg = agent._build_assistant_message(assistant_message, finish_reason)
    interim_has_content = bool((interim_msg.get("content") or "").strip())
    _reasoning = interim_msg.get("reasoning")
    interim_has_reasoning = isinstance(_reasoning, str) and bool(_reasoning.strip())
    interim_has_codex_reasoning = bool(interim_msg.get("codex_reasoning_items"))
    interim_has_codex_message_items = bool(interim_msg.get("codex_message_items"))
    reasoning_only = not interim_has_content and not getattr(assistant_message, "tool_calls", None)
    agent._codex_reasoning_only_streak = agent._codex_reasoning_only_streak + 1 if reasoning_only else 0
    streak = agent._codex_reasoning_only_streak

    if interim_has_content or interim_has_reasoning or interim_has_codex_reasoning or interim_has_codex_message_items:
        last_msg = messages[-1] if messages else None
        last_is_dict = isinstance(last_msg, dict)
        last_interim_visible = agent._interim_assistant_visible_text(last_msg) if last_is_dict else ""
        current_interim_visible = agent._interim_assistant_visible_text(interim_msg)
        if last_interim_visible or current_interim_visible:
            same_visible_output = last_interim_visible == current_interim_visible
        else:
            # Neither has text eligible for interim delivery: compare raw content+reasoning.
            same_visible_output = last_is_dict and (
                (last_msg.get("content") or "") == (interim_msg.get("content") or "")
                and (last_msg.get("reasoning") or "") == (interim_msg.get("reasoning") or "")
            )
        if (
            last_is_dict
            and last_msg.get("role") == "assistant"
            and last_msg.get("finish_reason") == "incomplete"
            and same_visible_output
        ):
            # Duplicate: refresh replay state in place, no re-emitted commentary.
            for _key in _CODEX_REPLAY_KEYS:
                if _key not in interim_msg:
                    continue
                if _key == "codex_reasoning_items":
                    from ..native_compaction import merge_interim_reasoning_items
                    last_msg[_key] = merge_interim_reasoning_items(last_msg.get(_key), interim_msg[_key])
                else:
                    last_msg[_key] = interim_msg[_key]
        else:
            append_message(messages, interim_msg)
            agent._emit_interim_assistant_message(interim_msg)

    if reasoning_only and streak >= 3:
        if agent._try_activate_fallback(reason=FailoverReason.incomplete_response):
            # The trigger may have consumed the turn budget; without a grace call the loop
            # exits before the fallback is ever asked.
            if api_call_count >= agent.max_iterations or agent.iteration_budget.remaining <= 0:
                agent._budget_grace_call = True
            agent._codex_incomplete_retries = 0
            agent._codex_reasoning_only_streak = 0
            if not agent.quiet_mode:
                agent._vprint(
                    f"{agent.log_prefix}↻ Codex reasoning-only stall after {streak} attempts — "
                    f"switching to fallback {agent.model} ({agent.provider})", diagnostic=True,
                )
            agent._emit_diagnostic_wait("↻ model stuck on internal reasoning — switching to fallback provider")
            agent._session_messages = messages
            return CODEX_FALLBACK_ACTIVATED
        # No fallback left: fall through to the terminal sentinel.
    elif n < 3 or reasoning_only:
        # A reasoning-only streak below 3 continues even once partials used up the aggregate
        # cap, so the mixed partial-then-stall variant reaches the ladder above.
        # If the interim has nothing the Responses converter will replay, a bare retry is
        # byte-identical; a replayable interim holding only a ``compaction`` checkpoint
        # ALSO re-sends identically. One bare retry, then always nudge.
        interim_replayable = interim_has_content or interim_has_codex_reasoning or interim_has_codex_message_items
        if not interim_replayable or n >= 2:
            _last_msg = messages[-1] if messages else None
            if isinstance(_last_msg, dict):
                _already_nudged = (
                    _last_msg.get("role") == "user" and _last_msg.get("content") == _CODEX_INCOMPLETE_NUDGE
                )
                # Alternation guard: the nudge may only follow an assistant row.
                if not _already_nudged and _last_msg.get("role") == "assistant":
                    append_message(messages, {"role": "user", "content": _CODEX_INCOMPLETE_NUDGE})
        if not interim_has_content and _codex_finish_reason(response) == "incomplete":
            agent._ephemeral_reasoning_off = True
            # No configured cap means the provider's own ceiling was hit: the observed
            # output_tokens IS that ceiling, so seed the escalation from it (else 4096).
            usage = getattr(response, "usage", None)
            observed = getattr(usage, "output_tokens", None) if not isinstance(usage, dict) else usage.get("output_tokens")
            agent._ephemeral_max_output_tokens = boosted_output_cap(
                agent, None, n, base=agent.max_tokens or int(observed or 0) or 4096
            )
        if not agent.quiet_mode:
            agent._vprint(f"{agent.log_prefix}↻ Codex response incomplete; continuing turn ({n}/3)", diagnostic=True)
        # Spinner/heartbeat notice: these retries can take minutes and otherwise look
        # like infinite thinking.
        # #70773: same FD-recycle corruption vector as #67142. The shared OpenAI client's connection pool
        # must NOT be closed from this watchdog/poll thread — worker threads from previous stale-killed
        # attempts may still be unwinding their SSL BIOs. The request-local client is already closed above
        # via _close_request_client_once. The shared client will be replaced lazily by
        # _ensure_primary_openai_client on the next request.
        # Surface the continuation on the live spinner/status line (CLI/TUI/Desktop) and gateway heartbeat:
        # each of these retries can spend minutes waiting on the provider, and without a distinct notice the
        # user only sees a generic thinking spinner ("infinite thinking", #64434).
        agent._emit_diagnostic_wait(
            f"↻ model returned reasoning with no final answer — asking it to continue ({n}/3)"
        )
        agent._session_messages = messages
        return None

    agent._codex_incomplete_retries = 0
    agent._codex_reasoning_only_streak = 0
    agent._persist_session(messages, conversation_history)
    return partial_result(
        messages, api_call_count, "Codex response remained incomplete after 3 continuation attempts"
    )


def _codex_finish_reason(response: Any) -> str:
    """Responses API max-output exhaustion is a normal Codex incomplete turn: route it to
    the Codex continuation path (``"incomplete"``), not the length rollback."""
    status = getattr(response, "status", None)
    if isinstance(status, str):
        status = status.strip().lower()
    incomplete_details = getattr(response, "incomplete_details", None)
    if isinstance(incomplete_details, dict):
        incomplete_reason = incomplete_details.get("reason")
    else:
        incomplete_reason = getattr(incomplete_details, "reason", None)
    if incomplete_reason is not None:
        incomplete_reason = str(incomplete_reason).strip().lower()
    if status == "incomplete" and incomplete_reason in {"max_output_tokens", "length"}:
        return "incomplete"
    if status == "incomplete" and incomplete_reason == "content_filter":
        return "content_filter"
    return "stop"


def visible_commentary(text: str, *, strip_thinking=None) -> str:
    """Use the same think stripping and secret redaction as live delivery."""
    if strip_thinking is None:
        from ..policy import strip_think_blocks

        strip_thinking = lambda value: strip_think_blocks(None, value)

    visible = strip_thinking(text).strip()
    return redact_sensitive_text(visible) if visible else visible


class InterimVisibleText:
    def _extract_codex_interim_visible_parts(self, assistant_msg: dict[str, Any]) -> list[str]:
            """Visible Codex commentary (``phase=commentary`` items), one string per message item.

            ``phase=analysis`` stays hidden (scratchpad); with ``display.show_commentary=false``
            commentary stays on the reasoning channel.
            """
            items = assistant_msg.get("codex_message_items") if getattr(self, "show_commentary", True) else None
            messages: list[str] = []
            for item in items if isinstance(items, list) else ():
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                phase, content_parts = item.get("phase"), item.get("content")
                if not isinstance(phase, str) or phase.strip().lower() != "commentary" or not isinstance(content_parts, list):
                    continue
                visible = "".join(
                    part["text"] for part in content_parts
                    if isinstance(part, dict) and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str) and part["text"].strip()
                ).strip()
                visible = self._visible_commentary(visible)
                if visible:
                    messages.append(visible)
            return messages


    def _visible_commentary(self, text: str) -> str:
            """Think-stripped, redacted commentary text ("" when nothing visible remains)."""
            return visible_commentary(text, strip_thinking=self._strip_think_blocks)


    def _extract_codex_interim_visible_text(self, assistant_msg: dict[str, Any]) -> str:
            """All visible Codex commentary joined, for comparison/fallback."""
            return "\n\n".join(self._extract_codex_interim_visible_parts(assistant_msg)).strip()


    def _interim_assistant_visible_text(self, assistant_msg: dict[str, Any]) -> str:
            """Assistant text eligible for interim delivery: structured Codex commentary first — a response can
            hold commentary AND a partial final answer while tools are pending, and treating content as
            progress leaks the answer early — else top-level content (may be a parts list)."""
            return (
                self._extract_codex_interim_visible_text(assistant_msg)
                or self._strip_think_blocks(flatten_message_text(assistant_msg.get("content"))).strip()
            )
