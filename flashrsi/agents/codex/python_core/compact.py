"""Local Responses compaction ported from Codex be6e8eac, core/src/compact.rs.

Compaction dispatch follows provider capabilities and token-budget mode. The
local Responses summarization path lives here; remote_compact.py and
context_budget.py own remote checkpoints and fresh-window rollovers.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from pathlib import Path

from .client import ResponseError, ResponsesClient, _backoff
from .context import assistant_text, is_hook_prompt, message, request_metadata
from .history import History, prepare_for_history, truncate_text
from .images import decode_image_url

_ASSETS = Path(__file__).with_name("assets") / "compact"
SUMMARIZATION_PROMPT = (_ASSETS / "prompt.md").read_text()
SUMMARY_PREFIX = (_ASSETS / "summary_prefix.md").read_text()
_MODEL_ITEMS = {
    "reasoning",
    "function_call",
    "custom_tool_call",
    "local_shell_call",
    "tool_search_call",
    "web_search_call",
    "image_generation_call",
    "compaction",
    "context_compaction",
}


async def maybe_compact(history, model, request, router, emit, *, force=False):
    """session/turn.rs: compact a full context before the next sampling step."""
    settings = request["settings"]
    from .context_budget import enabled, rollover, token_status
    from .remote_compact import compact_remote, supported

    settings["_compaction_injected_context"] = False
    if not force and not token_status(history, model, settings)["token_limit_reached"]:
        return False
    if enabled(settings, "token_budget"):
        await rollover(history, model, request, router, emit)
    elif supported(settings, request["llm"]):
        await compact_remote(history, model, request, router, emit)
    else:
        await compact(history, model, request, router, emit)
    return True


async def compact(history, model, request, router, emit):
    """compact.rs::run_compact_task_inner_impl, local Responses variant."""
    settings = request["settings"]
    phase = request.get("_compaction_phase", "mid_turn")
    if phase not in {"mid_turn", "pre_turn"}:
        raise ValueError(f"Unsupported native Codex compaction phase: {phase}")
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
    request_history = History(model)
    request_history.items = copy.deepcopy(history.items)
    prompt_item = message(
        "user",
        settings.get("compact_prompt")
        if settings.get("compact_prompt") is not None
        else SUMMARIZATION_PROMPT,
    )
    # Synthesized compaction input is local to the cloned request history and
    # does not pass Session::assign_missing_response_item_ids.
    prompt_item.pop("id")
    request_history.append(prompt_item)
    # Prompt::default has no tools and parallel_tool_calls=false. Do not mutate
    # the live model or its normal sampling request behavior.
    compact_model = copy.copy(model)
    compact_model.info = {**model.info, "supports_parallel_tool_calls": False}
    compact_settings = copy.deepcopy(settings)
    compact_settings.pop("output_schema", None)
    metadata = request_metadata(settings)
    nested = json.loads(metadata["x-codex-turn-metadata"])
    nested["request_kind"] = "compaction"
    nested["compaction"] = {
        "trigger": "auto",
        "reason": request.get("_compaction_reason", "context_limit"),
        "implementation": "responses",
        "phase": phase,
        "strategy": "memento",
    }
    metadata["x-codex-turn-metadata"] = json.dumps(
        nested, ensure_ascii=True, separators=(",", ":")
    )

    def event(event):
        emit(event)
        if event.get("type") == "server_reasoning_included":
            history.server_reasoning_included = True
        if event.get("type") == "response.output_item.done" and isinstance(
            event.get("item"), dict
        ):
            history.append(prepare_for_history(event["item"], settings["_turn_id"]))

    async with ResponsesClient(
        request["llm"], compact_model, compact_settings, settings["_thread_id"], event
    ) as client:
        retries, max_retries = 0, client.stream_retries
        # Compaction owns the stream retry loop. Its request history deliberately
        # stays fixed while emitted output items enter the live transcript.
        client.stream_retries = 0
        while True:
            inputs = request_history.input_items()
            try:
                result = await client.response(inputs, [], metadata)
                history.add_usage(result["usage"])
                from .context_budget import observe_usage

                observe_usage(history, result["usage"], settings)
                break
            except ResponseError as exc:
                history.add_usage(exc.usage)
                if exc.code == "context_length_exceeded" and len(inputs) > 1:
                    _remove_first_with_pair(request_history.items)
                    retries = 0
                    continue
                if exc.code == "context_length_exceeded":
                    history.set_usage_full()
                    raise
                if retries >= max_retries:
                    raise
                retries += 1
                emit(
                    {
                        "type": "error",
                        "message": f"Reconnecting... {retries}/{max_retries}",
                        "will_retry": True,
                    }
                )
                await asyncio.sleep(_backoff(retries))
    summary = next(
        (
            text
            for item in reversed(history.items)
            if (text := assistant_text(item)) is not None
        ),
        "",
    )
    replacement = build_compacted_history(
        collect_user_messages(history.items), SUMMARY_PREFIX + "\n" + summary
    )
    replacement[-1] = prepare_for_history(replacement[-1], settings["_turn_id"])
    context = [] if phase == "pre_turn" else request.get("_initial_context")
    if context is None:
        # The main turn's canonical initial-context items precede its first real
        # user prompt. Reuse precisely those resources, never rediscover files.
        first_user = next(
            (i for i, item in enumerate(history.items) if _real_user(item)),
            len(history.items),
        )
        context = copy.deepcopy(history.items[:first_user])
    context = copy.deepcopy(context)
    for index, item in enumerate(context):
        if item.get("type") == "message":
            item["id"] = "msg_" + str(uuid.uuid4())
        context[index] = prepare_for_history(item, settings["_turn_id"])
    history.items = insert_initial_context(replacement, context)
    from .context_budget import advance_window, recompute_usage

    advance_window(history, model, settings)
    # Session::recompute_token_usage changes last usage, preserving totals.
    recompute_usage(history, model, settings)
    if request.get("_history_sink"):
        request["_history_sink"](copy.deepcopy(history.items))
    if getattr(router, "hooks", None) is not None:
        await router.hooks.run(
            "PostCompact",
            matcher_input="auto",
            trigger="auto",
            model=model.info["slug"],
        )
    emit(
        {
            "type": "item.completed",
            "item": {"id": checkpoint, "type": "context_compaction"},
        }
    )
    emit(
        {
            "type": "warning",
            "message": "Heads up: Long threads and multiple compactions can cause the model to be less accurate. Start a new thread when possible to keep threads small and targeted.",
        }
    )


def tokens(text):
    return (len(text.encode()) + 3) // 4


def estimate_item_tokens(item):
    # context_manager/history.rs::estimate_response_item_model_visible_bytes.
    kind = item.get("type")
    encrypted = item.get("encrypted_content")
    if (
        kind in {"reasoning", "compaction", "context_compaction"}
        and encrypted is not None
    ):
        return (max(0, len(encrypted.encode()) * 3 // 4 - 650) + 3) // 4
    raw = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    size = len(raw.encode())
    content = (
        item.get("content")
        if kind in {"message", "agent_message"}
        else item.get("output")
    )
    for part in content if isinstance(content, list) else []:
        if part.get("type") == "input_image" and kind != "agent_message":
            url = part["image_url"]
            payload = _base64_payload(url, "image/")
            if payload is not None:
                replacement = 7373
                if part.get("detail") == "original":
                    try:
                        _, _, width, height = decode_image_url(url)
                        replacement = (
                            min(((width + 31) // 32) * ((height + 31) // 32), 10000) * 4
                        )
                    except (ValueError, OSError, OverflowError):
                        pass
                size = max(0, size - len(payload.encode())) + replacement
        elif part.get("type") == "encrypted_content" and kind in {
            "function_call_output",
            "agent_message",
        }:
            encoded_length = len(part["encrypted_content"].encode())
            size = max(0, size - encoded_length) + (encoded_length * 9 + 15) // 16
        elif part.get("type") == "input_audio":
            raise ValueError(
                "Codex Python core has not ported native audio duration token estimation"
            )
    return (size + 3) // 4


def _base64_payload(url, mime_prefix):
    if not url[:5].lower() == "data:" or "," not in url:
        return None
    metadata, payload = url[5:].split(",", 1)
    parts = metadata.split(";")
    if not parts[0].lower().startswith(mime_prefix) or not any(
        part.lower() == "base64" for part in parts[1:]
    ):
        return None
    return payload


def active_tokens(history):
    # Count local items since the latest model item, in addition to provider
    # usage. It is the most recent context size, not cumulative billing usage.
    last = next(
        (
            i
            for i in range(len(history.items) - 1, -1, -1)
            if history.items[i].get("type") in _MODEL_ITEMS
            or (
                history.items[i].get("type") == "message"
                and history.items[i].get("role") == "assistant"
            )
        ),
        len(history.items) - 1,
    )
    growth = sum(estimate_item_tokens(item) for item in history.items[last + 1 :])
    last_boundary = next(
        (
            i
            for i in range(len(history.items) - 1, -1, -1)
            if history.items[i].get("type") == "agent_message"
            or _real_user(history.items[i])
        ),
        0,
    )
    past_reasoning = (
        0
        if getattr(history, "server_reasoning_included", False)
        else sum(
            estimate_item_tokens(item)
            for item in history.items[:last_boundary]
            if item.get("type") == "reasoning"
            and item.get("encrypted_content") is not None
        )
    )
    return history.last_usage.get("total_tokens", 0) + growth + past_reasoning


def _contextual(text):
    value = text.strip()
    lower = value.lower()
    markers = [
        ("# agents.md instructions", "</instructions>"),
        ("<environment_context>", "</environment_context>"),
        ("<skill>", "</skill>"),
        ("<user_shell_command>", "</user_shell_command>"),
        ("<turn_aborted>", "</turn_aborted>"),
        ("<subagent_notification>", "</subagent_notification>"),
        ("<recommended_plugins>", "</recommended_plugins>"),
    ]
    if any(lower.startswith(start) and lower.endswith(end) for start, end in markers):
        return True
    if value.startswith("<external_") and ">" in value:
        key = value[len("<external_") :].split(">", 1)[0]
        if value.endswith(f"</external_{key}>"):
            return True
    if re.match(
        r'<codex_internal_context source="[a-z][a-z0-9_]*">[\s\S]*</codex_internal_context>$',
        value,
    ):
        return True
    if value.startswith("<goal_context>") and value.endswith("</goal_context>"):
        return True
    if is_hook_prompt(value):
        return True
    return value.startswith(
        (
            "Warning: Your account was flagged for potentially high-risk cyber activity",
            "Warning: The maximum number of unified exec processes you can keep open is",
        )
    ) or (
        value.startswith("Warning: apply_patch was requested via ")
        and value.endswith("Use the apply_patch tool instead of exec_command.")
    )


def _real_user(item):
    return (
        item.get("type") == "message"
        and item.get("role") == "user"
        and not any(
            _contextual(part.get("text", ""))
            for part in item.get("content", [])
            if part.get("type") == "input_text"
        )
    )


def collect_user_messages(items):
    # compact.rs::collect_user_messages; previous summaries and injected
    # contextual messages are excluded. Images are absent from UserMessage.text.
    result = []
    for item in items:
        if not _real_user(item):
            continue
        text = "".join(
            part["text"]
            for part in item.get("content", [])
            if part.get("type") == "input_text" and part.get("text")
        )
        if not text.startswith(SUMMARY_PREFIX + "\n"):
            result.append(
                {
                    "text": text,
                    "metadata": item.get("internal_chat_message_metadata_passthrough"),
                }
            )
    return result


def build_compacted_history(users, summary, max_tokens=20000):
    selected, remaining = [], max_tokens
    for user in reversed(users):
        if remaining <= 0:
            break
        cost = tokens(user["text"])
        selected.append(
            {
                **user,
                "text": user["text"]
                if cost <= remaining
                else truncate_text(user["text"], "tokens", remaining),
            }
        )
        remaining -= min(cost, remaining)
    result = []
    for user in reversed(selected):
        item = message("user", user["text"])
        if user.get("metadata") is not None:
            item["internal_chat_message_metadata_passthrough"] = copy.deepcopy(
                user["metadata"]
            )
        result.append(item)
    result.append(message("user", summary or "(no summary available)"))
    return result


def insert_initial_context(items, context):
    fallback = None
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        content = item.get("content", [])
        first = content[0] if content else {}
        if item.get("type") == "agent_message" and not (
            first.get("type") == "input_text"
            and first.get("text", "").startswith("Message Type: FINAL_ANSWER\n")
        ):
            return items[:index] + copy.deepcopy(context) + items[index:]
        if _real_user(item):
            fallback = index if fallback is None else fallback
            text = "".join(part.get("text", "") for part in item.get("content", []))
            if not text.startswith(SUMMARY_PREFIX + "\n"):
                return items[:index] + copy.deepcopy(context) + items[index:]
    index = (
        fallback
        if fallback is not None
        else next(
            (
                i
                for i in range(len(items) - 1, -1, -1)
                if items[i].get("type") in {"compaction", "context_compaction"}
            ),
            len(items),
        )
    )
    return items[:index] + copy.deepcopy(context) + items[index:]


def _remove_first_with_pair(items):
    if not items:
        return
    removed = items.pop(0)
    pairs = {
        "function_call": "function_call_output",
        "function_call_output": "function_call",
        "custom_tool_call": "custom_tool_call_output",
        "custom_tool_call_output": "custom_tool_call",
        "tool_search_call": "tool_search_output",
        "tool_search_output": "tool_search_call",
        "local_shell_call": "function_call_output",
    }
    other = pairs.get(removed.get("type"))
    if other and removed.get("call_id") is not None:
        index = next(
            (
                i
                for i, item in enumerate(items)
                if item.get("type") == other
                and item.get("call_id") == removed.get("call_id")
            ),
            None,
        )
        if index is not None:
            items.pop(index)
        elif removed.get("type") == "function_call_output":
            index = next(
                (
                    i
                    for i, item in enumerate(items)
                    if item.get("type") == "local_shell_call"
                    and item.get("call_id") == removed.get("call_id")
                ),
                None,
            )
            if index is not None:
                items.pop(index)
