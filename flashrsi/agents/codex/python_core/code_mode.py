"""Code Mode cells ported from Codex be6e8eac029b's runtime and protocol.

Python owns cell lifecycle and normal tool dispatch. A fresh Node V8 module
context executes each cell through code_mode_worker.js; persistent values are
JSON snapshots committed only when the cell completes, as in SessionRuntime.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import shutil
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .history import truncate_text
from .shell import ToolError, token_count, truncate


def parse_exec_source(source):
    if not isinstance(source, str) or not source.strip():
        raise ToolError(
            'exec expects raw JavaScript source text (non-empty). Provide JS only, optionally with first-line `// @exec: {"yield_time_ms": 10000, "max_output_tokens": 1000}`.'
        )
    first, separator, rest = source.partition("\n")
    pragma = first.lstrip()
    if not pragma.startswith("// @exec:"):
        return source, None, None
    if not separator or not rest.strip():
        raise ToolError(
            "exec pragma must be followed by JavaScript source on subsequent lines"
        )
    directive = pragma[len("// @exec:") :].strip()
    object_error = "exec pragma must be a JSON object with supported fields `yield_time_ms` and `max_output_tokens`"
    if not directive:
        raise ToolError(object_error)
    try:
        fields = json.loads(directive)
    except json.JSONDecodeError as error:
        raise ToolError(
            f"exec pragma must be valid JSON with supported fields `yield_time_ms` and `max_output_tokens`: {error.msg} at line {error.lineno} column {error.colno}"
        ) from None
    if not isinstance(fields, dict):
        raise ToolError(object_error)
    for key, value in fields.items():
        if key not in {"yield_time_ms", "max_output_tokens"}:
            raise ToolError(
                f"exec pragma only supports `yield_time_ms` and `max_output_tokens`; got `{key}`"
            )
        if value is not None and (type(value) is not int or value < 0):
            raise ToolError(
                "exec pragma fields `yield_time_ms` and `max_output_tokens` must be non-negative safe integers"
            )
        if value is not None and value > 9007199254740991:
            raise ToolError(
                f"exec pragma field `{key}` must be a non-negative safe integer"
            )
    return rest, fields.get("yield_time_ms"), fields.get("max_output_tokens")


def _audio_tokens(url):
    try:
        metadata, data = url.split(",", 1)
        if "base64" in metadata.lower().split(";")[1:]:
            raw = base64.b64decode(data, validate=True)
            if metadata.lower().startswith(
                ("data:audio/wav", "data:audio/x-wav", "data:audio/wave")
            ):
                with wave.open(io.BytesIO(raw)) as audio:
                    return math.ceil(audio.getnframes() / audio.getframerate() * 10)
    except (ValueError, wave.Error, EOFError):
        pass
    return token_count(url)


def _truncate_items(items, maximum):
    maximum = 10000 if maximum is None else maximum
    if all(item["type"] == "input_text" for item in items):
        combined = ""
        for item in items:
            if combined:
                combined += "\n"
            combined += item["text"]
        if len(combined.encode()) <= maximum * 4:
            return items
        return [
            {
                "type": "input_text",
                "text": truncate(
                    combined, {"mode": "tokens", "limit": maximum}, formatted=True
                ),
            }
        ]
    result, omitted_text, omitted_audio = [], 0, 0
    for item in items:
        if item["type"] == "input_image":
            result.append(item)
        elif item["type"] == "input_text":
            if maximum == 0:
                omitted_text += 1
            else:
                result.append(
                    {**item, "text": truncate_text(item["text"], "tokens", maximum)}
                )
                maximum = max(0, maximum - token_count(item["text"]))
        elif item["type"] == "input_audio":
            cost = _audio_tokens(item["audio_url"])
            if cost <= maximum:
                result.append(item)
                maximum -= cost
            else:
                omitted_audio += 1
    for count, kind in ((omitted_text, "text"), (omitted_audio, "audio")):
        if count:
            result.append(
                {"type": "input_text", "text": f"[omitted {count} {kind} items ...]"}
            )
    return result


@dataclass
class Cell:
    id: str
    call_id: str
    process: asyncio.subprocess.Process
    definitions: dict
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    items: list = field(default_factory=list)
    yielded: list = field(default_factory=list)
    extras: list = field(default_factory=list)
    nested: set = field(default_factory=set)
    notifications: set = field(default_factory=set)
    reader: asyncio.Task | None = None
    stderr: asyncio.Task | None = None
    observing: bool = False
    done: bool = False
    terminated: bool = False
    error: str | None = None


class CodeMode:
    def __init__(self, router):
        self.router = router
        self.cells = {}
        self.stored = {}
        self.next_cell_id = 1
        self.closed = False
        self.node = shutil.which("node")
        if self.node is None:
            raise ValueError(
                "Python Code Mode requires Node.js with V8 module support; node was not found"
            )

    async def execute_call(self, call):
        custom = call.get("type") == "custom_tool_call"
        response = {
            "type": "custom_tool_call_output" if custom else "function_call_output",
            "call_id": call["call_id"],
        }
        cell = None
        started = time.monotonic()
        try:
            if call["name"] == "exec":
                if not custom:
                    raise ToolError("exec expects raw JavaScript source text")
                source, delay, maximum = parse_exec_source(call.get("input", ""))
                if delay is None:
                    delay = (
                        30000
                        if self.router.settings.get("features", {}).get(
                            "code_mode_buffered_exec"
                        )
                        else 10000
                    )
                cell = await self._start(source, call["call_id"])
            else:
                if custom:
                    raise ToolError("wait expects JSON arguments")
                try:
                    args = json.loads(call.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError) as error:
                    raise ToolError(
                        f"failed to parse function arguments: {error}"
                    ) from None
                if not isinstance(args, dict) or not isinstance(
                    args.get("cell_id"), str
                ):
                    raise ToolError(
                        "failed to parse function arguments: missing field `cell_id`"
                    )
                delay, maximum = (
                    args.get("yield_time_ms", 10000),
                    args.get("max_tokens"),
                )
                if type(delay) is not int or delay < 0 or delay > (1 << 64) - 1:
                    raise ToolError(
                        "failed to parse function arguments: yield_time_ms must be a non-negative integer"
                    )
                if maximum is not None and (type(maximum) is not int or maximum < 0):
                    raise ToolError(
                        "failed to parse function arguments: max_tokens must be a non-negative integer"
                    )
                cell = self.cells.get(args["cell_id"])
                if cell is None:
                    return {
                        **response,
                        "output": self._render(
                            [],
                            f"exec cell {args['cell_id']} not found",
                            "Script failed",
                            maximum,
                            started,
                        ),
                    }
                if args.get("terminate", False):
                    if type(args["terminate"]) is not bool:
                        raise ToolError(
                            "failed to parse function arguments: terminate must be a boolean"
                        )
                    if not cell.done:
                        await self._terminate(cell)
            status, items, error = await self._observe(cell, delay)
            response["output"] = self._render(items, error, status, maximum, started)
            if cell.extras:
                response["extra_items"], cell.extras = cell.extras, []
            return response
        except ToolError as error:
            return {**response, "output": str(error)}
        except asyncio.CancelledError:
            if cell is not None:
                await self._terminate(cell)
            raise

    async def _start(self, source, call_id):
        if self.closed:
            raise ToolError("code mode session is shutting down")
        cell_id = str(self.next_cell_id)
        self.next_cell_id += 1
        definitions = self.router.code_mode_definitions()
        worker = Path(__file__).with_name("code_mode_worker.js")
        process = await asyncio.create_subprocess_exec(
            self.node,
            "--no-warnings",
            "--experimental-vm-modules",
            str(worker),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024,
        )
        cell = Cell(
            cell_id,
            call_id,
            process,
            {tool["global_name"]: tool for tool in definitions},
        )
        # The initial observer exists before evaluation, preserving an immediate
        # yield_control even if completion races the process read loop.
        cell.observing = True
        self.cells[cell_id] = cell
        cell.stderr = asyncio.create_task(process.stderr.read())
        cell.reader = asyncio.create_task(self._read(cell))
        initial = {"source": source, "tools": definitions, "values": self.stored}
        try:
            process.stdin.write(
                (json.dumps(initial, ensure_ascii=False) + "\n").encode()
            )
            await process.stdin.drain()
            await cell.ready.wait()
        except BaseException:
            await self._terminate(cell)
            await cell.reader
            self.cells.pop(cell.id, None)
            raise
        return cell

    async def _read(self, cell):
        try:
            while line := await cell.process.stdout.readline():
                event = json.loads(line)
                kind = event["type"]
                async with cell.changed:
                    if kind == "ready":
                        cell.ready.set()
                    elif kind == "content":
                        cell.items.append(event["item"])
                    elif kind == "yield" and cell.observing:
                        cell.yielded.append(cell.items)
                        cell.items = []
                        cell.observing = False
                    elif kind == "notify":
                        extra = {
                            "type": "custom_tool_call_output",
                            "call_id": cell.call_id,
                            "name": "exec",
                            "output": event["text"],
                        }
                        task = asyncio.create_task(self._notify(cell, extra))
                        cell.notifications.add(task)
                        task.add_done_callback(cell.notifications.discard)
                    elif kind == "tool":
                        task = asyncio.create_task(self._nested(cell, event))
                        cell.nested.add(task)
                        task.add_done_callback(cell.nested.discard)
                    elif kind in {"result", "fatal"}:
                        cell.error = event.get("error")
                        # Native CellActor delivers notifications separately
                        # from output events and joins them before completion.
                        if cell.notifications:
                            await asyncio.gather(*cell.notifications)
                        if not cell.terminated:
                            self.stored.update(event.get("writes", {}))
                        await self._cancel_nested(cell)
                        cell.done = True
                        cell.ready.set()
                    cell.changed.notify_all()
            if not cell.done:
                stderr = (await cell.stderr).decode(errors="replace")
                async with cell.changed:
                    cell.error = "code mode V8 worker closed unexpectedly" + (
                        f": {stderr.strip()}" if stderr else ""
                    )
                    cell.done = True
                    cell.ready.set()
                    cell.changed.notify_all()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            async with cell.changed:
                cell.error, cell.done = str(error), True
                cell.ready.set()
                cell.changed.notify_all()
        finally:
            await self._cancel_nested(cell)
            await self._cancel_notifications(cell)
            if cell.process.returncode is None and cell.done:
                try:
                    cell.process.kill()
                except ProcessLookupError:
                    pass
            await cell.process.wait()

    async def _notify(self, cell, item):
        try:
            if callable(getattr(self.router, "inject", None)):
                self.router.inject(item)
            else:
                cell.extras.append(item)
        except Exception as error:
            emit = getattr(self.router, "emit", lambda event: None)
            emit(
                {
                    "type": "warning",
                    "message": f"failed to deliver code mode notification: {error}",
                }
            )

    async def _nested(self, cell, event):
        result = {"id": event["id"]}
        try:
            definition = cell.definitions[event["name"]]
            tool = definition["tool_name"]
            namespace = tool.get("namespace")
            name = tool["name"]
            display = (
                f"{namespace}.{name}"
                if namespace and namespace != "functions"
                else name
            )
            value = event.get("input")
            if definition["kind"] == "freeform":
                if not isinstance(value, str):
                    raise ToolError(f"tool `{display}` expects a string input")
                call = {"type": "custom_tool_call", "input": value}
            else:
                if not event["has_input"]:
                    value = {}
                if not isinstance(value, dict):
                    raise ToolError(
                        f"tool `{display}` expects a JSON object for arguments"
                    )
                call = {
                    "type": "function_call",
                    "arguments": json.dumps(
                        value, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            call.update(
                name=name, call_id="exec-" + str(uuid.uuid4()), _source="code_mode"
            )
            if namespace:
                call["namespace"] = namespace
            result["value"] = await self.router.execute_nested(call)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            result["error"] = str(error)
        if cell.process.returncode is None and not cell.done:
            try:
                cell.process.stdin.write(
                    (json.dumps(result, ensure_ascii=False) + "\n").encode()
                )
                await cell.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass

    async def _observe(self, cell, delay):
        if (
            cell.observing
            and cell.reader is not None
            and not cell.yielded
            and getattr(cell, "initial_claimed", False)
        ):
            raise ToolError(f"exec cell {cell.id} already has an active observer")
        cell.initial_claimed = True
        cell.observing = True
        timeout = delay / 1000 + (1 if delay >= 10000 else 0)
        deadline = time.monotonic() + timeout
        try:
            async with cell.changed:
                while not cell.yielded and not cell.done:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(cell.changed.wait(), remaining)
                    except TimeoutError:
                        break
                if cell.yielded:
                    return (
                        f"Script running with cell ID {cell.id}",
                        cell.yielded.pop(0),
                        None,
                    )
                items, cell.items = cell.items, []
                if cell.done:
                    self.cells.pop(cell.id, None)
                    status = (
                        "Script terminated"
                        if cell.terminated
                        else "Script failed"
                        if cell.error is not None
                        else "Script completed"
                    )
                    return status, items, cell.error
                return f"Script running with cell ID {cell.id}", items, None
        finally:
            cell.observing = False

    @staticmethod
    def _render(items, error, status, maximum, started):
        if error is not None:
            items.append({"type": "input_text", "text": f"Script error:\n{error}"})
        items = _truncate_items(items, maximum)
        elapsed = math.floor((time.monotonic() - started) * 10 + 0.5) / 10
        output = [
            {
                "type": "input_text",
                "text": f"{status}\nWall time {elapsed:.1f} seconds\nOutput:\n",
            },
            *items,
        ]
        return output[0]["text"] if len(output) == 1 else output

    @staticmethod
    async def _cancel_nested(cell):
        tasks = list(cell.nested)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def _cancel_notifications(cell):
        tasks = list(cell.notifications)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _terminate(self, cell):
        cell.terminated = True
        await self._cancel_nested(cell)
        await self._cancel_notifications(cell)
        if cell.process.returncode is None:
            try:
                cell.process.kill()
            except ProcessLookupError:
                pass
        await cell.process.wait()
        async with cell.changed:
            cell.done, cell.error = True, None
            cell.changed.notify_all()

    async def close(self):
        self.closed = True
        cells = list(self.cells.values())
        for cell in cells:
            if not cell.done:
                await self._terminate(cell)
        for cell in cells:
            if cell.reader:
                await cell.reader
        self.cells.clear()
