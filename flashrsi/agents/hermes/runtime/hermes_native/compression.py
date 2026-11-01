"""Explicit host for Hermes v0.22.5's native Python context compressor.

The policy implementation is pinned in ``upstream_compaction``. This module owns
only the async I/O boundary, request accounting, atomic adoption and explicit
session state; it never imports an installed Hermes package or reads a profile.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Mapping

from .upstream_compaction import (
    auxiliary_client,
    clock,
    host_boundaries,
)
from .upstream_compaction.context_boundary import _fold_todo_snapshot
from .upstream_compaction.context_compressor import (
    ContextCompressor,
    salvage_grown_transcript,
)
from .upstream_compaction.context_errors import (
    get_context_length_from_provider_error,
    is_output_cap_error,
    parse_available_output_tokens_from_error,
)
from .upstream_compaction.conversation_compression_deadline import (
    resolve_context_compression_timeouts,
)
from .upstream_compaction.model_metadata import (
    estimate_messages_tokens_rough,
    estimate_request_tokens_rough,
    get_model_context_length,
)
from .upstream_compaction.usage_anchor import (
    anchored_context_tokens,
    capture_usage_anchor,
)


@dataclass(frozen=True)
class Recovery:
    retry: bool
    max_tokens: int | None = None
    reason: str = ""


def _mapping(value):
    if isinstance(value, Mapping):
        return dict(value)
    return vars(value) if hasattr(value, "__dict__") else {}


def _positive(value):
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result > 0 else None


def _integer(value, default, minimum=0, maximum=None):
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return (
        max(minimum, result) if maximum is None else min(maximum, max(minimum, result))
    )


def _flag(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _api_mode(route):
    mode = str(route.get("model_api") or route.get("api_mode") or "chat_completions")
    return (
        "codex_responses"
        if mode in {"responses", "openai-responses", "codex_responses"}
        else mode
    )


def resolve_context_length(settings, llm):
    """Explicit window overrides precede the pinned catalog; no metadata HTTP probes."""
    settings, llm = _mapping(settings), _mapping(llm)
    model_cfg = _mapping(settings.get("model"))
    context_cfg = _mapping(settings.get("context"))
    configured = next(
        (
            v
            for v in (
                settings.get("context_length"),
                model_cfg.get("context_length"),
                context_cfg.get("context_length"),
                llm.get("context_length"),
            )
            if _positive(v)
        ),
        None,
    )
    model = llm.get("model_name") or llm.get("model") or model_cfg.get("default", "")
    return get_model_context_length(
        str(model),
        config_context_length=_positive(configured),
        custom_providers=settings.get("custom_providers"),
        provider=llm.get("provider", "custom"),
        base_url=llm.get("base_url", ""),
        model_catalog_settings=settings,
    )


def _response_object(data):
    """Upstream micro-compaction accepts SDK-shaped responses; HTTP stays plain JSON."""
    if not isinstance(data, dict):
        return data
    result = dict(data)
    result["choices"] = [
        SimpleNamespace(**choice) if isinstance(choice, dict) else choice
        for choice in data.get("choices") or []
    ]
    return SimpleNamespace(**result)


def _serialized_bytes(messages):
    try:
        return len(
            json.dumps(messages, ensure_ascii=False, default=str).encode("utf-8")
        )
    except (TypeError, ValueError):
        return 0


class ContextEngine:
    """One explicit role/run's compressor and resumable context state."""

    def __init__(self, settings, llm, tools=None, event_sink=None):
        self.settings = _mapping(settings)
        self.llm = _mapping(llm)
        self.tools, self.event_sink = tools, event_sink
        self.config = _mapping(self.settings.get("compression"))
        cfg = self.config
        self.enabled = _flag(cfg.get("enabled"), True)
        self.checkpoint_required = _flag(cfg.get("checkpoint_required"))
        model_cfg = _mapping(self.settings.get("model"))
        self.model = str(
            self.llm.get("model_name")
            or self.llm.get("model")
            or model_cfg.get("default", "")
        )
        attempts = _integer(cfg.get("max_attempts", 3), 3)
        self.max_attempts = min(attempts if attempts >= 1 else 3, 10)
        self.attempts = 0
        self._boundary_pending = False
        self._native_disabled = False
        self._native_checkpoint_pending = False
        self._anchor = None
        self._archive: list[dict] = []
        self._last_activity = float(self.settings.get("_last_activity") or clock.time())
        self._idle_checked = False
        self._generation = 0
        self._lock = asyncio.Lock()
        self.compressor = ContextCompressor(
            model=self.model,
            threshold_percent=float(cfg.get("threshold", 0.50)),
            protect_first_n=_integer(cfg.get("protect_first_n", 3), 3),
            protect_last_n=_integer(cfg.get("protect_last_n", 20), 20),
            summary_target_ratio=float(cfg.get("target_ratio", 0.20)),
            quiet_mode=True,
            summary_model_override=cfg.get("summary_model"),
            base_url=str(self.llm.get("base_url") or ""),
            api_key=str(self.llm.get("api_key") or ""),
            config_context_length=resolve_context_length(self.settings, self.llm),
            provider=str(self.llm.get("provider") or ""),
            api_mode=_api_mode(self.llm),
            abort_on_summary_failure=_flag(cfg.get("abort_on_summary_failure")),
            max_tokens=_positive(
                self.llm.get("max_completion_tokens", self.llm.get("max_tokens"))
            ),
            model_thresholds=_mapping(cfg.get("model_thresholds")),
            threshold_tokens_cap=cfg.get("threshold_tokens"),
            proactive_prune_tokens=_integer(cfg.get("proactive_prune_tokens", 0), 0),
            proactive_prune_min_result_chars=_integer(
                cfg.get("proactive_prune_min_result_chars", 8000), 8000
            ),
            proactive_prune_min_reclaim_tokens=_integer(
                cfg.get("proactive_prune_min_reclaim_tokens", 4096), 4096
            ),
            min_tail_user_messages=_integer(cfg.get("min_tail_user_messages", 1), 1, 1),
            tail_mode=str(cfg.get("tail_mode", "lean")),
            custom_providers=self.settings.get("custom_providers"),
        )
        self.compressor._micro_compact_enabled = (
            _flag(cfg.get("micro_compact")) and not self.checkpoint_required
        )
        self.compressor._micro_compact_every_n_turns = _integer(
            cfg.get("micro_compact_every_n_turns", 1), 1, 1
        )
        self.compressor._micro_compact_defrag_threshold_tokens = _integer(
            cfg.get("micro_compact_defrag_threshold_tokens", 2000), 2000, 1
        )
        # Local archive is exposed by the host's session_search tool; no upstream DB is imported.
        self.compressor._session_id = (
            str(self.settings.get("session_id") or "native")
            if "session_search" in getattr(tools, "enabled", ())
            else ""
        )
        self._aux_config = _mapping(
            _mapping(self.settings.get("auxiliary")).get("compression")
        )
        self._apply_aux_context_ceiling()

    @property
    def context_length(self):
        return self.compressor.context_length

    def _apply_aux_context_ceiling(self):
        aux = self._aux_config
        aux_model = aux.get("model")
        if not aux_model or aux_model == self.model:
            return
        ceiling = get_model_context_length(
            aux_model,
            config_context_length=_positive(aux.get("context_length")),
            provider=aux.get("provider", self.llm.get("provider", "custom")),
            base_url=aux.get("base_url", self.llm.get("base_url", "")),
            model_catalog_settings=self.settings,
        )
        if 0 < ceiling < self.compressor.threshold_tokens:
            self.compressor._aux_context_ceiling = ceiling
            self.compressor._apply_threshold_tokens_cap()

    def _emit(self, event):
        if self.event_sink is not None:
            self.event_sink(event)

    def _schemas(self):
        return getattr(self.tools, "schemas", None) or None

    def _estimate(self, messages, system_prompt):
        return estimate_request_tokens_rough(
            messages,
            system_prompt=system_prompt or "",
            tools=self._schemas(),
            charge_stale_thinking=self.compressor._stale_thinking_on_wire(),
        )

    def _pressure(self, messages, system_prompt):
        tokens = anchored_context_tokens(
            messages,
            self._anchor,
            charge_stale_thinking=self.compressor._stale_thinking_on_wire(),
        )
        if tokens is None:
            from .native_responses import estimate_native_tokens

            native_tokens = estimate_native_tokens(
                self, messages, system_prompt, self._schemas()
            )
            if native_tokens is not None:
                return native_tokens, False
        return (
            (tokens, True)
            if tokens is not None
            else (self._estimate(messages, system_prompt), False)
        )

    def after_response(self, usage, messages):
        """Observe usage before the corresponding assistant row is appended."""
        usage = _mapping(usage)
        pt = _integer(usage.get("prompt_tokens", usage.get("input_tokens", 0)), 0)
        ct = _integer(usage.get("completion_tokens", usage.get("output_tokens", 0)), 0)
        self.compressor.update_from_response(
            {**usage, "prompt_tokens": pt, "completion_tokens": ct}
        )
        if pt > 0:
            self._anchor = capture_usage_anchor(pt, ct, messages)
            if self._boundary_pending and pt < self.compressor.threshold_tokens:
                self.attempts = 0
                self._boundary_pending = False
        else:
            self.compressor.note_usage_less_response()
        if self._native_checkpoint_pending:
            self._native_checkpoint_pending = False
            self._apply_native_checkpoint()
        self._last_activity = clock.time()

    def note_native_checkpoint(self):
        """Apply the checkpoint latch after its response's pre-checkpoint usage is observed."""
        self._native_checkpoint_pending = True

    def _apply_native_checkpoint(self):
        self.compressor.note_native_compaction_checkpoint()
        self._anchor = None
        reset = getattr(self.tools, "reset_read_dedup", None)
        if callable(reset):
            reset()

    async def before_request(self, messages, system_prompt, send_summary):
        if not self.enabled:
            return False
        changed = False
        if not self._idle_checked:
            self._idle_checked = True
            from .native_responses import has_replayable_checkpoint

            if has_replayable_checkpoint(self, messages):
                self._apply_native_checkpoint()
            self.compressor.lift_structural_backoff_if_grown(
                len(messages) + bool(system_prompt)
            )
            idle = _integer(self.config.get("idle_compact_after_seconds", 0), 0)
            tokens, _ = self._pressure(messages, system_prompt)
            floor = int(
                self.compressor.threshold_tokens * self.compressor.summary_target_ratio
            )
            if self.compressor.last_compression_rough_tokens > 0:
                floor = max(
                    floor, self.compressor.last_compression_rough_tokens + floor
                )
            if (
                idle > 0
                and clock.time() - self._last_activity >= idle
                and tokens > floor
                and not self.compressor.awaiting_real_usage_after_compression
                and not self.compressor.get_active_compression_failure_cooldown()
            ):
                changed = await self._rewrite(
                    "idle", messages, system_prompt, send_summary, current_tokens=tokens
                )
        return await self._automatic(messages, system_prompt, send_summary) or changed

    async def after_tools(self, messages, system_prompt, send_summary):
        if not self.enabled:
            return False
        if await self._automatic(messages, system_prompt, send_summary):
            return True
        return await self._prune(messages, system_prompt, send_summary)

    async def _automatic(self, messages, system_prompt, send_summary):
        tokens, anchored = self._pressure(messages, system_prompt)
        if not anchored and self.compressor.should_defer_preflight_to_real_usage(
            tokens
        ):
            return False
        if self.attempts >= self.max_attempts or not self.compressor.should_compress(
            tokens
        ):
            return False
        self.attempts += 1
        return await self._rewrite(
            "threshold", messages, system_prompt, send_summary, current_tokens=tokens
        )

    async def _prune(self, messages, system_prompt, send_summary):
        if self.compressor.proactive_prune_tokens <= 0:
            return False
        tokens, _ = self._pressure(messages, system_prompt)
        return await self._rewrite(
            "prune", messages, system_prompt, send_summary, current_tokens=tokens
        )

    async def compact(
        self, messages, system_prompt, send_summary, force=True, focus_topic=None
    ):
        return await self._rewrite(
            "manual",
            messages,
            system_prompt,
            send_summary,
            current_tokens=self._pressure(messages, system_prompt)[0],
            force=force,
            focus_topic=focus_topic,
        )

    async def finalise_turn(self, messages, system_prompt, send_summary):
        self._last_activity = clock.time()
        if not self.enabled or not self.compressor._micro_compact_enabled:
            return False
        return await self._rewrite("micro", messages, system_prompt, send_summary)

    def _summary_route(self, kwargs):
        authoritative = (
            isinstance(kwargs.get("task"), str) and type(kwargs.get("task")) is not str
        )
        fields = ("provider", "model", "base_url", "api_key", "api_mode", "timeout")
        explicit = {key: kwargs[key] for key in fields if key in kwargs}
        # Complete authoritative runtime cannot fill missing fields from a failed aux route.
        pin = bool(explicit) and any(
            key in explicit for key in ("provider", "base_url", "api_key", "api_mode")
        )
        if pin and not authoritative:
            # A pinned fallback is a complete route: it must never inherit a different host's key.
            base = dict(explicit)
        elif authoritative:
            base = dict(self.llm)
        else:
            base = {**self.llm, **self._aux_config}
            for key in ("base_url", "provider"):
                if self._aux_config.get(key) and self._aux_config[key] != self.llm.get(
                    key
                ):
                    base["api_key"] = self._aux_config.get("api_key", "")
                    break
        base.update(explicit)
        # An auxiliary/fallback protocol is authoritative over an inherited main role alias.
        explicit_mode = next(
            (
                r
                for r in (explicit, {} if authoritative else self._aux_config)
                if r.get("api_mode") or r.get("model_api")
            ),
            None,
        )
        if explicit_mode is not None:
            base["api_mode"] = _api_mode(explicit_mode)
        elif (
            any(
                self._aux_config.get(key) and self._aux_config[key] != self.llm.get(key)
                for key in ("base_url", "provider")
            )
            and not authoritative
            and not pin
        ):
            base["api_mode"] = "chat_completions"
        else:
            base["api_mode"] = _api_mode(base)
        base.pop("model_api", None)
        summary_effort = (
            self._aux_config.get("reasoning_effort")
            if not authoritative and not pin
            else None
        )
        if summary_effort is not None:
            effort = str(summary_effort).strip().lower()
            base["_summary_reasoning_config"] = {
                "enabled": effort not in {"none", "off", "false"},
                "effort": "none" if effort in {"none", "off", "false"} else effort,
            }
        base["model"] = (
            explicit.get("model")
            or base.get("model_name")
            or base.get("model")
            or self.model
        )
        if (
            self._aux_config.get("model")
            and not explicit.get("model")
            and not authoritative
        ):
            base["model"] = self._aux_config["model"]
        base.setdefault("api_key", "")
        return base

    async def _rewrite(self, mode, messages, system_prompt, send_summary, **kwargs):
        """Run an isolated policy worker; adopt state/history only while owning the attempt."""
        async with self._lock:
            if self.checkpoint_required:
                checkpoint = getattr(self.tools, "checkpoint_context", None)
                try:
                    token = (
                        checkpoint(copy.deepcopy(messages), self.snapshot_state())
                        if callable(checkpoint)
                        else None
                    )
                    if hasattr(token, "__await__"):
                        token = await token
                except Exception as error:
                    token = None
                    self._emit(
                        {
                            "type": "compression_checkpoint",
                            "committed": False,
                            "reason": str(error),
                        }
                    )
                if not token:
                    self._emit(
                        {
                            "type": "compression",
                            "mode": mode,
                            "committed": False,
                            "reason": "checkpoint_required_unavailable",
                        }
                    )
                    return False
            original = copy.deepcopy(messages)
            worker = copy.deepcopy(self.compressor)
            packed = (
                [{"role": "system", "content": system_prompt}] if system_prompt else []
            ) + copy.deepcopy(messages)
            self._generation += 1
            generation = self._generation
            cancelled = threading.Event()
            worker._compression_cancelled_check = cancelled.is_set
            loop = asyncio.get_running_loop()
            pending = set()
            idle, ceiling = resolve_context_compression_timeouts(self.config)

            async def dispatch(call_kwargs):
                route = self._summary_route(call_kwargs)
                payload = {
                    "model": route["model"],
                    "messages": call_kwargs["messages"],
                    "stream": False,
                }
                for key in ("temperature", "max_tokens", "tools"):
                    if call_kwargs.get(key) is not None:
                        payload[key] = call_kwargs[key]
                extra = route.get("extra_body")
                if isinstance(extra, dict):
                    payload.update(
                        {
                            key: value
                            for key, value in extra.items()
                            if key
                            not in {
                                "model",
                                "messages",
                                "max_tokens",
                                "max_completion_tokens",
                            }
                        }
                    )
                if isinstance(call_kwargs.get("route_info"), dict):
                    call_kwargs["route_info"].update(
                        provider=route.get("provider") or "custom", model=route["model"]
                    )
                coro = send_summary(payload, route)
                result = await asyncio.wait_for(coro, idle) if idle > 0 else await coro
                return _response_object(result)

            def sync_dispatch(**call_kwargs):
                if cancelled.is_set():
                    raise auxiliary_client.AuxiliaryExplicitCancellation()
                future = asyncio.run_coroutine_threadsafe(dispatch(call_kwargs), loop)
                pending.add(future)
                try:
                    return future.result()
                finally:
                    pending.discard(future)

            secret_values = tuple(
                {
                    str(route.get("api_key"))
                    for route in (self.llm, self._aux_config)
                    if route.get("api_key")
                }
            )

            def run_policy():
                cb = auxiliary_client.callback.set(sync_dispatch)
                sec = host_boundaries.secrets.set(secret_values)
                config_token = host_boundaries.compression_config.set(self.config)
                try:
                    if mode == "prune":
                        candidate, count = worker.prune_tool_results_only(
                            packed, kwargs.get("current_tokens")
                        )
                        return candidate, count > 0
                    if mode == "micro":
                        before = copy.deepcopy(packed)
                        candidate = worker._micro_compact(packed)
                        return candidate, candidate != before
                    candidate = worker.compress(packed, **kwargs)
                    return candidate, bool(worker._last_compression_made_progress)
                finally:
                    auxiliary_client.callback.reset(cb)
                    host_boundaries.secrets.reset(sec)
                    host_boundaries.compression_config.reset(config_token)

            try:
                task = asyncio.to_thread(run_policy)
                candidate, progress = (
                    await asyncio.wait_for(task, ceiling) if idle > 0 else await task
                )
            except asyncio.CancelledError:
                cancelled.set()
                self._generation += 1
                for future in tuple(pending):
                    future.cancel()
                raise
            except (TimeoutError, auxiliary_client.AuxiliaryExplicitCancellation):
                cancelled.set()
                for future in tuple(pending):
                    future.cancel()
                self.compressor.record_timeout_failure(
                    "Context compression summary timed out"
                )
                self._emit(
                    {
                        "type": "compression",
                        "mode": mode,
                        "committed": False,
                        "reason": "timeout",
                    }
                )
                return False
            finally:
                worker._compression_cancelled_check = None
            if (
                cancelled.is_set()
                or generation != self._generation
                or messages != original
            ):
                return False
            if not progress:
                self.compressor = worker
                self._emit(
                    {
                        "type": "compression",
                        "mode": mode,
                        "committed": False,
                        "reason": worker._last_summary_error
                        or "no_compressible_window",
                    }
                )
                return False
            if system_prompt and candidate and candidate[0].get("role") == "system":
                candidate = candidate[1:]
            if (
                self.tools is not None
                and getattr(self.tools, "todos", None) is not None
            ):
                shim = SimpleNamespace(
                    _todo_store=self.tools.todos,
                    _repair_message_sequence=lambda items: None,
                )
                _fold_todo_snapshot(shim, candidate)
            if mode not in ("prune", "micro"):
                old_tokens = estimate_messages_tokens_rough(original)
                if estimate_messages_tokens_rough(candidate) > old_tokens:
                    candidate = salvage_grown_transcript(
                        original, candidate, budget=old_tokens
                    )
                    if candidate is None:
                        self.compressor.record_rejected_compaction()
                        self._emit(
                            {
                                "type": "compression",
                                "mode": mode,
                                "committed": False,
                                "reason": "would_grow",
                            }
                        )
                        return False
            self._archive_messages(original)
            messages[:] = candidate
            self.compressor = worker
            self._anchor = None
            worker.last_compression_rough_tokens = self._estimate(
                messages, system_prompt
            )
            worker.last_prompt_tokens, worker.last_completion_tokens = -1, 0
            worker.awaiting_real_usage_after_compression = True
            if mode not in ("prune", "micro"):
                worker.record_completed_compaction(
                    used_fallback=worker._last_summary_fallback_used,
                    feasibility_skip=worker._last_feasibility_skip,
                )
            self._boundary_pending = True
            if self.tools is not None:
                for name in ("reset_read_dedup", "reset_skill_dedup"):
                    reset = getattr(self.tools, name, None)
                    if callable(reset):
                        reset()
            self._emit(
                {
                    "type": "compression",
                    "mode": mode,
                    "committed": True,
                    "messages_before": len(original),
                    "messages_after": len(messages),
                    "threshold_tokens": worker.threshold_tokens,
                    "fallback": bool(worker._last_summary_fallback_used),
                }
            )
            return True

    async def recover(self, error, messages, system_prompt, send_summary):
        response = getattr(error, "response", None)
        status = getattr(error, "status_code", None) or getattr(
            response, "status_code", None
        )
        text = str(error)
        if response is not None:
            try:
                text += " " + response.text
            except Exception:
                pass
        available = parse_available_output_tokens_from_error(text)
        lower = text.lower()
        from .native_compaction import is_native_compaction_rejection

        if (
            _api_mode(self.llm) == "codex_responses"
            and _flag(self.config.get("codex_responses_native"))
            and not self._native_disabled
            and is_native_compaction_rejection(text, status)
        ):
            self._native_disabled = True
            self._emit(
                {
                    "type": "compression",
                    "mode": "native",
                    "committed": False,
                    "reason": "native_compaction_rejected",
                }
            )
            return Recovery(True, reason="native_compaction_rejected")
        output_cap = is_output_cap_error(text)
        payload = status == 413 or any(
            p in lower
            for p in (
                "request entity too large",
                "payload too large",
                "request body too large",
            )
        )
        overflow = any(
            p in lower
            for p in (
                "context_length_exceeded",
                "context length",
                "maximum context",
                "context window",
                "prompt is too long",
                "prompt too long",
                "input is too long",
                "too many tokens",
                "input token count",
                "max_model_len",
                "maximum model length",
            )
        )
        if not (available is not None or output_cap or payload or overflow):
            return Recovery(False, reason="unrelated_error")
        if output_cap and available is None:
            return Recovery(False, reason="unparseable_output_cap")
        if available is not None:
            if self.attempts >= self.max_attempts:
                return Recovery(False, reason="max_compression_attempts")
            self.attempts += 1
            local = self.context_length - self._estimate(messages, system_prompt)
            cap = max(1, (min(available, local) if local > 0 else available) - 64)
            if self.enabled:
                try:
                    await self._rewrite(
                        "output_cap",
                        messages,
                        system_prompt,
                        send_summary,
                        current_tokens=self._pressure(messages, system_prompt)[0],
                        bypass_cooldown=True,
                    )
                except Exception:
                    pass
            return Recovery(True, max_tokens=cap, reason="output_cap")
        if not self.enabled:
            return Recovery(False, reason="compression_disabled")
        new_window = (
            get_context_length_from_provider_error(text, self.context_length)
            if overflow
            else None
        )
        if new_window is not None:
            self.compressor.update_model(
                model=self.model,
                context_length=new_window,
                base_url=self.compressor.base_url,
                api_key=self.compressor.api_key,
                provider=self.compressor.provider,
                api_mode=self.compressor.api_mode,
            )
            self.compressor._context_probed = True
        # Original turn_overflow.py leaves an unexplained small local request intact:
        # another request can own a single-slot server's context temporarily.
        from .upstream_compaction.context_endpoints import is_local_endpoint

        request_tokens = self._estimate(messages, system_prompt) + max(
            0,
            _integer(
                self.llm.get("max_completion_tokens", self.llm.get("max_tokens", 0)), 0
            ),
        )
        if (
            overflow
            and is_local_endpoint(str(self.llm.get("base_url") or ""))
            and not re.search(r"\d{4,}", text)
            and self.context_length > 0
            and request_tokens < self.context_length * 0.5
        ):
            self._emit(
                {
                    "type": "compression",
                    "mode": "context_overflow",
                    "committed": False,
                    "reason": "unexplained_local_context_rejection",
                }
            )
            return Recovery(False, reason="unexplained_local_context_rejection")
        if self.attempts >= self.max_attempts:
            return Recovery(False, reason="max_compression_attempts")
        self.attempts += 1
        original_count = len(messages)
        original_size = (
            _serialized_bytes(messages)
            if payload
            else estimate_messages_tokens_rough(messages)
        )
        await self._rewrite(
            "payload_too_large" if payload else "context_overflow",
            messages,
            system_prompt,
            send_summary,
            current_tokens=self._pressure(messages, system_prompt)[0],
            bypass_cooldown=True,
        )
        new_size = (
            _serialized_bytes(messages)
            if payload
            else estimate_messages_tokens_rough(messages)
        )
        progress = len(messages) < original_count or 0 < new_size < original_size * 0.95
        return Recovery(
            bool(progress or new_window is not None),
            reason="payload_too_large" if payload else "context_overflow",
        )

    def _archive_messages(self, messages):
        seen = {item["sha256"] for item in self._archive}
        for message in messages:
            raw = json.dumps(message, sort_keys=True, ensure_ascii=False, default=str)
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            if digest not in seen:
                seen.add(digest)
                self._archive.append(
                    {"sha256": digest, "message": copy.deepcopy(message)}
                )

    def search_archive(self, query="", session_id=None, limit=5):
        if session_id not in (None, "", self.compressor._session_id):
            return {"results": [], "session_id": self.compressor._session_id}
        query = str(query or "").casefold()
        results = []
        for index, item in enumerate(self._archive):
            message = item["message"]
            content = str(message.get("content") or "")
            offset = content.casefold().find(query) if query else 0
            if offset >= 0:
                start = max(0, offset - 300)
                results.append(
                    {
                        "index": index,
                        "role": message.get("role"),
                        "content": content[start : start + 6000],
                        "sha256": item["sha256"],
                        "total_chars": len(content),
                    }
                )
        return {
            "session_id": self.compressor._session_id,
            "results": results[-_integer(limit, 5, 1, 20) :],
            "total_matches": len(results),
        }

    def snapshot_state(self):
        # Configuration/credentials and runtime objects are deliberately not session state.
        names = (
            "compression_count",
            "last_prompt_tokens",
            "last_completion_tokens",
            "last_total_tokens",
            "last_real_prompt_tokens",
            "last_compression_rough_tokens",
            "awaiting_real_usage_after_compression",
            "summary_model",
            "_previous_summary",
            "_summary_has_user_turn",
            "_last_summary_error",
            "_consecutive_timeout_failures",
            "_consecutive_truncation_failures",
            "_consecutive_overload_aborts",
            "_last_summary_auth_failure",
            "_last_summary_network_failure",
            "_last_summary_truncated_failure",
            "_last_summary_empty_content_failure",
            "_last_summary_overload_failure",
            "_fallback_compression_streak",
            "_fallback_probe_at",
            "_ineffective_compression_count",
            "_anti_thrash_recovery_deadline",
            "_structural_no_op_len",
            "_proactive_prune_rearm_tokens",
            "_verify_compaction_cleared_threshold",
            "_provider_omits_usage",
            "_summary_model_fallen_back",
            "_micro_compact_cursor",
            "_micro_compact_rolling_summary",
            "_micro_compact_failure_cursor",
            "_micro_compact_failure_count",
            "_micro_compact_consecutive_failures",
            "_micro_compact_last_failure_cursor",
            "_micro_compact_passes",
            "_micro_compact_tokens_saved_total",
            "_micro_compact_turns_since_pass",
        )
        attrs = {
            name: copy.deepcopy(getattr(self.compressor, name))
            for name in names
            if hasattr(self.compressor, name)
        }
        now = clock.monotonic()
        for name in (
            "_summary_failure_cooldown_until",
            "_structural_no_op_backoff_until",
        ):
            attrs[name] = max(0.0, getattr(self.compressor, name, 0) - now)
        return {
            "version": 1,
            "model": self.model,
            "context_length": self.context_length,
            "saved_at": clock.time(),
            "last_activity": self._last_activity,
            "attempts": self.attempts,
            "boundary_pending": self._boundary_pending,
            "native_disabled": self._native_disabled,
            "anchor": copy.deepcopy(self._anchor),
            "compressor": attrs,
            "archive": copy.deepcopy(self._archive),
        }

    def restore_state(self, state):
        if (
            not isinstance(state, dict)
            or state.get("version") != 1
            or state.get("model") != self.model
        ):
            return
        allowed = set(self.snapshot_state()["compressor"]) | {
            "_summary_model_fallen_back"
        }
        attrs = state.get("compressor")
        age = max(0.0, clock.time() - float(state.get("saved_at") or clock.time()))
        if isinstance(attrs, dict):
            for name, value in attrs.items():
                if name not in allowed:
                    continue
                if name in (
                    "_summary_failure_cooldown_until",
                    "_structural_no_op_backoff_until",
                ):
                    value = clock.monotonic() + max(0.0, float(value) - age)
                setattr(self.compressor, name, copy.deepcopy(value))
        window = _positive(state.get("context_length"))
        if window and window < self.context_length:
            self.compressor.context_length = window
        self._anchor = copy.deepcopy(state.get("anchor"))
        self.attempts = _integer(state.get("attempts", 0), 0, 0, self.max_attempts)
        self._boundary_pending = bool(state.get("boundary_pending"))
        self._native_disabled = bool(state.get("native_disabled"))
        self._last_activity = float(state.get("last_activity") or self._last_activity)
        archive = state.get("archive")
        if isinstance(archive, list):
            self._archive = [
                copy.deepcopy(item)
                for item in archive
                if isinstance(item, dict)
                and isinstance(item.get("message"), dict)
                and isinstance(item.get("sha256"), str)
            ]
