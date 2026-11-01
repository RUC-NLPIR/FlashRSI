"""Original Hermes recovery oracle with fixed routes, errors and request copies.

Runs real source recovery and transport methods. Only credential discovery and
provider/network I/O are absent. Unicode's locale probe is an explicit input.
Run using the isolated original-oracle venv with --source at the pinned checkout.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

COMMIT = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
BASE_MESSAGES = [
    {"role": "system", "content": "系统指令: inspect résumé."},
    {"role": "user", "content": "中文 question: café?"},
]
SIGNED = {
    "type": "thinking",
    "thinking": "Inspect the file.",
    "signature": "fixed-signed-history",
}
TOOL_IMAGE = {
    "role": "tool",
    "tool_call_id": "read",
    "content": [
        {"type": "text", "text": "Screenshot text"},
        {"type": "image_url", "image_url": {"url": "https://fixture.invalid/shot.png"}},
    ],
}
STALE = {
    "role": "assistant",
    "content": "Older answer",
    "codex_reasoning_items": [
        {"type": "reasoning", "id": "rs_old", "encrypted_content": "old-fixed-blob"}
    ],
}
OWN = {
    "role": "assistant",
    "content": "Own answer",
    "codex_reasoning_items": [
        {
            "type": "reasoning",
            "id": "rs_own",
            "encrypted_content": "own-fixed-blob",
            "_issuer_kind": "other:https://api.openai.com/v1",
            "_issuer_model": "gpt-5.4",
        }
    ],
}


def error(message, status=400, **extra):
    return {"message": message, "status": status, **extra}


CASES = [
    {
        "name": "unicode_header_utf8",
        "key": "key—copied",
        "headers": {"x-test": "résumé"},
        "error": {"unicode": "ascii"},
        "locale_ascii": False,
    },
    {
        "name": "unicode_false_ascii_no_repair",
        "error": {"unicode": "ascii"},
        "locale_ascii": False,
    },
    {
        "name": "unicode_ascii_locale",
        "key": "key—copied",
        "headers": {"x-test": "résumé"},
        "error": {"unicode": "ascii"},
        "locale_ascii": True,
    },
    {
        "name": "unicode_surrogate",
        "messages": [{"role": "user", "content": "bad \ud800 paste"}],
        "error": {"unicode": "utf-8"},
        "locale_ascii": False,
    },
    {
        "name": "multimodal_tool_downgrade",
        "messages": [*BASE_MESSAGES, TOOL_IMAGE],
        "error": error("Invalid request: messages.2.content text is not set"),
    },
    {
        "name": "chat_signature_request_only",
        "messages": [
            *BASE_MESSAGES,
            {
                "role": "assistant",
                "content": "Read first.",
                "reasoning_details": [SIGNED],
            },
        ],
        "error": error("Invalid signature in thinking block"),
    },
    {
        "name": "anthropic_signed_request_only",
        "route": {
            "api_mode": "anthropic_messages",
            "base_url": "https://api.anthropic.com",
            "model": "claude-opus-4-6",
            "provider": "anthropic",
        },
        "messages": [
            *BASE_MESSAGES,
            {
                "role": "assistant",
                "content": "Read first.",
                "reasoning": "Inspect the file.",
                "reasoning_details": [SIGNED],
                "_anthropic_content_blocks": [
                    SIGNED,
                    {"type": "text", "text": "Read first."},
                ],
            },
        ],
        "error": error("Invalid signature in thinking block"),
    },
    {
        "name": "anthropic_fast_capacity",
        "route": {
            "api_mode": "anthropic_messages",
            "base_url": "https://api.anthropic.com",
            "model": "claude-opus-4-6",
            "provider": "anthropic",
        },
        "kwargs": {"extra_body": {"speed": "fast"}},
        "error": error(
            "rate limit", 429, headers={"anthropic-fast-input-tokens-limit": "0"}
        ),
    },
    {
        "name": "responses_foreign_then_own",
        "route": {
            "api_mode": "codex_responses",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5.4",
            "provider": "openai",
        },
        "messages": [*BASE_MESSAGES, STALE, OWN],
        "errors": [
            error("invalid_encrypted_content"),
            error("invalid_encrypted_content"),
        ],
    },
    {
        "name": "responses_token_expired",
        "route": {
            "api_mode": "codex_responses",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5.4",
            "provider": "openai",
        },
        "messages": [*BASE_MESSAGES, STALE, OWN],
        "error": error(
            "Provided authentication token is expired.", 401, code="token_expired"
        ),
    },
    {
        "name": "responses_repeat_own_rejection",
        "route": {
            "api_mode": "codex_responses",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5.4",
            "provider": "openai",
        },
        "messages": [*BASE_MESSAGES, OWN],
        "errors": [
            error("invalid_encrypted_content"),
            error("invalid_encrypted_content"),
        ],
        "new_turn_own": True,
    },
    {
        "name": "responses_all_turns",
        "route": {
            "api_mode": "codex_responses",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5.4",
            "provider": "openai",
        },
        "all_turns": True,
        "error": error("Unsupported reasoning.context all_turns"),
    },
]


class FixedError(Exception):
    def __init__(self, spec):
        super().__init__(spec.get("message", "fixed error"))
        self.status_code = spec.get("status", 400)
        self.body = {
            "error": {
                "message": str(self),
                **({"code": spec["code"]} if "code" in spec else {}),
            }
        }
        self.message = str(self)
        self.response = SimpleNamespace(headers=spec.get("headers", {}))


def _exception(spec):
    if "unicode" in spec:
        codec = spec["unicode"]
        return UnicodeEncodeError(
            codec,
            "\ud800" if codec == "utf-8" else "é",
            0,
            1,
            "surrogates not allowed"
            if codec == "utf-8"
            else "ordinal not in range(128)",
        )
    return FixedError(spec)


def _plain(value):
    if isinstance(value, (set, frozenset)):
        return [_plain(item) for item in sorted(value)]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def execute(case, *, native=False):
    if native:
        from flashrsi.agents.hermes.runtime.hermes_native.native_responses import (
            RecoveringResponsesTransport as Transport,
        )
        from flashrsi.agents.hermes.runtime.hermes_native.recovery import RecoveryHost
        from flashrsi.agents.hermes.runtime.hermes_native.upstream_loop.error_classifier import (
            classify_api_error,
        )
        from flashrsi.agents.hermes.runtime.hermes_native.upstream_recovery import (
            recovery,
        )
        from flashrsi.agents.hermes.runtime.hermes_native.upstream_recovery.retry_state import (
            TurnRetryState,
        )
    else:
        from agent import turn_recovery as recovery
        from agent.agent_runtime_helpers import extract_api_error_context
        from agent.conversation_compression import try_shrink_image_parts_in_messages
        from agent.error_classifier import classify_api_error
        from agent.transports.codex import ResponsesApiTransport as Transport
        from agent.turn_retry_state import TurnRetryState
        from run_agent import AIAgent
    route = {
        "provider": "custom",
        "base_url": "https://fixture.invalid/v1",
        "model": "parity-model",
        "api_mode": "chat_completions",
        **case.get("route", {}),
    }
    transport = Transport()
    transport._last_issuer_kind = "other:" + route["base_url"]
    transport._last_issuer_model = route["model"]
    transport._last_sent_all_turns = case.get("all_turns", False)
    transport._all_turns_rejected = frozenset()
    if native:
        engine = SimpleNamespace(
            config={},
            _native_disabled=False,
            _anchor=None,
            compressor=SimpleNamespace(),
            _responses_transport=transport,
        )
        host = RecoveryHost(
            {
                **route,
                "model_name": route["model"],
                "api_key": case.get("key", "fixed-ascii-key"),
            },
            engine,
            lambda event: None,
        )
    else:
        host = SimpleNamespace(
            **route,
            log_prefix="",
            api_key=case.get("key", "fixed-ascii-key"),
            _persist_disabled=True,
            session_id=None,
            _session_db=None,
            _is_anthropic_oauth=False,
        )
        host._get_transport = lambda: transport
        host._recover_with_credential_pool = lambda **kwargs: (
            False,
            kwargs.get("has_retried_429", False),
        )
        host._extract_api_error_context = extract_api_error_context
        host._try_shrink_image_parts_in_messages = try_shrink_image_parts_in_messages
        for method in (
            "_disable_codex_reasoning_replay",
            "_content_has_image_parts",
            "_try_strip_image_parts_from_tool_messages",
        ):
            value = getattr(AIAgent, method)
            setattr(
                host,
                method,
                value
                if method == "_content_has_image_parts"
                else MethodType(value, host),
            )
    host._vprint = host._buffer_vprint = lambda *args, **kwargs: None
    host._image_rejecting_models = set()
    host._no_list_tool_content_models = set()
    host._reasoning_rejecting_routes = {}
    host._force_ascii_payload = False
    host._unicode_sanitization_passes = 0
    host._codex_reasoning_replay_enabled = True
    host._codex_reasoning_replay_rejected = False
    host._reasoning_effort_rejected = host._reasoning_disable_rejected = (
        host._reasoning_floor_required
    ) = False
    host._ephemeral_max_output_tokens = None
    host._wire_reasoning_config = None
    host.codex_responses_native_compaction = False
    host._client_kwargs = {
        "api_key": host.api_key,
        "default_headers": copy.deepcopy(case.get("headers", {})),
    }
    host.client = SimpleNamespace(api_key=host.api_key)
    host.tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "读 résumé",
                "parameters": {"type": "object"},
            },
        }
    ]
    messages = copy.deepcopy(case.get("messages", BASE_MESSAGES))
    api_messages = copy.deepcopy(messages)
    kwargs = {
        "model": host.model,
        "messages": api_messages,
        "tools": copy.deepcopy(host.tools),
        **copy.deepcopy(case.get("kwargs", {})),
    }
    active_system_prompt = "系统指令: inspect résumé."
    retry = TurnRetryState()
    steps = []
    for index, spec in enumerate(case.get("errors", [case.get("error")])):
        if index and case.get("new_turn_own"):
            messages.append(copy.deepcopy(OWN))
            api_messages.append(copy.deepcopy(OWN))
            retry = TurnRetryState()
        exc = _exception(spec)
        with patch.object(
            recovery,
            "_runtime_uses_ascii_encoding",
            return_value=case.get("locale_ascii", False),
        ):
            before, active_system_prompt = recovery.recover_before_classification(
                host,
                exc,
                messages=messages,
                api_messages=api_messages,
                api_kwargs=kwargs,
                active_system_prompt=active_system_prompt,
            )
        verdict = classify_api_error(
            exc, provider=host.provider, model=host.model, base_url=host.base_url
        )
        after = False
        if not before:
            after, _ = recovery.recover_after_classification(
                host,
                exc,
                verdict,
                retry,
                status_code=getattr(exc, "status_code", None),
                error_context=host._extract_api_error_context(exc),
                messages=messages,
                api_messages=api_messages,
            )
        steps.append(
            _plain(
                {
                    "before": before,
                    "after": after,
                    "reason": verdict.reason.value,
                    "messages": copy.deepcopy(messages),
                    "api_messages": copy.deepcopy(api_messages),
                    "kwargs": copy.deepcopy(kwargs),
                    "prompt": active_system_prompt,
                    "api_key": host.api_key,
                    "headers": host._client_kwargs["default_headers"],
                    "image_models": host._image_rejecting_models,
                    "tool_models": host._no_list_tool_content_models,
                    "ascii": host._force_ascii_payload,
                    "unicode_passes": host._unicode_sanitization_passes,
                    "replay_enabled": host._codex_reasoning_replay_enabled,
                    "replay_rejected": host._codex_reasoning_replay_rejected,
                    "all_turns_rejected": transport._all_turns_rejected,
                    "rejected_thinking": getattr(
                        host, "_anthropic_rejected_thinking", (None, set())
                    )[1],
                    "fast_unavailable": getattr(
                        host, "_fast_mode_unavailable_models", set()
                    ),
                }
            )
        )
    return steps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source))
    sources = {
        rel: hashlib.sha256((args.source / rel).read_bytes()).hexdigest()
        for rel in (
            "agent/turn_recovery.py",
            "agent/turn_recovery_codex.py",
            "agent/turn_retry_state.py",
            "agent/message_sanitization.py",
            "agent/transports/codex.py",
            "agent/anthropic_thinking_replay.py",
            "agent/fast_mode.py",
            "agent/tool_dispatch_helpers.py",
            "agent/prompt_cache_boundary.py",
            "agent/prompt_caching.py",
            "run_agent.py",
        )
    }
    data = {
        "commit": COMMIT,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sources": sources,
        "boundaries": [
            "fixed explicit route/credentials",
            "fixed provider error",
            "explicit runtime ASCII locale probe",
            "no SDK client, provider request, profiles, credential pools or session database",
        ],
        "cases": [{"input": case, "output": execute(case)} for case in CASES],
    }
    args.output.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
