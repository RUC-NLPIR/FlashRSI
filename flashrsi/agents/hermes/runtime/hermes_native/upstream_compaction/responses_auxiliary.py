"""Pure Hermes v0.22.5 source helpers; see RESPONSES_PROVENANCE.json."""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import re
import unicodedata
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, fields
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Sequence, TypeGuard
from urllib.parse import urlparse, urlsplit, urlunsplit
logger = logging.getLogger(__name__)

from .responses_boundaries import *
from .responses_boundaries import _runtime_main_value

class AuxiliaryResponsesTransport:
    def __init__(self, model, base_url, provider):
        self._model = model
        self._client = SimpleNamespace(base_url=base_url, _hermes_aux_effective_provider=provider)

    def _build_responses_kwargs(self, kwargs: dict[str, Any]) -> tuple[dict[str, Any], str, Any]:
            """chat.completions kwargs → Responses API kwargs, ``(resp_kwargs, model, timeout)``; mirrors codex.py::build_kwargs."""
            # Separate system/instructions from replayable conversation messages, then route the rest through
            # the SINGLE shared chat->Responses converter used by the main agent transport
            # (agent/transports/codex.py). Maintaining a private conversion loop here let chat-style messages
            # with role="tool" leak straight into Responses input[] — which the Responses API rejects with
            # "Invalid value: 'tool'. Supported values are: 'assistant', 'system', 'developer', and 'user'."
            # (issue #5709, hit hard by flush_memories() / compression replaying real session history that
            # includes assistant tool_calls + role="tool" results). The shared converter encodes assistant tool
            # calls as `function_call` items and tool results as `function_call_output` items with a valid
            # call_id, so every Responses path normalizes tool history identically and cannot drift.
            from .responses_adapter import (
                _chat_messages_to_responses_input,
                _classify_responses_issuer,
                _responses_tools,
                _role_message_item,
                _wire_model_identity,
                classify_responses_route,
            )
            from .responses_transport import _alias_wire_tools
            model = kwargs.get("model", self._model)
            wire_model = _wire_model_identity(model)
            host = str(getattr(self._client, "base_url", "") or "")
            is_copilot = base_url_host_matches(host, "githubcopilot.com")
            # Same route classifier as the main transport, so the issuer stamp matches what it minted.
            route = classify_responses_route(SimpleNamespace(provider=None, base_url=host))
            is_xai = route.is_xai_responses
            is_github = route.is_github_responses
            tools = kwargs.get("tools")
            if tools:
                # xAI Responses rejects ``pattern``/``format`` JSON Schema keywords (400); strip for
                # chat_completion_helpers.py parity. Deep-copy first — sanitizers mutate inner dicts
                # in place and would strip the caller's tool registry.
                try:
                    import copy as _copy
                    from .responses_boundaries import strip_pattern_and_format, strip_slash_enum
                    tools = _copy.deepcopy(list(tools))
                    tools, _ = strip_pattern_and_format(tools)
                    tools, _ = strip_slash_enum(tools)
                except Exception as exc:
                    logger.warning(
                        "Auxiliary client: failed to sanitize tool schemas for "
                        "Codex/xAI Responses path: %s", exc,
                    )
            # Tool schemas go through the SAME converter (``strict: False``) and the SAME reserved-name
            # aliasing (OpenCode / Perplexity / xAI) as agent/transports/codex.py::build_kwargs. A private
            # list here sent raw names without ``strict``, so title/compression/MoA calls 400ed on routes
            # where the main loop worked (#114260). The alias map is request-local: it rides on the payload
            # (``_wire_aliases``, popped in ``create()``), never on the instance — aux adapters are shared.
            wire_tools, wire_aliases = _alias_wire_tools(
                _responses_tools(tools),
                {"provider": getattr(self._client, "_hermes_aux_effective_provider", "") or None, "base_url": host},
                is_xai,
            )
            renamed = {original: alias for alias, original in wire_aliases.items()}
            # System → ``instructions``; the rest goes through the SINGLE shared chat→Responses
            # converter (a private loop here once let role="tool" leak into input[]; the shared one
            # encodes tool history as function_call/function_call_output).
            instructions = "You are a helpful assistant."
            replay_messages: list[dict[str, Any]] = []
            for msg in kwargs.get("messages", []):
                content = msg.get("content") or ""
                if msg.get("role", "user") == "system":
                    instructions = content if isinstance(content, str) else str(content)
                    continue
                # Replayed history names each tool the way THIS request declares it.
                if renamed and msg.get("tool_calls"):
                    msg = {**msg, "tool_calls": [
                        {**tc, "function": {**tc["function"], "name": renamed[tc["function"]["name"]]}}
                        if isinstance(tc, dict) and (tc.get("function") or {}).get("name") in renamed else tc
                        for tc in msg["tool_calls"]
                    ]}
                replay_messages.append(msg)
            # Copilot binds replayed codex_message_items ids to a backend connection that doesn't
            # survive credential rotation (401 on replay) — same guard as build_kwargs. Aux calls
            # never send ``context_management`` (main-turn feature): no compaction checkpoint.
            # Auxiliary calls (context compression, flush_memories, MoA aggregation) go through this adapter
            # instead of agent/transports/codex.py's build_kwargs, so they need the same guard applied
            # independently. See #32716.
            # Aux requests run their own model; stamp/filter reasoning provenance against it, not the main agent's.
            issuer_kind = _classify_responses_issuer(base_url=host, **route._asdict())
            input_items = _chat_messages_to_responses_input(
                replay_messages, is_github_responses=is_copilot,
                current_issuer_kind=issuer_kind,
                current_issuer_model=wire_model, native_compaction_eligible=False,
            )
            resp_kwargs: dict[str, Any] = {
                # Codex only knows the base slug; strip the Hermes ``-900k`` picker suffix.
                "model": wire_model, "instructions": instructions,
                "input": input_items or [_role_message_item("user", "")], "store": False,
            }
            # Forward the chat.completions timeout; otherwise a Codex stream can sit behind a
            # dead-looking CLI until the user force-interrupts.
            timeout = kwargs.get("timeout")
            if timeout is not None:
                resp_kwargs["timeout"] = timeout
            # Per-request HTTP headers (OpenCode session affinity, Copilot x-initiator) map to real
            # headers via the SDK kwarg — forward them.
            if isinstance(kwargs.get("extra_headers"), dict) and kwargs["extra_headers"]:
                resp_kwargs["extra_headers"] = dict(kwargs["extra_headers"])
            # The Codex endpoint rejects max_output_tokens/temperature (400) — omit.
            extra_body = kwargs.get("extra_body") or {}
            if isinstance(extra_body, dict):
                # service_tier (fast mode) is a top-level Responses field; xAI's endpoint rejects it.
                service_tier = extra_body.get("service_tier")
                if isinstance(service_tier, str) and service_tier.strip() and not is_xai:
                    resp_kwargs["service_tier"] = service_tier.strip()
                reasoning_cfg = extra_body.get("reasoning")
                if isinstance(reasoning_cfg, dict):
                    # Shared per-model vocabulary with the main transport ("max" only where the model publishes it; "minimal"/"ultra"
                    # clamp to a listed level; ``()`` = the model takes no ``reasoning`` field at all — gpt-4o/4.1 on api.openai.com,
                    # #76255). ``enabled: False`` goes on the wire as ``effort: none`` where the vocabulary has it,
                    # since an omitted field leaves the model's default effort on (#75227).
                    from .responses_boundaries import clamp_effort
                    from .responses_transport import _codex_efforts_for_route
                    supported = _codex_efforts_for_route(model, host, is_codex_backend=route.is_codex_backend)
                    if supported and reasoning_cfg.get("enabled") is not False:
                        # Truthy-only: Codex 400s on e.g. {"effort": null}, so falsy → default.
                        effort = clamp_effort(reasoning_cfg.get("effort") or "medium", supported)
                        resp_kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
                        resp_kwargs["include"] = ["reasoning.encrypted_content"]
                    elif "none" in supported and not is_xai:
                        resp_kwargs["reasoning"] = {"effort": "none"}
            if wire_tools:
                resp_kwargs["tools"] = wire_tools
            if wire_aliases:
                resp_kwargs["_wire_aliases"] = wire_aliases
            # Response normalization is route-sensitive too (popped in ``create()``, never sent).
            resp_kwargs["_issuer_kind"] = issuer_kind
            # Stable prompt-cache routing: key is content-addressed from the static prefix
            # (instructions + tool schemas) so it survives across turns, scoped by the owning
            # conversation (rotation-stable logical scope, else the physical session id). Skip the
            # key where the main transport does: xAI takes it in extra_body, GitHub opts out.
            try:
                # Reuse the Responses transport's single authoritative hash algorithm and session-scope
                # normalization so equivalent static prefixes route to the same cache bucket across modes,
                # without concentrating unrelated sessions into one shared bucket (see #78941).
                from .responses_transport import _cache_scope_from_session_id, _content_cache_key
                from .responses_transport import _default_prompt_cache_retention_for_request
                if not (is_xai or is_github) and "prompt_cache_key" not in resp_kwargs:
                    scope = _cache_scope_from_session_id(
                        _runtime_main_value("cache_scope") or _runtime_main_value("session_id")
                    )
                    cache_key = _content_cache_key(resp_kwargs["instructions"], resp_kwargs.get("tools"), scope)
                    if cache_key:
                        resp_kwargs["prompt_cache_key"] = cache_key
                if "prompt_cache_retention" not in resp_kwargs:
                    cache_retention = _default_prompt_cache_retention_for_request(model, host)
                    if cache_retention:
                        resp_kwargs["prompt_cache_retention"] = cache_retention
            except Exception:
                logger.debug("Codex auxiliary: prompt_cache_key derivation skipped", exc_info=True)
            # Last, like the main transport: caller extra_body must not put a rejected Astra field back.
            from .responses_transport import _sanitize_astra_request_kwargs
            _sanitize_astra_request_kwargs(resp_kwargs, model, host)
            return resp_kwargs, model, timeout
