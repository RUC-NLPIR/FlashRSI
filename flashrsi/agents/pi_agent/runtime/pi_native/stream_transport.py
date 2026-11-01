"""Incremental HTTP SSE transport with Pi's request-opening retry policy."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import re

import httpx

from .provider_retry import ProviderRequestError, _delay, _retryable
from .stream_json import parse_json_with_repair


async def request_stream(
    client,
    url,
    headers,
    payload,
    retries=0,
    *,
    parser,
    on_event=None,
    cancel_event=None,
    timeout=None,
    max_retry_delay=60.0,
    no_retry_statuses=(),
):
    """Return a JSON body or a canonical Pi message from a live SSE body.

    Providers which return full JSON despite stream:true remain compatible.
    Once SSE starts, a broken connection finalizes that partial response and
    never replays already consumed chunks as an SDK request retry.
    """

    terminal = False

    async def emit(events):
        nonlocal terminal
        for event in events:
            if event["type"] in {"done", "error"}:
                terminal = True
            if on_event is not None:
                value = on_event(event)
                if inspect.isawaitable(value):
                    await value

    opened = False
    for attempt in range(max(0, retries) + 1):
        try:
            serialized = json.dumps(payload, ensure_ascii=False)
            kwargs = {"timeout": timeout} if timeout is not None else {}
            if re.search(r"[\ud800-\udfff]", serialized):
                kwargs["content"] = json.dumps(payload, ensure_ascii=True).encode(
                    "ascii"
                )
            else:
                kwargs["json"] = dict(payload)
            async with client.stream("POST", url, headers=headers, **kwargs) as reply:
                if reply.is_error:
                    await reply.aread()
                    raise ProviderRequestError(
                        f"{reply.status_code}: {reply.text}",
                        status=reply.status_code,
                        headers=reply.headers,
                        body=reply.text,
                    )
                if (
                    "text/event-stream"
                    not in reply.headers.get("content-type", "").lower()
                ):
                    await reply.aread()
                    value = reply.json()
                    if not isinstance(value, dict):
                        raise ValueError("provider returned a non-object JSON response")
                    return value
                opened = True
                await emit(parser.start())
                data = []
                event_type = None
                raw_lines = []
                anthropic = parser.message["api"] == "anthropic-messages"
                first_line = True
                done_sentinel = False

                async def dispatch():
                    nonlocal data, event_type, raw_lines, done_sentinel
                    if anthropic and event_type == "error":
                        await emit(parser.fail("\n".join(data)))
                    elif data:
                        raw = "\n".join(data)
                        if raw == "[DONE]" and not anthropic:
                            done_sentinel = True
                        allowed = not anthropic or event_type in {
                            "message_start",
                            "message_delta",
                            "message_stop",
                            "content_block_start",
                            "content_block_delta",
                            "content_block_stop",
                        }
                        if raw != "[DONE]" and allowed:
                            try:
                                event = (
                                    parse_json_with_repair(raw)
                                    if anthropic
                                    else json.loads(raw)
                                )
                            except ValueError as exc:
                                if anthropic:
                                    raise ValueError(
                                        f"Could not parse Anthropic SSE event {event_type}: {exc}; data={raw}; raw="
                                        + "\\n".join(raw_lines)
                                    ) from exc
                                raise
                            if not isinstance(event, dict):
                                raise ValueError("provider SSE data must be an object")
                            if event_type and "type" not in event:
                                event["type"] = event_type
                            events = [copy.deepcopy(value) for value in parser.feed(event)]
                            # Source provider pushes within one decoded event
                            # share the mutable partial message. The agent
                            # consumes those after that event has been handled,
                            # so start/end events see its completed partial.
                            # Keep parser push snapshots independent, but match
                            # this observable agent-loop scheduling boundary.
                            for emitted in events:
                                if "partial" in emitted:
                                    emitted["partial"] = copy.deepcopy(parser.message)
                            await emit(events)
                    data, event_type, raw_lines = [], None, []

                async for line in reply.aiter_lines():
                    if first_line:
                        line = line.removeprefix("\ufeff")
                        first_line = False
                    if line == "":
                        await dispatch()
                        if terminal or done_sentinel:
                            break
                    else:
                        raw_lines.append(line)
                        field, _, value = line.partition(":")
                        value = value.removeprefix(" ")
                        if field == "data":
                            data.append(value)
                        elif field == "event":
                            event_type = value
                    # Comments, id, and retry fields do not alter JSON events.
                await dispatch()
                canonical = parser.finish()
                await emit(parser.drain())
                return {"_pi_message": canonical, "_pi_streamed": True}
        except asyncio.CancelledError:
            if not opened or cancel_event is None or not cancel_event.is_set():
                raise
            error = (
                "Request was aborted"
                if parser.message["api"] == "anthropic-messages"
                else "Request aborted"
            )
            await emit(parser.abort(error))
            return {"_pi_message": parser.finish(), "_pi_streamed": True}
        except Exception as exc:
            if opened:
                await emit(parser.fail(str(exc)))
                return {"_pi_message": parser.finish(), "_pi_streamed": True}
            if isinstance(exc, httpx.RequestError):
                error = ProviderRequestError(str(exc))
                error.__cause__ = exc
            elif isinstance(exc, ProviderRequestError):
                error = exc
            else:
                raise
        if (
            attempt >= max(0, retries)
            or not _retryable(error)
            or error.status in no_retry_statuses
        ):
            raise error
        await asyncio.sleep(_delay(error, attempt, max_retry_delay))
    raise AssertionError("unreachable")
