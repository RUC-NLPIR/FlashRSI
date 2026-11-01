"""Incremental Anthropic message events, ported from pinned Pi v1.4.0.

The HTTP/SSE reader owns framing and cancellation. This state machine consumes
decoded provider events and emits independent snapshots of Pi provider events.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .anthropic_messages import normalize_anthropic_usage
from .compaction import js_json
from .openai_tools import current_tools
from .stream_json import parse_streaming_json, parse_tool_arguments


class AnthropicStream:
    def __init__(
        self,
        config: Mapping[str, Any],
        context,
        managed_effort: str | None = None,
        *,
        timestamp: int = 0,
        diagnostics: list[dict[str, Any]] | None = None,
    ):
        self.config = config
        llm = config.get("llm", {})
        name = str(llm.get("model_name", "")).strip()
        provider, model = (
            name.split("/", 1)
            if "/" in name
            else (str(llm.get("provider_name", "")), name)
        )
        self.message: dict[str, Any] = {
            "role": "assistant",
            "content": [],
            "api": "anthropic-messages",
            "provider": provider.strip().lower(),
            "model": model.strip(),
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
            "timestamp": timestamp,
        }
        if managed_effort:
            self.message["providerThinkingLevel"] = managed_effort
        if diagnostics:
            self.message["diagnostics"] = copy.deepcopy(diagnostics)
        self.events: list[dict[str, Any]] = []
        self._queued: list[dict[str, Any]] = []
        self._started = self._done = self._saw_start = self._saw_stop = False
        self._response_model = self.message["model"]
        self._raw_usage: dict[str, Any] = {}
        self._transformations = None
        self._oauth = "sk-ant-oat" in str(llm.get("api_key", ""))
        self._tools = current_tools(context)

    def _emit(self, kind, **values):
        event = copy.deepcopy({"type": kind, **values})
        self.events.append(event)
        return [event]

    def start(self) -> list[dict[str, Any]]:
        if self._started or self._done:
            return []
        self._started = True
        return self._emit("start", partial=self.message)

    def _usage(self):
        self.message["usage"] = normalize_anthropic_usage(
            self._raw_usage, self.config, response_model=self._response_model
        )

    def _block(self, provider_index):
        return next(
            (
                (index, block)
                for index, block in enumerate(self.message["content"])
                if block.get("index") == provider_index and "index" in block
            ),
            (None, None),
        )

    def feed(self, event: Mapping[str, Any]) -> list[dict[str, Any]]:
        if self._done:
            return []
        result = self.start()
        kind = event.get("type")
        if kind == "error":
            return result + self.fail(event.get("_raw_data", js_json(dict(event))))
        if kind == "message_start":
            self._saw_start = True
            message = event["message"]
            self.message["responseId"] = message["id"]
            transformations = message.get("input_transformations")
            if isinstance(transformations, list):
                self._transformations = transformations
            self._response_model = message.get("model")
            if self._response_model != self.message["model"]:
                self.message["responseModel"] = self._response_model
            raw = message.get("usage") or {}
            self._raw_usage = {
                key: raw.get(key) or 0
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                )
            }
            self._raw_usage["cache_creation"] = {
                "ephemeral_1h_input_tokens": (raw.get("cache_creation") or {}).get(
                    "ephemeral_1h_input_tokens"
                )
                or 0
            }
            # Initial thinking_tokens are deliberately ignored by upstream.
            self._usage()
        elif kind == "message_stop":
            self._saw_stop = True
        elif kind == "content_block_start":
            original = event["content_block"]
            block_kind = original.get("type")
            if block_kind == "fallback":
                if self.message["content"]:
                    return result + self.fail(
                        "Anthropic performed an unsupported mid-output model fallback"
                    )
                return result
            if block_kind == "text":
                block = {"type": "text", "text": original.get("text") or ""}
                emitted = "text_start"
            elif block_kind == "thinking":
                block = {
                    "type": "thinking",
                    "thinking": original.get("thinking") or "",
                    "thinkingSignature": original.get("signature") or "",
                }
                emitted = "thinking_start"
            elif block_kind == "redacted_thinking":
                block = {
                    "type": "thinking",
                    "thinking": "[Reasoning redacted]",
                    "thinkingSignature": original.get("data"),
                    "redacted": True,
                }
                emitted = "thinking_start"
            elif block_kind == "tool_use":
                name = original["name"]
                if self._oauth:
                    name = next(
                        (
                            tool["name"]
                            for tool in self._tools
                            if tool["name"].lower() == name.lower()
                        ),
                        name,
                    )
                block = {
                    "type": "toolCall",
                    "id": original["id"],
                    "name": name,
                    "arguments": copy.deepcopy(original.get("input"))
                    if original.get("input") is not None
                    else {},
                    "partialJson": "",
                }
                emitted = "toolcall_start"
            else:
                return result
            block["index"] = event["index"]
            self.message["content"].append(block)
            return result + self._emit(
                emitted,
                contentIndex=len(self.message["content"]) - 1,
                partial=self.message,
            )
        elif kind == "content_block_delta":
            index, block = self._block(event.get("index"))
            if block is None:
                return result
            delta = event.get("delta") or {}
            delta_kind = delta.get("type")
            if delta_kind == "text_delta" and block["type"] == "text":
                value = delta["text"]
                block["text"] += value
                emitted = "text_delta"
            elif delta_kind == "thinking_delta" and block["type"] == "thinking":
                value = delta["thinking"]
                block["thinking"] += value
                emitted = "thinking_delta"
            elif delta_kind == "input_json_delta" and block["type"] == "toolCall":
                value = delta["partial_json"]
                block["partialJson"] += value
                block["arguments"] = parse_streaming_json(block["partialJson"])
                emitted = "toolcall_delta"
            elif delta_kind == "signature_delta" and block["type"] == "thinking":
                block["thinkingSignature"] = (
                    block.get("thinkingSignature") or ""
                ) + delta["signature"]
                return result
            else:
                return result
            return result + self._emit(
                emitted, contentIndex=index, delta=value, partial=self.message
            )
        elif kind == "content_block_stop":
            index, block = self._block(event.get("index"))
            if block is None:
                return result
            block.pop("index", None)
            if block["type"] == "toolCall":
                block.update(parse_tool_arguments(block.pop("partialJson")))
                return result + self._emit(
                    "toolcall_end",
                    contentIndex=index,
                    toolCall=block,
                    partial=self.message,
                )
            field = "text" if block["type"] == "text" else "thinking"
            return result + self._emit(
                f"{field}_end",
                contentIndex=index,
                content=block[field],
                partial=self.message,
            )
        elif kind == "message_delta":
            transformations = event.get("input_transformations")
            if isinstance(transformations, list):
                self._transformations = transformations
            delta = event.get("delta") or {}
            reason = delta.get("stop_reason")
            if reason:
                self.message["rawStopReason"] = reason
                mapped = {
                    "end_turn": "stop",
                    "max_tokens": "length",
                    "tool_use": "toolUse",
                    "pause_turn": "stop",
                    "stop_sequence": "stop",
                    "refusal": "error",
                    "sensitive": "error",
                }.get(reason)
                if mapped is None:
                    return result + self.fail(f"Unhandled stop reason: {reason}")
                self.message["stopReason"] = mapped
                if reason == "refusal":
                    self.message["errorMessage"] = (
                        delta.get("stop_details") or {}
                    ).get("explanation") or "The model refused to complete the request"
                elif reason == "sensitive":
                    self.message["errorMessage"] = "Provider stopped with: sensitive"
            raw = event.get("usage") or {}
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                if raw.get(key) is not None:
                    self._raw_usage[key] = raw[key]
            one_hour = (raw.get("cache_creation") or {}).get(
                "ephemeral_1h_input_tokens"
            )
            if one_hour is not None:
                self._raw_usage["cache_creation"] = {
                    "ephemeral_1h_input_tokens": one_hour
                }
            reasoning = (raw.get("output_tokens_details") or {}).get("thinking_tokens")
            if reasoning is not None:
                self._raw_usage["output_tokens_details"] = {
                    "thinking_tokens": reasoning
                }
            self._usage()
        return result

    def _terminate(self, error: str, reason: str) -> list[dict[str, Any]]:
        if self._done:
            return []
        for block in self.message["content"]:
            block.pop("index", None)
            block.pop("partialJson", None)
        self.message.update(stopReason=reason, errorMessage=str(error))
        self._done = True
        return self._emit("error", reason=reason, error=self.message)

    def abort(self, error: str = "Request aborted") -> list[dict[str, Any]]:
        return self._terminate(error, "aborted")

    def fail(self, error: str) -> list[dict[str, Any]]:
        return self._terminate(error, "error")

    def finish(self) -> dict[str, Any]:
        if not self._done:
            if self._saw_start and not self._saw_stop:
                terminal = self.fail("Anthropic stream ended before message_stop")
            elif self.message["stopReason"] == "pending":
                terminal = self.fail("Anthropic stream ended without a stop reason")
            elif self.message["stopReason"] in {"aborted", "error"}:
                terminal = self.fail(
                    self.message.get("errorMessage") or "An unknown error occurred"
                )
            else:
                if self._transformations:
                    self.message.setdefault("diagnostics", []).append(
                        {
                            "type": "anthropic_input_transformations",
                            "timestamp": self.message["timestamp"],
                            "details": {
                                "transformations": [
                                    {
                                        key: item[key]
                                        for key in ("type", "path", "reason")
                                        if item.get(key) is not None
                                    }
                                    for item in self._transformations
                                ]
                            },
                        }
                    )
                self._done = True
                terminal = self._emit(
                    "done", reason=self.message["stopReason"], message=self.message
                )
            self._queued.extend(terminal)
        result = copy.deepcopy(self.message)
        result.pop("timestamp", None)
        result.pop("durationMs", None)
        return result

    def drain(self) -> list[dict[str, Any]]:
        result, self._queued = self._queued, []
        return result
