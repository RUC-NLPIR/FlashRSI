"""Explicit asynchronous host for the original Hermes request-repair ladder.

All decisions and payload mutations live in the pinned source modules. This
host supplies route state, current wire kwargs, JSON persistence and the SDK-free
transport. It never reads ambient profiles or refreshes provider credentials.
"""

from __future__ import annotations

from types import SimpleNamespace

from . import chat_transport, native_responses
from .model_catalog import supports_vision
from .upstream_compaction.anthropic_thinking_replay import (
    apply_rejected_thinking_suppression,
)
from .upstream_loop.reasoning import reasoning_replay_route
from .upstream_recovery.cache_cleanup import strip_anthropic_cache_control
from .upstream_recovery.codex_methods import CodexMethods
from .upstream_recovery.error_context import extract_api_error_context
from .upstream_recovery.images import try_shrink_image_parts_in_messages
from .upstream_recovery.reasoning_wire import _reasoning_config_for_wire
from .upstream_recovery.recovery import (
    recover_after_classification,
    recover_before_classification,
)
from .upstream_recovery.retry_state import TurnRetryState
from .upstream_recovery.sanitization import (
    _sanitize_structure_non_ascii,
    reapply_reasoning_echo,
    rejected_reasoning_carriers,
    sanitize_outbound_kwargs,
    strip_images_for_rejecting_model,
)
from .upstream_recovery.vision_methods import VisionMethods

_ROUTE_FLAGS = (
    "_reasoning_effort_rejected",
    "_reasoning_disable_rejected",
    "_reasoning_floor_required",
    "_codex_reasoning_replay_rejected",
    "_codex_reasoning_replay_enabled",
)


class RecoveryHost(CodexMethods, VisionMethods):
    log_prefix = ""
    session_id = None
    _session_db = None
    _persist_disabled = True
    _is_anthropic_oauth = False
    _extract_api_error_context = staticmethod(extract_api_error_context)
    _try_shrink_image_parts_in_messages = staticmethod(try_shrink_image_parts_in_messages)

    def __init__(self, route, engine, event_sink, state=None):
        self.engine, self.emit = engine, event_sink
        self._route_states = {}
        self._reasoning_rejecting_routes = {}
        self._image_rejecting_models = set()
        self._no_list_tool_content_models = set()
        self._force_ascii_payload = False
        self._unicode_sanitization_passes = 0
        self._ephemeral_reasoning_off = False
        self._ephemeral_max_output_tokens = None
        self._wire_reasoning_config = None
        self._fast_mode_unavailable_models = set()
        self._route_key = None
        self.bind_route(route)
        self.restore(state)

    def _vprint(self, message, **kwargs):
        self.emit({"type": "diagnostic", "message": message})

    _buffer_vprint = _vprint

    def _get_transport(self):
        return getattr(self.engine, "_responses_transport", None)

    @property
    def _usage_anchor(self):
        return self.engine._anchor

    @_usage_anchor.setter
    def _usage_anchor(self, value):
        self.engine._anchor = value

    @property
    def context_compressor(self):
        return self.engine.compressor

    def _model_supports_vision(self):
        return supports_vision(self.route, getattr(self.engine, "settings", {})) is True

    def _provider_supports_vision_tool_messages(self):
        explicit = self.route.get("supports_vision_tool_messages")
        if explicit is not None:
            return bool(explicit)
        profile = chat_transport.provider_profile(self.provider)
        if profile and getattr(profile, "supports_vision_tool_messages", None) is False:
            return False
        if self.provider in {"openrouter", "ai-gateway"} or self.provider.startswith("custom:"):
            target, separator, _ = self.model.partition("/")
            profile = chat_transport.provider_profile(target) if separator else None
            if profile and getattr(profile, "supports_vision_tool_messages", None) is False:
                return False
        return True

    def _recover_with_credential_pool(self, **kwargs):
        return False, kwargs.get("has_retried_429", False)

    def _save_route(self):
        if self._route_key is not None:
            self._route_states[self._route_key] = {
                name: getattr(self, name, name == "_codex_reasoning_replay_enabled")
                for name in _ROUTE_FLAGS
            }

    def bind_route(self, route):
        self._save_route()
        self.route = route
        self.provider = route.get("provider", "custom")
        self.model = route.get("model_name", route.get("model", ""))
        self.base_url = route.get("base_url", "")
        self.api_key = route.get("api_key", "")
        self.api_mode = native_responses.api_mode(route)
        self._route_key = (self.provider, self.base_url, self.model)
        flags = self._route_states.get(self._route_key, {})
        for name in _ROUTE_FLAGS:
            setattr(self, name, flags.get(name, name == "_codex_reasoning_replay_enabled"))
        self._client_kwargs = {
            "api_key": self.api_key,
            "default_headers": {
                **route.get("default_headers", {}), **route.get("extra_headers", {}),
            },
        }
        self.client = SimpleNamespace(api_key=self.api_key)
        self.codex_responses_native_compaction = native_responses._flag(
            self.engine.config.get("codex_responses_native")
        ) and not self.engine._native_disabled
        self.engine._native_replay_disabled = not self._codex_reasoning_replay_enabled

    def reasoning_for_wire(self, config, ephemeral_off=False):
        self.reasoning_config = config
        self._ephemeral_reasoning_off = ephemeral_off
        return _reasoning_config_for_wire(self)

    def begin(self, messages, payload, system_prompt):
        if not hasattr(self, "tools"):
            self.tools = payload.get("tools") or []
        return RecoveryAttempt(self, messages, payload, system_prompt)

    def snapshot(self):
        self._save_route()
        transport = self._get_transport()
        return {
            "version": 1,
            "routes": [[*key, values] for key, values in self._route_states.items()],
            "reasoning_rejected_carriers": [[*key, sorted(value)] for key, value in self._reasoning_rejecting_routes.items()],
            "image_rejecting_models": [list(key) for key in sorted(self._image_rejecting_models)],
            "no_list_tool_content_models": [list(key) for key in sorted(self._no_list_tool_content_models)],
            "force_ascii_payload": self._force_ascii_payload,
            "all_turns_rejected": sorted(getattr(transport, "_all_turns_rejected", ()) or ()),
            "anthropic_rejected_thinking": sorted(getattr(self, "_anthropic_rejected_thinking", (None, set()))[1]),
            "fast_mode_unavailable_models": sorted(self._fast_mode_unavailable_models),
        }

    def restore(self, state):
        if not isinstance(state, dict) or state.get("version") != 1:
            return
        self._route_states = {
            tuple(row[:3]): {name: bool(row[3][name]) for name in _ROUTE_FLAGS if name in row[3]}
            for row in state.get("routes", [])
            if isinstance(row, list) and len(row) == 4 and isinstance(row[3], dict)
        }
        self._reasoning_rejecting_routes = {
            tuple(row[:3]): set(row[3]) & {"reasoning", "reasoning_content", "reasoning_details"}
            for row in state.get("reasoning_rejected_carriers", [])
            if isinstance(row, list) and len(row) == 4 and isinstance(row[3], list)
        }
        for name in ("image_rejecting_models", "no_list_tool_content_models"):
            setattr(self, "_" + name, {tuple(row) for row in state.get(name, []) if isinstance(row, list) and len(row) == 2})
        self._force_ascii_payload = bool(state.get("force_ascii_payload"))
        self._anthropic_rejected_thinking = (self.session_id, set(state.get("anthropic_rejected_thinking", [])))
        self._fast_mode_unavailable_models = set(state.get("fast_mode_unavailable_models", []))
        self._route_key = None
        self.bind_route(self.route)
        self.engine._recovery_all_turns_rejected = frozenset(state.get("all_turns_rejected", []))


class RecoveryAttempt:
    def __init__(self, host, messages, payload, system_prompt):
        self.host, self.messages, self.payload = host, messages, payload
        self.api_messages = payload["messages"]
        self.system_prompt = system_prompt
        self.wire_kwargs = {}
        self.retry_state = TurnRetryState()

    def prepare(self):
        host = self.host
        apply_rejected_thinking_suppression(host, self.api_messages)
        replay = reasoning_replay_route(
            host.api_mode, host.provider, host.model, host.base_url,
            rejected=rejected_reasoning_carriers(host),
        )
        reapply_reasoning_echo(self.api_messages, *replay)
        strip_anthropic_cache_control(self.api_messages)
        strip_images_for_rejecting_model(host, self.api_messages)
        if (host.provider.lower(), host.model) in host._no_list_tool_content_models:
            host._try_strip_image_parts_from_tool_messages(self.api_messages)
        cap = host._ephemeral_max_output_tokens
        if cap is not None:
            key = "max_completion_tokens" if "max_completion_tokens" in self.payload else "max_tokens"
            self.payload[key] = cap
            self.payload.pop("max_tokens" if key == "max_completion_tokens" else "max_completion_tokens", None)
            host._ephemeral_max_output_tokens = None

    def capture(self, kwargs):
        self.wire_kwargs = kwargs

    def sanitize(self, kwargs):
        sanitize_outbound_kwargs(self.host, kwargs)

    def sync(self):
        host = self.host
        host.route["api_key"] = host.api_key
        if host._force_ascii_payload:
            _sanitize_structure_non_ascii(self.payload)
        for key in ("default_headers", "extra_headers"):
            values = host.route.get(key)
            if isinstance(values, dict):
                for name in values:
                    if name in host._client_kwargs["default_headers"]:
                        values[name] = host._client_kwargs["default_headers"][name]
        host.engine._native_disabled = not host.codex_responses_native_compaction if host.engine.config.get("codex_responses_native") else host.engine._native_disabled
        host.engine._native_replay_disabled = not host._codex_reasoning_replay_enabled

    def before(self, error):
        recovered, self.system_prompt = recover_before_classification(
            self.host, error, messages=self.messages, api_messages=self.api_messages,
            api_kwargs=self.wire_kwargs, active_system_prompt=self.system_prompt,
        )
        self.sync()
        return recovered

    def after(self, error, verdict):
        recovered, _ = recover_after_classification(
            self.host, error, verdict, self.retry_state,
            status_code=getattr(error, "status_code", None),
            error_context=self.host._extract_api_error_context(error),
            messages=self.messages, api_messages=self.api_messages,
        )
        self.sync()
        return recovered
