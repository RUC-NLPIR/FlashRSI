"""Codex be6e8eac compact_remote{,_history,_v2,_v2_attempt}.rs.

V1 installs the unary /responses/compact history. V2 collects exactly one
encrypted compaction item from a normal Responses stream and retains bounded
user/agent instructions locally. Neither path executes compaction tool calls.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid

from .client import ResponseError, ResponsesClient, _backoff
from .context import is_hook_prompt, request_metadata
from .context_budget import (
    advance_window,
    augment_initial_context,
    effective_window,
    enabled,
    install_history,
)
from .history import History, canonical_item, prepare_for_history, truncate_text

TRUNCATED_OUTPUT = "Output exceeded the available model context and was truncated"


def supported(settings, llm):
    provider = settings.get("model_providers", {}).get(
        settings.get("model_provider"), {}
    )
    name = provider.get(
        "name", "OpenAI" if settings.get("model_provider") == "openai" else ""
    )
    base_url = llm.get("base_url") or provider.get("base_url", "")
    return (
        name == "OpenAI"
        or name.lower() == "azure"
        or any(
            marker in base_url.lower()
            for marker in (
                "openai.azure.",
                "cognitiveservices.azure.",
                "aoai.azure.",
                "azure-api.",
                "azurefd.",
                "windows.net/openai",
            )
        )
    )


def _notice(item):
    content = item.get("content", [])
    if (
        item.get("type") != "message"
        or item.get("role") != "developer"
        or len(content) != 1
    ):
        return False
    text = content[0].get("text", "").strip()
    return (
        content[0].get("type") == "input_text"
        and text.startswith("<image_resize_notice>")
        and text.endswith("</image_resize_notice>")
    )


def history_groups(items):
    index = 0
    while index < len(items):
        source = items[index]
        index += 1
        notice = items[index] if index < len(items) and _notice(items[index]) else None
        if notice is not None:
            index += 1
        yield source, notice


def should_keep(item):
    from .compact import _real_user

    kind = item.get("type")
    if kind == "message":
        role = item.get("role")
        if role == "assistant":
            return True
        if role == "user":
            return _real_user(item) or any(
                is_hook_prompt(part.get("text", ""))
                for part in item.get("content", [])
                if part.get("type") == "input_text"
            )
        return False
    return kind in {"agent_message", "compaction", "context_compaction"}


def trim_trailing_outputs(items, model):
    from .compact import estimate_item_tokens, tokens

    result = copy.deepcopy(items)
    limit = effective_window(model)
    if limit is None:
        return result
    total = tokens(model.instructions) + sum(
        estimate_item_tokens(item) for item in result
    )
    rewritten, consumed = [], 0
    for item, notice in reversed(list(history_groups(result))):
        if total <= limit:
            break
        kind = item.get("type")
        if kind not in {
            "function_call_output",
            "custom_tool_call_output",
            "tool_search_output",
        }:
            break
        replacement = copy.deepcopy(item)
        if kind == "tool_search_output":
            replacement["tools"] = []
        else:
            replacement["output"] = TRUNCATED_OUTPUT
        total -= estimate_item_tokens(item) + (
            estimate_item_tokens(notice) if notice is not None else 0
        )
        total += estimate_item_tokens(replacement)
        consumed += 1 + (notice is not None)
        rewritten.append(replacement)
    if consumed:
        result = result[:-consumed] + list(reversed(rewritten))
    return result


def _text_tokens(item):
    from .compact import estimate_item_tokens, tokens

    if item.get("type") != "message":
        return estimate_item_tokens(item)
    return sum(
        tokens(part["text"])
        for part in item.get("content", [])
        if part.get("type") in {"input_text", "output_text"}
    )


def truncate_retained_messages(items, max_tokens=64000):
    from .compact import tokens

    remaining, selected = max_tokens, []
    for item, notice in reversed(list(history_groups(copy.deepcopy(items)))):
        if remaining == 0:
            continue
        notice_tokens = max(1, _text_tokens(notice)) if notice is not None else 0
        cost = max(1, _text_tokens(item)) + notice_tokens
        if cost <= remaining:
            selected.append((item, notice))
            remaining -= cost
        elif remaining > notice_tokens and item.get("type") == "message":
            budget, content = remaining - notice_tokens, []
            for part in item.get("content", []):
                if part.get("type") in {"input_text", "output_text"}:
                    if budget == 0:
                        continue
                    cost = tokens(part["text"])
                    if cost <= budget:
                        budget -= cost
                    else:
                        part["text"] = truncate_text(part["text"], "tokens", budget)
                        budget = 0
                    if part["text"]:
                        content.append(part)
                else:
                    content.append(part)
            if content:
                item["content"] = content
                selected.append((item, notice))
                remaining = 0
    return [item for group in reversed(selected) for item in group if item is not None]


def build_v2_history(items, compaction_output, max_tokens=64000):
    from .compact import estimate_item_tokens

    retained = []
    for item, notice in history_groups(items):
        kind = item.get("type")
        if kind == "agent_message":
            first = next(iter(item.get("content", [])), {})
            keep = (
                not (
                    first.get("type") == "input_text"
                    and first.get("text", "").startswith("Message Type: FINAL_ANSWER\n")
                )
                and estimate_item_tokens(item) <= 10000
            )
        else:
            keep = kind == "message" and item.get("role") in {
                "user",
                "developer",
                "system",
            }
        if keep and should_keep(item):
            retained.append(copy.deepcopy(item))
            if notice is not None:
                retained.append(copy.deepcopy(notice))
    return [*truncate_retained_messages(retained, max_tokens), compaction_output]


def process_history(items, history, model, request):
    from .compact import insert_initial_context

    retained = [
        item
        for group in history_groups(items)
        if should_keep(group[0])
        for item in group
        if item is not None
    ]
    context = []
    if request.get("_compaction_phase", "mid_turn") != "pre_turn":
        context = augment_initial_context(
            request.get("_initial_context", []), history, model, request["settings"]
        )
        context = [
            prepare_for_history(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"id", "internal_chat_message_metadata_passthrough"}
                },
                request["settings"]["_turn_id"],
            )
            for item in context
        ]
    # Replacement installation assigns IDs but does not stamp the server output
    # with this turn ID. Kept user metadata continues identifying original turns.
    return [
        prepare_for_history(item, "")
        for item in insert_initial_context(retained, context)
    ]


def compaction_metadata(settings, implementation, phase, reason="context_limit"):
    metadata = request_metadata(settings)
    turn = json.loads(metadata["x-codex-turn-metadata"])
    turn.update(
        request_kind="compaction",
        compaction={
            "trigger": "auto",
            "reason": reason,
            "implementation": implementation,
            "phase": phase,
            "strategy": "memento",
        },
    )
    metadata["x-codex-turn-metadata"] = json.dumps(turn, separators=(",", ":"))
    return metadata


async def compact_remote(history, model, request, router, emit):
    settings = request["settings"]
    phase = request.get("_compaction_phase", "mid_turn")
    v2 = enabled(settings, "remote_compaction_v2", True)
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
    clone = History(model)
    clone.items = trim_trailing_outputs(history.items, model)
    inputs = clone.input_items()
    metadata = compaction_metadata(
        settings,
        "responses_compaction_v2" if v2 else "responses_compact",
        phase,
        request.get("_compaction_reason", "context_limit"),
    )
    client = request.get("_client")
    owned = client is None
    compact_settings = copy.deepcopy(settings)
    compact_settings.pop("output_schema", None)
    if owned:
        client = ResponsesClient(
            request["llm"], model, compact_settings, settings["_thread_id"], emit
        )
        await client.__aenter__()
    old_emit, old_settings = client.emit, client.settings
    client.emit, client.settings = emit, compact_settings
    try:
        if v2:
            retries, max_retries = 0, min(client.stream_retries, 2)
            while True:
                try:
                    response = await client.response(
                        [*inputs, {"type": "compaction_trigger"}],
                        router.specs,
                        metadata,
                        retry_stream=False,
                    )
                    outputs = [
                        parsed
                        for item in response["items"]
                        if item.get("type") in {"compaction", "compaction_summary"}
                        and (parsed := canonical_item(item)) is not None
                    ]
                    if len(outputs) != 1:
                        raise ResponseError(
                            f"remote compaction v2 expected exactly one compaction output item, got {len(outputs)} from {len(response['items'])} output items",
                            code="fatal",
                            retryable=False,
                        )
                    replacement = build_v2_history(inputs, outputs[0])
                    break
                except ResponseError as error:
                    if not error.retryable or retries >= max_retries:
                        raise
                    retries += 1
                    emit(
                        {
                            "type": "error",
                            "message": f"Reconnecting... {retries}/{max_retries}",
                            "will_retry": True,
                        }
                    )
                    await asyncio.sleep(
                        error.delay if error.delay is not None else _backoff(retries)
                    )
        else:
            replacement = await client.compact_response(inputs, router.specs, metadata)
            replacement = [
                parsed
                for item in replacement
                if (parsed := canonical_item(item)) is not None
            ]
    finally:
        client.emit, client.settings = old_emit, old_settings
        if owned:
            await client.__aexit__(None, None, None)
    advance_window(history, model, settings)
    replacement = process_history(replacement, history, model, request)
    install_history(history, replacement, model, request)
    settings["_compaction_injected_context"] = phase != "pre_turn"
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
