"""Callable controls for Pi's headless loop, kept outside Snapshot configuration.

The queue drain modes and hook boundaries follow packages/agent/src/{agent,
agent-loop,types}.ts at the pinned revision in UPSTREAM.md.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import time
from collections.abc import Mapping
from typing import Any

from .compaction import js_json
from .openai_tools import current_tools


class PendingMessageQueue:
    def __init__(self, mode: str = "one-at-a-time"):
        if mode not in {"all", "one-at-a-time"}:
            raise ValueError("Pi queue mode must be all or one-at-a-time")
        self.mode = mode
        self.messages: list[dict[str, Any]] = []

    def enqueue(self, message: dict[str, Any] | str) -> None:
        if isinstance(message, str):
            message = {
                "role": "user",
                "content": message,
                "timestamp": round(time.time() * 1000),
            }
        if not isinstance(message, Mapping):
            raise TypeError("Pi queued message must be a message mapping or string")
        self.messages.append(message if isinstance(message, dict) else dict(message))

    def has_items(self) -> bool:
        return bool(self.messages)

    def peek(self) -> list[dict[str, Any]]:
        return self.messages[:] if self.mode == "all" else self.messages[:1]

    def drain(self) -> list[dict[str, Any]]:
        result = self.peek()
        del self.messages[: len(result)]
        return result

    def clear(self) -> None:
        self.messages.clear()


async def call(callback, *args):
    """Allow native sync/async hooks, with an optional trailing abort signal."""
    if callback is None:
        return None
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        pass
    else:
        try:
            signature.bind(*args)
        except TypeError:
            # Source hooks accept an optional signal. Python callers may omit
            # that unused parameter, without hiding TypeError raised inside it.
            signature.bind(*args[:-1])
            args = args[:-1]
    value = callback(*args)
    return await value if inspect.isawaitable(value) else value


def hook(hooks, name):
    if hooks is None:
        return None
    camel = name.split("_")[0] + "".join(part.title() for part in name.split("_")[1:])
    if isinstance(hooks, Mapping):
        return hooks.get(name, hooks.get(camel))
    return getattr(hooks, name, getattr(hooks, camel, None))


async def drain(queue, hooks, name):
    callback = hook(hooks, name)
    if callback is not None:
        return await call(callback) or []
    if queue is None:
        return []
    if isinstance(queue, asyncio.Queue):
        try:
            return [queue.get_nowait()]
        except asyncio.QueueEmpty:
            return []
    value = queue.drain() if hasattr(queue, "drain") else queue()
    return (await value if inspect.isawaitable(value) else value) or []


def declare_tool_changes(context, pending, timestamp):
    """Commit the executable tool set at the same boundary as Pi's loop."""

    def declaration(tool):
        tool = tool.get("function", tool)
        return {
            key: copy.deepcopy(tool[key])
            for key in ("name", "description", "parameters", "constrainedSampling")
            if key in tool
        }

    pending = list(pending)
    system_index = next(
        (
            i
            for i in range(len(pending) - 1, -1, -1)
            if isinstance(pending[i], Mapping) and pending[i].get("role") == "system"
        ),
        None,
    )
    baseline = list(pending)
    if system_index is not None:
        baseline[system_index] = {
            key: value
            for key, value in pending[system_index].items()
            if key not in {"toolsAdded", "toolsRemoved"}
        }
    previous = current_tools([*context["messages"], *baseline])
    current = [declaration(tool) for tool in context.get("tools", [])]
    old = {tool["name"]: declaration(tool) for tool in previous}
    new = {tool["name"]: tool for tool in current}
    added = [
        tool for tool in current if js_json(tool) != js_json(old.get(tool["name"]))
    ]
    removed = [
        {"name": tool["name"]}
        for tool in previous
        if js_json(declaration(tool)) != js_json(new.get(tool["name"]))
    ]
    if not added and not removed and system_index is None:
        return pending
    update = (
        baseline[system_index]
        if system_index is not None
        else {
            "role": "system",
            "content": "",
            "timestamp": timestamp,
        }
    )
    if added:
        update["toolsAdded"] = added
    if removed:
        update["toolsRemoved"] = removed
    if system_index is not None:
        baseline[system_index] = update
        return baseline
    index = next(
        (
            i
            for i, item in enumerate(pending)
            if not isinstance(item, Mapping) or item.get("role") != "system"
        ),
        len(pending),
    )
    return [*pending[:index], update, *pending[index:]]


class EventLog(list):
    """Store immutable events and serialize an optional live observer.

    Synchronous observers run at append time; async observers are awaited by
    the loop at scheduling boundaries and for every provider delta.
    """

    def __init__(self, observer=None):
        super().__init__()
        self.observer = observer
        self.pending = []
        self.lock = asyncio.Lock()

    def append(self, value):
        value = copy.deepcopy(value)
        super().append(value)
        if self.observer is not None:
            self.pending.append(copy.deepcopy(value))

    async def flush(self):
        async with self.lock:
            while self.pending:
                await call(self.observer, self.pending.pop(0))
