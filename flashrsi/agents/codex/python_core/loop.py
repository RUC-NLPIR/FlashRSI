"""Python port of core/src/session/{turn,stream_events_utils}.rs.

Pinned source: openai/codex be6e8eac029b183056b7e4402879f15d2c85f61b.
This is the actual evolvable sampling/tool loop. The framework adapter only
supplies paths/configuration and maps its final event to a Trajectory.
"""

from __future__ import annotations

import asyncio
import copy
import struct
import time
import uuid
from pathlib import Path

from .client import ResponseError, ResponsesClient, _backoff
from .context import (
    TurnMetadataState,
    assistant_text,
    initial_context,
    message,
    request_metadata,
)
from .context_budget import (
    augment_initial_context,
    configure,
    observe_usage,
    record_budget_messages,
)
from .history import History, prepare_for_history
from .hooks import HookStopped
from .models import Model
from .resources import Resources
from .tools import ToolRouter

# features/src/lib.rs::FEATURES at the pinned revision. Removed compatibility
# keys no longer enable a mechanism; accepting them must not invent one.
REMOVED_FEATURES = frozenset(
    {
        "undo",
        "js_repl",
        "js_repl_tools_only",
        "terminal_resize_reflow",
        "search_tool",
        "codex_git_commit",
        "sqlite",
        "apply_patch_freeform",
        "use_linux_sandbox_bwrap",
        "request_rule",
        "experimental_windows_sandbox",
        "elevated_windows_sandbox",
        "remote_models",
        "multi_agent_mode",
        "enable_fanout",
        "apps_mcp_path_override",
        "tool_search",
        "tool_search_always_defer_mcp_tools",
        "unavailable_dummy_tools",
        "plugin_hooks",
        "external_migration",
        "resize_all_images",
        "item_ids",
        "skill_env_var_dependency_prompt",
        "steer",
        "collaboration_modes",
        "remote_control",
        "image_detail_original",
        "tui_app_server",
        "workspace_owner_usage_nudge",
        "responses_websockets",
        "responses_websockets_v2",
    }
)


def validate(settings):
    # UI/storage flags do not participate in an ephemeral headless turn. Every
    # other explicitly enabled feature must have an implementation here.
    supported = {
        "shell_tool",
        "view_image",
        "unified_exec",
        "apply_patch_freeform",
        "hooks",
        "plugins",
        "plugin_hooks",
        "multi_agent",
        "personality",
        "collaboration_modes",
        "enable_request_compression",
        "request_user_input",
        "image_detail_original",
        "shell_environment",
        "shell_snapshot",
        "web_search_request",
        "web_search_cached",
        "tool_search_always_defer_mcp_tools",
        "tool_search",
        "sqlite",
        "terminal_resize_reflow",
        "code_mode_host",
        "code_mode",
        "code_mode_only",
        "code_mode_buffered_exec",
        "multi_agent_v2",
        "memories",
        "memory_tool",
        "token_budget",
        "remote_compaction_v2",
    }
    known = {
        "features",
        "model",
        "model_provider",
        "model_providers",
        "model_reasoning_effort",
        "model_reasoning_summary",
        "model_verbosity",
        "model_context_window",
        "model_auto_compact_token_limit",
        "model_auto_compact_token_limit_scope",
        "tool_output_token_limit",
        "service_tier",
        "personality",
        "base_instructions",
        "developer_instructions",
        "user_instructions",
        "compact_prompt",
        "output_schema",
        "sandbox_mode",
        "sandbox_workspace_write",
        "approval_policy",
        "allow_login_shell",
        "shell",
        "shell_environment_policy",
        "mcp_servers",
        "skills",
        "plugins",
        "hooks",
        "notify",
        "agents",
        "web_search",
        "update_plan_enabled",
        "project_doc_max_bytes",
        "project_doc_fallback_filenames",
        "project_root_markers",
        "projects",
        "history",
        "log_dir",
        "cli_auth_credentials_store",
        "otel",
        "thread_id",
        "memories",
        "code_mode",
        "multi_agent_v2",
        "token_budget",
    }
    unknown = {key for key in settings if not key.startswith("_") and key not in known}
    if unknown:
        raise ValueError(
            "Codex Python core has not implemented configuration: "
            + ", ".join(sorted(unknown))
        )
    for key, value in settings.get("features", {}).items():
        enabled = value.get("enabled", True) if isinstance(value, dict) else value
        if enabled and key not in supported and key not in REMOVED_FEATURES:
            raise ValueError(
                f"Codex Python port has not implemented enabled feature {key!r}"
            )
    for key in (
        "permissions",
        "remote_mcp_servers",
        "experimental_realtime_start_instructions",
        "model_instructions_file",
        "experimental_instructions_file",
        "model_catalog_json",
    ):
        if settings.get(key):
            raise ValueError(
                f"Codex Python port has not implemented configuration {key!r}"
            )
    if settings.get("approval_policy", "never") != "never":
        raise ValueError(
            "Python Codex headless execution requires approval_policy=never"
        )
    if settings.get("model_auto_compact_token_limit_scope", "total") not in {
        "total",
        "body_after_prefix",
    }:
        raise ValueError("Invalid Codex model_auto_compact_token_limit_scope")
    if settings.get("web_search") not in {None, "disabled", "cached", "live"}:
        raise ValueError("Unsupported Codex web_search mode")


class ToolSchedule:
    """tools/parallel.rs: shared parallel calls, exclusive serial calls.

    Tools start at output_item.done while the model is still streaming. Their
    outputs enter history in call order, after the response's completed items.
    """

    def __init__(self, router):
        self.router = router
        self.tasks = []
        self.calls = {}
        self.cancelled_at = {}
        self.shared = []
        self.barrier = None
        self.stopped = None
        self.pending_error = None

    def submit(self, call):
        parallel = self.router.supports_parallel(call)
        dependencies = [self.barrier] if self.barrier else []
        if not parallel:
            dependencies += self.shared

        async def run():
            try:
                if dependencies:
                    # The native RwLock only gates admission. A failed prior
                    # dispatch releases its lock; its error does not prevent
                    # later, independent calls from running.
                    await asyncio.gather(*dependencies, return_exceptions=True)
                if self.stopped is not None:
                    raise asyncio.CancelledError
                return await self.router.execute(call)
            except HookStopped as error:
                self.stopped = self.stopped or error
                self.cancelled_at[asyncio.current_task()] = time.monotonic()
                for pending in self.tasks:
                    if pending is not asyncio.current_task() and not pending.done():
                        self.cancelled_at.setdefault(pending, time.monotonic())
                        pending.cancel()
                raise

        task = asyncio.create_task(run())
        self.tasks.append(task)
        self.calls[task] = (copy.deepcopy(call), time.monotonic())
        if parallel:
            self.shared.append(task)
        else:
            self.barrier, self.shared = task, []

    async def drain(self, append):
        while self.tasks:
            task = self.tasks[0]
            try:
                # The turn owns cancellation. Retain the pending call until
                # close() records its terminal result, rather than dropping a
                # partially drained batch when this coroutine is cancelled.
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                pass
            error = self._record_first(append)
            self.pending_error = self.pending_error or error
        self.shared, self.barrier = [], None
        first_error, self.pending_error = self.pending_error, None
        if first_error is not None:
            raise first_error

    def _record_first(self, append):
        task = self.tasks.pop(0)
        call, started = self.calls.pop(task)
        cancelled_at = self.cancelled_at.pop(task, None)
        error = None if task.cancelled() else task.exception()
        if task.cancelled() or isinstance(error, HookStopped):
            item = self._aborted(call, started, cancelled_at)
        elif error is not None:
            emit = getattr(self.router, "emit", lambda event: None)
            emit(
                {
                    "type": "error",
                    "message": f"in-flight tool future failed during drain: {error}",
                }
            )
            # Native release builds log fatal dispatch errors and keep draining.
            # An explicit unsupported-capability error must remain visible as
            # a rejected execution in this partial port.
            return error if isinstance(error, ValueError) else None
        else:
            item = task.result()
        extras = item.pop("extra_items", [])
        try:
            append(item)
            for extra in extras:
                append(extra)
        except Exception as append_error:
            return append_error
        return error

    @staticmethod
    def _aborted(call, started, cancelled_at=None):
        # parallel.rs uses elapsed().as_secs_f32().max(0.1), including time
        # waiting for the parallel-execution gate.
        ended = time.monotonic() if cancelled_at is None else cancelled_at
        seconds = max(0.1, struct.unpack("f", struct.pack("f", ended - started))[0])
        name = call.get("name", "")
        namespace = call.get("namespace") or "functions"
        if name.startswith("functions."):
            namespace, name = name.split(".", 1)
        text = (
            f"Wall time: {seconds:.1f} seconds\naborted by user"
            if namespace == "functions" and name in {"shell_command", "unified_exec"}
            else f"aborted by user after {seconds:.1f}s"
        )
        if call.get("type") == "tool_search_call":
            return {
                "type": "tool_search_output",
                "call_id": call.get("call_id"),
                "status": "completed",
                "execution": "client",
                "tools": [],
            }
        kind = (
            "custom_tool_call_output"
            if call.get("type") == "custom_tool_call"
            else "function_call_output"
        )
        return {"type": kind, "call_id": call.get("call_id"), "output": text}

    async def close(self, append=None):
        for task in self.tasks:
            if not task.done():
                self.cancelled_at.setdefault(task, time.monotonic())
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        while self.tasks:
            if append is None:
                task = self.tasks.pop(0)
                self.calls.pop(task)
                self.cancelled_at.pop(task, None)
            else:
                error = self._record_first(append)
                self.pending_error = self.pending_error or error
        self.shared, self.barrier = [], None
        first_error, self.pending_error = self.pending_error, None
        # HookStopped already determines the turn's interrupted status.
        if first_error is not None and not isinstance(first_error, HookStopped):
            raise first_error


def _validate_cached_turn(cache, request, model):
    """Reject actor/schema changes that cannot yet be replayed in place."""
    previous = cache["history"].model
    # These ModelInfo fields affect initialized tools, resource fragments, or
    # the collaboration protocol. Reusing their old actors would be silent
    # semantic drift; ordinary model/effort/budget updates need no new actors.
    fields = (
        "shell_type",
        "tool_mode",
        "multi_agent_version",
        "supports_search_tool",
        "apply_patch_tool_type",
        "web_search_tool_type",
        "supports_image_detail_original",
        "experimental_supported_tools",
        "include_skills_usage_instructions",
        "include_plugin_usage_instructions",
        "include_apps_usage_instructions",
    )
    changed = [key for key in fields if previous.info.get(key) != model.info.get(key)]
    if changed:
        raise ValueError(
            "Codex Python cached model switch changes unsupported tool/resource "
            "capabilities: " + ", ".join(changed)
        )
    mutable = {
        "model",
        "model_reasoning_effort",
        "model_reasoning_summary",
        "model_verbosity",
        "model_context_window",
        "model_auto_compact_token_limit",
        "model_auto_compact_token_limit_scope",
        "tool_output_token_limit",
        "service_tier",
        "output_schema",
        "compact_prompt",
    }
    old, new = cache["client"].settings, request["settings"]
    changed = {
        key
        for key in old.keys() | new.keys()
        if not key.startswith("_")
        and key not in mutable
        and old.get(key) != new.get(key)
    }
    if changed or old.get("_provider_capabilities") != new.get(
        "_provider_capabilities"
    ):
        raise ValueError(
            "Codex Python cached continuation cannot change initialized resource "
            "configuration: " + ", ".join(sorted(changed or {"provider capabilities"}))
        )
    if (
        Path(request["home"]).resolve() != cache["resources"].home
        or Path(request["cwd"]).resolve() != cache["resources"].cwd
        or request.get("environment") != cache["router"]._environment
    ):
        raise ValueError(
            "Codex Python cached continuation cannot change its environment"
        )


async def _previous_model_compact(history, previous, model, request, router, emit):
    """turn.rs::maybe_run_previous_model_inline_compact / with_model."""
    from .compact import active_tokens, maybe_compact
    from .context_budget import effective_window

    old_hash, new_hash = previous.info.get("comp_hash"), model.info.get("comp_hash")
    reason = (
        "comp_hash_changed"
        if old_hash is not None and new_hash is not None and old_hash != new_hash
        else None
    )
    settings = copy.deepcopy(request["settings"])
    old_model = Model(previous.info["slug"], settings)
    old_model.instructions = model.instructions
    old_window, new_window = effective_window(old_model), effective_window(model)
    active = active_tokens(history)
    hard_reached = new_window is not None and active >= new_window
    limit = model.auto_compact_token_limit
    limit_reached = hard_reached or (
        settings.get("model_auto_compact_token_limit_scope", "total") == "total"
        and limit is not None
        and active > limit
    )
    if reason is None and (
        old_window is not None
        and new_window is not None
        and old_window > new_window
        and previous.info["slug"] != model.info["slug"]
        and limit_reached
    ):
        reason = "model_downshift"
    if reason is None:
        return False
    effort = request["llm"].get("reasoning_effort")
    if effort is None:
        effort = settings.get("model_reasoning_effort") or model.info.get(
            "default_reasoning_level"
        )
    supported = [
        entry["effort"] for entry in old_model.info["supported_reasoning_levels"]
    ]
    if effort not in supported:
        effort = (
            supported[(len(supported) - 1) // 2]
            if supported
            else old_model.info.get("default_reasoning_level")
        )
    settings["model_reasoning_effort"] = effort
    settings["_model_info"] = old_model.info
    configure(settings, old_model)
    previous_request = {
        **request,
        "settings": settings,
        "llm": {
            **request["llm"],
            "model_name": old_model.info["slug"],
            "reasoning_effort": effort,
        },
        "_compaction_phase": "pre_turn",
        "_compaction_reason": reason,
    }
    client = request["_client"]
    current_llm, current_model, current_settings = (
        client.llm,
        client.model,
        client.settings,
    )
    client.llm, client.model, client.settings = (
        previous_request["llm"],
        old_model,
        settings,
    )
    history.model = old_model
    try:
        return await maybe_compact(
            history, old_model, previous_request, router, emit, force=True
        )
    finally:
        client.llm, client.model, client.settings = (
            current_llm,
            current_model,
            current_settings,
        )
        history.model = model
        request["settings"]["_window_number"] = getattr(history, "window_number", 0)
        request["settings"]["_compaction_injected_context"] = settings.get(
            "_compaction_injected_context", False
        )


async def run_session(request, emit):
    """Run one native-style user turn; child continuations may supply history."""
    settings = copy.deepcopy(request["settings"])
    cache = request.get("_session_cache")
    if cache:
        for key in ("_thread_id", "_session_id", "_installation_id"):
            if key in cache["client"].settings:
                settings.setdefault(key, cache["client"].settings[key])
    settings.setdefault("_thread_id", str(uuid.uuid4()))
    settings.setdefault("_session_id", settings["_thread_id"])
    settings.setdefault("_turn_id", str(uuid.uuid4()))
    settings.setdefault("_installation_id", str(uuid.uuid4()))
    settings["_started_at_unix_ms"] = int(time.time() * 1000)
    settings.setdefault("thread_id", settings["_thread_id"])
    request = {**request, "settings": settings}
    request.setdefault("_input_queue", asyncio.Queue())
    reused = bool(cache)
    home, cwd = Path(request["home"]), Path(request["cwd"])
    router = resources = subagents = schedule = turn_metadata = None
    history = client = None
    output, error, status = "", None, "finished"
    starting_usage = {}

    def append(item):
        history.append(prepare_for_history(item, settings["_turn_id"]))
        if request.get("_history_sink"):
            request["_history_sink"](copy.deepcopy(history.items))

    def drain_input():
        queue = request.get("_input_queue")
        found = False
        if queue is not None:
            while not queue.empty():
                value = queue.get_nowait()
                values = value if isinstance(value, list) else [value]
                for item in values:
                    append(message("user", item) if isinstance(item, str) else item)
                found = True
        if found and subagents is not None:
            drained = getattr(subagents, "input_drained", None)
            if drained:
                drained()
        return found

    def flush_injections():
        # Background code cells notify independently from user steering. Their
        # output follows the observing tool output and precedes model sampling.
        pending = router._pending_injections
        while pending:
            append(pending.pop(0))

    try:
        clock = settings.get("features", {}).get("current_time_reminder")
        if clock and (not isinstance(clock, dict) or clock.get("enabled", True)):
            if isinstance(clock, dict) and clock.get("clock_source") == "external":
                raise ValueError(
                    "Fatal error: failed to read current time: current-time request failed: code=-32000 message=external current time is not supported in exec mode"
                )
            raise ValueError(
                "Codex Python core has not implemented current_time_reminder"
            )
        validate(settings)
        turn_metadata = TurnMetadataState(cwd)
        settings["_turn_metadata_state"] = turn_metadata
        turn_metadata.start()
        if any((home / "rules").rglob("*.rules")):
            raise ValueError("Codex Python core has not implemented execpolicy rules")
        if "" in settings.get("otel", {}).get("span_attributes", {}):
            emit(
                {
                    "type": "warning",
                    "message": "Ignoring invalid `otel.span_attributes` config: configured span attribute key must not be empty",
                }
            )
        model = Model(request["llm"]["model_name"], settings)
        settings["_model_info"] = model.info
        configure(settings, model)
        previous_model = None
        model_switch = None
        if reused:
            history, router, resources, subagents, client = (
                cache[name]
                for name in ("history", "router", "resources", "subagents", "client")
            )
            starting_usage = dict(history.usage)
            _validate_cached_turn(cache, request, model)
            previous_model = cache.get("previous_model", history.model)
            if previous_model.info["slug"] != model.info["slug"] and model.instructions:
                model_switch = (
                    "<model_switch>\nThe user was previously using a different model. "
                    "Please continue the conversation according to the following instructions:\n\n"
                    + model.instructions
                    + "\n</model_switch>"
                )
            # SessionConfiguration owns the immutable base prompt. Model
            # changes are conveyed through a developer world-state fragment.
            model.instructions = cache["base_instructions"]
            refreshed = ResponsesClient(
                request["llm"], model, settings, settings["_thread_id"], emit
            )
            await refreshed.__aenter__()
            await client.__aexit__(None, None, None)
            client = refreshed
            history.model = router.model = model
            resources.settings = resources.hooks.settings = settings
            resources.memories.settings = resources.mcp.settings = settings
            router.settings = router.shell.settings = settings
            router.shell.model_info = model.info
            router.emit = resources.emit = resources.hooks.emit = resources.mcp.emit = (
                emit
            )
            for server in resources.mcp.servers.values():
                server.emit = emit
            subagents.settings = settings
            subagents.emit = emit
            resources.hooks.stop_hook_active = False
            subagents.request = request
            request["_initial_context"] = cache["initial_context"]
        else:
            history = History(model)
            router = ToolRouter(settings, cwd, model, emit, request.get("environment"))
            router.shell.start_snapshot(home, request.get("_shell_environment"))
            settings["_shell_path"] = router.shell.session_shell
            request["_shell_environment"] = (
                router.shell.session_shell,
                router.shell.snapshot,
            )
            resources = Resources(home, cwd, settings, emit, request.get("environment"))
            from .subagents import Subagents

            request["_history_provider"] = lambda: copy.deepcopy(history.items)
            subagents = Subagents(router, request, emit, run_session)
            contexts = await resources.start(router)
            request["_initial_context"] = initial_context(
                contexts, settings, cwd, model
            )
            request["_initial_context"] = subagents.augment_initial_context(
                request["_initial_context"]
            )
            if request.get("initial_history") is not None:
                for item in request["initial_history"]:
                    append(item)
                if request.get("_rebuild_initial_context"):
                    for item in augment_initial_context(
                        request["_initial_context"], history, model, settings
                    ):
                        append(item)
            else:
                for item in augment_initial_context(
                    request["_initial_context"], history, model, settings
                ):
                    append(item)
            client = ResponsesClient(
                request["llm"], model, settings, settings["_thread_id"], emit
            )
            await client.__aenter__()
        settings["_shell_path"] = router.shell.session_shell
        emit({"type": "codex.shell.selected", "path": router.shell.session_shell})
        request["_client"] = client
        router.history = history
        router.append = append
        if not hasattr(router, "_pending_injections"):
            router._pending_injections = []
        router.inject = router._pending_injections.append
        router.prepare_code_mode()
        request["_history_provider"] = lambda: copy.deepcopy(history.items)
        subagents.request = request
        schedule = ToolSchedule(router)
        starting_usage = dict(history.usage)
        if cache is not None:
            cache.update(
                history=history,
                router=router,
                resources=resources,
                subagents=subagents,
                client=client,
                initial_context=request["_initial_context"],
                base_instructions=model.instructions,
            )
        history.server_reasoning_included = False
        settings["_window_number"] = getattr(history, "window_number", 0)
        if reused or request.get("initial_history"):
            from .compact import maybe_compact

            compacted = False
            if previous_model is not None:
                compacted = await _previous_model_compact(
                    history, previous_model, model, request, router, emit
                )
            previous_injected = settings.pop("_compaction_injected_context", False)
            if model_switch:
                context = copy.deepcopy(request["_initial_context"])
                for item in context:
                    if (
                        item.get("type") == "message"
                        and item.get("role") == "developer"
                    ):
                        item["content"] = [
                            part
                            for part in item["content"]
                            if not part.get("text", "").startswith("<model_switch>")
                        ]
                        item["content"].insert(
                            0, {"type": "input_text", "text": model_switch}
                        )
                        break
                request["_initial_context"] = context
                if cache is not None:
                    cache["initial_context"] = context
            current_compacted = await maybe_compact(
                history,
                model,
                {**request, "_compaction_phase": "pre_turn"},
                router,
                emit,
            )
            compacted |= current_compacted
            injected = settings.pop("_compaction_injected_context", False)
            if not current_compacted:
                injected = previous_injected
            if compacted and not injected:
                for item in request["_initial_context"]:
                    current = copy.deepcopy(item)
                    current.pop("id", None)
                    append(current)
            elif model_switch and not (current_compacted and injected):
                append(message("developer", model_switch))
        if request.get("_initial_input_items") is not None:
            injections = []
            for item in request["_initial_input_items"]:
                append(item)
        else:
            prompt, injections = await resources.before_prompt(request["prompt"])
            append(message("user", request.get("prompt_content") or prompt))
        for item in injections:
            append(item)
        if cache is not None:
            # Native commits PreviousTurnSettings after pre-turn compaction
            # and input hooks succeed, so a failed migration retries its old
            # model/hash rather than accepting a partially migrated turn.
            cache["previous_model"] = model
        emit({"type": "thread.started", "thread_id": settings["_thread_id"]})
        emit(
            {
                "type": "flashrsi.python_core.started",
                "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                "source": str(Path(__file__).parent),
            }
        )
        retries = 0
        can_drain_pending_input = request.get("_initial_input_items") == []
        while True:
            flush_injections()
            if can_drain_pending_input:
                drain_input()
            can_drain_pending_input = True
            last_message = None
            needs_follow_up = False

            def stream_event(event):
                nonlocal last_message, needs_follow_up
                emit(event)
                if event.get("type") == "server_reasoning_included":
                    history.server_reasoning_included = True
                if event.get("type") != "response.output_item.done":
                    return
                item = event.get("item")
                if not isinstance(item, dict):
                    return
                append(item)
                if item.get("type") == "tool_search_call" and (
                    item.get("execution") != "client" or item.get("call_id") is None
                ):
                    return
                text = assistant_text(item)
                if text is not None:
                    last_message = text
                # Native ToolRouter retains legacy local_shell_call in history
                # without dispatching it or requesting another sampling step.
                if item.get("type") in {
                    "function_call",
                    "custom_tool_call",
                    "tool_search_call",
                }:
                    schedule.submit(item)
                    needs_follow_up = True
                # AgentMessage outputs are durable protocol items. Only
                # explicit collaboration tool calls deliver agent messages.

            client.emit = stream_event
            try:
                response = await client.response(
                    history.input_items(),
                    router.specs,
                    request_metadata(settings),
                    retry_stream=False,
                )
            except ResponseError as exc:
                await schedule.drain(append)
                flush_injections()
                history.add_usage(exc.usage)
                if exc.code == "context_length_exceeded":
                    history.set_usage_full()
                if not exc.retryable or retries >= client.stream_retries:
                    raise
                retries += 1
                emit(
                    {
                        "type": "error",
                        "message": f"Reconnecting... {retries}/{client.stream_retries}",
                        "will_retry": True,
                    }
                )
                await asyncio.sleep(
                    exc.delay if exc.delay is not None else _backoff(retries)
                )
                continue
            history.add_usage(response["usage"])
            observe_usage(history, response["usage"], settings)
            await schedule.drain(append)
            flush_injections()
            retries = 0
            needs_follow_up |= response.get("end_turn") is False
            model_needs_follow_up = needs_follow_up
            needs_follow_up |= not request["_input_queue"].empty()
            from .context_budget import token_status

            budget_status = token_status(history, model, settings)
            limit_reached = bool(
                budget_status and budget_status.get("token_limit_reached")
            )
            rollover_requested = settings.get("_new_context_window_requested", False)
            record_budget_messages(
                history,
                model,
                request,
                append,
                not limit_reached and not (needs_follow_up and rollover_requested),
            )
            if needs_follow_up:
                from .compact import maybe_compact

                if limit_reached or rollover_requested:
                    settings.pop("_new_context_window_requested", None)
                    await maybe_compact(
                        history, model, request, router, emit, force=True
                    )
                    can_drain_pending_input = not model_needs_follow_up
                continue
            output = last_message or ""
            continuations = await resources.after_turn(output, "finished")
            if continuations:
                for item in continuations:
                    append(item)
                continue
            break
    except HookStopped as exc:
        status, error = "interrupted", str(exc) or "Codex turn stopped by hook"
    except asyncio.CancelledError:
        status, error = "interrupted", "Codex turn interrupted"
    except Exception as exc:
        status, error = "error", str(exc) or type(exc).__name__
    finally:
        cleanup_error = None
        try:
            if turn_metadata is not None:
                await turn_metadata.close()
            if schedule is not None:
                await schedule.close(append)
        except BaseException as exc:
            cleanup_error = exc
        finally:
            try:
                if cache is None or not cache:
                    await close_session(
                        {
                            "client": client,
                            "subagents": subagents,
                            "resources": resources,
                            "router": router,
                        }
                    )
                elif router is not None and (
                    status == "interrupted"
                    or isinstance(cleanup_error, asyncio.CancelledError)
                ):
                    # A scheduler failure must not leave interrupted processes
                    # alive while this thread retains its MCP actors/history.
                    await router.reset_processes()
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
        if isinstance(cleanup_error, asyncio.CancelledError):
            status, error = "interrupted", error or "Codex turn interrupted"
        elif cleanup_error is not None:
            status = "error"
            error = (
                ((error + "\n") if error else "")
                + "Codex cleanup failed: "
                + (str(cleanup_error) or type(cleanup_error).__name__)
            )
    return {
        "status": status,
        "output": output if status == "finished" else "",
        "usage": {
            key: value - starting_usage.get(key, 0)
            for key, value in history.usage.items()
        }
        if history is not None
        else {},
        "error_message": error,
        "history": history.items if history is not None else [],
    }


async def close_session(cache):
    """Release every actor even if another closer fails or gets interrupted."""

    async def close_all():
        errors = []
        for name in ("subagents", "resources", "router", "client"):
            value = cache.get(name)
            if value is None:
                continue
            try:
                if name == "client":
                    await value.__aexit__(None, None, None)
                else:
                    await value.close()
            except BaseException as exc:
                errors.append(exc)
        cache.clear()
        if errors:
            raise errors[0]

    cleanup = asyncio.create_task(close_all())
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        await cleanup
        raise
