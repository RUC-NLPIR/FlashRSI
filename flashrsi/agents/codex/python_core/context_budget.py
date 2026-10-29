"""Window budgets from Codex be6e8eac, session/{context_window,token_budget}.rs.

Window state follows state/auto_compact_window.rs; rendered fragments follow
context/token_budget_context.rs. Rollovers preserve environment actors while
replacing only model-visible conversation history.
"""

from __future__ import annotations

import copy
import time
import uuid

from .context import message
from .history import prepare_for_history

DEFAULT_REMINDER = (
    "Your context window is nearly exhausted (only {n_remaining} tokens remaining) and will be automatically reset for you soon. "
    "Once reset, message items in current context window will be cleared in the new window, but notes and history items will be persistent across windows."
)


def enabled(settings, name, default=False):
    value = settings.get("features", {}).get(name, default)
    return value.get("enabled", default) if isinstance(value, dict) else bool(value)


def configure(settings, model):
    """config::resolve_token_budget_config / session::apply_model_defaults."""
    if not enabled(settings, "token_budget"):
        settings["_token_budget"] = None
        return None
    supplied = settings.get("features", {}).get("token_budget", {})
    supplied = supplied if isinstance(supplied, dict) else {}
    allowed = {
        "enabled",
        "mode",
        "reminder_threshold_tokens",
        "reminder_message_template",
        "guidance_message",
        "auto_compact_fallback_prompt",
        "auto_compact_fallback_buffer_tokens",
    }
    if set(supplied) - allowed:
        raise ValueError(
            "Unsupported features.token_budget configuration: "
            + ", ".join(sorted(set(supplied) - allowed))
        )
    config = {
        "mode": supplied.get("mode", "thread"),
        "reminder_threshold_tokens": supplied.get("reminder_threshold_tokens"),
        "reminder_message_template": supplied.get(
            "reminder_message_template", DEFAULT_REMINDER
        ),
        "guidance_message": supplied.get("guidance_message"),
        "auto_compact_fallback_prompt": supplied.get("auto_compact_fallback_prompt"),
        "auto_compact_fallback_buffer_tokens": supplied.get(
            "auto_compact_fallback_buffer_tokens"
        ),
    }
    guidance = config["guidance_message"]
    if guidance is not None:
        if not isinstance(guidance, str):
            raise ValueError("features.token_budget.guidance_message must be a string")
        if not guidance.strip():
            config["guidance_message"] = None
    prompt = config["auto_compact_fallback_prompt"]
    if prompt is not None:
        if not isinstance(prompt, str):
            raise ValueError(
                "features.token_budget.auto_compact_fallback_prompt must be a string"
            )
        config["auto_compact_fallback_prompt"] = prompt.strip() or None
    _validate_config(config)
    defaults = (model.info.get("model_messages") or {}).get("token_budget")
    if defaults and not (set(supplied) - {"enabled", "mode"}):
        candidate = {**config, **copy.deepcopy(defaults)}
        try:
            # Model-owned strings are validated verbatim, whereas TOML prompt
            # strings were trimmed in resolve_token_budget_config above.
            _validate_config(candidate)
        except ValueError:
            # Native apply_model_defaults logs and retains config defaults.
            pass
        else:
            config = candidate
    settings["_token_budget"] = config
    return config


def _validate_config(config):
    if config["mode"] not in {"thread", "name"}:
        raise ValueError("features.token_budget.mode must be thread or name")
    for key in ("reminder_threshold_tokens", "auto_compact_fallback_buffer_tokens"):
        value = config[key]
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError(f"features.token_budget.{key} must be positive")
    for key in (
        "reminder_message_template",
        "guidance_message",
        "auto_compact_fallback_prompt",
    ):
        value = config[key]
        if value is not None and (
            not isinstance(value, str) or len(value.encode()) > 2000
        ):
            raise ValueError(f"features.token_budget.{key} must not exceed 2000 bytes")
    if (
        not isinstance(config["reminder_message_template"], str)
        or not config["reminder_message_template"].strip()
    ):
        raise ValueError(
            "features.token_budget.reminder_message_template must not be empty"
        )
    if (
        config["auto_compact_fallback_prompt"] is not None
        and config["auto_compact_fallback_buffer_tokens"] is None
    ):
        raise ValueError(
            "features.token_budget.auto_compact_fallback_buffer_tokens is required when auto_compact_fallback_prompt is set"
        )


def _uuid7():
    random = uuid.uuid4().int
    return str(
        uuid.UUID(
            int=(int(time.time() * 1000) << 80)
            | (7 << 76)
            | ((random >> 64 & 0xFFF) << 64)
            | (2 << 62)
            | (random & ((1 << 62) - 1))
        )
    )


def window(history, settings):
    state = getattr(history, "_context_budget_window", None)
    if state is None:
        identity = _uuid7()
        state = {
            "first_window_id": identity,
            "window_id": identity,
            "previous_window_id": None,
            "number": getattr(
                history, "window_number", settings.get("_window_number", 0)
            ),
            "prefill": None,
            "prefill_observed": False,
            "reminder_delivered": False,
            "fallback_delivered": False,
        }
        history._context_budget_window = state
    return state


def observe_usage(history, usage, settings):
    if (
        usage
        and settings.get("model_auto_compact_token_limit_scope", "total")
        == "body_after_prefix"
    ):
        state = window(history, settings)
        if not state["prefill_observed"]:
            state["prefill"] = max(0, usage.get("input_tokens", 0))
            state["prefill_observed"] = True


def effective_window(model):
    size = model.info.get("context_window") or model.info.get("max_context_window")
    return (
        size * model.info["effective_context_window_percent"] // 100
        if size is not None
        else None
    )


def token_status(history, model, settings):
    from .compact import active_tokens

    active = active_tokens(history)
    scope = settings.get("model_auto_compact_token_limit_scope", "total")
    if scope == "body_after_prefix":
        prefill = window(history, settings)["prefill"]
        scope_tokens = active - (active if prefill is None else prefill)
        scope_limit = settings.get("model_auto_compact_token_limit")
        if scope_limit is None:
            scope_limit = model.auto_compact_token_limit
    elif scope == "total":
        prefill, scope_tokens, scope_limit = (
            None,
            active,
            model.auto_compact_token_limit,
        )
    else:
        raise ValueError(
            "model_auto_compact_token_limit_scope must be total or body_after_prefix"
        )
    hard_limit = effective_window(model)
    remaining = [
        max(0, limit - used)
        for limit, used in ((scope_limit, scope_tokens), (hard_limit, active))
        if limit is not None
    ]
    config = settings.get("_token_budget")
    if config is None and enabled(settings, "token_budget"):
        config = configure(settings, model)
    buffer = (
        config["auto_compact_fallback_buffer_tokens"]
        if config and config["auto_compact_fallback_prompt"]
        else 0
    )
    hard_reached = hard_limit is not None and active >= hard_limit
    return {
        "active_context_tokens": active,
        "auto_compact_scope_tokens": scope_tokens,
        "auto_compact_scope_limit": scope_limit,
        "full_context_window_limit": hard_limit,
        "base_window_tokens_remaining": min(remaining) if remaining else None,
        "auto_compact_window_prefill_tokens": prefill,
        "full_context_window_limit_reached": hard_reached,
        "token_limit_reached": hard_reached
        or (scope_limit is not None and scope_tokens >= scope_limit + buffer),
    }


def record_budget_messages(
    history, model, request, append, allow_auto_compact_fallback
):
    settings = request["settings"]
    config = settings.get("_token_budget")
    if config is None:
        config = configure(settings, model)
    if config is None:
        return
    remaining = token_status(history, model, settings)["base_window_tokens_remaining"]
    if remaining is None:
        return
    state = window(history, settings)
    threshold = config["reminder_threshold_tokens"]
    if (
        threshold is not None
        and remaining <= threshold
        and not state["reminder_delivered"]
    ):
        state["reminder_delivered"] = True
        append(
            message(
                "developer",
                config["reminder_message_template"].replace(
                    "{n_remaining}", str(remaining)
                ),
            )
        )
    if (
        allow_auto_compact_fallback
        and remaining == 0
        and config["auto_compact_fallback_prompt"] is not None
        and not state["fallback_delivered"]
    ):
        state["fallback_delivered"] = True
        append(message("developer", config["auto_compact_fallback_prompt"]))


def context_sections(history, model, settings):
    config = settings.get("_token_budget")
    if config is None:
        config = configure(settings, model)
    if config is None or effective_window(model) is None:
        return []
    state = window(history, settings)
    identity = (
        "Thread id: " + settings["_thread_id"]
        if config["mode"] == "thread"
        else "Agent name: " + settings.get("_agent_path", "/root")
    )
    lines = [
        identity,
        "First context window id: " + state["first_window_id"],
        "Current context window id: " + state["window_id"],
    ]
    if state["previous_window_id"] is not None:
        lines.append("Previous context window id: " + state["previous_window_id"])
    if settings.get("_token_budget_notes_hint"):
        lines.append(settings["_token_budget_notes_hint"])
    result = ["<context_window>\n" + "\n".join(lines) + "\n</context_window>"]
    if config["guidance_message"] is not None:
        result.append(
            "<context_window_guidance>\n"
            + config["guidance_message"]
            + "\n</context_window_guidance>"
        )
    return result


def augment_initial_context(items, history, model, settings):
    """Refresh full-context window fragments without copying a previous window ID."""
    result = copy.deepcopy(items)
    sections = context_sections(history, model, settings)
    if not sections:
        return result
    for item in result:
        if item.get("type") == "message" and item.get("role") == "developer":
            content = [
                part
                for part in item.get("content", [])
                if not (
                    part.get("type") == "input_text"
                    and part.get("text", "").startswith(
                        ("<context_window>", "<context_window_guidance>")
                    )
                )
            ]
            # Session renders the window identity before world-state sections
            # (skills/permissions), following explicit developer instructions.
            insertion = (
                1
                if content
                and content[0].get("text") == settings.get("developer_instructions")
                else 0
            )
            content[insertion:insertion] = [
                {"type": "input_text", "text": text} for text in sections
            ]
            item["content"] = content
            return result
    result.insert(
        0,
        message(
            "developer", [{"type": "input_text", "text": text} for text in sections]
        ),
    )
    return result


def advance_window(history, model, settings):
    state = window(history, settings)
    state.update(
        previous_window_id=state["window_id"],
        window_id=_uuid7(),
        number=state["number"] + 1,
        prefill=None,
        prefill_observed=False,
        reminder_delivered=False,
        fallback_delivered=False,
    )
    settings["_new_context_window_requested"] = False
    history.window_number = settings["_window_number"] = state["number"]


def recompute_usage(history, model, settings):
    from .compact import estimate_item_tokens, tokens

    total = tokens(model.instructions) + sum(
        estimate_item_tokens(item) for item in history.items
    )
    history.last_usage = dict.fromkeys(history.last_usage, 0)
    history.last_usage["total_tokens"] = total
    if (
        settings.get("model_auto_compact_token_limit_scope", "total")
        == "body_after_prefix"
    ):
        state = window(history, settings)
        if not state["prefill_observed"]:
            state["prefill"] = max(0, total)


def install_history(history, items, model, request):
    settings = request["settings"]
    history.items = items
    recompute_usage(history, model, settings)
    if request.get("_history_sink"):
        request["_history_sink"](copy.deepcopy(history.items))


async def rollover(history, model, request, router, emit):
    settings = request["settings"]
    if getattr(router, "hooks", None) is not None:
        await router.hooks.run(
            "PreCompact", matcher_input="auto", trigger="auto", model=model.info["slug"]
        )
    checkpoint = "ctx_" + str(uuid.uuid4())
    emit(
        {
            "type": "item.started",
            "item": {"id": checkpoint, "type": "context_compaction"},
        }
    )
    if not hasattr(history, "archived_windows"):
        history.archived_windows = []
    history.archived_windows.append(copy.deepcopy(history.items))
    advance_window(history, model, settings)
    context = augment_initial_context(
        request.get("_initial_context", []), history, model, settings
    )
    context = [
        prepare_for_history(
            {
                key: value
                for key, value in item.items()
                if key not in {"id", "internal_chat_message_metadata_passthrough"}
            },
            settings["_turn_id"],
        )
        for item in context
    ]
    install_history(history, context, model, request)
    settings["_compaction_injected_context"] = True
    emit(
        {
            "type": "item.completed",
            "item": {"id": checkpoint, "type": "context_compaction"},
        }
    )
    if getattr(router, "hooks", None) is not None:
        await router.hooks.run(
            "PostCompact",
            matcher_input="auto",
            trigger="auto",
            model=model.info["slug"],
        )
