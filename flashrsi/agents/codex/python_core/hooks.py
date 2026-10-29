"""Command hook execution from Codex v0.147.0's hooks crate."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import tempfile
import uuid
from pathlib import Path

from .shell import token_count, truncate


def _matches_schema(value, schema, document):
    if value is None and "default" in schema and schema["default"] is None:
        return True
    if "$ref" in schema:
        target = document
        for key in schema["$ref"].removeprefix("#/").split("/"):
            target = target[key]
        if not _matches_schema(value, target, document):
            return False
    if any(
        not _matches_schema(value, entry, document) for entry in schema.get("allOf", [])
    ):
        return False
    if "anyOf" in schema and not any(
        _matches_schema(value, entry, document) for entry in schema["anyOf"]
    ):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if "const" in schema and value != schema["const"]:
        return False
    types = schema.get("type")
    if types:
        valid = {
            "null": value is None,
            "boolean": isinstance(value, bool),
            "string": isinstance(value, str),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "integer": type(value) is int,
            "number": type(value) in {int, float},
        }
        if not any(
            valid[kind] for kind in ([types] if isinstance(types, str) else types)
        ):
            return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            return False
        if schema.get("additionalProperties") is False and any(
            key not in properties for key in value
        ):
            return False
        if any(
            not _matches_schema(entry, properties[key], document)
            for key, entry in value.items()
            if key in properties
        ):
            return False
    return True


class HookBlocked(RuntimeError):
    """A configured hook stopped a turn before its model request."""


class HookStopped(RuntimeError):
    """A universal continue:false stops the turn, rather than denying a tool."""

    def __init__(self, event, reason):
        self.event = event
        super().__init__(reason or "Stopped by hook")


class HookFeedback(str):
    """PostToolUse feedback replaces model-visible output for any tool type."""


def message(text: str, role: str = "developer") -> dict:
    return {
        "type": "message",
        "role": role,
        "content": [{"type": "input_text", "text": text}],
    }


class Hooks:
    def __init__(self, home, cwd, settings, emit, environment, plugins=()):
        self.home, self.cwd = Path(home), Path(cwd)
        self.settings, self.emit = settings, emit
        self.environment = {**environment, "CODEX_HOME": str(home)}
        self.handlers = {}
        self.stop_hook_active = False
        if not settings.get("features", {}).get("hooks", True):
            return
        sources = []
        path = self.home / "hooks.json"
        if path.is_file():
            sources.append((json.loads(path.read_text()).get("hooks", {}), {}, path))
        sources.append((settings.get("hooks", {}), {}, self.home / "config.toml"))
        for plugin in plugins:
            sources.extend(
                (
                    source.get("hooks", {}),
                    plugin.environment,
                    plugin.root / "hooks/hooks.json",
                )
                for source in plugin.hook_sources
            )
        supported = {
            "SessionStart",
            "SubagentStart",
            "UserPromptSubmit",
            "Stop",
            "SubagentStop",
            "SessionEnd",
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
            "PreCompact",
            "PostCompact",
        }
        order = 0
        states = settings.get("hooks", {}).get("state", {})
        for events, environment, source_path in sources:
            for event, groups in events.items():
                if event == "state":
                    continue
                if event not in supported:
                    if groups:
                        raise ValueError(
                            f"Python Codex core does not yet support {event} hooks"
                        )
                    continue
                for group_index, group in enumerate(groups):
                    for handler_index, original in enumerate(group.get("hooks", [])):
                        handler = dict(original)
                        if handler.get("type") != "command":
                            raise ValueError(
                                f"unsupported {event} hook type: {handler.get('type')}"
                            )
                        label = re.sub(r"(?<!^)(?=[A-Z])", "-", event).lower()
                        state_key = f"{source_path}:{label.replace('-', '_')}:{group_index}:{handler_index}"
                        if states.get(state_key, {}).get("enabled") is False:
                            continue
                        handler["_run_id"] = f"{label}:{order}:{source_path}"
                        order += 1
                        handler["timeout"] = max(
                            1,
                            int(
                                handler.get("timeout")
                                or (1 if event == "SessionEnd" else 600)
                            ),
                        )
                        if event == "SessionEnd":
                            handler["timeout"] = min(3, handler["timeout"])
                        if handler.get("async") and event != "SessionEnd":
                            emit(
                                {
                                    "type": "warning",
                                    "message": f"skipping async hook in {source_path}: async hooks are not supported yet",
                                }
                            )
                            continue
                        if not handler.get("command", "").strip():
                            emit(
                                {
                                    "type": "warning",
                                    "message": f"skipping empty hook command in {source_path}",
                                }
                            )
                            continue
                        self.handlers.setdefault(event, []).append(
                            (group.get("matcher"), handler, environment)
                        )

    def _input(self, event, **fields):
        settings = self.settings
        data = {
            "session_id": settings.get("_session_id", settings.get("_thread_id", "")),
            "transcript_path": settings.get("_transcript_path"),
            "cwd": str(self.cwd),
            "hook_event_name": event,
        }
        if event in {"PreCompact", "PostCompact"}:
            data["model"] = settings.get("model", "")
        elif event != "SessionEnd":
            data.update(
                model=settings.get("model", ""),
                permission_mode="bypassPermissions"
                if settings.get("approval_policy") == "never"
                else "default",
            )
        if event not in {"SessionStart", "SessionEnd"}:
            data["turn_id"] = str(settings.get("_turn_id", "0"))
        data.update(fields)
        return data

    async def _execute(self, event, handler, plugin_environment, payload):
        env = {**self.environment, **plugin_environment}
        shell = env.get("SHELL") or "/bin/sh"
        command = handler["command"]
        self.emit({"type": "hook_started", "event": event, "command": command})
        try:
            child = await asyncio.create_subprocess_exec(
                shell,
                "-lc",
                command,
                cwd=self.cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            self.emit(
                {
                    "type": "warning",
                    "message": f"failed to start {event} hook: {error}",
                }
            )
            return {}
        try:
            stdout, stderr = await asyncio.wait_for(
                child.communicate(
                    json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    ).encode()
                ),
                float(handler.get("timeout", 600)),
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as error:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await child.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            self.emit(
                {
                    "type": "warning",
                    "message": f"{event} hook timed out after {handler.get('timeout', 600)}s",
                }
            )
            return {}
        stdout, stderr = (
            stdout.decode(errors="replace").strip(),
            stderr.decode(errors="replace").strip(),
        )
        self.emit(
            {
                "type": "hook_completed",
                "event": event,
                "exit_code": child.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
        if child.returncode == 2 and event in {
            "UserPromptSubmit",
            "Stop",
            "SubagentStop",
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
        }:
            if stderr:
                return {"decision": "block", "reason": stderr}
            self.emit(
                {
                    "type": "warning",
                    "message": f"{event} hook exited with code 2 but did not write a blocking reason to stderr",
                }
            )
            return {}
        if child.returncode != 0:
            self.emit(
                {
                    "type": "warning",
                    "message": f"{event} hook exited with code {child.returncode}: {stderr}",
                }
            )
            return {}
        if not stdout:
            return {}
        if event == "SessionEnd":
            return {}
        try:
            result = json.loads(stdout)
            if not isinstance(result, dict):
                raise ValueError("hook JSON output must be an object")
            label = re.sub(r"(?<!^)(?=[A-Z])", "-", event).lower()
            schema_path = (
                self.home
                / "python_core/resource_assets/hook_schemas"
                / f"{label}.command.output.schema.json"
            )
            schema = json.loads(schema_path.read_text())
            if not _matches_schema(result, schema, schema):
                raise ValueError("hook output does not match the pinned event schema")
            unsupported = None
            if event in {"PreToolUse", "PermissionRequest"}:
                if result.get("continue") is False:
                    unsupported = "continue:false"
                elif result.get("stopReason") is not None:
                    unsupported = "stopReason"
            if event in {
                "PreToolUse",
                "PermissionRequest",
                "PostToolUse",
            } and result.get("suppressOutput"):
                unsupported = unsupported or "suppressOutput"
            if unsupported:
                raise ValueError(f"{event} hook returned unsupported {unsupported}")
            specific = result.get("hookSpecificOutput", {})
            if specific and specific.get("hookEventName") != event:
                raise ValueError("hookEventName does not match the active event")
            result.update(specific)
            if result.get("systemMessage"):
                self.emit({"type": "warning", "message": result["systemMessage"]})
            return result
        except (ValueError, TypeError) as error:
            if stdout[:1] in "[{":
                self.emit(
                    {
                        "type": "warning",
                        "message": f"hook returned invalid {event} JSON output: {error}",
                    }
                )
                return {}
            return (
                {"additionalContext": stdout}
                if event in {"SessionStart", "SubagentStart", "UserPromptSubmit"}
                else {}
            )

    async def run(self, event, matcher_input=None, matcher_aliases=(), **fields):
        selected = []
        for matcher, handler, env in self.handlers.get(event, []):
            if event not in {"Stop", "UserPromptSubmit"} and matcher and matcher != "*":
                if matcher_input is None:
                    continue
                exact = re.fullmatch(r"[A-Za-z0-9_|]+", matcher)
                matches = any(
                    candidate in matcher.split("|")
                    if exact
                    else re.search(matcher, candidate) is not None
                    for candidate in (matcher_input, *matcher_aliases)
                )
                if not matches:
                    continue
            selected.append((handler, env))
        payload = self._input(event, **fields)
        results = await asyncio.gather(
            *(self._execute(event, handler, env, payload) for handler, env in selected)
        )
        contexts, decisions = [], []
        for result, (handler, _) in zip(results, selected, strict=True):
            if result.get("continue") is False and event == "PostToolUse":
                reason = (result.get("reason") or "").strip()
                stop_reason = result.get("stopReason")
                result["_feedback"] = reason or (
                    stop_reason
                    if stop_reason is not None
                    else "PostToolUse hook stopped execution"
                )
            elif result.get("continue") is False:
                raise HookStopped(event, result.get("stopReason"))
            if result.get("decision") == "block" and "_feedback" not in result:
                reason = (result.get("reason") or "").strip()
                if not reason:
                    self.emit(
                        {
                            "type": "warning",
                            "message": f"{event} hook blocked without a reason",
                        }
                    )
                    continue
                if event in {"Stop", "SubagentStop"}:
                    result["_run_id"] = handler["_run_id"]
                else:
                    raise HookBlocked(reason)
            text = result.get("additionalContext")
            if isinstance(text, str):
                contexts.append(
                    message(
                        self._spill(text, handler.get("additionalContextLimit", 2500))
                    )
                )
            decisions.append(result)
        return contexts, decisions

    def _spill(self, text, limit):
        if not limit or token_count(text) <= limit:
            return text
        path = (
            Path(tempfile.gettempdir())
            / "hook_outputs"
            / str(self.settings.get("_session_id", ""))
            / f"{uuid.uuid4()}.txt"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        footer = f"\n\nFull hook output saved to: {path}"
        return (
            truncate(
                text,
                {"mode": "tokens", "limit": max(0, limit - token_count(footer))},
                formatted=True,
            )
            + footer
        )

    async def before_tool(self, name, arguments, call_id=None, aliases=()):
        contexts, results = await self.run(
            "PreToolUse",
            matcher_input=name,
            matcher_aliases=aliases,
            tool_name=name,
            tool_input=arguments,
            tool_use_id=call_id or str(uuid.uuid4()),
        )
        for result in results:
            decision = result.get("permissionDecision")
            if decision in {"deny", "ask"}:
                raise HookBlocked(
                    result.get("permissionDecisionReason")
                    or "Tool execution blocked by hook"
                )
            if decision == "allow" and "updatedInput" in result:
                arguments = result["updatedInput"]
        return arguments, contexts

    async def after_tool(self, name, arguments, output, call_id=None, aliases=()):
        contexts, results = await self.run(
            "PostToolUse",
            matcher_input=name,
            matcher_aliases=aliases,
            tool_name=name,
            tool_input=arguments,
            tool_response=output,
            tool_use_id=call_id or str(uuid.uuid4()),
        )
        for result in results:
            if name.startswith("mcp__") and "updatedMCPToolOutput" in result:
                output = result["updatedMCPToolOutput"]
        feedback = [result["_feedback"] for result in results if "_feedback" in result]
        if feedback:
            output = HookFeedback("\n\n".join(feedback))
        return output, contexts
