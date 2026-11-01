"""Native OpenClaw tools with deterministic receipts and bounded authority."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .policy import ToolPolicy
from .resources import load as load_resources


def schemas() -> list[dict[str, Any]]:
    return [
        {"name": "read", "description": "Read a UTF-8 file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1}}, "required": ["path"]}},
        {"name": "write", "description": "Write a UTF-8 file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "edit", "description": "Replace an exact string in a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "oldText": {"type": "string"}, "newText": {"type": "string"}, "old": {"type": "string", "description": "Deprecated alias for oldText"}, "new": {"type": "string", "description": "Deprecated alias for newText"}}, "required": ["path", "oldText", "newText"]}},
        {"name": "apply_patch", "description": "Apply a unified diff to a workspace file", "parameters": {"type": "object", "properties": {"patch": {"type": "string"}}, "required": ["patch"]}},
        {"name": "exec", "description": "Run a shell command in the workspace", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "workdir": {"type": "string"}, "env": {"type": "object", "additionalProperties": {"type": "string"}}, "timeout": {"type": "number"}, "yieldMs": {"type": "number"}, "background": {"type": "boolean"}, "max_output_chars": {"type": "integer"}, "maxOutputChars": {"type": "integer"}}, "required": ["command"]}},
        {"name": "process", "description": "Run and inspect a background process", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["run", "poll", "log", "write", "kill", "clear", "list"]}, "command": {"type": "string"}, "workdir": {"type": "string"}, "env": {"type": "object", "additionalProperties": {"type": "string"}}, "sessionId": {"type": "string"}, "data": {"type": "string"}, "eof": {"type": "boolean"}, "timeout": {"type": "number"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["action"]}},
        {"name": "read_skill", "description": "Read a skill instruction file", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "memory_search", "description": "Search workspace Markdown and SQLite memory", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["query"]}},
    ]


def _relative(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return path.as_posix()


def _error(tool: str, message: str, *, error_type: str = "tool_error", **extra: Any) -> dict[str, Any]:
    return {"ok": False, "tool": tool, "error": message, "error_type": error_type, **extra}


class ToolRunner:
    def __init__(self, workspace: Path, root: Path, policy: ToolPolicy):
        self.workspace, self.root, self.policy = Path(workspace).resolve(), Path(root).resolve(), policy
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._process_tasks: dict[str, asyncio.Task] = {}
        self._process_output: dict[str, str] = {}

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.policy.check(name)
        if name == "read":
            return self._read(args)
        if name == "write":
            return self._write(args)
        if name == "edit":
            return self._edit(args)
        if name == "apply_patch":
            return self._patch(args)
        if name == "exec":
            return await self._exec(args)
        if name == "process":
            return await self._process(args)
        if name == "read_skill":
            return self._skill(args)
        if name == "memory_search":
            return self._memory(args)
        raise ValueError(f"unknown tool: {name}")

    def _read(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            path = self.policy.path(args["path"])
            text = path.read_text(encoding="utf-8")
        except KeyError:
            return _error("read", "missing required argument: path", error_type="invalid_arguments")
        except PermissionError:
            raise
        except (OSError, UnicodeError) as exc:
            return _error("read", str(exc), error_type=type(exc).__name__)
        try:
            offset = args.get("offset")
            if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int)):
                return _error("read", "offset must be an integer", error_type="invalid_arguments")
            start = max((offset - 1) if offset else 0, 0)
            limit = args.get("limit")
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
                return _error("read", "limit must be an integer", error_type="invalid_arguments")
            if limit is not None and limit < 0:
                return _error("read", "limit must be non-negative", error_type="invalid_arguments")
            lines = text.split("\n")
            if start >= len(lines):
                return _error("read", f"offset {offset} is beyond end of file", error_type="invalid_arguments")
            end = start + limit if limit is not None else len(lines)
        except (TypeError, ValueError):
            return _error("read", "offset and limit must be integers", error_type="invalid_arguments")
        return {"ok": True, "tool": "read", "path": _relative(path, self.workspace), "content": "\n".join(lines[start:end]), "line_start": start + 1, "line_end": min(end, len(lines)), "total_lines": len(lines)}

    def _write(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            path = self.policy.path(args["path"])
            content = str(args["content"])
        except KeyError as exc:
            return _error("write", f"missing required argument: {exc.args[0]}", error_type="invalid_arguments")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except PermissionError:
            raise
        except (OSError, UnicodeError) as exc:
            return _error("write", str(exc), error_type=type(exc).__name__, path=_relative(path, self.workspace))
        return {"ok": True, "tool": "write", "path": _relative(path, self.workspace), "bytes": len(content.encode("utf-8")), "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}

    def _edit(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            path = self.policy.path(args["path"])
            before = path.read_text(encoding="utf-8")
            old_value = args.get("oldText", args.get("old"))
            new_value = args.get("newText", args.get("new"))
            if not isinstance(old_value, str) or not isinstance(new_value, str):
                raise KeyError("oldText/newText")
            old, new = old_value, new_value
        except KeyError as exc:
            return _error("edit", f"missing required argument: {exc.args[0]}", error_type="invalid_arguments")
        except PermissionError:
            raise
        except (OSError, UnicodeError) as exc:
            return _error("edit", str(exc), error_type=type(exc).__name__)
        count = before.count(old)
        if count != 1:
            return _error("edit", f"expected one match, found {count}", error_type="match_error", path=_relative(path, self.workspace), matches=count)
        after = before.replace(old, new)
        try:
            path.write_text(after, encoding="utf-8")
        except OSError as exc:
            return _error("edit", str(exc), error_type=type(exc).__name__, path=_relative(path, self.workspace))
        return {"ok": True, "tool": "edit", "path": _relative(path, self.workspace), "replacements": 1, "sha256": hashlib.sha256(after.encode("utf-8")).hexdigest()}

    def _patch(self, args: dict[str, Any]) -> dict[str, Any]:
        patch = str(args.get("patch", ""))
        lines = patch.splitlines(keepends=True)
        old_header = next((line for line in lines if line.startswith("--- ")), None)
        new_header = next((line for line in lines if line.startswith("+++ ")), None)
        if old_header is None or new_header is None:
            return _error("apply_patch", "patch must contain --- and +++ file headers", error_type="invalid_patch")
        old_name = old_header[4:].split("\t", 1)[0].strip()
        new_name = new_header[4:].split("\t", 1)[0].strip()
        target_name = new_name if new_name != "/dev/null" else old_name
        target_name = target_name.removeprefix("a/").removeprefix("b/")
        if target_name == "/dev/null" or not target_name:
            return _error("apply_patch", "patch has no target", error_type="invalid_patch")
        try:
            path = self.policy.path(target_name)
            exists = path.exists()
            before = path.read_text(encoding="utf-8") if exists else ""
        except (OSError, UnicodeError, PermissionError) as exc:
            return _error("apply_patch", str(exc), error_type=type(exc).__name__)
        source = before.splitlines(keepends=True)
        hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
        hunks: list[tuple[int, int, int, int, list[str]]] = []
        index = 0
        while index < len(lines):
            match = hunk_re.match(lines[index].rstrip("\n"))
            if not match:
                index += 1
                continue
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            index += 1
            body: list[str] = []
            while index < len(lines) and not hunk_re.match(lines[index].rstrip("\n")):
                if lines[index].startswith((" ", "+", "-", "\\")):
                    body.append(lines[index])
                index += 1
            hunks.append((old_start, old_count, new_start, new_count, body))
        if not hunks:
            return _error("apply_patch", "patch contains no hunks", error_type="invalid_patch")
        offset = 0
        output = list(source)
        for old_start, old_count, _new_start, new_count, body in hunks:
            removed = [line[1:] for line in body if line[:1] in (" ", "-")]
            replacement = [line[1:] for line in body if line[:1] in (" ", "+")]
            if len(removed) != old_count or len(replacement) != new_count:
                return _error("apply_patch", "hunk line counts do not match header", error_type="invalid_patch")
            pos = max(0, old_start - 1 + offset)
            if output[pos : pos + len(removed)] != removed:
                return _error("apply_patch", f"patch context not found at line {old_start}", error_type="context_error", path=_relative(path, self.workspace))
            output[pos : pos + len(removed)] = replacement
            offset += len(replacement) - len(removed)
        after = "".join(output)
        try:
            if new_name == "/dev/null":
                if path.exists():
                    path.unlink()
                changed = bool(before)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(after, encoding="utf-8")
                changed = before != after
        except OSError as exc:
            return _error("apply_patch", str(exc), error_type=type(exc).__name__, path=_relative(path, self.workspace))
        return {"ok": True, "tool": "apply_patch", "path": _relative(path, self.workspace), "changed": changed, "hunks": len(hunks), "sha256": hashlib.sha256(after.encode("utf-8")).hexdigest() if new_name != "/dev/null" else None}

    async def _exec(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            timeout = float(args.get("timeout", 30))
            if timeout <= 0:
                raise ValueError
            command = str(args["command"])
            workdir = self.policy.path(args.get("workdir", "."))
            if not workdir.is_dir():
                return _error("exec", f"workdir is not a directory: {workdir}", error_type="invalid_arguments")
            max_output = max(0, int(args.get("max_output_chars", args.get("maxOutputChars", 0))))
            extra_env = args.get("env") or {}
            if not isinstance(extra_env, dict):
                return _error("exec", "env must be an object", error_type="invalid_arguments")
        except (KeyError, TypeError, ValueError):
            return _error("exec", "command and a positive timeout are required", error_type="invalid_arguments")
        try:
            yield_ms = max(0.0, float(args.get("yieldMs", 0)))
        except (TypeError, ValueError):
            return _error("exec", "yieldMs must be a non-negative number", error_type="invalid_arguments")
        if args.get("background") or yield_ms:
            started = await self._process({
                "action": "run",
                "command": command,
                "timeout": yield_ms / 1000 if yield_ms else 0,
                "workdir": str(workdir),
                "env": extra_env,
            })
            started["tool"] = "exec"
            if max_output and isinstance(started.get("output"), str) and len(started["output"]) > max_output:
                started["output"] = started["output"][:max_output]
                started["truncated"] = True
            return started
        started = time.monotonic()
        try:
            env = os.environ.copy()
            env.update({str(key): str(value) for key, value in extra_env.items()})
            proc = await asyncio.create_subprocess_shell(command, cwd=workdir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return _error("exec", f"command timed out after {timeout:g}s", error_type="timeout", returncode=-1, duration_ms=round((time.monotonic() - started) * 1000))
        except OSError as exc:
            return _error("exec", str(exc), error_type=type(exc).__name__)
        output = out.decode("utf-8", "replace")
        truncated = False
        if max_output and len(output) > max_output:
            output = output[:max_output]
            truncated = True
        return {"ok": proc.returncode == 0, "tool": "exec", "output": output, "returncode": proc.returncode, "duration_ms": round((time.monotonic() - started) * 1000), "truncated": truncated}

    async def _process(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run and inspect a process within this turn's workspace scope."""
        action = str(args.get("action", "list")).lower()
        if action == "list":
            rows = []
            for session_id, task in self._process_tasks.items():
                if task.done():
                    await self._finish_process(session_id)
                rows.append(
                    {
                        "sessionId": session_id,
                        "running": not task.done(),
                        "returncode": self._processes[session_id].returncode,
                        "output": self._process_output.get(session_id, "")[-2000:],
                    }
                )
            return {"ok": True, "tool": "process", "action": action, "sessions": rows}
        if action == "run":
            command = str(args.get("command", "")).strip()
            if not command:
                return _error("process", "command is required", error_type="invalid_arguments")
            try:
                timeout = float(args.get("timeout", 0))
            except (TypeError, ValueError):
                return _error("process", "timeout must be a number", error_type="invalid_arguments")
            if timeout < 0:
                return _error("process", "timeout must be non-negative", error_type="invalid_arguments")
            extra_env = args.get("env") or {}
            if not isinstance(extra_env, Mapping):
                return _error("process", "env must be an object", error_type="invalid_arguments")
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    cwd=self.policy.path(args.get("workdir", ".")),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ, **{str(key): str(value) for key, value in extra_env.items()}},
                )
            except OSError as exc:
                return _error("process", str(exc), error_type=type(exc).__name__)
            session_id = "proc-" + uuid.uuid4().hex[:12]
            self._processes[session_id] = proc
            self._process_output[session_id] = ""
            task = asyncio.create_task(self._collect_process(session_id))
            self._process_tasks[session_id] = task
            if timeout:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout)
                except asyncio.TimeoutError:
                    pass
            if task.done():
                await self._finish_process(session_id)
            return {
                "ok": True,
                "tool": "process",
                "action": action,
                "sessionId": session_id,
                "running": not task.done(),
                "output": self._process_output.get(session_id, ""),
                "returncode": proc.returncode,
            }
        session_id = str(args.get("sessionId", ""))
        if not session_id or session_id not in self._process_tasks:
            return _error("process", "unknown sessionId", error_type="not_found")
        task = self._process_tasks[session_id]
        proc = self._processes[session_id]
        if action == "poll":
            try:
                timeout = max(0.0, float(args.get("timeout", 0)))
            except (TypeError, ValueError):
                return _error("process", "timeout must be a number", error_type="invalid_arguments")
            if not task.done() and timeout:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout)
                except asyncio.TimeoutError:
                    pass
            if task.done():
                await self._finish_process(session_id)
            return {
                "ok": True,
                "tool": "process",
                "action": action,
                "sessionId": session_id,
                "running": not task.done(),
                "returncode": proc.returncode,
                "output": self._process_output.get(session_id, ""),
            }
        if action == "log":
            if task.done():
                await self._finish_process(session_id)
            try:
                offset = max(0, int(args.get("offset", 0)))
                limit = max(0, int(args.get("limit", 2000)))
            except (TypeError, ValueError):
                return _error("process", "offset and limit must be integers", error_type="invalid_arguments")
            output = self._process_output.get(session_id, "")
            return {
                "ok": True,
                "tool": "process",
                "action": action,
                "sessionId": session_id,
                "running": not task.done(),
                "content": output[offset : offset + limit],
                "offset": offset,
                "total": len(output),
            }
        if action == "write":
            data = args.get("data", "")
            if not isinstance(data, str):
                return _error("process", "data must be a string", error_type="invalid_arguments")
            if proc.stdin is None or proc.returncode is not None:
                return _error("process", "process stdin is closed", error_type="closed")
            try:
                proc.stdin.write(data.encode("utf-8"))
                await proc.stdin.drain()
                if args.get("eof"):
                    proc.stdin.close()
                    await proc.stdin.wait_closed()
            except (BrokenPipeError, ConnectionError, OSError) as exc:
                return _error("process", str(exc), error_type="closed")
            return {
                "ok": True,
                "tool": "process",
                "action": action,
                "sessionId": session_id,
                "bytes": len(data.encode("utf-8")),
            }
        if action == "kill":
            if not task.done():
                proc.terminate()
                try:
                    await asyncio.wait_for(asyncio.shield(task), 2)
                except asyncio.TimeoutError:
                    proc.kill()
                    await task
            await self._finish_process(session_id)
            return {
                "ok": True,
                "tool": "process",
                "action": action,
                "sessionId": session_id,
                "running": False,
                "returncode": proc.returncode,
                "output": self._process_output.get(session_id, ""),
            }
        if action == "clear":
            self._process_output[session_id] = ""
            return {
                "ok": True,
                "tool": "process",
                "action": action,
                "sessionId": session_id,
                "running": not task.done(),
            }
        return _error("process", f"unknown action: {action}", error_type="invalid_arguments")

    async def _collect_process(self, session_id: str) -> None:
        proc = self._processes[session_id]
        stream = proc.stdout
        if stream is not None:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                self._process_output[session_id] = self._process_output.get(session_id, "") + chunk.decode("utf-8", "replace")
        await proc.wait()

    async def _finish_process(self, session_id: str) -> None:
        task = self._process_tasks[session_id]
        if not task.done():
            return
        try:
            task.result()
        except (asyncio.CancelledError, OSError):
            return

    def _skill(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", ""))
        if not name or Path(name).is_absolute() or ".." in name.replace("\\", "/").split("/"):
            return _error("read_skill", "skill name must be a relative name", error_type="invalid_arguments")
        loaded = load_resources(self.root, self.workspace, self.policy.config)
        skill = loaded.skill(name)
        if skill is None:
            return _error("read_skill", f"skill not found: {name}", error_type="not_found")
        try:
            content = skill.path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            return _error("read_skill", str(exc), error_type=type(exc).__name__)
        return {"ok": True, "tool": "read_skill", "name": skill.name, "path": _relative(skill.path, self.workspace), "content": content, "sha256": skill.digest}

    def _memory(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        try:
            offset = max(int(args.get("offset", 0)), 0)
            limit = max(int(args.get("limit", 20)), 0)
        except (TypeError, ValueError):
            return _error("memory_search", "offset and limit must be integers", error_type="invalid_arguments")
        memory_cfg = self.policy.config.get("memory")
        memory_cfg = memory_cfg if isinstance(memory_cfg, Mapping) else {}
        if memory_cfg.get("enabled") is False:
            return {
                "ok": True,
                "tool": "memory_search",
                "query": query,
                "offset": offset,
                "limit": limit,
                "total": 0,
                "results": [],
            }
        needle = query.casefold()
        hits: list[dict[str, Any]] = []
        # OpenClaw's memory settings can select curated root files and a daily
        # memory directory. Keep discovery workspace-scoped even when the
        # general tool sandbox is disabled, so a memory query never expands
        # authority merely because ``sandbox.mode`` is off.
        curated = memory_cfg.get("curated_files", ("MEMORY.md", "USER.md"))
        if isinstance(curated, str):
            curated = (curated,)
        elif not isinstance(curated, (list, tuple, set)):
            curated = ("MEMORY.md", "USER.md")
        files: set[Path] = set()
        for name in curated:
            if not isinstance(name, str) or not name.strip():
                continue
            path = (self.workspace / name).resolve()
            if path.is_file() and path.is_relative_to(self.workspace):
                files.add(path)
        daily_dir = memory_cfg.get("daily_dir", "memory")
        if isinstance(daily_dir, str) and daily_dir.strip():
            daily = (self.workspace / daily_dir).resolve()
            if daily.is_dir() and daily.is_relative_to(self.workspace):
                for candidate in daily.rglob("*.md"):
                    try:
                        path = candidate.resolve()
                    except OSError:
                        continue
                    if path.is_file() and path.is_relative_to(self.workspace):
                        files.add(path)
        files = sorted(files)
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if needle and needle not in text.casefold():
                continue
            line = next((i for i, value in enumerate(text.splitlines(), 1) if not needle or needle in value.casefold()), 1)
            lines = text.splitlines()
            start = max(line - 2, 0)
            end = min(start + 5, len(lines))
            hits.append({"path": _relative(path, self.workspace), "line": line, "snippet": "\n".join(lines[start:end]), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        # Session memory indexes are optional. Search text-bearing columns while
        # tolerating unrelated SQLite files and schema versions.
        for candidate in sorted(self.workspace.glob("**/*.sqlite")):
            try:
                dbpath = candidate.resolve()
            except OSError:
                continue
            if not dbpath.is_file() or not dbpath.is_relative_to(self.workspace):
                continue
            if dbpath.name == "session.sqlite" and dbpath.parent.name == ".openclaw":
                continue
            try:
                with sqlite3.connect(dbpath) as db:
                    tables = [r[0] for r in db.execute("select name from sqlite_master where type='table'")]
                    for table in tables:
                        cols = [r[1] for r in db.execute(f'pragma table_info("{table.replace(chr(34), chr(34) * 2)}")')]
                        text_col = next((c for c in ("content", "text", "body", "value") if c in cols), None)
                        if not text_col:
                            continue
                        rows = db.execute(f'select "{text_col.replace(chr(34), chr(34) * 2)}" from "{table.replace(chr(34), chr(34) * 2)}"').fetchall()
                        for (value,) in rows:
                            value = str(value or "")
                            if needle and needle not in value.casefold():
                                continue
                            hits.append({"path": _relative(dbpath, self.workspace), "table": table, "snippet": value[:1000], "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()})
            except (OSError, sqlite3.Error):
                continue
        return {"ok": True, "tool": "memory_search", "query": query, "offset": offset, "limit": limit, "total": len(hits), "results": hits[offset : offset + limit]}
