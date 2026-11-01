"""Hermes's headless Chat/Responses conversation path, using upstream policies.

The upstream product's gateway, session database, provider discovery and UI are
outside this explicit-configuration runtime. Policy helpers and iteration
accounting come from the pinned upstream Python source beside this module.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import httpx

from . import anthropic_transport, chat_transport, native_responses
from ._vendor.truncation import boosted_output_cap
from .compression import ContextEngine, resolve_context_length
from .iteration_budget import IterationBudget
from .native_continuation import ContinuationState
from .policy import (
    _DROPPED_TOOLCALL_NUDGE_CONTENT,
    _EMPTY_SUMMARY_RESPONSE,
    _EMPTY_TOOL_RESPONSE_NUDGE,
    EMPTY_RESPONSE_EXPLANATION,
    MAX_ITERATIONS_SUMMARY_REQUEST,
    TOOL_CALL_ARGUMENTS_CORRUPTION_MARKER,
    TRUNCATED_ACTION,
    TRUNCATED_ACTION_UNREPORTED,
    _coerce_content_text,
    _deduplicate_tool_calls,
    _get_continuation_prompt,
    _invalid_tool_name_error_content,
    _join_truncated_parts,
    extract_reasoning,
    repair_tool_call,
    strip_think_blocks,
)
from .recovery import RecoveryHost
from .resources import load_resources
from .retry import InvalidResponseError, ProviderError, RetryBudget
from .session import Session
from .tools import HermesTools
from .upstream_chat.gemini import is_native_gemini_base_url
from .upstream_compaction.responses_adapter import (
    _derive_responses_function_call_id,
    _split_responses_tool_id,
)
from .upstream_loop import empty_response_guard
from .upstream_loop.assistant_storage import _assistant_tool_call_dict
from .upstream_loop.fallback import _fallback_entries
from .upstream_loop.guards import (
    intent_ack_continuation_mode,
    looks_like_codex_intermediate_ack,
    looks_like_degenerate_final,
    promoted_reasoning_announces_action,
    tool_results_this_turn,
    trailing_continue_intent,
)
from .upstream_loop.history import AIAgent as HistoryPolicy
from .upstream_loop.housekeeping import _HOUSEKEEPING_TOOLS, _LINE_IS_REPLY_TOOLS
from .upstream_loop.nudges import (
    _CODEX_ACK_CONTINUATION_NUDGE,
    _DEGENERATE_FINAL_NUDGE,
)
from .upstream_loop.provider_label import provider_label
from .upstream_loop.reasoning import (
    apply_reasoning_content_policy,
    reasoning_replay_route,
)
from .upstream_loop.reasoning_carriers import carrier_record
from .upstream_loop.reasoning_promotion import answer_in_reasoning_capability
from .upstream_loop.refusal import content_policy_copy
from .upstream_loop.repetition_guard import (
    STOP_PATH_MIN_CHARS,
    is_repetition_dominated,
    is_runaway_repetition,
)
from .upstream_loop.stale_markers import _STALE_MARKER_RE
from .upstream_loop.toolcall_ids import deterministic_call_id
from .upstream_loop.truncation import (
    _CEILING_NO_TEXT,
    _REPETITION_DOMINATED,
    _WINDOW_FILLED,
    _prompt_filled_window,
    repetition_copy,
)

_TOOL_CALL_STORAGE_POLICY = SimpleNamespace(
    _split_responses_tool_id=_split_responses_tool_id,
    _derive_responses_function_call_id=_derive_responses_function_call_id,
    _deterministic_call_id=deterministic_call_id,
)


@dataclass
class NativeHermesResult:
    output: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    status: str = "finished"
    error_message: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)


class _PartialTurn(Exception):
    def __init__(self, output, detail=None):
        super().__init__(detail or output)
        self.output = output


class _RouteRestart(Exception):
    """A fallback changed route; repeat preflight before spending an iteration."""


class _ContentPolicyBlocked(Exception):
    def __init__(self, output, detail):
        super().__init__(f"content_policy_blocked: {detail}")
        self.output = output


def _call_objects(raw: Any) -> list[SimpleNamespace]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Hermes provider returned a non-list tool_calls field")
    result = []
    for index, call in enumerate(raw):
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            raise ValueError("Hermes provider returned a malformed tool call")
        function = call["function"]
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, (dict, list)):
            arguments = json.dumps(arguments)
        elif not arguments or not str(arguments).strip():
            arguments = "{}"
        else:
            arguments = str(arguments)
        item = SimpleNamespace(
            id=call.get("id"),
            type="function",
            call_id=call.get("call_id"),
            response_item_id=call.get("response_item_id"),
            extra_content=copy.deepcopy(call.get("extra_content")),
            function=SimpleNamespace(
                name=str(function.get("name") or ""),
                arguments=arguments,
                thought_signature=function.get("thought_signature"),
            ),
        )
        stored = _assistant_tool_call_dict(_TOOL_CALL_STORAGE_POLICY, item, index)
        item.id = stored["id"]
        item.call_id = stored["call_id"]
        item.response_item_id = stored["response_item_id"]
        result.append(item)
    return result


def _unique_ids(calls: list[SimpleNamespace], messages: list[dict]) -> None:
    taken = {
        call["id"] for message in messages for call in message.get("tool_calls", [])
    }
    for call in calls:
        original, number = call.id, 2
        while call.id in taken:
            call.id = f"{original}_d{number}"
            number += 1
        if call.id != original and getattr(call, "call_id", None):
            call.call_id = call.id
        taken.add(call.id)


def _assistant(raw: dict, finish: str, calls: list) -> dict:
    content = raw.get("content")
    if content is not None and not isinstance(content, str):
        content = _coerce_content_text(content)
    reasoning = extract_reasoning(None, SimpleNamespace(**raw))
    message = {
        "role": "assistant",
        "content": strip_think_blocks(None, content or "").strip(),
        "reasoning": reasoning,
        "finish_reason": finish,
    }
    for name in ("reasoning_content", "reasoning_details"):
        if raw.get(name) is not None:
            message[name] = copy.deepcopy(raw[name])
    for name in (
        "codex_reasoning_items",
        "codex_message_items",
        "codex_reasoning_trimmed",
        "phase",
        "stop_details",
    ):
        if raw.get(name) is not None:
            message[name] = copy.deepcopy(raw[name])
    ordered = raw.get("anthropic_content_blocks", raw.get("_anthropic_content_blocks"))
    if ordered:
        message["anthropic_content_blocks"] = copy.deepcopy(ordered)
    if reasoning and "reasoning_content" not in message:
        message["reasoning_content"] = reasoning
    if record := carrier_record(SimpleNamespace(**raw)):
        message.update({key: value for key, value in record.items() if key != "type"})
        message["reasoning_details"] = [*message.get("reasoning_details", []), record]
    if calls:
        message["tool_calls"] = [
            _assistant_tool_call_dict(_TOOL_CALL_STORAGE_POLICY, call, index)
            for index, call in enumerate(calls)
        ]
    return message


def _repair_corrupted_history(messages):
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls", []):
            function = call["function"]
            try:
                json.loads(function["arguments"])
            except (ValueError, TypeError):
                function["arguments"] = "{}"
                for result in messages[index + 1 :]:
                    if result.get("tool_call_id") == call["id"]:
                        result["content"] = (
                            TOOL_CALL_ARGUMENTS_CORRUPTION_MARKER
                            + "\n"
                            + result["content"]
                        )
                        break


def _wire_messages(
    messages: list[dict], system_prompt: str, *, include_native=False, route=None
) -> list[dict]:
    result = [{"role": "system", "content": system_prompt}] if system_prompt else []
    fields = {
        "role",
        "content",
        "name",
        "tool_call_id",
        "tool_calls",
        "reasoning_content",
        "reasoning_details",
        "reasoning",
        "extra_content",
        "reasoning_opaque",
        "reasoning_text",
        "_anthropic_content_blocks",
        "anthropic_content_blocks",
    }
    if include_native:
        fields.update(
            {
                "codex_reasoning_items",
                "codex_message_items",
                "codex_reasoning_trimmed",
                "phase",
                "_compressed_summary",
                "_compressed_summary_has_user_turn",
            }
        )
    for item in messages:
        wire = {
            key: copy.deepcopy(value) for key, value in item.items() if key in fields
        }
        if item.get("api_content") is not None:
            wire["content"] = item["api_content"]
        if route:
            replay = reasoning_replay_route(
                native_responses.api_mode(route),
                route.get("provider", ""),
                route.get("model_name", ""),
                route.get("base_url", ""),
            )
            apply_reasoning_content_policy(item, wire, *replay)
        if item.get("_thinking_prefill") or HistoryPolicy._is_thinking_only_assistant(
            wire, drop_codex_reasoning_items=not include_native
        ):
            continue
        if wire.get("role") == "tool":
            wire.pop("name", None)
        if (
            wire.get("role") == "user"
            and result
            and result[-1].get("role") == "user"
            and isinstance(wire.get("content"), str)
            and isinstance(result[-1].get("content"), str)
        ):
            result[-1]["content"] += "\n\n" + wire["content"]
            continue
        result.append(wire)
    for item in result:
        if isinstance(item.get("content"), str):
            item["content"] = item["content"].strip()
        for call in item.get("tool_calls", []):
            if not include_native:
                call.pop("call_id", None)
                call.pop("response_item_id", None)
            function = call.get("function", {})
            try:
                function["arguments"] = json.dumps(
                    json.loads(function["arguments"]),
                    separators=(",", ":"),
                    sort_keys=True,
                )
            except (KeyError, TypeError, ValueError):
                pass
    return result


def _add_usage(total: dict, usage: Any) -> None:
    if not isinstance(usage, dict):
        return
    for source, target in (
        ("prompt_tokens", "input"),
        ("completion_tokens", "output"),
    ):
        value = usage.get(source, 0)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            total[target] = total.get(target, 0) + value
    cached = (usage.get("prompt_tokens_details") or {}).get(
        "cached_tokens", usage.get("cache_read_tokens", 0)
    )
    if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0:
        total["cache_read_input_tokens"] = (
            total.get("cache_read_input_tokens", 0) + cached
        )
    written = usage.get("cache_write_tokens", 0)
    if isinstance(written, int) and not isinstance(written, bool) and written > 0:
        total["cache_creation_input_tokens"] = (
            total.get("cache_creation_input_tokens", 0) + written
        )
    total["total_tokens"] = total.get("input", 0) + total.get("output", 0)


def _scope(call: SimpleNamespace, cwd: Path) -> tuple[list[Path], bool] | None:
    name = call.function.name
    if name in {"skills_list", "skill_view"}:
        return [], False
    if name not in {"read_file", "search_files", "write_file", "patch"}:
        return None
    try:
        args = json.loads(call.function.arguments)
        if not isinstance(args, dict):
            return None
        paths = [args.get("path", ".")]
        # V4A patch bodies carry their own file targets; never trust a decoy path.
        if name == "patch" and isinstance(args.get("patch"), str):
            from ._vendor.patch_parser import parse_v4a_patch

            operations, error = parse_v4a_patch(args["patch"])
            if error or not operations:
                return None
            paths = [
                path
                for operation in operations
                for path in (operation.file_path, operation.new_path)
                if path
            ]
        resolved = []
        for path in paths:
            if not isinstance(path, str) or not path:
                return None
            value = Path(path).expanduser()
            resolved.append((cwd / value).resolve())
        return resolved, name in {"write_file", "patch"}
    except (ValueError, OSError, RuntimeError):
        return None


def _segments(calls: list, cwd: Path) -> list[tuple[str, list]]:
    """Hermes's ordered parallel runs, with stateful tools and path conflicts as barriers."""
    segments, pending, reservations = [], [], []

    def flush():
        nonlocal pending, reservations
        if pending:
            mode = "parallel" if len(pending) > 1 else "sequential"
            if mode == "sequential" and segments and segments[-1][0] == mode:
                segments[-1][1].extend(pending)
            else:
                segments.append((mode, pending))
        pending, reservations = [], []

    for call in calls:
        scope = _scope(call, cwd)
        if scope is None:
            flush()
            if segments and segments[-1][0] == "sequential":
                segments[-1][1].append(call)
            else:
                segments.append(("sequential", [call]))
            continue
        paths, writer = scope
        if any(
            (writer or other_writer)
            and (path == other or path in other.parents or other in path.parents)
            for path in paths
            for other, other_writer in reservations
        ):
            flush()
        reservations.extend((path, writer) for path in paths)
        pending.append(call)
    flush()
    return segments


async def _execute_batch(calls, tools, cwd, events, append, recovery_host=None):
    async def one(call):
        name = call.function.name
        args = json.loads(call.function.arguments)
        events.append(
            {
                "type": "tool_execution_start",
                "id": call.id,
                "name": name,
                "arguments": args,
            }
        )
        job = asyncio.create_task(asyncio.to_thread(tools.execute, name, args))
        try:
            value = await asyncio.shield(job)
        except asyncio.CancelledError:
            # No filesystem or shell work may continue after this run returns.
            await _settle(asyncio.create_task(asyncio.to_thread(tools.close)))
            try:
                await _settle(job)
            except Exception:
                pass
            raise
        except Exception as exc:
            value = json.dumps({"error": str(exc)})
        if recovery_host is not None:
            value = recovery_host._tool_result_content_for_active_model(name, value)
        if not isinstance(value, (str, list)):
            value = json.dumps(value, ensure_ascii=False)
        events.append(
            {"type": "tool_execution_end", "id": call.id, "name": name, "result": value}
        )
        return {"role": "tool", "name": name, "tool_call_id": call.id, "content": value}

    pending = list(calls)
    while pending:
        # A stateful tool can change cwd, so resolve later file aliases again
        # after each barrier before deciding which operations can run together.
        mode, segment = _segments(pending, tools.cwd)[0]
        if mode == "sequential":
            segment = segment[:1]
        if mode == "parallel":
            jobs = [asyncio.create_task(one(call)) for call in segment]
            try:
                results = await asyncio.gather(*jobs)
            except BaseException:
                for job in jobs:
                    if not job.cancelling():
                        job.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
                raise
            for result in results:
                append(result)
        else:
            for call in segment:
                append(await one(call))
        del pending[: len(segment)]


async def _settle(job):
    """Finish cleanup even if a timeout and a parent cancellation arrive together."""
    while not job.done():
        try:
            await asyncio.shield(job)
        except asyncio.CancelledError:
            continue
    return job.result()


async def run(
    config: Mapping[str, Any],
    prompt: str,
    cwd: Path,
    snapshot_root: Path,
    *,
    _state: dict | None = None,
) -> NativeHermesResult:
    result = NativeHermesResult(usage={"input": 0, "output": 0, "total_tokens": 0})
    if _state is not None:
        _state["result"] = result
    events, messages = result.events, result.messages
    tools = None
    session = engine = recovery_host = None
    api_calls = api_requests = 0

    def append(message):
        messages.append(message)
        events.append({"type": "message", **copy.deepcopy(message)})

    try:
        llm = dict(config["llm"])
        llm.setdefault("provider", "custom")
        llm["model_api"] = (
            llm.get("model_api")
            or llm.get("api_mode")
            or config.get("api_mode", "chat_completions")
        )
        if native_responses.api_mode(llm) not in {
            "chat_completions",
            "openai-completions",
            "codex_responses",
            "anthropic_messages",
        }:
            raise ValueError(
                "Hermes Snapshot supports Chat Completions, Responses and Anthropic Messages protocols"
            )
        if is_native_gemini_base_url(llm.get("base_url", "")):
            raise ValueError(
                "Hermes Snapshot requires a Gemini OpenAI-compatible endpoint; native Gemini protocol is unsupported"
            )
        if native_responses.api_mode(llm) == "chat_completions":
            chat_transport.validate_chat_route(llm)
        run_config = {
            **config,
            "llm": llm,
            "_runtime_started_at": datetime.now().astimezone().isoformat(),
        }
        bundle = load_resources(snapshot_root, cwd, run_config)
        tools = HermesTools(cwd, snapshot_root, enabled_tools=bundle.enabled_tools)
        settings = getattr(bundle, "settings", dict(config))
        agent_settings = settings.get("agent") or {}
        if not isinstance(agent_settings, dict):
            agent_settings = {}
        agent_settings = {
            **agent_settings,
            **{
                name: settings[name]
                for name in (
                    "api_max_retries",
                    "auto_recovery_cycles",
                    "stall_guards",
                    "intent_ack_continuation",
                    "empty_response_guard",
                )
                if name in settings
            },
        }
        settings = {**settings, "agent": agent_settings}
        if settings.get("session_file"):
            session_path = Path(settings["session_file"]).expanduser()
            settings = {
                **settings,
                "session_file": str(
                    session_path if session_path.is_absolute() else cwd / session_path
                ),
            }
        if configure_settings := getattr(tools, "configure_settings", None):
            configure_settings(settings)
        names = {schema["function"]["name"] for schema in tools.schemas}
        model = llm["model_name"].strip()
        if configure_tools := getattr(tools, "configure_model", None):
            configure_tools(model, provider=llm.get("provider", "custom"))
        key = llm["api_key"]
        if not key:
            raise ValueError("Hermes llm.api_key is required")
        timeout = float(config.get("timeout", 300))
        maximum = config.get("max_iterations", config.get("max_turns", sys.maxsize))
        budget = IterationBudget(maximum)
        if settings.get("session_file"):
            session_path = Path(settings["session_file"]).expanduser()
            session = Session(
                session_path if session_path.is_absolute() else cwd / session_path
            )
            await session.open()
            if session.state.get("runtime_started_at"):
                settings = {
                    **settings,
                    "_runtime_started_at": session.state["runtime_started_at"],
                }
            else:
                session.state["runtime_started_at"] = run_config["_runtime_started_at"]
            messages.extend(copy.deepcopy(session.state.get("messages", [])))
            settings = {
                **settings,
                "_last_activity": session.state.get("last_activity"),
            }
            if getattr(tools, "todos", None) and session.state.get("todos"):
                saved_todos = session.state["todos"]
                tools.todos.restore(
                    saved_todos.get("todos", []),
                    revision=saved_todos.get("revision", 0),
                )
            tools.checkpoint_context = session.save_checkpoint
        compression_settings = settings.get("compression", {})
        compression_enabled = (
            compression_settings.get("enabled", True)
            if isinstance(compression_settings, dict)
            else True
        )
        if isinstance(compression_enabled, str):
            compression_enabled = compression_enabled.strip().lower() in {
                "true",
                "1",
                "yes",
                "on",
            }
        selected_explicitly = any(
            name in config
            for name in ("enabled_tools", "tools", "enabled_toolsets", "toolsets")
        )
        disabled = settings.get("disabled_toolsets", [])
        if (
            compression_enabled
            and (not selected_explicitly or "session_search" in bundle.enabled_tools)
            and "session_search" not in disabled
            and (bind_search := getattr(tools, "enable_history_search", None))
        ):
            bind_search(lambda **kwargs: engine.search_archive(**kwargs))
        names = {schema["function"]["name"] for schema in tools.schemas}
        engine = ContextEngine(settings, llm, tools=tools, event_sink=events.append)
        if session:
            engine.restore_state(session.state.get("context_state", {}))
        recovery_host = RecoveryHost(
            llm, engine, events.append,
            (session.state.get("context_state", {}).get("recovery") if session else None),
        )
        engine._recovery_host = recovery_host
        recovery_host.tools = tools.schemas

        def refresh_prompt():
            nonlocal bundle
            bundle = load_resources(
                snapshot_root,
                tools.cwd,
                {
                    **settings,
                    "context_length": engine.context_length,
                    "enabled_tools": list(names),
                    "_scratch_dir": str(getattr(tools, "scratch_dir", "")),
                },
            )

        refresh_prompt()

        fallback_chain = iter(
            _fallback_entries(
                settings.get("fallback_providers", settings.get("fallback_model"))
            )
        )
        route_restarts = 0

        def activate_fallback(reason=None):
            nonlocal llm, model, engine, settings, route_restarts
            for candidate in fallback_chain:
                fallback = dict(candidate)
                same_provider = fallback["provider"] == llm.get("provider")
                base = fallback.get("base_url") or (
                    llm.get("base_url") if same_provider else None
                )
                credential = fallback.get("api_key")
                if not credential and same_provider and base == llm.get("base_url"):
                    credential = llm.get("api_key")
                if not base or not credential:
                    events.append(
                        {
                            "type": "diagnostic",
                            "message": f"Skipped fallback {fallback['model']}: explicit base_url and api_key are required for its route.",
                        }
                    )
                    continue
                previous = model
                route = {
                    **llm,
                    **fallback,
                    "model_name": fallback["model"],
                    "base_url": base,
                    "api_key": credential,
                }
                # A backup's protocol and overrides belong to its own route.
                route["model_api"] = (
                    fallback.get("model_api")
                    or fallback.get("api_mode")
                    or "chat_completions"
                )
                try:
                    if native_responses.api_mode(route) not in {
                        "chat_completions",
                        "codex_responses",
                        "anthropic_messages",
                    } or is_native_gemini_base_url(base):
                        raise ValueError("unsupported native provider protocol")
                    if native_responses.api_mode(route) == "chat_completions":
                        chat_transport.validate_chat_route(route)
                except ValueError as error:
                    events.append(
                        {
                            "type": "diagnostic",
                            "message": f"Skipped fallback {fallback['model']}: {error}",
                        }
                    )
                    continue
                for option in (
                    "request_overrides",
                    "extra_body",
                    "extra_headers",
                    "capabilities",
                    "runtime_capabilities",
                ):
                    if option not in fallback:
                        route.pop(option, None)
                llm, model = route, route["model_name"]
                settings = {**settings, "llm": route}
                # The original compressor owns the model-switch reset policy:
                # summaries survive; usage anchors, cooldowns and old trigger
                # budgets cannot price this new route.
                engine.settings, engine.llm, engine.model = settings, route, model
                engine.compressor.update_model(
                    model=model,
                    context_length=resolve_context_length(
                        {
                            "context_length": fallback.get("context_length"),
                            "custom_providers": settings.get("custom_providers"),
                        },
                        {
                            key: value
                            for key, value in route.items()
                            if key != "context_length" or key in fallback
                        },
                    ),
                    base_url=base,
                    api_key=credential,
                    provider=route["provider"],
                    api_mode=native_responses.api_mode(route),
                )
                engine._anchor = None
                engine.attempts = 0
                engine._boundary_pending = False
                engine._native_disabled = False
                engine._apply_aux_context_ceiling()
                recovery_host.bind_route(route)
                if configure_tools := getattr(tools, "configure_model", None):
                    configure_tools(model, provider=route.get("provider", "custom"))
                refresh_prompt()
                route_restarts += 1
                events.append(
                    {
                        "type": "provider_fallback",
                        "from_model": previous,
                        "model": model,
                        "provider": route["provider"],
                        "reason": getattr(reason, "value", reason),
                    }
                )
                raise _RouteRestart()
            return False

        def checkpoint():
            if session is not None:
                session.save(
                    messages,
                    tools.todos.snapshot() if getattr(tools, "todos", None) else {},
                    {**engine.snapshot_state(), "recovery": recovery_host.snapshot()},
                )

        events.append(
            {
                "type": "session",
                "harness": "hermes",
                "baseline": "v0.22.5",
                "cwd": str(cwd),
            }
        )
        events.extend(
            {"type": "diagnostic", "message": item} for item in bundle.diagnostics
        )
        manual_compact = prompt.strip() == "/compress" or prompt.strip().startswith(
            "/compress "
        )
        if not manual_compact:
            append({"role": "user", "content": prompt})

        async with AsyncExitStack() as http_stack:
            client = await http_stack.enter_async_context(
                httpx.AsyncClient(timeout=timeout)
            )

            async def rebuild_transport():
                nonlocal client
                await client.aclose()
                client = await http_stack.enter_async_context(
                    httpx.AsyncClient(timeout=timeout)
                )

            ephemeral_cap = requested_cap = None
            ephemeral_reasoning_off = False
            continuation = ContinuationState()
            active_recovery = None

            async def post(payload, route, *, summary=False, iteration_summary=False):
                nonlocal api_requests
                responses = native_responses.api_mode(route) == "codex_responses"
                anthropic = native_responses.api_mode(route) == "anthropic_messages"
                request_options = {}
                wire_aliases = {}
                headers = (
                    anthropic_transport.anthropic_headers(route, settings)
                    if anthropic else native_responses.request_headers(route)
                )
                if responses:
                    endpoint, payload = native_responses.prepare(
                        payload, route, engine, summary=summary
                    )
                    if iteration_summary:
                        for field in ("tools", "tool_choice", "parallel_tool_calls"):
                            payload.pop(field, None)
                    headers.update(payload.pop("extra_headers", {}) or {})
                    if "timeout" in payload:
                        request_options["timeout"] = payload.pop("timeout")
                elif anthropic:
                    payload = anthropic_transport.prepare_anthropic(
                        payload, route,
                        {**settings, **({"_chat_auxiliary": True} if summary else {"_recovery_reasoning": recovery_host})},
                    )
                    wire_aliases = payload.pop("_wire_aliases", {})
                    endpoint = anthropic_transport.anthropic_endpoint(route)
                else:
                    headers.update(chat_transport.chat_headers(route))
                    payload = chat_transport.prepare_chat(
                        payload,
                        route,
                        {**settings, **({"_chat_auxiliary": True} if summary else {"_recovery_reasoning": recovery_host})},
                    )
                    wire_aliases = payload.pop("_wire_aliases", {})
                    endpoint = (
                        route.get("base_url") or "https://api.openai.com/v1"
                    ).rstrip("/")
                    if not endpoint.endswith("/chat/completions"):
                        endpoint += "/chat/completions"
                headers.update(payload.pop("extra_headers", {}) or {})
                if "timeout" in payload:
                    request_options["timeout"] = payload.pop("timeout")
                if not summary and active_recovery is not None:
                    active_recovery.sanitize(payload)
                    active_recovery.capture(copy.deepcopy(payload))
                payload.update(payload.pop("extra_body", {}) or {})
                api_requests += 1
                events.append(
                    {
                        "type": "api_request",
                        "api_call": api_requests,
                        "summary": summary,
                        "iteration_summary": iteration_summary,
                    }
                )
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    **request_options,
                )
                if response.is_error:
                    try:
                        body = response.json()
                    except ValueError:
                        body = {"message": response.text}
                    raise ProviderError(response, body)
                data = (
                    native_responses.decode_response(response.text)
                    if responses
                    else anthropic_transport.decode_anthropic(response.text)
                    if anthropic else response.json()
                )
                if not isinstance(data, dict) or data.get("error"):
                    raise InvalidResponseError(
                        f"Hermes provider error: {data.get('error') if isinstance(data, dict) else 'invalid response'}"
                    )
                try:
                    return (
                        native_responses.ingest(data, route, engine, summary=summary)
                        if responses
                        else anthropic_transport.ingest_anthropic(data, wire_aliases)
                        if anthropic
                        else chat_transport.ingest_chat(data, wire_aliases)
                    )
                except ValueError as exc:
                    raise InvalidResponseError(str(exc)) from exc

            async def send_summary(payload, route):
                return await post(payload, route, summary=True)

            async def request(*, iteration_summary=False):
                nonlocal ephemeral_cap, requested_cap, ephemeral_reasoning_off, active_recovery
                _repair_corrupted_history(messages)
                payload = {
                    "model": model,
                    "messages": _wire_messages(
                        messages,
                        bundle.system_prompt,
                        include_native=native_responses.api_mode(llm)
                        == "codex_responses",
                        route=llm,
                    ),
                    "stream": False,
                }
                if recovery_host.tools:
                    payload["tools"] = copy.deepcopy(recovery_host.tools)
                for parameter in (
                    "temperature",
                    "top_p",
                    "max_tokens",
                    "max_completion_tokens",
                    "reasoning_effort",
                    "seed",
                ):
                    if parameter in llm:
                        payload[parameter] = llm[parameter]
                if ephemeral_cap is not None:
                    cap_field = (
                        "max_completion_tokens"
                        if "max_completion_tokens" in payload
                        else "max_tokens"
                    )
                    payload[cap_field] = ephemeral_cap
                    payload.pop(
                        "max_tokens"
                        if cap_field == "max_completion_tokens"
                        else "max_completion_tokens",
                        None,
                    )
                requested_cap = payload.get(
                    "max_completion_tokens", payload.get("max_tokens")
                )
                if ephemeral_reasoning_off:
                    payload["reasoning_effort"] = "none"
                    ephemeral_reasoning_off = False
                ephemeral_cap = None
                active_recovery = recovery_host.begin(messages, payload, bundle.system_prompt)
                retries = RetryBudget(
                    settings,
                    llm,
                    events.append,
                    activate_fallback=activate_fallback,
                    rebuild_transport=rebuild_transport
                    if route_restarts == 0
                    else None,
                    recovery=active_recovery,
                )
                while True:
                    try:
                        active_recovery.prepare()
                        # Failed attempts replay the same overrides (including a
                        # one-shot output/reasoning recovery) inside this iteration.
                        data = await post(
                            copy.deepcopy(payload),
                            llm,
                            iteration_summary=iteration_summary,
                        )
                        choices = data.get("choices")
                        if (
                            not isinstance(choices, list)
                            or not choices
                            or not isinstance(choices[0], dict)
                            or not isinstance(choices[0].get("message"), dict)
                        ):
                            raise InvalidResponseError(
                                "Hermes provider returned no assistant message"
                            )
                        try:
                            _call_objects(choices[0]["message"].get("tool_calls"))
                        except ValueError as exc:
                            raise InvalidResponseError(str(exc)) from exc
                        break
                    except json.JSONDecodeError as exc:
                        error = InvalidResponseError(str(exc))
                        if iteration_summary or not await retries.recover(error):
                            raise error from exc
                    except Exception as exc:
                        if iteration_summary or not await retries.recover(
                            exc,
                            context_length=engine.context_length,
                            num_messages=len(messages),
                        ):
                            raise
                raw = choices[0]["message"]
                raw["_responses_status"] = data.get("responses_status")
                raw["_responses_incomplete_reason"] = data.get(
                    "responses_incomplete_reason"
                )
                return (
                    raw,
                    choices[0].get("finish_reason") or "stop",
                    data.get("usage"),
                )

            invalid_names = invalid_json = empty_retries = dropped_retries = 0
            length_retries = truncated_calls = 0
            parts = []
            fragment_start = None
            empty_scaffolding = []
            post_tool_empty_retried = False
            last_tool_content = None
            last_tools_housekeeping = False
            ack_continuations = 0
            thinking_prefill_retries = 0
            empty_host = SimpleNamespace(
                model=model,
                provider=llm.get("provider", ""),
                api_mode=native_responses.api_mode(llm),
                base_url=llm.get("base_url", ""),
                api_key=llm.get("api_key", ""),
                _pricing_metadata=settings.get("pricing_metadata", {}),
                _empty_content_retries=0,
            )
            (
                empty_host._empty_guard_enabled,
                empty_host._empty_guard_cost_threshold_usd,
            ) = empty_response_guard.resolve_guard_settings(
                agent_settings.get("empty_response_guard")
            )
            completed = False
            if manual_compact:
                focus = prompt.strip()[len("/compress") :].strip() or None
                changed = await engine.compact(
                    messages,
                    bundle.system_prompt,
                    send_summary,
                    force=True,
                    focus_topic=focus,
                )
                result.output = (
                    "Context compressed."
                    if changed
                    else "Context was preserved; no compression was committed."
                )
                if changed:
                    refresh_prompt()
                completed = True
            while budget.consume():
                if completed:
                    break
                if await engine.before_request(
                    messages, bundle.system_prompt, send_summary
                ):
                    refresh_prompt()
                    checkpoint()
                api_calls += 1
                try:
                    raw, finish, usage = await request()
                except _RouteRestart:
                    if (
                        route_restarts
                        > RetryBudget(settings, llm, events.append).maximum
                    ):
                        raise _PartialTurn(
                            "Provider fallback restart limit exceeded before the task finished."
                        )
                    budget.refund()
                    api_calls -= 1
                    continue
                except Exception as exc:
                    recovery = await engine.recover(
                        exc, messages, bundle.system_prompt, send_summary
                    )
                    if not recovery.retry:
                        raise
                    refresh_prompt()
                    checkpoint()
                    ephemeral_cap = recovery.max_tokens
                    budget.refund()
                    api_calls -= 1
                    continue
                if finish not in {"length", "content_filter"}:
                    engine.after_response(usage, messages)
                calls = _call_objects(raw.get("tool_calls"))
                if finish in {"content_filter", "error", "aborted"}:
                    if finish == "content_filter":
                        try:
                            activate_fallback("content_policy_blocked")
                        except _RouteRestart:
                            budget.refund()
                            api_calls -= 1
                            continue
                        refusal = (raw.get("content") or "").strip()
                        if not refusal:
                            refusal = (
                                extract_reasoning(None, SimpleNamespace(**raw)) or ""
                            )
                        raise _ContentPolicyBlocked(
                            "⚠️ "
                            + content_policy_copy(
                                label=provider_label(llm.get("provider", "custom")),
                                summary=refusal or "the model returned no explanation",
                            ),
                            refusal or "model declined (content_filter)",
                        )
                    raise ValueError(f"Hermes response stopped with {finish}")
                message = _assistant(raw, finish, calls)
                if finish == "incomplete":
                    _add_usage(result.usage, usage)
                    previous = {id(row) for row in messages}
                    decision = continuation.step(
                        messages,
                        message,
                        configured_cap=llm.get(
                            "max_tokens", llm.get("max_completion_tokens")
                        ),
                        usage=usage,
                        response_status=raw.get("_responses_status"),
                        incomplete_reason=raw.get("_responses_incomplete_reason"),
                        api_call_count=api_calls,
                    )
                    for row in messages:
                        if id(row) not in previous:
                            events.append({"type": "message", **copy.deepcopy(row)})
                    checkpoint()
                    if not decision.continue_turn:
                        detail = decision.result["final_response"]
                        raise _PartialTurn(detail)
                    ephemeral_cap = decision.max_output_tokens
                    ephemeral_reasoning_off = decision.reasoning_off
                    continue
                continuation.reset()
                if finish == "length":
                    if calls:
                        truncated_calls += 1
                        if truncated_calls > 4:
                            raise _PartialTurn(
                                TRUNCATED_ACTION,
                                "Model repeatedly returned truncated tool calls; no action executed",
                            )
                        # Same iteration retry, never execute a truncated action.
                        ephemeral_cap = boosted_output_cap(
                            SimpleNamespace(
                                max_tokens=llm.get(
                                    "max_tokens", llm.get("max_completion_tokens")
                                )
                            ),
                            requested_cap,
                            truncated_calls,
                        )
                        budget.refund()
                        api_calls -= 1
                        continue
                    if message["content"] and is_repetition_dominated(
                        message["content"]
                    ):
                        _, output, error = _REPETITION_DOMINATED
                        raise _PartialTurn(output, error)
                    length_retries += 1
                    if not message["content"]:
                        ephemeral_reasoning_off = True
                    if message["content"]:
                        if fragment_start is None:
                            fragment_start = len(messages)
                        parts.append((message["content"], False))
                        message["_length_continuation_fragment"] = True
                        append(message)
                    filled = _prompt_filled_window(
                        SimpleNamespace(
                            context_compressor=engine.compressor,
                            provider=llm.get("provider", ""),
                            api_mode=native_responses.api_mode(llm),
                        ),
                        SimpleNamespace(usage=usage),
                    )
                    if length_retries >= 4 or filled is not None:
                        joined = strip_think_blocks(
                            None, _join_truncated_parts(parts)
                        ).strip()
                        if fragment_start is not None:
                            messages[:] = [
                                item
                                for item in messages
                                if not (
                                    item.get("_length_continuation_fragment")
                                    or item.get("_length_continuation_nudge")
                                )
                            ]
                        if joined:
                            append(
                                {
                                    "role": "assistant",
                                    "content": joined,
                                    "finish_reason": "length",
                                }
                            )
                        if filled is not None:
                            notice = _WINDOW_FILLED.format(
                                prompt=filled[0], ctx=filled[1]
                            )
                            raise _PartialTurn(
                                f"{joined}\n\n{notice}" if joined else notice,
                                f"Prompt used {filled[0]} of {filled[1]} context tokens; no room to answer",
                            )
                        raise _PartialTurn(
                            joined or _CEILING_NO_TEXT,
                            "Model output remained truncated after four continuations",
                        )
                    ephemeral_cap = boosted_output_cap(
                        SimpleNamespace(
                            max_tokens=llm.get(
                                "max_tokens", llm.get("max_completion_tokens")
                            )
                        ),
                        requested_cap,
                        length_retries,
                    )
                    append(
                        {
                            "role": "user",
                            "content": _get_continuation_prompt(False),
                            "_length_continuation_nudge": True,
                        }
                    )
                    continue
                _add_usage(result.usage, usage)
                truncated_calls = 0
                if calls:
                    _unique_ids(calls, messages)
                    for call in calls:
                        if call.function.name not in names:
                            repaired = repair_tool_call(
                                SimpleNamespace(valid_tool_names=names),
                                call.function.name,
                            )
                            if repaired:
                                call.function.name = repaired
                    invalid = [
                        call for call in calls if call.function.name not in names
                    ]
                    valid = [call for call in calls if call.function.name in names]
                    invalid_names = invalid_names + 1 if invalid and not valid else 0
                    if invalid_names >= 3:
                        raise _PartialTurn(
                            f"Model generated invalid tool call: {invalid[0].function.name[:80]}"
                        )
                    if invalid and not valid:
                        append(_assistant(raw, finish, calls))
                        for call in calls:
                            append(
                                {
                                    "role": "tool",
                                    "name": call.function.name,
                                    "tool_call_id": call.id,
                                    "content": _invalid_tool_name_error_content(
                                        call.function.name, names
                                    ),
                                }
                            )
                        continue
                    errors = []
                    for call in valid:
                        try:
                            json.loads(call.function.arguments)
                        except json.JSONDecodeError as exc:
                            if not call.function.arguments.rstrip().endswith(
                                ("}", "]")
                            ):
                                raise _PartialTurn(
                                    TRUNCATED_ACTION_UNREPORTED,
                                    "Truncated tool arguments; the action was not executed",
                                ) from exc
                            errors.append((call.function.name, str(exc)))
                    if errors:
                        invalid_json += 1
                        if invalid_json < 3:
                            continue
                        invalid_json = 0
                        append(_assistant(raw, finish, calls))
                        for call in calls:
                            error = next(
                                (
                                    error
                                    for name, error in errors
                                    if name == call.function.name
                                ),
                                None,
                            )
                            content = (
                                f"Error: Invalid JSON arguments. {error}. For tools with no required parameters, use an empty object: {{}}. Please retry with valid JSON."
                                if error
                                else "Skipped: other tool call in this response had invalid JSON."
                            )
                            append(
                                {
                                    "role": "tool",
                                    "name": call.function.name,
                                    "tool_call_id": call.id,
                                    "content": content,
                                }
                            )
                        continue
                    invalid_json = 0
                    calls = _deduplicate_tool_calls(calls)
                    tool_message = _assistant(raw, finish, calls)
                    tool_content = tool_message["content"]
                    if _STALE_MARKER_RE.fullmatch(tool_content.strip()):
                        tool_content = tool_message["content"] = ""
                    if not all(
                        call.function.name in _HOUSEKEEPING_TOOLS for call in calls
                    ):
                        last_tool_content = None
                        last_tools_housekeeping = False
                    if strip_think_blocks(None, tool_content).strip():
                        last_tool_content = tool_content
                        last_tools_housekeeping = all(
                            call.function.name in _LINE_IS_REPLY_TOOLS for call in calls
                        )
                    append(tool_message)
                    for call in calls:
                        if call.function.name not in names:
                            append(
                                {
                                    "role": "tool",
                                    "name": call.function.name,
                                    "tool_call_id": call.id,
                                    "content": _invalid_tool_name_error_content(
                                        call.function.name, names
                                    ),
                                }
                            )
                    await _execute_batch(
                        [call for call in calls if call.function.name in names],
                        tools,
                        tools.cwd,
                        events,
                        append,
                        recovery_host,
                    )
                    if await engine.after_tools(
                        messages, bundle.system_prompt, send_summary
                    ):
                        refresh_prompt()
                    checkpoint()
                    empty_retries = dropped_retries = 0
                    empty_host._empty_content_retries = 0
                    continue
                promoted = None
                if (
                    finish == "stop"
                    and not message["content"].strip()
                    and not any(
                        isinstance(detail, dict)
                        and (
                            (
                                detail.get("type") in {"thinking", "redacted_thinking"}
                                and (detail.get("signature") or detail.get("data"))
                            )
                            or str(detail.get("type") or "").endswith(
                                ".native_assistant"
                            )
                        )
                        for detail in message.get("reasoning_details") or ()
                    )
                    and answer_in_reasoning_capability(
                        SimpleNamespace(
                            model=model,
                            base_url=llm.get("base_url", ""),
                            provider=llm.get("provider", ""),
                            requested_provider=llm.get("requested_provider", ""),
                            api_mode=native_responses.api_mode(llm),
                            _custom_providers=settings.get("custom_providers", []),
                        )
                    )
                ):
                    promoted = extract_reasoning(None, SimpleNamespace(**raw)) or None
                    if promoted:
                        message["api_content"] = promoted
                answer = promoted or message["content"]
                visible = strip_think_blocks(None, answer).strip()
                reused_tool_answer = False
                if not visible and last_tool_content and last_tools_housekeeping:
                    answer = last_tool_content
                    visible = strip_think_blocks(None, answer).strip()
                    reused_tool_answer = True
                    last_tool_content = None
                    last_tools_housekeeping = False
                if not visible:
                    if (
                        not post_tool_empty_retried
                        and any(item.get("role") == "tool" for item in messages[-5:])
                        and not any(
                            marker in str(raw.get("content") or "").lower()
                            for marker in ("<think>", "<thinking>", "<reasoning>")
                        )
                    ):
                        post_tool_empty_retried = True
                        last_tool_content = None
                        last_tools_housekeeping = False
                        sentinel = {
                            **message,
                            "content": "(empty)",
                            "_empty_recovery_synthetic": True,
                        }
                        nudge = {
                            "role": "user",
                            "content": _EMPTY_TOOL_RESPONSE_NUDGE,
                            "_empty_recovery_synthetic": True,
                        }
                        empty_scaffolding.extend([sentinel, nudge])
                        append(sentinel)
                        append(nudge)
                        continue
                    structured = bool(
                        message.get("reasoning")
                        or message.get("reasoning_content")
                        or message.get("reasoning_details")
                    )
                    if structured and thinking_prefill_retries < 2:
                        thinking_prefill_retries += 1
                        message.update(
                            finish_reason="incomplete", _thinking_prefill=True
                        )
                        empty_scaffolding.append(message)
                        append(message)
                        continue
                    empty_host._empty_content_retries = empty_retries
                    response = SimpleNamespace(usage=usage)
                    empty_response_guard.record_empty_attempt(
                        empty_host,
                        finish_reason=finish,
                        response=response,
                        observed_generation=structured,
                    )
                    retry_limit = empty_response_guard.empty_retry_budget(
                        empty_host, response
                    )
                    if (
                        empty_retries >= retry_limit
                        or empty_response_guard.deterministic_empty(empty_host)
                    ):
                        try:
                            activate_fallback()
                        except _RouteRestart:
                            empty_retries = thinking_prefill_retries = 0
                            budget.refund()
                            api_calls -= 1
                            continue
                        for scaffold in empty_scaffolding:
                            if scaffold in messages:
                                messages.remove(scaffold)
                        append({"role": "assistant", "content": "(empty)"})
                        result.output = (
                            "⚠️ No reply: "
                            + EMPTY_RESPONSE_EXPLANATION.format(model=model)
                        )
                        completed = True
                        break
                    empty_retries += 1
                    from .retry import sleep
                    from .upstream_loop.retry_utils import jittered_backoff

                    await sleep(
                        jittered_backoff(empty_retries, base_delay=5.0, max_delay=60.0)
                    )
                    # Do not persist empty assistant rows or expose internal reasoning.
                    continue
                guard = SimpleNamespace(
                    model=model,
                    api_mode=native_responses.api_mode(llm),
                    _intent_ack_continuation=agent_settings.get(
                        "intent_ack_continuation", "auto"
                    ),
                    _strip_think_blocks=lambda value: strip_think_blocks(None, value),
                )
                ack_mode = intent_ack_continuation_mode(guard)
                stalled = (
                    agent_settings.get("stall_guards", True)
                    and names
                    and ack_continuations < 2
                    and (
                        trailing_continue_intent(visible)
                        or (promoted and promoted_reasoning_announces_action(visible))
                    )
                )
                degenerate = (
                    agent_settings.get("stall_guards", True)
                    and ack_mode != "off"
                    and ack_continuations < 2
                    and tool_results_this_turn(messages) > 0
                    and looks_like_degenerate_final(visible, user_message=prompt)
                )
                ack = (
                    ack_mode != "off"
                    and names
                    and ack_continuations < 2
                    and looks_like_codex_intermediate_ack(
                        guard,
                        user_message=prompt,
                        assistant_content=visible,
                        messages=messages,
                        require_workspace=ack_mode == "codex_only",
                    )
                )
                if stalled or degenerate or ack:
                    ack_continuations += 1
                    message["finish_reason"] = "incomplete"
                    append(message)
                    append(
                        {
                            "role": "user",
                            "content": _DEGENERATE_FINAL_NUDGE
                            if degenerate and not stalled
                            else _CODEX_ACK_CONTINUATION_NUDGE,
                        }
                    )
                    continue
                ack_continuations = 0
                if len(visible) >= STOP_PATH_MIN_CHARS and is_runaway_repetition(
                    visible
                ):
                    _, output, error = repetition_copy(
                        "before delivery",
                        "so the repeated output was discarded.",
                        "; refusing to return a",
                    )
                    raise _PartialTurn(output, error)
                if finish == "tool_calls" and dropped_retries < 3:
                    dropped_retries += 1
                    message["_dropped_toolcall_nudge"] = True
                    append(message)
                    append(
                        {
                            "role": "user",
                            "content": _DROPPED_TOOLCALL_NUDGE_CONTENT,
                            "_dropped_toolcall_nudge": True,
                        }
                    )
                    continue
                for scaffold in empty_scaffolding:
                    if scaffold in messages:
                        messages.remove(scaffold)
                while messages and messages[-1].get("_dropped_toolcall_nudge"):
                    messages.pop()
                append(
                    {"role": "assistant", "content": visible}
                    if reused_tool_answer
                    else message
                )
                result.output = strip_think_blocks(
                    None, _join_truncated_parts([*parts, (answer, False)])
                ).strip()
                completed = True
                for row in messages:
                    row.pop("_length_continuation_fragment", None)
                    row.pop("_length_continuation_nudge", None)
                break
            if not completed:
                append({"role": "user", "content": MAX_ITERATIONS_SUMMARY_REQUEST})
                result.output = _EMPTY_SUMMARY_RESPONSE
                try:
                    for _ in range(2):
                        raw, _finish, _usage = await request(iteration_summary=True)
                        text = raw.get("content") or ""
                        if not isinstance(text, str):
                            text = _coerce_content_text(text)
                        if not text.strip():
                            continue
                        visible = strip_think_blocks(None, text).strip()
                        if visible:
                            result.output = visible
                            append({"role": "assistant", "content": visible})
                        break
                except Exception as exc:
                    events.append(
                        {
                            "type": "diagnostic",
                            "message": f"Failed to get summary response: {exc}",
                        }
                    )
                    result.output = (
                        f"I ran out of steps for this turn ({maximum} tool calls) before finishing, and couldn't "
                        "produce a summary. Send `continue` to keep going, or raise `max_iterations` in your config."
                    )
                if (
                    not messages
                    or messages[-1].get("role") != "assistant"
                    or messages[-1].get("content") != result.output
                ):
                    append({"role": "assistant", "content": result.output})
            if completed and not manual_compact:
                await engine.finalise_turn(messages, bundle.system_prompt, send_summary)
        events.append(
            {
                "type": "hermes_result",
                "final_response": result.output,
                "api_calls": api_calls,
                "api_requests": api_requests,
                "completed": completed,
                "iteration_budget_exhausted": not completed,
                "failed": False,
            }
        )
    except asyncio.CancelledError:
        result.status = "error"
        result.error_message = "Hermes run was cancelled"
        events.append(
            {
                "type": "hermes_result",
                "api_calls": api_calls,
                "api_requests": api_requests,
                "completed": False,
                "aborted": True,
                "failed": True,
                "error": result.error_message,
            }
        )
        raise
    except Exception as exc:
        result.status = "error"
        result.error_message = str(exc) or type(exc).__name__
        if isinstance(exc, (_PartialTurn, _ContentPolicyBlocked)):
            result.output = exc.output
            if (
                isinstance(exc, _PartialTurn)
                and messages
                and messages[-1].get("role") == "tool"
            ):
                append({"role": "assistant", "content": exc.output})
        events.append(
            {
                "type": "hermes_result",
                "api_calls": api_calls,
                "api_requests": api_requests,
                "completed": False,
                "partial": isinstance(exc, _PartialTurn),
                "failed": True,
                "error": result.error_message,
                **(
                    {
                        "failure_reason": "content_policy_blocked",
                        "failure_retryable": False,
                    }
                    if isinstance(exc, _ContentPolicyBlocked)
                    else {}
                ),
            }
        )
    finally:
        if session is not None:
            try:
                if engine is not None:
                    session.save(
                        messages,
                        tools.todos.snapshot() if getattr(tools, "todos", None) else {},
                        {**engine.snapshot_state(), **({"recovery": recovery_host.snapshot()} if recovery_host is not None else {})},
                    )
            except Exception as exc:
                result.status = "error"
                result.error_message = f"Could not persist Hermes session: {exc}"
                for event in reversed(events):
                    if event.get("type") == "hermes_result":
                        event.update(
                            failed=True, completed=False, error=result.error_message
                        )
                        break
                events.append(
                    {"type": "session_error", "message": result.error_message}
                )
            finally:
                session.close()
        if tools is not None:
            closing = asyncio.create_task(asyncio.to_thread(tools.close))
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await _settle(closing)
                raise
    return result
