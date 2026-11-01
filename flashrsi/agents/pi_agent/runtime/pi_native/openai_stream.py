"""Incremental Pi v1.4.0 OpenAI provider event state machines.

This module consumes decoded SSE objects, without an SDK or Node process. The
transport owns framing, HTTP errors and timing; semantic events are independent
snapshots, including the source's temporary argument buffers while streaming.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from .compaction import js_json
from .openai_options import apply_service_tier_pricing
from .openai_provider import compat_options, selected_model
from .openai_tools import append_grammar_delta, declared_tools, grammar_properties
from .stream_json import parse_streaming_json, parse_tool_arguments


class OpenAIStream:
    """Stateful source port for one Chat Completions or Responses reply.

    feed returns newly emitted events. At EOF, finish returns the canonical
    assistant; drain then returns EOF block-end and done/error events. abort
    preserves the partial assistant and returns its terminal error event.
    """

    def __init__(self, config, api, context, managed_effort=None):
        self.config, self.api = config, api
        self.model = selected_model(config, api)
        self.compat = compat_options(self.model, api)
        self.grammar = grammar_properties(declared_tools(context), self.compat)
        self.message: dict[str, Any] = {
            "role": "assistant",
            "content": [],
            "api": api,
            "provider": self.model["provider"],
            "model": self.model["id"],
            **(
                {"providerThinkingLevel": managed_effort}
                if managed_effort is not None
                else {}
            ),
            "usage": {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
                "totalTokens": 0,
                "cost": {
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "total": 0,
                },
            },
            "stopReason": "pending",
        }
        self.events, self._pending = [], []
        self._started = self._closed = self._terminal = self._has_finish = False
        self._text = self._thinking = None
        self._details = None
        self._tools_by_index, self._tools_by_id = {}, {}
        self._slots, self._reasoning_ids = {}, {}

    def _emit(self, kind, **fields):
        event = {"type": kind, **fields}
        if kind not in {"done", "error"}:
            event["partial"] = self.message
        snapshot = copy.deepcopy(event)
        self.events.append(snapshot)
        self._pending.append(snapshot)

    def _start(self):
        if not self._started:
            self._started = True
            self._emit("start")

    def drain(self):
        events, self._pending = self._pending, []
        return events

    def start(self):
        if not self._closed:
            self._start()
        return self.drain()

    def fail(self, error):
        if not self._closed:
            self._start()
            self._fail(str(error))
        return self.drain()

    def feed(self, event):
        if self._closed:
            return []
        self._start()
        try:
            if self.api == "openai-completions":
                self._chat(event)
            else:
                self._responses(event)
        except (ValueError, TypeError, KeyError) as exc:
            self._fail(str(exc))
        return self.drain()

    def _index(self, block):
        return next(
            index
            for index, value in enumerate(self.message["content"])
            if value is block
        )

    def _new_block(self, block):
        self.message["content"].append(block)
        kind = {"text": "text", "thinking": "thinking", "toolCall": "toolcall"}[
            block["type"]
        ]
        self._emit(kind + "_start", contentIndex=self._index(block))
        return block

    def _thinking_block(self, signature):
        if self._thinking is None:
            self._thinking = self._new_block(
                {"type": "thinking", "thinking": "", "thinkingSignature": signature}
            )
        return self._thinking

    def _custom_append(self, block, next_input, close):
        custom = block["customInput"]
        delta = append_grammar_delta(
            custom["jsonBuffer"], custom["property"], next_input, close
        )
        block["arguments"] = {custom["property"]: next_input}
        return delta

    def _custom_value(self, block):
        value = block["arguments"].get(block["customInput"]["property"])
        return value if isinstance(value, str) else ""

    def _chat_tool(self, item):
        index = item.get("index")
        function = item.get("function") or {}
        custom = item.get("custom") or {}
        has_custom = item.get("custom") is not None
        has_function = item.get("function") is not None
        name = function.get("name")
        if name is None:
            name = custom.get("name") or ""
        block = (
            self._tools_by_index.get(index) if isinstance(index, (int, float)) else None
        )
        if block is None and item.get("id"):
            block = self._tools_by_id.get(item["id"])
        if block is None:
            block = {
                "type": "toolCall",
                "id": item.get("id") or "",
                "name": name,
                "arguments": {},
            }
            if has_custom and not has_function:
                prop = self.grammar.get(name, "input")
                block["arguments"] = {prop: ""}
                block["customInput"] = {
                    "property": prop,
                    "jsonBuffer": {"input": "", "started": False, "closed": False},
                }
            else:
                block["partialArgs"] = ""
            if isinstance(index, (int, float)):
                block["streamIndex"] = index
                self._tools_by_index[index] = block
            if item.get("id"):
                self._tools_by_id[item["id"]] = block
            self._new_block(block)
        if isinstance(index, (int, float)) and "streamIndex" not in block:
            block["streamIndex"] = index
            self._tools_by_index[index] = block
        if item.get("id"):
            self._tools_by_id[item["id"]] = block
            if not block["id"]:
                block["id"] = item["id"]
        if not block["name"] and name:
            block["name"] = name
        if has_custom and not has_function and "customInput" not in block:
            prop = self.grammar.get(block["name"], "input")
            block["arguments"] = {prop: ""}
            block["customInput"] = {
                "property": prop,
                "jsonBuffer": {"input": "", "started": False, "closed": False},
            }
            block.pop("partialArgs", None)
        delta = ""
        if function.get("arguments"):
            delta = function["arguments"]
            block["partialArgs"] = block.get("partialArgs", "") + delta
            block["arguments"] = parse_streaming_json(block["partialArgs"])
        elif custom.get("input"):
            delta = (
                self._custom_append(
                    block, self._custom_value(block) + custom["input"], False
                )
                or ""
            )
        self._emit("toolcall_delta", contentIndex=self._index(block), delta=delta)

    def _chat(self, event):
        if not isinstance(event, dict):
            return
        if event.get("error"):
            error = event["error"]
            raise ValueError(
                error.get("message", js_json(error))
                if isinstance(error, dict)
                else str(error)
            )
        if not self.message.get("responseId") and event.get("id") is not None:
            self.message["responseId"] = event["id"]
        model = event.get("model")
        if isinstance(model, str) and model and model != self.model["id"]:
            self.message.setdefault("responseModel", model)
        choice = (event.get("choices") or [None])[0]
        usage = event.get("usage") or (choice or {}).get("usage")
        if usage is not None:
            self.message["usage"] = self._usage(usage)
        if choice is None:
            return
        reason = choice.get("finish_reason")
        if reason:
            self._has_finish = True
            self.message["rawStopReason"] = reason
            stop = {
                "stop": "stop",
                "end": "stop",
                "length": "length",
                "function_call": "toolUse",
                "tool_calls": "toolUse",
            }.get(reason, "error")
            self.message["stopReason"] = stop
            if stop == "error":
                self.message["errorMessage"] = f"Provider finish_reason: {reason}"
        delta = choice.get("delta") or {}
        for field in ("reasoning_content", "reasoning", "reasoning_text"):
            value = delta.get(field)
            if isinstance(value, str) and value:
                signature = (
                    "reasoning_content"
                    if self.model["provider"] == "opencode-go" and field == "reasoning"
                    else field
                )
                block = self._thinking_block(signature)
                block["thinking"] += value
                self._emit(
                    "thinking_delta", contentIndex=self._index(block), delta=value
                )
                break
        for detail in delta.get("reasoning_details") or []:
            if not isinstance(detail, dict):
                continue
            field = {
                "reasoning.text": "text",
                "reasoning.summary": "summary",
                "reasoning.encrypted": "data",
            }.get(detail.get("type"))
            if field is None or not isinstance(detail.get(field), str):
                continue
            if detail.get("id") is not None and not isinstance(detail["id"], str):
                continue
            if "format" in detail and not isinstance(detail["format"], str):
                continue
            if "index" in detail and (
                isinstance(detail["index"], bool)
                or not isinstance(detail["index"], (int, float))
            ):
                continue
            if (
                field == "text"
                and detail.get("signature") is not None
                and not isinstance(detail["signature"], str)
            ):
                continue
            self._thinking_block("")
            if self._details is None:
                self._details = []
            previous = self._details[-1] if self._details else None
            if (
                previous
                and detail["type"] == previous["type"]
                and field in {"text", "summary"}
            ):
                previous[field] += detail[field]
                for key in ("signature", "format") if field == "text" else ("format",):
                    if not previous.get(key):
                        if key in detail:
                            previous[key] = detail[key]
                        else:
                            previous.pop(key, None)
                for key in ("id", "index"):
                    if previous.get(key) is None:
                        if key in detail:
                            previous[key] = detail[key]
                        else:
                            previous.pop(key, None)
            else:
                self._details.append(copy.deepcopy(detail))
        if delta.get("content"):
            if self._text is None:
                self._text = self._new_block({"type": "text", "text": ""})
            self._text["text"] += delta["content"]
            self._emit(
                "text_delta",
                contentIndex=self._index(self._text),
                delta=delta["content"],
            )
        for item in delta.get("tool_calls") or []:
            self._chat_tool(item)

    def _create_slot(self, index, item):
        kind = item.get("type")
        if kind == "reasoning":
            block = {"type": "thinking", "thinking": ""}
        elif kind == "message":
            if item.get("phase") == "final_answer":
                self.message["stopReason"] = "stop"
            block = {"type": "text", "text": ""}
        elif kind in {"function_call", "custom_tool_call"}:
            block = {
                "type": "toolCall",
                "id": f"{item.get('call_id', 'undefined')}|{item.get('id', 'undefined')}",
                "name": item["name"],
                "arguments": {},
            }
            if "namespace" in item:
                block["namespace"] = item["namespace"]
            if kind == "function_call":
                block["partialJson"] = item.get("arguments") or ""
            else:
                prop = self.grammar.get(item["name"], "input")
                block["arguments"] = {prop: item.get("input") or ""}
                block["customInput"] = {
                    "property": prop,
                    "jsonBuffer": {"input": "", "started": False, "closed": False},
                }
        else:
            return None
        self._new_block(block)
        self._slots[index] = block
        return block

    def _tool_delta(self, block, delta):
        if delta is not None:
            self._emit("toolcall_delta", contentIndex=self._index(block), delta=delta)

    def _responses(self, event):
        kind, index = event.get("type"), event.get("output_index")
        block = self._slots.get(index)
        if kind == "response.created":
            self.message["responseId"] = event["response"]["id"]
        elif kind == "response.output_item.added":
            self._create_slot(index, event["item"])
        elif kind in {
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
            "response.reasoning_summary_part.done",
        }:
            if block is not None and block["type"] == "thinking":
                delta = "\n\n" if kind.endswith("part.done") else event["delta"]
                block["thinking"] += delta
                self._emit(
                    "thinking_delta", contentIndex=self._index(block), delta=delta
                )
        elif kind in {"response.output_text.delta", "response.refusal.delta"}:
            if block is not None and block["type"] == "text":
                block["text"] += event["delta"]
                self._emit(
                    "text_delta", contentIndex=self._index(block), delta=event["delta"]
                )
        elif kind in {
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        }:
            if block is not None and "partialJson" in block:
                previous = block["partialJson"]
                value = (
                    event["arguments"]
                    if kind.endswith(".done")
                    else previous + event["delta"]
                )
                block["partialJson"] = value
                block["arguments"] = parse_streaming_json(value)
                if kind.endswith(".delta"):
                    self._tool_delta(block, event["delta"])
                elif value.startswith(previous) and len(value) > len(previous):
                    self._tool_delta(block, value[len(previous) :])
        elif kind in {
            "response.custom_tool_call_input.delta",
            "response.custom_tool_call_input.done",
        }:
            if block is not None and "customInput" in block:
                close = kind.endswith(".done")
                value = (
                    event["input"]
                    if close
                    else self._custom_value(block) + event["delta"]
                )
                self._tool_delta(block, self._custom_append(block, value, close))
        elif kind == "response.output_item.done":
            item = event["item"]
            if item.get("type") == "message" and item.get("phase") == "final_answer":
                self.message["stopReason"] = "stop"
            block = block if block is not None else self._create_slot(index, item)
            if block is None:
                return
            if item["type"] == "reasoning" and block["type"] == "thinking":
                summary = "\n\n".join(
                    part.get("text", "") for part in item.get("summary") or []
                )
                content = "\n\n".join(
                    part.get("text", "") for part in item.get("content") or []
                )
                block["thinking"] = summary or content or block["thinking"]
                block["thinkingSignature"] = js_json(item)
                self._reasoning_ids[item["id"]] = block
                self._emit(
                    "thinking_end",
                    contentIndex=self._index(block),
                    content=block["thinking"],
                )
            elif item["type"] == "message" and block["type"] == "text":
                block["text"] = "".join(
                    part.get("text", "")
                    if part["type"] == "output_text"
                    else part.get("refusal", "")
                    for part in item.get("content") or []
                )
                signature = {"v": 1}
                if "id" in item:
                    signature["id"] = item["id"]
                if item.get("phase"):
                    signature["phase"] = item["phase"]
                block["textSignature"] = js_json(signature)
                self._emit(
                    "text_end", contentIndex=self._index(block), content=block["text"]
                )
            elif item["type"] == "function_call" and "partialJson" in block:
                self._final_arguments(
                    block, item.get("arguments") or block["partialJson"]
                )
                if "namespace" in item:
                    block["namespace"] = item["namespace"]
                block.pop("partialJson", None)
                self._emit(
                    "toolcall_end", contentIndex=self._index(block), toolCall=block
                )
            elif item["type"] == "custom_tool_call" and "customInput" in block:
                self._tool_delta(
                    block,
                    self._custom_append(
                        block, item.get("input", self._custom_value(block)), True
                    ),
                )
                if "namespace" in item:
                    block["namespace"] = item["namespace"]
                block.pop("customInput", None)
                self._emit(
                    "toolcall_end", contentIndex=self._index(block), toolCall=block
                )
            else:
                return
            self._slots.pop(index, None)
        elif kind in {"response.completed", "response.incomplete"}:
            self._terminal_response(event["response"])
        elif kind == "error":
            raise ValueError(
                f"Error Code {event.get('code', 'undefined')}: {event.get('message', 'undefined')}"
            )
        elif kind == "response.failed":
            self._terminal = True
            response = event.get("response") or {}
            if "status" in response:
                self.message["rawStopReason"] = response["status"]
            error, details = (
                response.get("error"),
                response.get("incomplete_details") or {},
            )
            text = (
                f"{error.get('code') or 'unknown'}: {error.get('message') or 'no message'}"
                if error
                else (
                    f"incomplete: {details['reason']}"
                    if details.get("reason")
                    else "Unknown error (no error details in response)"
                )
            )
            raise ValueError(text)

    def _terminal_response(self, response):
        self._terminal = True
        for item in response.get("output") or []:
            if item.get("type") != "reasoning" or not item.get("encrypted_content"):
                continue
            block = self._reasoning_ids.get(item.get("id"))
            if block is not None and block.get("thinkingSignature"):
                stored = json.loads(block["thinkingSignature"])
                if not stored.get("encrypted_content"):
                    stored["encrypted_content"] = item["encrypted_content"]
                    block["thinkingSignature"] = js_json(stored)
        if response.get("id"):
            self.message["responseId"] = response["id"]
        if response.get("usage") is not None:
            self.message["usage"] = self._usage(response["usage"])
        else:
            self._cost(self.message["usage"])
        apply_service_tier_pricing(
            self.message["usage"], self.model["id"], response.get("service_tier")
        )
        status = response.get("status")
        reason = (response.get("incomplete_details") or {}).get("reason")
        reason = reason if isinstance(reason, str) else None
        if status is not None:
            self.message["rawStopReason"] = f"{status}.{reason}" if reason else status
        if not status or status in {"completed", "in_progress", "queued"}:
            self.message["stopReason"] = (
                "toolUse"
                if any(b["type"] == "toolCall" for b in self.message["content"])
                else "stop"
            )
            self.message.pop("errorMessage", None)
        elif status == "incomplete":
            self.message["stopReason"] = (
                "length" if reason == "max_output_tokens" else "error"
            )
            if reason != "max_output_tokens":
                self.message["errorMessage"] = (
                    f"Response incomplete: {reason}"
                    if reason
                    else "Response incomplete without a provider reason"
                )
        elif status in {"failed", "cancelled"}:
            self.message["stopReason"] = "error"
            self.message.pop("errorMessage", None)
        else:
            raise ValueError(f"Unhandled stop reason: {status}")

    def _final_arguments(self, block, value):
        block.update(parse_tool_arguments(value))

    def _cost(self, usage):
        rates = self.model.get("cost") or {}
        tokens = usage["input"] + usage["cacheRead"] + usage["cacheWrite"]
        threshold = -1
        for tier in rates.get("tiers", []):
            if tokens > tier["inputTokensAbove"] > threshold:
                threshold, rates = tier["inputTokensAbove"], tier
        cost = {
            key: rates.get(key, 0) / 1000000 * usage[key]
            for key in ("input", "output", "cacheRead", "cacheWrite")
        }
        cost["total"] = (
            cost["input"] + cost["output"] + cost["cacheRead"] + cost["cacheWrite"]
        )
        usage["cost"] = cost
        return usage

    def _usage(self, raw):
        chat = self.api == "openai-completions"
        prefix = "prompt" if chat else "input"
        output_prefix = "completion" if chat else "output"
        details = raw.get(prefix + "_tokens_details") or {}
        cached = details.get("cached_tokens")
        if chat:
            if cached is None:
                cached = raw.get("prompt_cache_hit_tokens")
            if cached is None:
                cached = raw.get("cached_tokens")
        cached = cached or 0
        written = details.get("cache_write_tokens") or 0
        prompt, output = (
            raw.get(prefix + "_tokens") or 0,
            raw.get(output_prefix + "_tokens") or 0,
        )
        input_tokens = max(0, prompt - cached - written)
        return self._cost(
            {
                "input": input_tokens,
                "output": output,
                "cacheRead": cached,
                "cacheWrite": written,
                "reasoning": (raw.get(output_prefix + "_tokens_details") or {}).get(
                    "reasoning_tokens"
                )
                or 0,
                "totalTokens": input_tokens + output + cached + written
                if chat
                else raw.get("total_tokens") or 0,
            }
        )

    def _cleanup(self):
        for block in self.message["content"]:
            if (
                block["type"] == "thinking"
                and self.api == "openai-completions"
                and self._details is not None
            ):
                block["thinkingSignature"] = js_json(self._details)
            for key in (
                "index",
                "partialArgs",
                "partialJson",
                "customInput",
                "streamIndex",
            ):
                block.pop(key, None)

    def _fail(self, error, *, aborted=False):
        self._cleanup()
        self.message["stopReason"] = "aborted" if aborted else "error"
        self.message["errorMessage"] = error
        self._closed = True
        self._emit("error", reason=self.message["stopReason"], error=self.message)

    def abort(self, error="Request aborted"):
        if not self._closed:
            self._start()
            self._fail(error, aborted=True)
        return self.drain()

    def finish(self):
        if self._closed:
            return copy.deepcopy(self.message)
        self._start()
        try:
            if self.api == "openai-completions":
                for block in self.message["content"]:
                    if block["type"] in {"text", "thinking"}:
                        if block["type"] == "thinking" and self._details is not None:
                            block["thinkingSignature"] = js_json(self._details)
                        self._emit(
                            block["type"] + "_end",
                            contentIndex=self._index(block),
                            content=block[
                                "text" if block["type"] == "text" else "thinking"
                            ],
                        )
                    else:
                        if "customInput" in block:
                            self._tool_delta(
                                block,
                                self._custom_append(
                                    block, self._custom_value(block), True
                                ),
                            )
                        else:
                            self._final_arguments(block, block.get("partialArgs"))
                        for key in ("partialArgs", "customInput", "streamIndex"):
                            block.pop(key, None)
                        self._emit(
                            "toolcall_end",
                            contentIndex=self._index(block),
                            toolCall=block,
                        )
                if not self._has_finish and not self.compat.get(
                    "supportsFinishReason", True
                ):
                    self.message["stopReason"] = (
                        "toolUse"
                        if any(b["type"] == "toolCall" for b in self.message["content"])
                        else "stop"
                    )
                if self.message["stopReason"] == "error":
                    raise ValueError(
                        self.message.get("errorMessage")
                        or "Provider returned an error stop reason"
                    )
                if (
                    self.compat.get("supportsFinishReason", True)
                    and not self._has_finish
                ) or self.message["stopReason"] == "pending":
                    raise ValueError("Stream ended without finish_reason")
            else:
                if not self._terminal:
                    raise ValueError(
                        "OpenAI Responses stream ended before a terminal response event"
                    )
                if self.message["stopReason"] == "toolUse":
                    for block in self.message["content"]:
                        if "partialJson" in block or "customInput" in block:
                            raise ValueError(
                                f"OpenAI Responses stream completed with an unfinished tool call: {block['name']} ({block['id']})"
                            )
                if self.message["stopReason"] == "pending":
                    raise ValueError(
                        "OpenAI Responses stream ended without a stop reason"
                    )
                if self.message["stopReason"] in {"aborted", "error"}:
                    raise ValueError(
                        self.message.get("errorMessage") or "An unknown error occurred"
                    )
            self._closed = True
            self._emit("done", reason=self.message["stopReason"], message=self.message)
        except (ValueError, TypeError, KeyError) as exc:
            self._fail(str(exc))
        return copy.deepcopy(self.message)
