"""HTTP/JSON boundary for the pinned Hermes Responses transport.

All conversion, request policy, normalization and token buckets come from the
actual upstream Python helpers. This boundary supplies explicit role settings
and converts SDK-shaped objects to plain JSON; it never creates an SDK client.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from types import SimpleNamespace

from .native_compaction import (
    has_compaction_checkpoint,
    native_compaction_context_management,
    resolve_native_compaction_capabilities,
)
from .upstream_chat.reasoning_config import (
    parse_reasoning_effort,
    resolve_reasoning_config,
)
from .upstream_compaction.model_metadata import estimate_request_tokens_rough
from .upstream_compaction.responses_adapter import (
    _chat_messages_to_responses_input,
    _classify_responses_issuer,
    _normalize_codex_response,
    _preflight_codex_api_kwargs,
    _wire_model_identity,
    classify_responses_route,
)
from .upstream_compaction.responses_auxiliary import AuxiliaryResponsesTransport
from .upstream_compaction.responses_boundaries import (
    codex_cloudflare_headers,
    request_settings,
)
from .upstream_compaction.responses_transport import ResponsesApiTransport
from .upstream_compaction.responses_usage import normalize_usage
from .upstream_recovery.transport_methods import ResponsesRecoveryMethods


class RecoveringResponsesTransport(ResponsesRecoveryMethods, ResponsesApiTransport):
    """Original transport plus its original stateful request-repair methods."""


def api_mode(route):
    value = str(route.get("model_api") or route.get("api_mode") or "").lower()
    if value == "openai-completions":
        return "chat_completions"
    if value in {"anthropic", "anthropic-messages", "anthropic_messages"}:
        return "anthropic_messages"
    return (
        "codex_responses"
        if value in {"responses", "openai-responses", "codex_responses"}
        else value
    )


def _flag(value, default=False):
    if value is None:
        return default
    return (
        value.strip().lower() in {"true", "1", "yes", "on"}
        if isinstance(value, str)
        else bool(value)
    )


def policy_agent(engine, route):
    """Project explicit host fields onto the original native-compaction contract."""
    settings = getattr(engine, "settings", {})
    cfg = getattr(engine, "config", {})
    base = route.get("base_url") or "https://api.openai.com/v1"
    agent = SimpleNamespace(
        api_mode=api_mode(route),
        model=route.get("model")
        or route.get("model_name")
        or getattr(engine, "model", ""),
        provider=route.get("provider", ""),
        base_url=base,
        capabilities=route.get("capabilities") or settings.get("capabilities") or {},
        compression_enabled=getattr(engine, "enabled", False),
        compression_checkpoint_required=getattr(engine, "checkpoint_required", False),
        codex_responses_native_compaction=_flag(cfg.get("codex_responses_native"))
        and not getattr(engine, "_native_disabled", False),
        codex_responses_compact_threshold=cfg.get("codex_responses_compact_threshold"),
        context_compressor=getattr(engine, "compressor", None),
    )
    flags = classify_responses_route(agent)._asdict()
    # An explicitly resolved capability remains authoritative across model switches.
    explicit = route.get("runtime_capabilities", settings.get("runtime_capabilities"))
    agent.runtime_capabilities = (
        explicit
        if isinstance(explicit, dict)
        else resolve_native_compaction_capabilities(
            model=agent.model,
            base_url=agent.base_url,
            provider=agent.provider,
            is_codex_backend=flags["is_codex_backend"],
        )
    )
    return agent, flags


def context_management(engine, route):
    if engine is None or api_mode(route) != "codex_responses":
        return None
    agent, flags = policy_agent(engine, route)
    return native_compaction_context_management(agent, **flags)


def request_headers(route):
    """Explicit token and original Codex client/account identity; no OAuth discovery."""
    headers = {
        "Authorization": f"Bearer {route.get('api_key') or ''}",
        "Content-Type": "application/json",
    }
    agent, flags = policy_agent(None, route)
    if flags["is_codex_backend"]:
        headers.update(
            codex_cloudflare_headers(
                str(route.get("api_key") or ""), base_url=agent.base_url
            )
        )
    return headers


def native_wire_items(engine, messages, route=None):
    route = route or getattr(engine, "llm", {})
    if not context_management(engine, route):
        return None
    agent, flags = policy_agent(engine, route)
    return _chat_messages_to_responses_input(
        messages,
        is_xai_responses=flags["is_xai_responses"],
        is_github_responses=flags["is_github_responses"],
        replay_encrypted_reasoning=not getattr(
            engine, "_native_replay_disabled", False
        ),
        current_issuer_kind=_classify_responses_issuer(
            base_url=agent.base_url, **flags
        ),
        current_issuer_model=_wire_model_identity(
            (route.get("request_overrides") or {}).get("model", agent.model)
        ),
        native_compaction_eligible=True,
    )


def has_replayable_checkpoint(engine, messages, route=None):
    return has_compaction_checkpoint(native_wire_items(engine, messages, route))


def estimate_native_tokens(engine, messages, system_prompt="", tools=None):
    items = native_wire_items(engine, messages)
    return (
        None
        if items is None
        else estimate_request_tokens_rough(
            items, system_prompt=system_prompt or "", tools=tools
        )
    )


def prepare(payload, route, engine=None, *, summary=False):
    """Return ``(HTTP endpoint, JSON body)``; summaries never activate native compaction.

    ``extra_headers`` is an upstream SDK boundary field: the HTTP host must pop
    it from the returned body and merge it into its request headers.
    """
    payload, route = copy.deepcopy(payload), dict(route)
    agent, flags = policy_agent(engine, {**route, "model": payload.get("model")})
    transport = (
        getattr(engine, "_responses_transport", None) if engine is not None else None
    )
    if transport is None:
        transport = RecoveringResponsesTransport()
        transport._all_turns_rejected = getattr(engine, "_recovery_all_turns_rejected", frozenset())
        if engine is not None:
            engine._responses_transport = transport
    settings = getattr(engine, "settings", {})
    overrides = copy.deepcopy(route.get("request_overrides") or {})
    # The chat-shaped host payload is already composed from explicit llm fields.
    for key, value in payload.items():
        if key not in {
            "model",
            "messages",
            "tools",
            "stream",
            "max_tokens",
            "max_completion_tokens",
            "reasoning_effort",
        }:
            overrides[key] = value
    reasoning = route.get("reasoning_config", settings.get("reasoning_config"))
    if reasoning is None:
        reasoning = route.get("reasoning") or settings.get("reasoning")
    if payload.get("reasoning_effort") is not None:
        reasoning = parse_reasoning_effort(payload["reasoning_effort"])
    elif reasoning is None and not summary:
        agent_settings = dict(settings.get("agent") or {})
        for name in ("reasoning_effort", "reasoning_overrides"):
            if name in settings:
                agent_settings[name] = settings[name]
        reasoning = resolve_reasoning_config({"agent": agent_settings}, agent.model)
    if recovery_host := getattr(engine, "_recovery_host", None):
        reasoning = recovery_host.reasoning_for_wire(reasoning)
    directive = (
        None if summary else context_management(engine, {**route, "model": agent.model})
    )
    # The provider owns the lossy boundary; extra_body cannot silently bypass its gate.
    overrides.pop("context_management", None)
    extra_body = overrides.get("extra_body")
    if isinstance(extra_body, dict):
        extra_body.pop("context_management", None)
    token = request_settings.set(
        {
            **route,
            "session_id": settings.get("session_id"),
            "cache_scope": settings.get("cache_scope_id"),
        }
    )
    try:
        if summary:
            auxiliary = AuxiliaryResponsesTransport(
                agent.model, agent.base_url, agent.provider
            )
            auxiliary_payload = dict(payload)
            auxiliary_extra = copy.deepcopy(route.get("extra_body") or {})
            for field in ("reasoning", "service_tier"):
                if field in payload:
                    auxiliary_extra[field] = payload[field]
            if route.get("_summary_reasoning_config"):
                auxiliary_extra.setdefault(
                    "reasoning", route["_summary_reasoning_config"]
                )
            auxiliary_payload["extra_body"] = auxiliary_extra
            result, _, _ = auxiliary._build_responses_kwargs(auxiliary_payload)
            auxiliary._last_wire_aliases = result.pop("_wire_aliases", {})
            auxiliary._last_issuer_kind = result.pop("_issuer_kind", None)
            auxiliary._last_issuer_model = _wire_model_identity(agent.model)
            if engine is not None:
                engine._responses_summary_transport = auxiliary
        else:
            result = transport.build_kwargs(
                model=agent.model,
                messages=payload.get("messages") or [],
                tools=payload.get("tools"),
                base_url=agent.base_url,
                provider=agent.provider,
                **flags,
                reasoning_config=reasoning,
                session_id=settings.get("session_id"),
                cache_scope_id=settings.get("cache_scope_id"),
                max_tokens=payload.get(
                    "max_completion_tokens", payload.get("max_tokens")
                ),
                text_verbosity=route.get("text_verbosity")
                or settings.get("text_verbosity"),
                request_overrides=overrides,
                context_management=directive,
                replay_encrypted_reasoning=not getattr(
                    engine, "_native_replay_disabled", False
                ),
            )
        if flags["is_codex_backend"]:
            result["stream"] = True
        result = _preflight_codex_api_kwargs(
            result,
            allow_stream=flags["is_codex_backend"],
            is_github_responses=flags["is_github_responses"],
            sanitize_harmony_tokens=flags["is_codex_backend"],
        )
    finally:
        request_settings.reset(token)
    # SDK extra_body fields are serialized directly into the body.
    extra_body = result.pop("extra_body", None)
    if isinstance(extra_body, dict):
        result.update(extra_body)
    if summary:
        result.pop("context_management", None)
    endpoint = agent.base_url.rstrip("/")
    if not endpoint.endswith("/responses"):
        endpoint += "/responses"
    return endpoint, result


def _objects(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _objects(item) for key, item in value.items()})
    return [_objects(item) for item in value] if isinstance(value, list) else value


def _plain(value):
    if isinstance(value, SimpleNamespace):
        return {key: _plain(item) for key, item in vars(value).items()}
    return [_plain(item) for item in value] if isinstance(value, list) else value


def ingest(data, route, engine=None, *, summary=False):
    """Normalize a Responses object into the existing host's Chat-shaped result."""
    agent, flags = policy_agent(engine, route)
    transport = getattr(
        engine,
        "_responses_summary_transport" if summary else "_responses_transport",
        None,
    )
    issuer_kind = _classify_responses_issuer(base_url=agent.base_url, **flags)
    requested_model = (route.get("request_overrides") or {}).get("model", agent.model)
    issuer_model = (
        getattr(transport, "_last_issuer_model", None)
        if getattr(transport, "_last_issuer_kind", None) == issuer_kind
        else None
    ) or _wire_model_identity(requested_model)
    normalized_data = copy.deepcopy(data)
    if summary and not normalized_data.get("output"):
        # auxiliary_codex_response preserves its historical empty completed result.
        normalized_data["output"] = [{"type": "message", "content": []}]
    message, finish = _normalize_codex_response(
        _objects(normalized_data),
        issuer_kind=issuer_kind,
        issuer_model=issuer_model,
        recover_leaked_tool_call=not summary,
    )
    message = _plain(message)
    status = str(data.get("status") or "").strip().lower()
    details = data.get("incomplete_details")
    incomplete_reason = (
        str(details.get("reason") or "").strip().lower()
        if isinstance(details, dict)
        else ""
    )
    # turn_response_check._derive_finish_reason supersedes normalization for
    # provider output exhaustion: retry complete-looking calls before execution.
    if status == "incomplete" and incomplete_reason in {"max_output_tokens", "length"}:
        finish = "length" if message.get("tool_calls") else "incomplete"
    elif status == "incomplete" and incomplete_reason == "content_filter":
        finish = "content_filter"
    if (
        summary
        and finish != "tool_calls"
        and (finish == "incomplete" or status == "incomplete")
    ):
        # Aux callers reject partial summaries through their existing length gate.
        finish = "length"
    aliases = getattr(transport, "_last_wire_aliases", None) or {}
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        function["name"] = aliases.get(function.get("name"), function.get("name"))
    usage = normalize_usage(
        data.get("usage"), provider=agent.provider, api_mode="codex_responses"
    )
    canonical = asdict(usage)
    # prompt_tokens is the COMPLETE input, including cache reads/writes.
    canonical.update(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )
    if (
        not summary
        and engine is not None
        and has_replayable_checkpoint(engine, [{"role": "assistant", **message}], route)
    ):
        engine.note_native_checkpoint()
    return {
        "id": data.get("id"),
        "model": data.get("model") or agent.model,
        "responses_status": status,
        "responses_incomplete_reason": incomplete_reason,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": canonical,
    }


def decode_response(text):
    """Read JSON or completed Responses SSE without requiring the OpenAI SDK."""
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except (TypeError, ValueError):
        pass
    final, items, deltas = None, {}, []
    for block in str(text).replace("\r\n", "\n").split("\n\n"):
        raw = "\n".join(
            line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")
        )
        if not raw or raw == "[DONE]":
            continue
        event = json.loads(raw)
        kind = event.get("type", "")
        if kind in {"error", "response.failed"}:
            raise RuntimeError(
                f"Responses stream failed: {event.get('error') or event.get('response') or event}"
            )
        if kind in {"response.completed", "response.incomplete", "response.done"}:
            final = event.get("response") or final
        if kind == "response.output_item.done" and isinstance(event.get("item"), dict):
            items[event.get("output_index", len(items))] = event["item"]
        if kind == "response.output_text.delta":
            deltas.append(str(event.get("delta") or ""))
    if not isinstance(final, dict):
        raise RuntimeError(
            "Responses stream ended before a completed or incomplete response"
        )
    if not final.get("output") and items:
        final["output"] = [items[index] for index in sorted(items)]
    if not final.get("output") and deltas:
        final["output_text"] = "".join(deltas)
    return final
