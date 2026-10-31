"""Codex transcript storage, normalization, truncation and token accounting.

Ported from rust-v0.147.0 (be6e8eac), core/src/context_manager/{history,
normalize}.rs, protocol/src/{models,protocol}.rs and utils/string/src/truncate.rs.
Rollback, persisted sessions and automatic compaction are outside this module.
"""

from __future__ import annotations

import copy
import math
from uuid import UUID, uuid4, uuid5

from .images import prepare_item
from .models import Model

_TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
_SYNTHETIC_NAMESPACE = UUID("90d38d3e-6a5b-4d52-bfe2-2f1e634bfac4")
_ITEM_FIELDS = {
    "additional_tools": ("role", "tools"),
    "message": ("role", "content", "phase"),
    "agent_message": ("author", "recipient", "content"),
    "reasoning": ("summary", "content", "encrypted_content"),
    "function_call": (
        "name",
        "namespace",
        "arguments",
        "encrypted_function_args",
        "call_id",
    ),
    "function_call_output": ("call_id", "output"),
    "custom_tool_call": ("status", "call_id", "name", "namespace", "input"),
    "custom_tool_call_output": ("call_id", "name", "output"),
    "local_shell_call": ("call_id", "status", "action"),
    "tool_search_call": ("call_id", "status", "execution", "arguments"),
    "tool_search_output": ("call_id", "status", "execution", "tools"),
    "web_search_call": ("status", "action"),
    "image_generation_call": ("status", "revised_prompt", "result"),
    "compaction": ("encrypted_content",),
    "context_compaction": ("encrypted_content",),
}
_ITEM_ID_PREFIXES = {
    "additional_tools": "at",
    "message": "msg",
    "agent_message": "amsg",
    "reasoning": "rs",
    "function_call": "fc",
    "function_call_output": "fco",
    "custom_tool_call": "ctc",
    "custom_tool_call_output": "ctco",
    "local_shell_call": "lsh",
    "tool_search_call": "tsc",
    "tool_search_output": "tso",
    "web_search_call": "ws",
    "image_generation_call": "ig",
    "compaction": "cmp",
    "context_compaction": "cmp",
}
# protocol::models::ResponseItem is deserialized before the SSE event reaches
# the task loop. Missing required fields and invalid nested types discard the
# entire item; merely projecting present keys can install unusable checkpoints
# or execute malformed calls. JSON-valued fields still accept any JSON value.
_ITEM_REQUIRED = {
    "additional_tools": {"role": str, "tools": list},
    "message": {"role": str, "content": list},
    "agent_message": {"author": str, "recipient": str, "content": list},
    "reasoning": {"summary": list},
    "function_call": {"name": str, "arguments": str, "call_id": str},
    "function_call_output": {"call_id": str, "output": (str, list)},
    "custom_tool_call": {"call_id": str, "name": str, "input": str},
    "custom_tool_call_output": {"call_id": str, "output": (str, list)},
    "local_shell_call": {"status": str, "action": dict},
    "tool_search_call": {"execution": str, "arguments": object},
    "tool_search_output": {"status": str, "execution": str, "tools": list},
    "web_search_call": {},
    "image_generation_call": {"status": str, "result": str},
    "compaction": {"encrypted_content": str},
    "context_compaction": {},
}
_ITEM_OPTIONAL = {
    "message": {"phase": str},
    "reasoning": {"content": list, "encrypted_content": str},
    "function_call": {"namespace": str, "encrypted_function_args": list},
    "custom_tool_call": {"status": str, "namespace": str},
    "custom_tool_call_output": {"name": str},
    "local_shell_call": {"call_id": str},
    "tool_search_call": {"call_id": str, "status": str},
    "tool_search_output": {"call_id": str},
    "web_search_call": {"status": str, "action": dict},
    "image_generation_call": {"revised_prompt": str},
    "context_compaction": {"encrypted_content": str},
}


def prepare_for_history(item, turn_id):
    """Session::prepare_conversation_items_for_history identity/turn boundary."""
    item = copy.deepcopy(item)
    kind = item.get("type")
    if kind in _ITEM_FIELDS:
        if turn_id and kind != "additional_tools":
            metadata = item.get("internal_chat_message_metadata_passthrough") or {}
            if not metadata.get("turn_id"):
                metadata["turn_id"] = turn_id
            item["internal_chat_message_metadata_passthrough"] = metadata
        if not item.get("id"):
            item["id"] = _ITEM_ID_PREFIXES[kind] + "_" + str(uuid4())
    return item


class History:
    def __init__(self, model: Model):
        self.model = model
        self.items = []
        self.usage = dict.fromkeys(_TOKEN_FIELDS, 0)
        self.last_usage = dict.fromkeys(_TOKEN_FIELDS, 0)
        self.server_reasoning_included = False

    def append(self, item):
        # ContextManager::record_items / process_item. Parsing into the Rust
        # ResponseItem enum also drops extra server-only JSON fields.
        item = canonical_item(item)
        if item is None or (item["type"] == "message" and item["role"] == "system"):
            return
        item = prepare_item(item)
        if item["type"] in {"function_call_output", "custom_tool_call_output"}:
            policy = self.model.info["truncation_policy"]
            limit = math.ceil(policy["limit"] * 1.2)
            item["output"] = _truncate_output(item["output"], policy["mode"], limit)
        self.items.append(item)

    def add_usage(self, usage):
        # TokenUsageInfo::append_last_usage / TokenUsage::add_assign. Provider
        # rollout-budget units are per response and are not summed upstream.
        if not usage:
            return
        self.last_usage = {key: usage.get(key, 0) for key in _TOKEN_FIELDS}
        for key in _TOKEN_FIELDS:
            self.usage[key] += self.last_usage[key]

    def set_usage_full(self):
        # Session::set_total_tokens_full / TokenUsageInfo::fill_to_context_window.
        window = self.model.info.get("context_window") or self.model.info.get(
            "max_context_window"
        )
        if window is None:
            return
        window = window * self.model.info["effective_context_window_percent"] // 100
        delta = max(0, window - self.usage["total_tokens"])
        self.usage = dict.fromkeys(_TOKEN_FIELDS, 0)
        self.usage["total_tokens"] = window
        self.last_usage = dict.fromkeys(_TOKEN_FIELDS, 0)
        self.last_usage["total_tokens"] = delta

    def input_items(self):
        # ContextManager::for_prompt normalizes a clone, leaving durable history
        # untouched. All calls need outputs; orphan outputs are removed.
        items = copy.deepcopy(self.items)
        outputs = {
            kind: {i.get("call_id") for i in items if i["type"] == kind}
            for kind in (
                "function_call_output",
                "custom_tool_call_output",
                "tool_search_output",
            )
        }
        normalized = []
        for item in items:
            normalized.append(item)
            kind = item["type"]
            call_id = item.get("call_id")
            if kind in {"function_call", "local_shell_call"}:
                output_type, prefix = "function_call_output", "fco"
            elif kind == "custom_tool_call":
                output_type, prefix = "custom_tool_call_output", "ctco"
            elif kind == "tool_search_call":
                output_type, prefix = "tool_search_output", "tso"
            else:
                continue
            if call_id is None or call_id in outputs[output_type]:
                continue
            synthetic = {"type": output_type, "call_id": call_id}
            if item.get("id"):
                synthetic["id"] = (
                    prefix
                    + "_"
                    + str(uuid5(_SYNTHETIC_NAMESPACE, prefix + ":" + item["id"]))
                )
            if kind == "tool_search_call":
                synthetic.update(status="completed", execution="client", tools=[])
            else:
                synthetic["output"] = "aborted"
            normalized.append(synthetic)
        calls = {
            "function_call_output": {
                i.get("call_id")
                for i in items
                if i["type"] in {"function_call", "local_shell_call"}
            },
            "custom_tool_call_output": {
                i.get("call_id") for i in items if i["type"] == "custom_tool_call"
            },
            "tool_search_output": {
                i.get("call_id") for i in items if i["type"] == "tool_search_call"
            },
        }
        normalized = [
            i
            for i in normalized
            if i["type"] not in calls
            or i.get("call_id") in calls[i["type"]]
            or (
                i["type"] == "tool_search_output"
                and (i.get("call_id") is None or i.get("execution") == "server")
            )
        ]
        modalities = self.model.info["input_modalities"]
        for item in normalized:
            content = (
                item.get("content") if item["type"] == "message" else item.get("output")
            )
            if isinstance(content, list):
                for index, part in enumerate(content):
                    media = {"input_image": "image", "input_audio": "audio"}.get(
                        part.get("type")
                    )
                    if media is not None and media not in modalities:
                        content[index] = {
                            "type": "input_text",
                            "text": f"{media} content omitted because you do not support {media} input",
                        }
            if item["type"] == "image_generation_call" and "image" not in modalities:
                item["result"] = ""
        return normalized


def canonical_item(item, *, strict=False):
    """Deserialize/project supported ResponseItem variants; malformed items drop."""
    try:
        return _canonical_item(item)
    except (TypeError, ValueError):
        if strict:
            raise
        return None


def _check_fields(value, required, optional=None):
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    for key, shape in required.items():
        if key not in value or not isinstance(value[key], shape):
            raise ValueError(f"invalid required field {key}")
    for key, shape in (optional or {}).items():
        if value.get(key) is not None and not isinstance(value[key], shape):
            raise ValueError(f"invalid optional field {key}")


def _canonical_item(item):
    if not isinstance(item, dict):
        return None
    kind = item.get("type")
    if kind == "compaction_summary":
        kind = "compaction"
    if not isinstance(kind, str) or kind not in _ITEM_FIELDS:
        return None
    _check_fields(item, _ITEM_REQUIRED[kind], _ITEM_OPTIONAL.get(kind))
    _check_fields(item, {}, {"id": str})
    keys = ("id", "internal_chat_message_metadata_passthrough", *_ITEM_FIELDS[kind])
    result = {
        "type": kind,
        **{k: copy.deepcopy(item[k]) for k in keys if item.get(k) is not None},
    }
    metadata = result.get("internal_chat_message_metadata_passthrough")
    if kind == "additional_tools":
        result.pop("internal_chat_message_metadata_passthrough", None)
    elif metadata is not None:
        _check_fields(metadata, {}, {"turn_id": str})
        result["internal_chat_message_metadata_passthrough"] = {
            key: metadata[key] for key in ("turn_id",) if metadata.get(key) is not None
        }
    if kind == "reasoning":
        result["summary"] = [
            _text_part(part, {"summary_text"}) for part in result["summary"]
        ]
        result.setdefault("encrypted_content", None)
        content = item.get("content")
        # The upstream serde skip predicate omits a present list without any
        # reasoning_text, while absent content serializes as null.
        if content is None:
            result["content"] = None
        else:
            content = [_text_part(part, {"reasoning_text", "text"}) for part in content]
            if any(part["type"] == "reasoning_text" for part in content):
                result["content"] = content
            else:
                result.pop("content", None)
    if kind in {"message", "agent_message"}:
        allowed = (
            {"input_text", "encrypted_content"}
            if kind == "agent_message"
            else {"input_text", "output_text", "input_image", "input_audio"}
        )
        result["content"] = [_content_part(part, allowed) for part in result["content"]]
    elif kind in {"function_call_output", "custom_tool_call_output"} and isinstance(
        result.get("output"), list
    ):
        result["output"] = [
            _content_part(
                part, {"input_text", "input_image", "input_audio", "encrypted_content"}
            )
            for part in result["output"]
        ]
    if kind == "message" and result.get("phase") not in {
        None,
        "commentary",
        "final_answer",
    }:
        raise ValueError("invalid message phase")
    if kind == "function_call" and result.get("encrypted_function_args") is not None:
        if not all(
            isinstance(value, str) for value in result["encrypted_function_args"]
        ):
            raise ValueError("invalid encrypted function arguments")
    if kind == "local_shell_call":
        if result["status"] not in {"completed", "in_progress", "incomplete"}:
            raise ValueError("invalid local shell status")
        result["action"] = _shell_action(result["action"])
    elif kind == "web_search_call" and result.get("action") is not None:
        result["action"] = _web_action(result["action"])
    if kind in {"local_shell_call", "tool_search_call", "tool_search_output"}:
        result.setdefault("call_id", None)
    return result


def _text_part(part, allowed):
    _check_fields(part, {"type": str, "text": str})
    if part["type"] not in allowed:
        raise ValueError("invalid text content variant")
    return {"type": part["type"], "text": part["text"]}


def _content_part(part, allowed):
    fields = {
        "input_text": ("text",),
        "output_text": ("text",),
        "input_image": ("image_url", "detail"),
        "input_audio": ("audio_url",),
        "encrypted_content": ("encrypted_content",),
    }
    _check_fields(part, {"type": str})
    kind = part["type"]
    if kind not in allowed:
        raise ValueError("invalid content variant")
    _check_fields(part, {fields[kind][0]: str})
    if kind == "input_image" and part.get("detail") is not None:
        if part["detail"] not in {"auto", "low", "high", "original"}:
            raise ValueError("invalid image detail")
    return {
        "type": part["type"],
        **{
            key: copy.deepcopy(part[key])
            for key in fields[part["type"]]
            if part.get(key) is not None
        },
    }


def _shell_action(action):
    _check_fields(
        action,
        {"type": str, "command": list},
        {"timeout_ms": int, "working_directory": str, "env": dict, "user": str},
    )
    if action["type"] != "exec" or not all(
        isinstance(v, str) for v in action["command"]
    ):
        raise ValueError("invalid shell action")
    timeout = action.get("timeout_ms")
    if timeout is not None and (
        type(timeout) is not int or not 0 <= timeout <= 2**64 - 1
    ):
        raise ValueError("invalid shell timeout")
    env = action.get("env")
    if env is not None and not all(isinstance(v, str) for v in env.values()):
        raise ValueError("invalid shell environment")
    return {
        "type": "exec",
        **{
            key: copy.deepcopy(action.get(key))
            for key in ("command", "timeout_ms", "working_directory", "env", "user")
        },
    }


def _web_action(action):
    _check_fields(action, {"type": str})
    fields = {
        "search": {"query": str, "queries": list},
        "open_page": {"url": str},
        "find_in_page": {"url": str, "pattern": str},
    }
    kind = action["type"]
    if kind not in fields:
        return {"type": "other"}
    _check_fields(action, {}, fields[kind])
    if kind == "search" and action.get("queries") is not None:
        if not all(isinstance(v, str) for v in action["queries"]):
            raise ValueError("invalid web queries")
    return {
        "type": kind,
        **{
            key: copy.deepcopy(action[key])
            for key in fields[kind]
            if action.get(key) is not None
        },
    }


def _truncate_output(output, mode, limit):
    if isinstance(output, str):
        return truncate_text(output, mode, limit)
    remaining = limit
    result, omitted = [], 0
    for part in output:
        if part["type"] == "input_text":
            if remaining == 0:
                omitted += 1
                continue
            cost = len(part["text"].encode())
            if mode == "tokens":
                cost = (cost + 3) // 4
            result.append(
                {
                    "type": "input_text",
                    "text": truncate_text(part["text"], mode, remaining),
                }
            )
            remaining = max(0, remaining - cost)
        elif part["type"] == "input_audio":
            # Upstream charges duration-dependent audio tokens. No fake byte
            # estimator: audio decoding/token accounting has not been ported.
            raise ValueError(
                "Codex Python core does not yet support audio tool-output token accounting"
            )
        else:
            result.append(part)
    if omitted:
        result.append(
            {"type": "input_text", "text": f"[omitted {omitted} text items ...]"}
        )
    return result


def truncate_text(text, mode, limit):
    """utils/string/truncate.rs::truncate_with_byte_estimate, UTF-8 boundaries."""
    data = text.encode()
    budget = limit * 4 if mode == "tokens" else limit
    if not text or (budget > 0 and len(data) <= budget):
        return text
    left_budget, right_budget = budget // 2, budget - budget // 2
    left = data[:left_budget].decode(errors="ignore")
    right = (
        data[len(data) - right_budget :].decode(errors="ignore") if right_budget else ""
    )
    removed = (
        (max(0, len(data) - budget) + 3) // 4
        if mode == "tokens"
        else len(text) - len(left) - len(right)
    )
    return (
        left
        + f"…{removed} {'tokens' if mode == 'tokens' else 'chars'} truncated…"
        + right
    )
