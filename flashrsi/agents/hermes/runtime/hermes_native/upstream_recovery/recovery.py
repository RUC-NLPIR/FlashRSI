from __future__ import annotations
import logging
import locale
import math
import re
from typing import Any, Optional
from ..upstream_loop.error_classifier import FailoverReason
from .retry_state import TurnRetryState
from .codex import _is_codex_token_expired, _recover_stale_codex_reasoning
from .vision import _provider_model_key
from .sanitization import (_looks_like_corrupt_image_rejection, _looks_like_image_content_rejection, _sanitize_messages_non_ascii, _sanitize_messages_surrogates, _sanitize_structure_non_ascii, _sanitize_structure_surrogates, _strip_images_from_messages, _strip_non_ascii, record_reasoning_field_rejection)
from .boundaries import (_recover_welcome_tier, _pool_error_context, _try_refresh_nous_paid_entitlement_credentials, _refresh_credentials_after_401, fast_mode_unprovisioned, mark_fast_mode_unavailable)
logger=logging.getLogger(__name__)

logger = logging.getLogger("agent.conversation_loop")


def _runtime_uses_ascii_encoding() -> bool:
    """Return whether the process genuinely needs an ASCII-only request fallback."""
    encoding = locale.getpreferredencoding(False).strip().lower().replace("_", "-")
    return encoding in {"ascii", "us-ascii", "ansi-x3.4-1968"}


def _vlines(agent: Any, *lines: str) -> None:
    """Force-``_vprint`` each line prefixed with ``agent.log_prefix``."""
    for line in lines:
        agent._vprint(f"{agent.log_prefix}{line}", force=True, diagnostic=True)


def _image_error_max_dimension(error: Exception) -> Optional[int]:
    """Extract a provider-reported image dimension ceiling, if present."""
    parts = []
    for value in (error, getattr(error, "message", None), getattr(error, "body", None)):
        if value:
            try:
                parts.append(str(value))
            except Exception:
                pass
    text = " ".join(parts).lower()
    # OpenAI Codex Responses reports a tile-patch budget (ceil(w/32)×ceil(h/32))
    # instead of a pixel ceiling. A square image is the worst case for the budget,
    # so a per-side cap of isqrt(limit)*32 px keeps isqrt(limit)² ≤ limit — for the
    # 30000-patch ceiling that is 5536 px. Without this the caller falls back to
    # 8000 px and a 6000 px image that already exceeds the budget is skipped (#106337).
    if "patches after processing" in text:
        match = re.search(r"exceeding the limit of\s*(\d{2,7})", text)
        if not match:
            return None
        max_dimension = math.isqrt(int(match.group(1))) * 32
        return max_dimension if 512 <= max_dimension <= 8000 else None
    if "image" not in text or "dimension" not in text or "max allowed size" not in text:
        return None
    match = re.search(r"max allowed size(?:\s+for [^:]+)?:\s*(\d{3,5})\s*pixels?", text)
    if not match:
        return None
    try:
        max_dimension = int(match.group(1))
    except ValueError:
        return None
    return max_dimension if 512 <= max_dimension <= 8000 else None


def _repair_transport_credentials(agent: Any) -> bool:
    """Strip non-ASCII from ``_client_kwargs["default_headers"]`` and the API key.

    Non-ASCII in the key makes httpx fail encoding the Authorization header — the usual
    persistent cause of UnicodeEncodeError that survives message/tool sanitization (#6843,
    e.g. ʋ instead of v from a bad copy-paste). Entra ID bearer providers are callables
    minting ASCII JWTs; skip them (``_strip_non_ascii`` would crash). Returns True when
    either the headers or the key were repaired.
    """
    _client_kwargs = getattr(agent, "_client_kwargs", None)
    _default_headers = _client_kwargs.get("default_headers") if isinstance(_client_kwargs, dict) else None
    _repaired = bool(isinstance(_default_headers, dict) and _sanitize_structure_non_ascii(_default_headers))
    _raw_key = getattr(agent, "api_key", None) or ""
    if isinstance(_raw_key, str) and _raw_key:
        _clean_key = _strip_non_ascii(_raw_key)
        if _clean_key != _raw_key:
            agent.api_key = _clean_key
            if isinstance(_client_kwargs, dict):
                _client_kwargs["api_key"] = _clean_key
            # The live client reads its own api_key copy on every request.
            if getattr(agent, "client", None) is not None and hasattr(agent.client, "api_key"):
                agent.client.api_key = _clean_key
            _repaired = True
            _vlines(
                agent,
                "⚠️  API key contained non-ASCII characters (bad copy-paste?) — stripped them. "
                "If auth fails, re-copy the key from your provider's dashboard.",
            )
    return _repaired


def _recover_unicode_encode_error(
    agent: Any, api_error: Exception, messages: list[dict[str, Any]], api_messages: Any,
    api_kwargs: Any, active_system_prompt: Any,
) -> tuple[bool, Any]:
    """UnicodeEncodeError recovery: lone surrogates (clipboard paste) first, then an ASCII
    codec under a non-UTF-8 locale. Sanitizes in place; bounded by the caller's
    ``_unicode_sanitization_passes < 2`` guard (surrogate strip, then ASCII-only)."""
    _err_str = str(api_error).lower()
    _is_ascii_codec = "'ascii'" in _err_str or "ascii" in _err_str
    # utf-8 refusing U+D800..U+DFFF ("surrogates not allowed").
    _is_surrogate_error = "surrogate" in _err_str or ("'utf-8'" in _err_str and not _is_ascii_codec)
    # Sanitize canonical messages for surrogate recovery, but keep ASCII recovery
    # request-local: API copies may carry fields absent from the durable transcript.
    _surrogates_found = _sanitize_messages_surrogates(messages)
    _surrogates_found |= isinstance(api_messages, list) and _sanitize_messages_surrogates(api_messages)
    _surrogates_found |= isinstance(api_kwargs, dict) and _sanitize_structure_surrogates(api_kwargs)
    # Gate the retry on the error type, not on whether anything was found — a new
    # transformed field could slip through.
    if _surrogates_found or _is_surrogate_error:
        if _surrogates_found:
            # In-place rewrites may have popped _DB_PERSISTED_MARKER off stamped live dicts;
            # force a full flush scan so the repaired rows are rewritten.
            agent._db_flush_scan_prefix = None
        agent._unicode_sanitization_passes += 1
        agent._buffer_vprint(
            "⚠️  Stripped invalid surrogate characters from messages. Retrying..."
            if _surrogates_found else
            "⚠️  Surrogate encoding error — retrying after full-payload sanitization..."
        )
        return True, active_system_prompt
    if not _is_ascii_codec:
        return False, active_system_prompt

    # Error text is provider-controlled and can mention ``ascii`` even when the
    # process sends UTF-8. In that normal case, do not rewrite conversation,
    # tools, prompts, or prefill; only repair values that can poison an ASCII
    # transport header. If nothing was repaired, an identical retry cannot
    # succeed — return False so the error surfaces through the normal path
    # instead of burning both sanitization passes on unchanged requests.
    if not _runtime_uses_ascii_encoding():
        if not _repair_transport_credentials(agent):
            return False, active_system_prompt
        agent._unicode_sanitization_passes += 1
        _vlines(
            agent,
            "⚠️  Repaired non-ASCII request credentials/headers without changing conversation content. Retrying...",
        )
        return True, active_system_prompt

    agent._force_ascii_payload = True
    # Strip all non-ASCII from the request-local api_messages (reused across retries). The
    # failed attempt's api_kwargs is NOT touched: build_api_request rebuilds it from
    # ``agent.tools`` on the next iteration and ``sanitize_outbound_kwargs`` strips the whole
    # payload under ``_force_ascii_payload``. Canonical agent state stays byte-stable.
    _messages_sanitized = isinstance(api_messages, list) and _sanitize_messages_non_ascii(api_messages)

    _system_sanitized = False
    if isinstance(active_system_prompt, str):
        _sanitized_system = _strip_non_ascii(active_system_prompt)
        if _sanitized_system != active_system_prompt:
            active_system_prompt = _sanitized_system
            _system_sanitized = True

    _transport_repaired = _repair_transport_credentials(agent)

    # Always retry on ASCII codec detection: _force_ascii_payload sanitizes the full
    # api_kwargs next iteration even when the checks above find nothing.
    agent._unicode_sanitization_passes += 1
    _vlines(
        agent,
        "⚠️  System encoding is ASCII — stripped non-ASCII characters from request payload. Retrying..."
        if (_messages_sanitized or _system_sanitized or _transport_repaired) else
        "⚠️  System encoding is ASCII — enabling full-payload sanitization for retry...",
    )
    return True, active_system_prompt


def _strip_request_images_and_retry(agent: Any, api_messages: Any) -> bool:
    """Strip image parts from the per-call ``api_messages`` copy; True if anything was removed.

    Shared by the corrupt-image recoveries: a bad payload says nothing about the model, so it
    is stripped for this attempt only and the model is never recorded as image-rejecting."""
    if isinstance(api_messages, list) and _strip_images_from_messages(api_messages):
        _vlines(agent, "⚠️  Provider rejected a corrupted image — stripped images from the retry payload and retrying...")
        return True
    return False


def recover_before_classification(
    agent: Any, api_error: Exception, *, messages: list[dict[str, Any]], api_messages: Any,
    api_kwargs: Any, active_system_prompt: Any,
) -> tuple[bool, Any]:
    """Recovery branches that run BEFORE ``classify_api_error``: UnicodeEncodeError
    sanitization, Anthropic fast mode with no capacity (drop ``speed`` for that model),
    provider image-content rejection (record the (provider, model);
    build_api_request strips images from that model's requests only), an unknown-field
    rejection naming a replayed reasoning key (recorded per (provider, host, model),
    stripped on the retry), and the Bedrock
    AnthropicBedrock SDK streaming fallback. Returns ``(retry_now, active_system_prompt)``;
    the prompt may be ASCII-sanitized in place."""
    if isinstance(api_error, UnicodeEncodeError) and getattr(agent, '_unicode_sanitization_passes', 0) < 2:
        _recovered, active_system_prompt = _recover_unicode_encode_error(
            agent, api_error, messages, api_messages, api_kwargs, active_system_prompt
        )
        if _recovered:
            return True, active_system_prompt

    # Anthropic fast mode with no capacity: a 429 whose fast-mode limit header is 0 can never
    # succeed at fast speed, and it says nothing about the key's standard-speed limits. Stop
    # sending ``speed`` to this model and retry now, before credential rotation benches the key.
    if fast_mode_unprovisioned(api_error, api_kwargs) and mark_fast_mode_unavailable(agent):
        _vlines(agent, f"⚠️  Fast mode isn't available for {agent.model} on this Anthropic organization — using standard speed for this session, retrying...")
        logger.warning("%sFast mode: %s has a fast-mode limit of 0; standard speed for this session", agent.log_prefix, agent.model)
        return True, active_system_prompt

    # Some providers 4xx on image_url content: record the (provider, model) and retry;
    # build_api_request strips images from that model's requests only. English phrase
    # match; extend it.
    _err_body = ""
    try:
        _err_body = str(getattr(api_error, "body", None) or getattr(api_error, "message", None) or str(api_error))
    except Exception:
        pass
    _err_status = getattr(api_error, "status_code", None)
    # 4xx-only gate: 5xx/timeouts are transient and take the retry path.
    _status_ok = _err_status is None or (400 <= int(_err_status) < 500)
    # Guarded PER MODEL, not by a turn-global flag: in a fallback chain the next model can reject
    # images too, and a turn-wide flag would skip its recovery and fail the turn.
    _model_key = _provider_model_key(agent)
    _rejected = agent._image_rejecting_models
    _corrupt = _looks_like_corrupt_image_rejection(_err_body)
    if _status_ok and (_corrupt or (_model_key not in _rejected and _looks_like_image_content_rejection(_err_body))):
        # Send-path only. A rejection says what THIS model accepts, not what the conversation
        # holds: stripping ``messages`` (canonical history) and forcing a flush deleted every
        # image — and every image-only message — from state.db for good, so a later switch to a
        # vision model found them gone. Same failure as the ASCII strip in #117802.
        if _corrupt:
            # A bad payload says nothing about the model's capability: strip this attempt only
            # (like the image_corrupt branch below) and leave the model unmarked so a later good
            # image still reaches it. Retry only if something was stripped, or a text-only
            # request would loop on the same error.
            if _strip_request_images_and_retry(agent, api_messages):
                return True, active_system_prompt
        else:
            # Record the model; the retry re-enters build_api_request with the same
            # api_messages and strip_images_for_rejecting_model strips them there.
            _rejected.add(_model_key)
            _vlines(
                agent,
                "⚠️  Server rejected image content — sending text only to this model; "
                "images stay in the session history.",
            )
            return True, active_system_prompt

    # A strict schema rejected a replayed reasoning key BY NAME: record it per (provider, host, model)
    # and retry once; build_api_request re-shapes api_messages without it. An unnamed upstream error
    # never counts, and a key already recorded falls through to normal handling (no loop).
    _sent = api_kwargs.get("messages") if isinstance(api_kwargs, dict) else None
    if _status_ok and (_new := record_reasoning_field_rejection(agent, _err_body, _sent or api_messages)):
        _vlines(agent, f"⚠️  {agent.model} rejected replayed {', '.join(sorted(_new))} — retrying without it for this model.")
        return True, active_system_prompt

    # AnthropicBedrock SDK raises "Unexpected event order" when Bedrock errors before
    # message_start; fall back to native Converse for this session.
    if (
        isinstance(api_error, RuntimeError)
        and "unexpected event order" in str(api_error).lower()
        and getattr(agent, "provider", "") == "bedrock"
        and agent.api_mode == "anthropic_messages"
        and not getattr(agent, "_bedrock_converse_fallback_attempted", False)
    ):
        agent._bedrock_converse_fallback_attempted = True
        agent.api_mode = "bedrock_converse"
        agent._bedrock_region = getattr(agent, "_bedrock_region", None) or "us-east-1"
        agent.client = None  # Drop the AnthropicBedrock client
        agent._client_kwargs = {}
        _vlines(agent, "⚠️  AnthropicBedrock SDK streaming failed — falling back to native Converse API for this session.")
        return True, active_system_prompt
    return False, active_system_prompt


def _recover_format_errors(
    agent: Any, api_error: Exception, classified: Any, _retry: TurnRetryState,
    messages: list[dict[str, Any]], api_messages: Any,
) -> bool:
    """One-shot format-recovery strips: thinking-signature → invalid-encrypted-content
    replay disable → native-compaction reject → llama.cpp grammar strip. Returns True when
    the request was repaired and should be retried."""
    # Upstream mutation can invalidate a thinking signature. Native Anthropic has multiple replay
    # carriers and preserved historical blocks, so suppress the rejected opaque blocks across all
    # carriers and persist that suppression. Other transports keep their established one-request
    # repair: drop reasoning_details only.
    if classified.reason == FailoverReason.thinking_signature and not _retry.thinking_sig_retry_attempted:
        _retry.thinking_sig_retry_attempted = True
        from .boundaries import remember_rejected_thinking, tracks_rejected_thinking

        if tracks_rejected_thinking(agent):
            removed = remember_rejected_thinking(agent, api_messages)
            detail = "suppressed rejected Anthropic replay blocks"
        else:
            removed = 0
            for message in api_messages:
                if isinstance(message, dict) and "reasoning_details" in message:
                    message.pop("reasoning_details", None)
                    removed += 1
            detail = "stripped reasoning_details"
        _vlines(agent, f"⚠️  Thinking block signature invalid, {detail} and retrying...")
        logger.warning(
            "%sThinking block signature recovery: %s from %d carrier/message(s) "
            "(canonical messages unchanged)",
            agent.log_prefix, detail, removed,
        )
        return True

    # 400 ``invalid_encrypted_content`` on a stale ``codex_reasoning_items`` blob (the 401
    # ``token_expired`` twin is taken ahead of the credential pool in the caller).
    if classified.reason == FailoverReason.invalid_encrypted_content and _recover_stale_codex_reasoning(
        agent, _retry, messages, api_messages
    ):
        return True

    # Structured 400 naming ``context_management``: disable native compaction for the
    # session, retry once; local compression takes over.
    if (
        agent.api_mode == "codex_responses"
        and not _retry.native_compaction_reject_retry_attempted
        and bool(getattr(agent, "codex_responses_native_compaction", False))
    ):
        from ..native_compaction import is_native_compaction_rejection
        if is_native_compaction_rejection(api_error, getattr(api_error, "status_code", None)):
            _retry.native_compaction_reject_retry_attempted = True
            agent.codex_responses_native_compaction = False
            _vlines(
                agent,
                "⚠️  Provider rejected native compaction (context_management) — disabled for this session, "
                "local compression stays active. Retrying...",
            )
            logger.warning(
                "%sNative compaction rejection recovery: disabled "
                "codex_responses_native for this session and retrying",
                agent.log_prefix,
            )
            return True

    # llama.cpp ``json-schema-to-grammar`` rejects regex escapes and most ``format``
    # values: strip ``pattern``/``format`` from ``agent.tools``, retry once.
    if classified.reason == FailoverReason.llama_cpp_grammar_pattern and not _retry.llama_cpp_grammar_retry_attempted:
        _retry.llama_cpp_grammar_retry_attempted = True
        try:
            from .schema import strip_pattern_and_format
            _, _stripped = strip_pattern_and_format(agent.tools)
        except Exception as _strip_exc:  # pragma: no cover — defensive
            logger.warning("%sllama.cpp grammar recovery: strip helper failed: %s", agent.log_prefix, _strip_exc)
            _stripped = 0
        if _stripped:
            _vlines(agent, f"⚠️  llama.cpp rejected tool schema grammar — stripped {_stripped} pattern/format keyword(s), retrying...")
            logger.warning(
                "%sllama.cpp grammar recovery: stripped %d "
                "pattern/format keyword(s) from tool schemas",
                agent.log_prefix, _stripped,
            )
            return True
        # Nothing to strip — fall through to normal retry rather than loop on the same error.
        logger.warning(
            "%sllama.cpp grammar error but no pattern/format "
            "keywords to strip — falling through to normal retry",
            agent.log_prefix,
        )
    return False


def _clamp_to_affordable_budget(agent: Any, api_error: Exception, classified: Any, _retry: TurnRetryState) -> bool:
    """A credit-limited 402 (OpenRouter: "...requested up to 65536 tokens, but can only afford
    56272") means the account has credit and the output cap was too large: retry ONCE with the
    cap lowered to the affordable budget instead of abandoning the provider as billing (#49769).
    Same budget parse as the auxiliary client's retry. The 402 itself says the request's cap
    exceeded the budget (which may be a boosted continuation cap above ``agent.max_tokens``),
    so a second credit-limited 402 on this call is genuine exhaustion."""
    if classified.reason != FailoverReason.billing or _retry.affordable_402_clamp_attempted:
        return False
    from .affordable import _affordable_max_tokens_from_error

    affordable = _affordable_max_tokens_from_error(api_error)
    if affordable is None:
        return False
    _retry.affordable_402_clamp_attempted = True
    agent._ephemeral_max_output_tokens = affordable
    _vlines(agent, f"💳 Credit balance covers fewer output tokens — retrying with max_tokens={affordable:,}...")
    logger.info("%sCredit-limited 402: retrying once with max_tokens=%d", agent.log_prefix, affordable)
    return True


def _reject_all_turns(agent: Any, api_error: Exception) -> bool:
    reject = getattr(agent._get_transport(), "reject_all_turns", None)
    return bool(reject(api_error)) if callable(reject) else False


def recover_after_classification(
    agent: Any, api_error: Exception, classified: Any, _retry: TurnRetryState, *,
    status_code: Optional[int], error_context: Any, messages: list[dict[str, Any]],
    api_messages: Any,
) -> tuple[bool, bool]:
    """One-shot recovery chain that runs AFTER ``classify_api_error`` and before the
    generic retry path. Order is load-bearing (each branch may ``return`` early):
    welcome-tier repair → credit-limited 402 output-cap clamp → ``reasoning.context`` opt-out → Nous paid-entitlement refresh →
    Codex stale-reasoning strip on 401 ``token_expired`` → credential-pool rotation → image shrink → multimodal-tool-content strip → corrupt-image
    strip → Anthropic OAuth 1M-beta disable → per-provider 401 credential refresh →
    format-recovery strips.
    Returns ``(retry_now, recovered_with_pool)``; the latter feeds the Nous rate-limit guard."""
    from .boundaries import _is_nous_inference_route

    # The credit-limited 402 clamp runs before pool rotation, which would bench a credential
    # that still has credit. A ``reasoning.context`` 400 is classified reasoning_mandatory, whose rung
    # would drop the whole reasoning config; omit only the all_turns opt-in, ahead of it.
    if _recover_welcome_tier(agent, classified, _retry) or _clamp_to_affordable_budget(
        agent, api_error, classified, _retry
    ) or (agent.api_mode == "codex_responses" and _reject_all_turns(agent, api_error)):
        return True, False

    # 401 ``token_expired`` while the transcript still carries ``codex_reasoning_items`` is a
    # stale replayed blob far more often than a dead bearer (#88510): strip BEFORE the pool
    # refreshes/benches every healthy entry over a session-state problem. A real expiry pays
    # one extra round-trip and then takes the credential path below as before.
    if _is_codex_token_expired(agent, api_error) and _recover_stale_codex_reasoning(
        agent, _retry, messages, api_messages
    ):
        return True, False

    if (
        classified.reason == FailoverReason.billing
        # A usage-window 402 is the plan's own limit: refreshing credentials cannot lift it.
        and not (getattr(classified, "error_context", None) or {}).get("usage_window")
        and _is_nous_inference_route(
            getattr(agent, "provider", "") or "", getattr(agent, "base_url", "") or ""
        )
        and not _retry.nous_paid_entitlement_refresh_attempted
    ):
        _retry.nous_paid_entitlement_refresh_attempted = True
        if _try_refresh_nous_paid_entitlement_credentials(agent):
            _vlines(agent, "🔐 Nous paid access verified — refreshed runtime credentials and retrying request...")
            return True, False

    recovered_with_pool, _retry.has_retried_429 = agent._recover_with_credential_pool(
        status_code=status_code, has_retried_429=_retry.has_retried_429,
        classified_reason=classified.reason, error_context=_pool_error_context(agent, classified, error_context),
        billing_unverified=classified.billing_unverified,
    )
    if recovered_with_pool:
        return True, recovered_with_pool

    # Shrink oversized native image parts in-place and retry once.
    if classified.reason == FailoverReason.image_too_large and not _retry.image_shrink_retry_attempted:
        _retry.image_shrink_retry_attempted = True
        if agent._try_shrink_image_parts_in_messages(
            api_messages, max_dimension=_image_error_max_dimension(api_error) or 8000
        ):
            _vlines(agent, "📐 Image(s) exceeded provider size limit — shrank and retrying...")
            return True, recovered_with_pool
        logger.info(
            "image-shrink recovery: no data-URL image parts found "
            "or shrink didn't reduce size; surfacing original error."
        )

    # Strict OpenAI-spec providers 400 on list-type tool content: strip images, mark
    # (provider, model) no-list-tool-content for the session, retry once.
    if (
        classified.reason == FailoverReason.multimodal_tool_content_unsupported
        and not _retry.multimodal_tool_content_retry_attempted
    ):
        _retry.multimodal_tool_content_retry_attempted = True
        if agent._try_strip_image_parts_from_tool_messages(api_messages):
            _vlines(agent, "📐 Provider rejected list-type tool content — downgraded screenshots to text and retrying...")
            return True, recovered_with_pool
        logger.info(
            "multimodal-tool-content recovery: no list-type tool "
            "messages with image parts found; surfacing original error."
        )

    # Route rejecting a reasoning disable: a reasoning-mandatory route (Nous Portal / OpenRouter,
    # e.g. GLM-5.3) 400s on ``reasoning: {enabled: false}``; a chat-only OpenAI-compatible relay
    # 400s on the ``reasoning_effort: none`` the title/continuation disable projects (#114460).
    # The catalog guard in the provider profile normally swallows the first, but a process that
    # warmed its caps cache before the route flipped keeps sending it. One-shot: never send a
    # disable again this session (the wire builder omits it → route default), queue a catalog
    # refresh so the guard is right next time (no-op for providers without a catalog), retry.
    if (
        classified.reason == FailoverReason.reasoning_mandatory
        and not _retry.reasoning_mandatory_retry_attempted
    ):
        _retry.reasoning_mandatory_retry_attempted = True
        sent = getattr(agent, "_wire_reasoning_config", None)
        if isinstance(sent, dict) and sent.get("enabled") is not False and sent.get("effort") not in (None, "none"):
            # The rejected request carried an ENABLED config: the route refuses that reasoning
            # level (#100536: ``reasoning.effort: max`` on a Responses relay). Dropping a disable
            # would resend the identical request; omit the reasoning fields instead (route default).
            agent._reasoning_effort_rejected = True
            _vlines(agent, f"⚠️  {agent.model} rejects reasoning effort {sent['effort']} — using the route's default for this session, retrying...")
            logger.warning("%sReasoning-effort recovery: dropping reasoning config for %s", agent.log_prefix, agent.model)
            return True, recovered_with_pool
        agent._reasoning_disable_rejected = True
        # "Reasoning is mandatory ... cannot be disabled" understands the field and refuses only the
        # OFF: step up to the floor effort (the closest the route allows to what the user asked for)
        # rather than the route default. A relay that does not know the field at all keeps the
        # drop (a floor would 400 the same way).
        from ..upstream_loop.error_classifier import is_reasoning_required_rejection
        agent._reasoning_floor_required = is_reasoning_required_rejection(str(api_error))
        try:
            from .boundaries import refresh_reasoning_caps_async
            refresh_reasoning_caps_async(agent.provider)
        except Exception:
            pass
        if agent._reasoning_floor_required:
            from .boundaries import REASONING_FLOOR_EFFORT
            _vlines(agent, f"⚠️  {agent.model} cannot disable reasoning — using effort={REASONING_FLOOR_EFFORT} for this session, retrying...")
            logger.warning("%sReasoning-disable recovery: stepping reasoning up to %s for %s",
                           agent.log_prefix, REASONING_FLOOR_EFFORT, agent.model)
        else:
            _vlines(agent, f"⚠️  {agent.model} rejects disabling reasoning — using the route's default for this session, retrying...")
            logger.warning("%sReasoning-disable recovery: dropping reasoning disable for %s", agent.log_prefix, agent.model)
        return True, recovered_with_pool

    # Provider rejected the image bytes; shrinking can't help, so strip image parts.
    # Strip ONLY the per-call copy: replacing msg["content"] on the shallow api_messages
    # rows keeps canonical history's images (transient rejection must not erase history).
    if classified.reason == FailoverReason.image_corrupt:
        if _strip_request_images_and_retry(agent, api_messages):
            return True, recovered_with_pool
        logger.info("image-corrupt recovery: no image parts found to strip; surfacing original error.")

    # Anthropic OAuth subscription rejected the 1M-context beta: disable it for this
    # session, rebuild the client, retry once. Reactive so capable subscriptions keep 1M.
    if (
        # See PR #17680 for the original report (we chose reactive recovery over the proposed unconditional
        # omit so capable subscriptions don't silently lose the capability).
        classified.reason == FailoverReason.oauth_long_context_beta_forbidden
        and agent.api_mode == "anthropic_messages"
        and agent._is_anthropic_oauth
        and not _retry.oauth_1m_beta_retry_attempted
    ):
        _retry.oauth_1m_beta_retry_attempted = True
        if not getattr(agent, "_oauth_1m_beta_disabled", False):
            agent._oauth_1m_beta_disabled = True
            try:
                agent._anthropic_client.close()
            except Exception:
                pass
            agent._rebuild_anthropic_client()
            _vlines(agent, "🔕 OAuth subscription doesn't support the 1M-context beta — disabled for this session and retrying...")
            return True, recovered_with_pool

    if _refresh_credentials_after_401(agent, api_error, _retry, status_code):
        return True, recovered_with_pool

    if _recover_format_errors(agent, api_error, classified, _retry, messages, api_messages):
        return True, recovered_with_pool
    return False, recovered_with_pool
