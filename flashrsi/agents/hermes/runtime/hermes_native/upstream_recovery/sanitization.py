from __future__ import annotations
import re
import copy
from functools import partial
from typing import Any, Callable, Iterable, NamedTuple
from .boundaries import DB_ROW_SNAPSHOT
from .vision import _provider_model_key
from ..upstream_loop.boundaries import get_provider_profile

_SURROGATE_RE = re.compile(r'[\ud800-\udfff]')


_MESSAGE_CORE_KEYS = frozenset({"content", "name", "tool_calls", "role", DB_ROW_SNAPSHOT})


def _sanitize_surrogates(text: str) -> str:
    """Replace lone surrogate code points with U+FFFD; no-op when none present."""
    # ``str.isascii`` is an O(1) flag check; surrogates are never ASCII, so the
    # regex scan only runs for the (rare) non-ASCII leaf.
    if text.isascii():
        return text
    return _SURROGATE_RE.sub('\ufffd', text)


def _strip_non_ascii(text: str) -> str:
    """Drop non-ASCII characters — last resort for ASCII-only system encodings (LANG=C)."""
    if text.isascii():
        return text
    return text.encode('ascii', errors='ignore').decode('ascii')


def _fix_str_field(container: Any, key: Any, fix: Callable[[str], str]) -> bool:
    """Apply ``fix`` to ``container[key]`` if it is a str; True if it changed."""
    value = container.get(key) if isinstance(container, dict) else container[key]
    fixed = fix(value) if isinstance(value, str) else value
    if fixed == value:
        return False
    container[key] = fixed
    return True


def _sanitize_structure(payload: Any, fix: Callable[[str], str]) -> bool:
    """Apply ``fix`` to every str inside nested dict/list ``payload`` in-place."""
    found = False
    stack = [payload]
    while stack:
        node = stack.pop()
        items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
        for key, value in list(items):
            if isinstance(value, str):
                found |= _fix_str_field(node, key, fix)
            elif isinstance(value, (dict, list)):
                stack.append(value)
    return found


def _sanitize_messages(messages: list, fix: Callable[[str], str], *, deep: bool) -> bool:
    """Apply ``fix`` to the string fields of every message dict in-place (content / part text,
    name, tool_call arguments, non-core top-level str fields). ``deep=True`` adds tool_call ids,
    function names, and NESTED non-core fields (``reasoning_details`` from byte-level models)."""
    from .boundaries import _DB_PERSISTED_MARKER

    found = False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        msg_found = False
        content = msg.get("content")
        parts = [(p, "text") for p in content if isinstance(p, dict)] if isinstance(content, list) else None
        fields = parts if parts is not None else [(msg, "content")]
        fields.append((msg, "name"))
        tool_calls = msg.get("tool_calls")
        for tc in tool_calls if isinstance(tool_calls, list) else ():
            fn = tc.get("function") if isinstance(tc, dict) else None
            fields += [(tc, "id")] if deep and isinstance(tc, dict) else []
            fields += ([(fn, "name")] if deep else []) + [(fn, "arguments")] if isinstance(fn, dict) else []
        for container, key in fields:
            msg_found |= _fix_str_field(container, key, fix)
        for key, value in [kv for kv in msg.items() if kv[0] not in _MESSAGE_CORE_KEYS]:
            if isinstance(value, str):
                msg_found |= _fix_str_field(msg, key, fix)
            elif deep and isinstance(value, (dict, list)):
                msg_found |= _sanitize_structure(value, fix)
        if msg_found:
            # In-place repair of a live dict stales its persisted row; pop the marker so the
            # flush rewrites it (no-op on api_messages wire copies).
            msg.pop(_DB_PERSISTED_MARKER, None)
            found = True
    return found


_sanitize_structure_surrogates = partial(_sanitize_structure, fix=_sanitize_surrogates)


_sanitize_messages_surrogates = partial(_sanitize_messages, fix=_sanitize_surrogates, deep=True)


_sanitize_structure_non_ascii = partial(_sanitize_structure, fix=_strip_non_ascii)


_sanitize_messages_non_ascii = partial(_sanitize_messages, fix=_strip_non_ascii, deep=False)


def sanitize_outbound_kwargs(agent: Any, api_kwargs: dict) -> None:
    """Outbound-request chokepoint for every built kwargs dict (main loop and iteration summary).

    Tool descriptions, extra_body and kwargs strings can carry invalid code points that
    providers reject with a non-retryable 400 (#50959); one in-place walk makes the whole
    payload json.dumps()-safe. The ASCII strip is opt-in via the recovery flag set after an
    ASCII-codec rejection.
    """
    _sanitize_structure_surrogates(api_kwargs)
    if agent._force_ascii_payload:
        # ``tools`` is built from ``agent.tools`` per attempt and usually aliases it; detach
        # before the in-place strip so the retry never rewrites the canonical tool schemas.
        # A structural clone suffices: ``_sanitize_structure`` only rebinds str leaves
        # inside dict/list containers.
        if api_kwargs.get("tools") is not None and api_kwargs["tools"] is getattr(agent, "tools", None):
            # Lazy: conversation_loop imports this module (cycle).
            from .boundaries import _clone_message_for_send

            api_kwargs["tools"] = _clone_message_for_send(api_kwargs["tools"])
        _sanitize_structure_non_ascii(api_kwargs)


_IMAGE_PART_TYPES = {"image_url", "image", "input_image"}


def _strip_images_from_messages(messages: list) -> bool:
    """Remove image content parts from all messages in-place (server rejected images).

    ``tool`` / ``tool_calls`` messages left empty get a placeholder, NOT deleted (deleting
    orphans the paired ``tool_call_id`` → HTTP 400); other now-empty messages are dropped.
    Rewritten messages lose their ``api_content`` sidecar (it carries the removed images):
    a caller rewriting a persisted row must not leave bytes that replay them next turn. The
    current callers pass per-call clones, where this is a no-op.
    """
    from .boundaries import _DB_PERSISTED_MARKER
    from .boundaries import drop_stale_api_content

    found = False
    to_delete = []
    for i, msg in enumerate(messages):
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        new_parts = [p for p in content if not (isinstance(p, dict) and p.get("type") in _IMAGE_PART_TYPES)]
        if len(new_parts) < len(content):
            found = True
            if new_parts:
                msg["content"] = new_parts
                # Rewriting a stamped live dict stales its persisted row; pop the marker.
                msg.pop(_DB_PERSISTED_MARKER, None)
            elif msg.get("role") == "tool" or msg.get("tool_calls"):
                msg["content"] = "[image content removed — server does not support images]"
                msg.pop(_DB_PERSISTED_MARKER, None)
            else:
                to_delete.append(i)
            drop_stale_api_content(msg)
    for i in reversed(to_delete):
        del messages[i]
    return found


_IMAGE_REJECTION_PHRASES = (
    "only 'text' content type is supported", "only text content type is supported",
    "image_url is not supported", "image content is not supported",
    "multimodal is not supported", "multimodal content is not supported", "multimodal input is not supported",
    "vision is not supported", "vision input is not supported",
    "does not support images", "does not support image input", "does not support multimodal",
    "does not support vision", "model does not support image",
    # DashScope-style gateways reject non-text blocks with this generic body.
    # Some OpenAI-compatible endpoints (e.g. (issue #57948)
    "unexpected item type in content",
    # ChatGPT-account Codex backend rejects data:image URLs in input_image; keyed on the
    # field-path apostrophe so other URL errors don't false-trip.
    "image_url'. expected",
    # DeepSeek's text-only request-body variant error.
    "unknown variant `image_url`, expected `text`", "unknown variant image_url, expected text",
    # OpenRouter HTTP 404 when no upstream endpoint accepts image input (passes the 4xx
    # gate; without this the gateway queue wedges behind the stuck turn).
    # Without this phrase the agent never strips the images, the retry loop re-sends the same rejected
    # request until exhaustion, and the gateway leaves every subsequent message queued behind the stuck turn
    # — the P1 in issue #21160.
    "no endpoints found that support image input",
)


_IMAGE_CORRUPT_PHRASES = (
    # ChatGPT-account Codex backend's wording for corrupt/unsupported native image payloads.
    "image data you provided does not represent a valid image",
    # Kimi/Moonshot et al. reject truncated/corrupt image bytes baked into history.
    # Kimi / Moonshot / other OpenAI-compatible Chinese providers reject truncated or corrupt image bytes
    # with HTTP 400 "Invalid request: prepare image failed ... failed to decode image: invalid or
    # unsupported image format". Like the Codex case above, the bad bytes are baked into immutable
    # conversation history and re-sent on every retry, wedging the session. Strip the images so the turn
    # recovers instead of exhausting retries. (issue #76884; complements the proactive full-decode
    # validation in tools/vision_tools._normalize_to_supported_image)
    "failed to decode image",
)


def strip_images_for_rejecting_model(agent: Any, api_messages: Any) -> bool:
    """Send-path image strip for a model that rejected image content (see turn_recovery).

    Runs on the per-call ``api_messages`` copy in Hermes's own message format, BEFORE the
    provider-specific conversion: the part types this stripper knows are that format's, and a
    converted payload (Bedrock Converse ``{"image": ...}`` blocks carry no ``type``) would slip
    past it. History is never touched. Keyed on each rejecting (provider, model), so a model
    that accepts images gets them again.
    """
    if _provider_model_key(agent) not in agent._image_rejecting_models:
        return False
    return isinstance(api_messages, list) and _strip_images_from_messages(api_messages)


def _looks_like_image_content_rejection(error_body: str) -> bool:
    """Return True when a provider error says image/multimodal input is unsupported."""
    body = str(error_body or "").lower()
    return any(phrase in body for phrase in _IMAGE_REJECTION_PHRASES)


def _looks_like_corrupt_image_rejection(error_body: str) -> bool:
    """Return True when the rejection is about a bad image payload, not the model's capability."""
    body = str(error_body or "").lower()
    return any(phrase in body for phrase in _IMAGE_CORRUPT_PHRASES)


_REASONING_ECHO_RULES: tuple = (
    # (family, exact providers (raw), exact providers (lowered), model substrings (lowered), hosts)
    ("kimi", frozenset({"kimi-coding", "kimi-coding-cn"}), frozenset(), (), ("api.kimi.com", "moonshot.ai", "moonshot.cn")),
    ("deepseek", frozenset(), frozenset({"deepseek"}), ("deepseek",), ("api.deepseek.com",)),
    ("mimo", frozenset(), frozenset({"xiaomi"}), ("mimo",), ("api.xiaomimimo.com", "xiaomimimo.com")),
    # Portal stealth model that 400s on a tool-call turn without reasoning_content (f86276d2ebc).
    ("missingno", frozenset(), frozenset(), ("stealth/missingno",), ()),
)


_REASONING_ECHO_RULE_BY_FAMILY = {rule[0]: rule for rule in _REASONING_ECHO_RULES}


RC, R, RD = "reasoning_content", "reasoning", "reasoning_details"


REASONING_CARRIERS = (RC, R, RD)


_ALL_CARRIERS = frozenset(REASONING_CARRIERS)


def matches_reasoning_echo_family(family: str, provider: Any, model: Any, base_url: Any) -> bool:
    """True when (provider, model, base_url) matches one echo-back family (families can overlap;
    membership is tested independently). Raises KeyError for an unknown family."""
    from ..upstream_loop.urls import base_url_host_matches

    _, raw_providers, lowered_providers, model_subs, hosts = _REASONING_ECHO_RULE_BY_FAMILY[family]
    model_lower = (model or "").lower()
    return (
        provider in raw_providers or (provider or "").lower() in lowered_providers
        or any(sub in model_lower for sub in model_subs) or any(base_url_host_matches(base_url, host) for host in hosts)
    )


def reasoning_echo_family(provider: Any, model: Any, base_url: Any) -> str | None:
    """``"kimi"`` / ``"deepseek"`` / ``"mimo"`` (first match in table order) when the endpoint
    enforces reasoning_content echo-back on tool-call turns, else ``None``."""
    families = (rule[0] for rule in _REASONING_ECHO_RULES)
    return next((f for f in families if matches_reasoning_echo_family(f, provider, model, base_url)), None)


def needs_reasoning_echo(provider: Any, model: Any, base_url: Any) -> bool:
    """True when the endpoint requires reasoning_content echo-back (the must-echo tier)."""
    return reasoning_echo_family(provider, model, base_url) is not None


def _replayable_reasoning_text(msg: dict) -> str | None:
    """The turn's reasoning text: a non-blank ``reasoning_content`` wins over ``reasoning``."""
    for key in (RC, R):
        value = msg.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _apply_legacy_must_echo_pad(source_msg: dict, api_msg: dict) -> None:
    """Native-adapter wires (``carriers=None``): the pre-replay contract, byte-for-byte. An explicit
    value is kept verbatim (legacy "" upgraded to " "); a tool-call turn holding only another
    provider's ``reasoning`` is padded instead of converted into a native thinking block."""
    existing, reasoning = source_msg.get(RC), source_msg.get(R)
    if isinstance(existing, str):
        api_msg[RC] = existing or " "
    elif isinstance(reasoning, str) and reasoning and not source_msg.get("tool_calls"):
        api_msg[RC] = reasoning
    else:
        api_msg[RC] = " "


def apply_reasoning_content_policy(
    source_msg: dict, api_msg: dict, needs_thinking_pad: bool, carriers: frozenset | None = None,
) -> None:
    """Shape an assistant replay message's reasoning keys for the active route (mutates ``api_msg``).

    ``needs_thinking_pad`` is the must-echo flag; ``carriers`` the keys the route reads
    (``reasoning_replay_route``). ``carriers=None`` is a non-chat-completions wire: only the
    must-echo ``reasoning_content`` rides there and ``reasoning_details`` is left to the adapter.
    Keys the route does not read are removed, so a strict host never sees one (#45655, #70233).
    """
    if source_msg.get("role") != "assistant":
        return
    text = _replayable_reasoning_text(source_msg)
    effective = carriers if carriers is not None else (frozenset({RC}) if needs_thinking_pad else frozenset())
    if carriers is None and needs_thinking_pad:
        _apply_legacy_must_echo_pad(source_msg, api_msg)
    elif RC in effective and (text is not None or needs_thinking_pad):
        # Must-echo tier: every assistant turn carries the field; " " (not "") when there is no
        # text, because DeepSeek V4 rejects empty string (#17341) and a legacy "" pad upgrades.
        api_msg[RC] = text if text is not None else " "
    else:
        # Also drops a non-string value (None after compaction) and a whitespace pad written
        # for a must-echo provider: never pass null, never replay a pad as reasoning.
        api_msg.pop(RC, None)
    if R in effective and text is not None:
        api_msg[R] = text
    else:
        api_msg.pop(R, None)
    if carriers is not None and RD not in carriers:
        # Private ``*.native_assistant`` records (Gemini/Copilot carriers) survive: the transport lifts
        # them onto the route that reads them and filters them from every other wire.
        private = [d for d in api_msg.pop(RD, None) or () if isinstance(d, dict)
                   and str(d.get("type") or "").endswith(".native_assistant")]
        if private:
            api_msg[RD] = private


def _reasoning_shape(msg: dict) -> tuple:
    return tuple(msg.get(key) for key in REASONING_CARRIERS)


def reapply_reasoning_echo(api_messages: list, needs_thinking_pad: bool, carriers: frozenset | None = None) -> int:
    """Reconcile already-built assistant turns with the ACTIVE route.

    ``api_messages`` is built once under the primary; a mid-conversation fallback or a recorded
    field rejection changes the route, so baked-in keys are reconciled both ways: TO a must-echo
    provider the pad is re-applied (else 400), TO a strict one the keys are stripped (else 422),
    and a carrier the new route reads is restored from the text that is still present.
    Idempotent. Returns the number of assistant turns changed.
    """
    changed = 0
    for api_msg in api_messages:
        if api_msg.get("role") != "assistant":
            continue
        before = _reasoning_shape(api_msg)
        if carriers is None and needs_thinking_pad and api_msg.get(RC):
            continue
        apply_reasoning_content_policy(api_msg, api_msg, needs_thinking_pad, carriers)
        changed += _reasoning_shape(api_msg) != before
    return changed


_UNKNOWN_FIELD_PHRASES = (
    "extra inputs are not permitted", "is unsupported", "no such field", "unknown field",
    "unrecognized request argument", "unrecognized field", "unknown parameter", "unexpected field",
    "additional propert", "unknown key",
)


_NAMED_FIELD_RES = {
    RC: re.compile(r"(?<![\w])reasoning_content(?![\w])"),
    RD: re.compile(r"(?<![\w])reasoning_details(?![\w])"),
    # The bare word is also a top-level request param; only a message-path mention counts.
    R: re.compile(r"messages[^\n]{0,80}?(?<![\w])reasoning(?![\w])"),
}


def rejected_reasoning_fields(error_body: Any, sent_messages: Any) -> frozenset:
    """Reasoning keys to drop after an unknown-field rejection that names one this request carried.

    Strict schemas report one offending key per error, so the drop is widened to the keys the
    same schema will reject next: a rejected ``reasoning_details`` / ``reasoning`` takes the
    other non-standard carrier too (``reasoning_content`` still carries the text); a rejected
    ``reasoning_content`` (the most widely accepted alias) takes all three. One retry, not three.
    """
    body = str(error_body or "").lower()
    if not any(phrase in body for phrase in _UNKNOWN_FIELD_PHRASES):
        return frozenset()
    sent = {
        key for msg in (sent_messages if isinstance(sent_messages, list) else ())
        if isinstance(msg, dict) and msg.get("role") == "assistant" for key in REASONING_CARRIERS if key in msg
    }
    named = {key for key in sent if _NAMED_FIELD_RES[key].search(body)}
    if not named:
        return frozenset()
    return frozenset(sent & (_ALL_CARRIERS if RC in named else {R, RD}))


def reasoning_route_key(agent: Any) -> tuple[str, str, str]:
    """``(provider, base_url host, model)``: one gateway serves models on different upstream lanes,
    so a rejection learned for one model must not strip carriers from its siblings."""
    from ..upstream_loop.urls import base_url_hostname

    return (
        (getattr(agent, "provider", "") or "").strip().lower(),
        base_url_hostname(getattr(agent, "base_url", "") or "") or "",
        (getattr(agent, "model", "") or "").strip(),
    )


_REJECTION_MODEL_CONFIG_KEY = "reasoning_rejected_carriers"


def rejected_reasoning_carriers(agent: Any) -> frozenset:
    """Reasoning keys the active (provider, host, model) rejected in this session.

    Persisted in the session's ``model_config`` so a resumed process (``--resume``, a gateway
    restart) never re-learns a rejection with another 400. Loaded once per ``session_id``.
    """
    routes = agent.__dict__.setdefault("_reasoning_rejecting_routes", {})
    session_id = getattr(agent, "session_id", None)
    if session_id and getattr(agent, "_reasoning_rejections_loaded_for", None) != session_id:
        agent._reasoning_rejections_loaded_for = session_id
        getter = getattr(getattr(agent, "_session_db", None), "get_session_model_config_value", None)
        stored = getter(session_id, _REJECTION_MODEL_CONFIG_KEY, []) if callable(getter) else []
        for entry in stored if isinstance(stored, list) else ():
            if isinstance(entry, list) and len(entry) == 4 and isinstance(entry[3], list):
                routes.setdefault(tuple(entry[:3]), set()).update(k for k in entry[3] if k in _ALL_CARRIERS)
    return frozenset(routes.get(reasoning_route_key(agent), ()))


def record_reasoning_field_rejection(agent: Any, error_body: Any, sent_messages: Any) -> frozenset:
    """Remember the reasoning keys this route rejected; returns the NEW ones (empty = no retry).

    The next ``build_api_request`` re-shapes ``api_messages`` without them for this
    (provider, host, model) for the rest of the session. A repeat rejection of an already
    recorded key returns empty, so recovery can never loop. History is never touched.
    """
    if getattr(agent, "api_mode", "chat_completions") != "chat_completions":
        return frozenset()
    fields = rejected_reasoning_fields(error_body, sent_messages)
    if needs_reasoning_echo(getattr(agent, "provider", ""), getattr(agent, "model", ""), getattr(agent, "base_url", "")):
        # Must-echo routes 400 on any tool turn WITHOUT reasoning_content; a body naming it is a
        # value complaint ("must not be empty"), never a schema that lacks the field.
        fields -= {RC}
    if not fields:
        return frozenset()
    new = fields - rejected_reasoning_carriers(agent)
    if not new:
        return frozenset()
    routes = agent._reasoning_rejecting_routes
    routes.setdefault(reasoning_route_key(agent), set()).update(new)
    patcher = getattr(getattr(agent, "_session_db", None), "patch_session_model_config", None)
    if callable(patcher) and getattr(agent, "session_id", None) and not getattr(agent, "_persist_disabled", False):
        patcher(agent.session_id, {_REJECTION_MODEL_CONFIG_KEY: [[*key, sorted(v)] for key, v in sorted(routes.items())]})
    return frozenset(new)
