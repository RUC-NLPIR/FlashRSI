"""HTTP Responses protocol port of Codex rust-v0.147.0 (be6e8eac).

The request is built from core/src/client.rs::build_responses_request rather
than OpenAI SDK defaults. Stream interpretation follows codex-api/src/sse/
responses.rs; request retry and stream retry are distinct layers upstream.
WebSockets and authenticated-account recovery are not ported.
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
import re
from uuid import uuid4

import httpx

from .history import canonical_item
from .models import Model, validate_model_settings


def _lite_tools(tools):
    """tools/tool_spec.rs::create_tools_json_for_responses_lite."""
    namespace = {
        "type": "namespace",
        "name": "functions",
        "description": "",
        "tools": [],
    }
    result, index = [], None
    for tool in copy.deepcopy(tools):
        if tool["type"] in {"function", "custom"}:
            namespace["tools"].append(tool)
        elif tool["type"] == "namespace" and tool["name"] == "functions":
            if tool.get("description", "").strip():
                namespace["description"] = tool["description"]
            namespace["tools"].extend(tool["tools"])
        else:
            result.append(tool)
            continue
        if index is None:
            index = len(result)
    if index is not None and namespace["tools"]:
        result.insert(index, namespace)
    return result


class ResponseError(RuntimeError):
    def __init__(
        self,
        message,
        *,
        code="stream",
        retryable=True,
        delay=None,
        partial_items=None,
        usage=None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.delay = delay
        self.partial_items = partial_items or []
        self.usage = usage or {}


class ResponsesClient:
    def __init__(self, llm: dict, model: Model, settings: dict, thread_id: str, emit):
        validate_model_settings(settings)
        validate_model_settings({"model_reasoning_effort": llm.get("reasoning_effort")})
        self.llm, self.model, self.settings = (
            copy.deepcopy(llm),
            model,
            copy.deepcopy(settings),
        )
        self.thread_id, self.emit = thread_id, emit
        self.provider = settings.get("model_providers", {}).get(
            settings.get("model_provider"), {}
        )
        self.base_url = (
            llm.get("base_url")
            or self.provider.get("base_url")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.url = self.base_url + "/responses"
        self.request_retries = min(self.provider.get("request_max_retries", 4), 100)
        self.stream_retries = min(self.provider.get("stream_max_retries", 5), 100)
        self.idle_timeout = self.provider.get("stream_idle_timeout_ms", 300000) / 1000
        self.turn_state = None
        self._http = None
        self._installation_id = str(uuid4())

    async def __aenter__(self):
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self.idle_timeout), follow_redirects=True
        )
        return self

    async def __aexit__(self, *exc):
        await self._http.aclose()
        self._http = None

    def request(self, items: list, tools: list, client_metadata: dict | None = None):
        """core::ModelClientSession::{build_reasoning,build_responses_request}."""
        info, settings = self.model.info, self.settings
        lite = info["use_responses_lite"]
        reasoning = {}
        effort = self.llm.get("reasoning_effort")
        if effort is None:
            effort = settings.get("model_reasoning_effort")
        if effort is None:
            effort = info.get("default_reasoning_level")
        if effort is not None:
            reasoning["effort"] = "max" if effort == "ultra" else effort
        summary = settings.get("model_reasoning_summary")
        if summary is None:
            summary = info["default_reasoning_summary"]
        if info["supports_reasoning_summary_parameter"] and summary != "none":
            reasoning["summary"] = summary
        if lite:
            reasoning["context"] = "all_turns"
        # Non-OpenAI providers must not receive internal metadata or encrypted
        # function args; this is separate from reasoning.encrypted_content.
        input_items = copy.deepcopy(items)
        for item in input_items:
            identity = item.get("id")
            if identity is not None and not re.fullmatch(
                r"[^_]+_.+", identity, re.DOTALL
            ):
                item.pop("id", None)
            if not self.is_openai:
                item.pop("internal_chat_message_metadata_passthrough", None)
                if item.get("type") == "function_call":
                    item.pop("encrypted_function_args", None)
            if lite:
                for field in ("content", "output"):
                    if isinstance(item.get(field), list):
                        for part in item[field]:
                            if part.get("type") == "input_image":
                                part.pop("detail", None)
        payload = {
            "model": info["slug"],
            "input": input_items,
            "tools": copy.deepcopy(tools),
            "tool_choice": "auto",
            "parallel_tool_calls": info["supports_parallel_tool_calls"] and not lite,
            "reasoning": reasoning,
            "store": self.provider.get("name", "").lower() == "azure"
            or any(
                marker in self.base_url.lower()
                for marker in (
                    "openai.azure.",
                    "cognitiveservices.azure.",
                    "aoai.azure.",
                    "azure-api.",
                    "azurefd.",
                    "windows.net/openai",
                )
            ),
            "stream": True,
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": settings.get("_session_id", self.thread_id),
            "client_metadata": client_metadata
            if client_metadata is not None
            else {
                "x-codex-installation-id": self._installation_id,
                "session_id": self.thread_id,
                "thread_id": self.thread_id,
                "x-codex-window-id": self.thread_id + ":0",
            },
        }
        if self.model.instructions:
            payload["instructions"] = self.model.instructions
        if lite:
            prefix = [
                {
                    "type": "additional_tools",
                    "role": "developer",
                    "tools": _lite_tools(tools)
                    if settings.get("_provider_capabilities", {}).get(
                        "namespace_tools", True
                    )
                    else copy.deepcopy(tools),
                }
            ]
            if self.model.instructions:
                prefix.append(
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [
                            {"type": "input_text", "text": self.model.instructions}
                        ],
                    }
                )
            payload["input"] = prefix + input_items
            payload.pop("instructions", None)
            payload.pop("tools", None)
        verbosity = (
            settings.get("model_verbosity") or info.get("default_verbosity")
            if info["support_verbosity"]
            else None
        )
        text = {}
        if verbosity is not None:
            text["verbosity"] = verbosity
        if settings.get("output_schema") is not None:
            text["format"] = {
                "type": "json_schema",
                "strict": settings.get("output_schema_strict", True),
                "schema": settings["output_schema"],
                "name": "codex_output_schema",
            }
        if text:
            payload["text"] = text
        service_tier = settings.get("service_tier")
        if service_tier != "default" and any(
            tier["id"] == service_tier for tier in info["service_tiers"]
        ):
            payload["service_tier"] = service_tier
        features = settings.get("features", {})
        if (
            features.get("concurrent_reasoning_summaries")
            and self.is_openai
            and "summary" in reasoning
        ):
            payload["stream_options"] = {
                "reasoning_summary_delivery": "sequential_cutoff"
            }
        return payload

    @property
    def is_openai(self):
        # ModelProviderInfo::is_openai compares the provider's display name.
        return self.provider.get("name") == "OpenAI" or (
            self.settings.get("model_provider") == "openai" and not self.provider
        )

    def _headers(self, metadata):
        headers = {
            "accept": "text/event-stream",
            "content-type": "application/json",
            "originator": "codex_exec",
            "session-id": metadata.get("session_id", self.thread_id),
            "thread-id": self.thread_id,
            "x-client-request-id": self.thread_id,
        }
        headers.update(self.provider.get("http_headers", {}))
        headers.update(self.llm.get("extra_headers", {}))
        if self.llm.get("api_key"):
            headers["authorization"] = "Bearer " + self.llm["api_key"]
        for key in (
            "x-codex-window-id",
            "x-codex-turn-metadata",
            "x-codex-parent-thread-id",
            "x-openai-subagent",
        ):
            if key in metadata:
                headers[key] = metadata[key]
        if self.turn_state is not None:
            headers["x-codex-turn-state"] = self.turn_state
        if self.model.info["use_responses_lite"]:
            headers["x-openai-internal-codex-responses-lite"] = "true"
        return headers

    async def compact_response(self, items, tools, metadata=None):
        """codex-api/endpoint/compact.rs: unary remote compaction, HTTP retries only."""
        if not items:
            return []
        if self._http is None:
            raise RuntimeError("ResponsesClient must be used with async with")
        full = self.request(items, tools, metadata)
        fields = {
            "model",
            "input",
            "instructions",
            "tools",
            "parallel_tool_calls",
            "reasoning",
            "service_tier",
            "prompt_cache_key",
            "text",
        }
        payload = {key: value for key, value in full.items() if key in fields}
        # API-key authentication does not send the account-only tier hint.
        payload.pop("service_tier", None)
        headers = self._headers(full["client_metadata"])
        headers["accept"] = "application/json"
        for attempt in range(self.request_retries + 1):
            try:
                response = await self._http.post(
                    self.base_url + "/responses/compact",
                    json=payload,
                    headers=headers,
                    params=self.provider.get("query_params"),
                    timeout=self.idle_timeout * 4,
                )
                if not 200 <= response.status_code < 300:
                    if response.status_code >= 500 and attempt < self.request_retries:
                        await asyncio.sleep(_backoff(attempt + 1))
                        continue
                    raise _http_error(response.status_code, response.text)
                self.turn_state = self.turn_state or response.headers.get(
                    "x-codex-turn-state"
                )
                try:
                    value = response.json()
                    output = value["output"]
                    if not isinstance(output, list):
                        raise ValueError("output must be an array")
                    parsed = []
                    for item in output:
                        if not isinstance(item, dict) or not isinstance(
                            item.get("type"), str
                        ):
                            raise ValueError("invalid response item")
                        projected = canonical_item(item, strict=True)
                        if projected is not None:
                            parsed.append(projected)
                        # ResponseItem::Other accepts unknown variants; the
                        # history manager subsequently excludes them.
                    return parsed
                except (KeyError, TypeError, ValueError) as error:
                    raise ResponseError(
                        "failed to parse CompactHistoryResponse: " + str(error),
                        retryable=False,
                    ) from error
            except httpx.TransportError as error:
                if attempt >= self.request_retries:
                    raise ResponseError(str(error)) from error
                await asyncio.sleep(_backoff(attempt + 1))

    async def response(
        self,
        items: list,
        tools: list,
        client_metadata: dict | None = None,
        *,
        retry_stream: bool = True,
    ) -> dict:
        if self._http is None:
            raise RuntimeError("ResponsesClient must be used with async with")
        payload = self.request(items, tools, client_metadata)
        headers = self._headers(payload["client_metadata"])
        # core/src/responses_retry.rs. A completed output item has already been
        # acted on upstream; callers must resolve a partial stream explicitly
        # instead of replaying tool effects from an unchanged request history.
        stream_retries = self.stream_retries if retry_stream else 0
        for stream_attempt in range(stream_retries + 1):
            if self.turn_state is not None:
                headers["x-codex-turn-state"] = self.turn_state
            try:
                return await self._request_with_retry(payload, headers)
            except ResponseError as error:
                if (
                    error.partial_items
                    or not error.retryable
                    or stream_attempt >= stream_retries
                ):
                    raise
                attempt = stream_attempt + 1
                self.emit(
                    {
                        "type": "error",
                        "message": f"Reconnecting... {attempt}/{self.stream_retries}",
                        "will_retry": True,
                    }
                )
                await asyncio.sleep(
                    error.delay if error.delay is not None else _backoff(attempt)
                )

    async def _request_with_retry(self, payload, headers):
        # codex-client/src/retry.rs::run_with_retry. Provider retry_429=false;
        # Retry-After headers do not override this transport retry policy.
        for attempt in range(self.request_retries + 1):
            try:
                async with self._http.stream(
                    "POST",
                    self.url,
                    json=payload,
                    headers=headers,
                    params=self.provider.get("query_params"),
                ) as response:
                    if not 200 <= response.status_code < 300:
                        body = (await response.aread()).decode(errors="replace")
                        if (
                            response.status_code >= 500
                            and attempt < self.request_retries
                        ):
                            await asyncio.sleep(_backoff(attempt + 1))
                            continue
                        raise _http_error(response.status_code, body)
                    self.turn_state = self.turn_state or response.headers.get(
                        "x-codex-turn-state"
                    )
                    if "x-reasoning-included" in response.headers:
                        self.emit({"type": "server_reasoning_included"})
                    return await self._reduce(response)
            except httpx.TransportError as error:
                if attempt >= self.request_retries:
                    raise ResponseError(str(error)) from error
                await asyncio.sleep(_backoff(attempt + 1))

    async def _reduce(self, response):
        items, pending_error = [], None
        stream = _sse_events(response).__aiter__()
        while True:
            try:
                data = await asyncio.wait_for(anext(stream), self.idle_timeout)
            except StopAsyncIteration:
                error = pending_error or ResponseError(
                    "stream closed before response.completed"
                )
                error.partial_items = items
                raise error
            except TimeoutError as exc:
                raise ResponseError(
                    "idle timeout waiting for SSE", partial_items=items
                ) from exc
            except httpx.TransportError as exc:
                raise ResponseError(str(exc), partial_items=items) from exc
            try:
                event = json.loads(data)
            except (ValueError, UnicodeError):
                # The upstream decoder logs malformed/unknown events and keeps
                # consuming; [DONE] is not Responses completion.
                continue
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                continue
            kind = event["type"]
            if kind == "response.output_item.done":
                item = canonical_item(event.get("item"))
                if item is None:
                    continue
                event["item"] = item
                items.append(item)
            self.emit(event)
            if kind == "response.output_item.done":
                continue
            elif kind == "response.failed":
                pending_error = _stream_error(
                    (event.get("response") or {}).get("error") or {}
                )
            elif kind == "response.incomplete":
                reason = (
                    (event.get("response") or {}).get("incomplete_details") or {}
                ).get("reason", "unknown")
                pending_error = ResponseError(
                    "Incomplete response returned, reason: " + str(reason)
                )
            elif kind == "response.completed" and event.get("response") is not None:
                completed = event["response"]
                try:
                    if not isinstance(completed["id"], str):
                        raise ValueError("response id must be a string")
                    if (
                        completed.get("end_turn") is not None
                        and type(completed["end_turn"]) is not bool
                    ):
                        raise ValueError("end_turn must be a boolean")
                    usage = _usage(completed.get("usage"))
                except (KeyError, ValueError, TypeError) as exc:
                    pending_error = ResponseError(
                        "failed to parse ResponseCompleted: " + str(exc)
                    )
                    continue
                return {
                    "items": items,
                    "usage": usage,
                    "response_id": completed["id"],
                    "end_turn": completed.get("end_turn"),
                }


async def _sse_events(response):
    """SSE framing equivalent to eventsource_stream, across arbitrary chunks."""
    data = []
    first = True
    async for line in response.aiter_lines():
        if first:
            line, first = line.removeprefix("\ufeff"), False
        if not line:
            if data:
                yield "\n".join(data)
                data = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data.append(value.removeprefix(" "))


def _usage(usage):
    # sse/responses.rs::From<ResponseCompletedUsage> for TokenUsage.
    if usage is None:
        return {}
    result = {
        key: usage[key] for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    result.update(
        cached_input_tokens=details["cached_tokens"] if details is not None else 0,
        cache_write_input_tokens=details.get("cache_write_tokens", 0)
        if details is not None
        else 0,
        reasoning_output_tokens=output_details["reasoning_tokens"]
        if output_details is not None
        else 0,
    )
    if any(
        type(value) is not int or not -(2**63) <= value < 2**63
        for value in result.values()
    ):
        raise ValueError("token usage fields must be 64-bit integers")
    if usage.get("codex_rollout_budget_units") is not None:
        result["codex_rollout_budget_units"] = usage["codex_rollout_budget_units"]
    return result


def _stream_error(error):
    code = error.get("code") or "stream"
    message = error.get("message") or "response.failed event received"
    fatal = {
        "context_length_exceeded",
        "insufficient_quota",
        "usage_not_included",
        "cyber_policy",
        "invalid_prompt",
        "bio_policy",
        "server_is_overloaded",
        "slow_down",
    }
    if code == "cyber_policy" and not str(error.get("message") or "").strip():
        message = "This request has been flagged for possible cybersecurity risk."
    delay = None
    if code == "rate_limit_exceeded":
        match = re.search(
            r"try again in\s*(\d+(?:\.\d+)?)\s*(s|ms|seconds?)", message, re.IGNORECASE
        )
        if match:
            delay = float(match[1]) / (1000 if match[2].lower() == "ms" else 1)
    return ResponseError(message, code=code, retryable=code not in fatal, delay=delay)


def _http_error(status, body):
    try:
        error = json.loads(body).get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    code = error.get("code", "") if isinstance(error, dict) else ""
    fatal = status in {400, 429} or (
        status == 503 and code in {"server_is_overloaded", "slow_down"}
    )
    return ResponseError(
        f"HTTP {status}: {body}", code=code or f"http_{status}", retryable=not fatal
    )


def _backoff(attempt):
    # Both upstream HTTP and core retry loops use 200ms * 2^(n-1), ±10%.
    return int(200 * 2 ** max(0, attempt - 1) * random.uniform(0.9, 1.1)) / 1000
