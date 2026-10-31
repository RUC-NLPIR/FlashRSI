"""Stdio MCP lifecycle and approval semantics from Codex v0.147.0."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import time
from pathlib import Path


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class McpError(RuntimeError):
    pass


class StdioServer:
    def __init__(self, name, config, home, cwd, environment, emit):
        self.name, self.config, self.home, self.cwd = (
            name,
            config,
            Path(home),
            Path(cwd),
        )
        self.environment, self.emit = environment, emit
        self.process = None
        self.pending = {}
        self.counter = 0
        self.reader = self.stderr_reader = None
        self.capabilities = {}
        self.instructions = None

    async def start(self):
        config = self.config
        if config.get("url"):
            raise ValueError(
                "Python Codex core currently supports stdio MCP; streamable HTTP/OAuth is not implemented"
            )
        if config.get("environment_id") not in {None, "local"}:
            raise ValueError(
                "Python Codex core does not support remote MCP execution environments"
            )
        defaults = (
            "HOME",
            "LOGNAME",
            "PATH",
            "SHELL",
            "USER",
            "__CF_USER_TEXT_ENCODING",
            "LANG",
            "LC_ALL",
            "TERM",
            "TMPDIR",
            "TZ",
        )
        names = list(defaults)
        for value in config.get("env_vars", []):
            if isinstance(value, dict):
                if value.get("source") == "remote":
                    raise ValueError(
                        "remote env_vars requires a remote MCP stdio environment"
                    )
                value = value["name"]
            names.append(value)
        env = {key: self.environment[key] for key in names if key in self.environment}
        env.update(config.get("env", {}))
        cwd = Path(config.get("cwd") or self.cwd)
        if not cwd.is_absolute():
            cwd = self.home / cwd
        arguments = []
        for argument in config.get("args", []):
            candidate = self.home / argument
            arguments.append(
                str(candidate)
                if not Path(argument).is_absolute() and candidate.is_file()
                else argument
            )
        command = config["command"]
        if not Path(command).is_absolute() and (self.home / command).is_file():
            command = str(self.home / command)
        self.process = await asyncio.create_subprocess_exec(
            command,
            *arguments,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=10 * 1024 * 1024,
        )
        self.reader = asyncio.create_task(self._read())
        self.stderr_reader = asyncio.create_task(self._stderr())
        result = await self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"elicitation": {"form": {}, "url": {}}},
                "clientInfo": {
                    "name": "codex-mcp-client",
                    "version": "0.147.0",
                    "title": "Codex",
                },
            },
            timeout=config.get("startup_timeout_sec", 10),
        )
        self.capabilities = result.get("capabilities", {})
        self.instructions = result.get("instructions")
        await self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def _stderr(self):
        while line := await self.process.stderr.readline():
            self.emit(
                {
                    "type": "mcp_log",
                    "server": self.name,
                    "message": line.decode(errors="replace").rstrip(),
                }
            )

    async def _read(self):
        error = McpError(f"MCP server {self.name!r} closed its output")
        try:
            while line := await self.process.stdout.readline():
                value = json.loads(line)
                if "method" in value:
                    if "id" in value:
                        if value["method"] == "elicitation/create":
                            await self.send(
                                {
                                    "jsonrpc": "2.0",
                                    "id": value["id"],
                                    "result": {"action": "decline"},
                                }
                            )
                        elif value["method"] == "ping":
                            await self.send(
                                {"jsonrpc": "2.0", "id": value["id"], "result": {}}
                            )
                        else:
                            await self.send(
                                {
                                    "jsonrpc": "2.0",
                                    "id": value["id"],
                                    "error": {
                                        "code": -32601,
                                        "message": "Method not found",
                                    },
                                }
                            )
                    else:
                        self.emit(
                            {
                                "type": "mcp_notification",
                                "server": self.name,
                                "notification": value,
                            }
                        )
                    continue
                future = self.pending.pop(value.get("id"), None)
                if future is not None and not future.done():
                    if "error" in value:
                        future.set_exception(McpError(_json(value["error"])))
                    else:
                        future.set_result(value.get("result", {}))
        except asyncio.CancelledError:
            raise
        except Exception as caught:
            error = McpError(f"MCP {self.name}: {caught}")
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
            self.pending.clear()

    async def send(self, value):
        self.process.stdin.write((_json(value) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params=None, timeout=None):
        self.counter += 1
        request_id = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        value = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            value["params"] = params
        try:
            await self.send(value)
            return await asyncio.wait_for(
                future, timeout or self.config.get("tool_timeout_sec", 60)
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": request_id, "reason": "Request cancelled"},
                }
            )
            raise
        finally:
            self.pending.pop(request_id, None)

    async def list(self, method, key):
        values, params, seen = [], {}, set()
        while True:
            result = await self.request(method, params)
            values.extend(result.get(key, []))
            cursor = result.get("nextCursor")
            if not cursor:
                return values
            if cursor in seen:
                raise McpError(f"MCP {method} repeated pagination cursor")
            seen.add(cursor)
            params = {"cursor": cursor}

    async def close(self):
        if self.process is None:
            return
        self.process.stdin.close()
        if self.process.returncode is None:
            try:
                await asyncio.wait_for(self.process.wait(), 0.5)
            except asyncio.TimeoutError:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self.process.wait(), 1)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await self.process.wait()
        for task in (self.reader, self.stderr_reader):
            if task:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self.reader, self.stderr_reader) if task),
            return_exceptions=True,
        )


def _schema(value):
    if isinstance(value, bool):
        return {"type": "string"}
    if isinstance(value, list):
        return [_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    value = dict(value)
    if "const" in value:
        value["enum"] = [value.pop("const")]
    for key in ("properties", "$defs", "definitions", "patternProperties"):
        if isinstance(value.get(key), dict):
            value[key] = {name: _schema(entry) for name, entry in value[key].items()}
    for key in (
        "items",
        "prefixItems",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
    ):
        if key in value:
            value[key] = _schema(value[key])
    if isinstance(value.get("additionalProperties"), dict):
        value["additionalProperties"] = _schema(value["additionalProperties"])
    if not any(key in value for key in ("type", "$ref", "allOf", "anyOf", "oneOf")):
        value["type"] = "object" if "properties" in value else "string"
    return value


class Mcp:
    def __init__(self, home, cwd, settings, emit, environment, plugins=()):
        self.home, self.cwd, self.settings, self.emit, self.environment = (
            home,
            cwd,
            settings,
            emit,
            environment,
        )
        self.configs = dict(settings.get("mcp_servers", {}))
        self.plugin_names = {}
        for plugin in plugins:
            for name, config in plugin.mcp_servers.items():
                if name in self.configs:
                    emit(
                        {
                            "type": "warning",
                            "message": f"skipping duplicate plugin MCP server name: {name}",
                        }
                    )
                else:
                    self.configs[name] = config
                    self.plugin_names[name] = [plugin.name]
        self.servers = {}
        self.hooks = None

    async def start(self, router):
        for name, config in sorted(self.configs.items()):
            if not config.get("enabled", True):
                continue
            server = StdioServer(
                name, config, self.home, self.cwd, self.environment, self.emit
            )
            try:
                await server.start()
                tools = (
                    await server.list("tools/list", "tools")
                    if "tools" in server.capabilities
                    else []
                )
                self.servers[name] = server
                for tool in sorted(tools, key=lambda tool: tool["name"]):
                    original = tool["name"]
                    if (
                        config.get("enabled_tools") is not None
                        and original not in config["enabled_tools"]
                    ):
                        continue
                    if original in config.get("disabled_tools", []):
                        continue
                    namespace = "mcp__" + re.sub(r"[^a-zA-Z0-9_-]", "_", name)
                    tool_name = re.sub(r"[^a-zA-Z0-9_-]", "_", original)
                    instructions = (server.instructions or "").strip()
                    description = (
                        instructions.encode()[: 512 * 1024].decode(errors="ignore")
                        if instructions
                        else f"Tools in the {namespace} namespace."
                    )
                    spec = {
                        "type": "namespace",
                        "name": namespace,
                        "description": description,
                        "tools": [
                            {
                                "type": "function",
                                "name": tool_name,
                                "description": tool.get("description") or "",
                                "parameters": _schema(
                                    tool.get(
                                        "inputSchema",
                                        {"type": "object", "properties": {}},
                                    )
                                ),
                                "strict": False,
                            }
                        ],
                    }

                    async def call(arguments, server=server, tool=tool):
                        return await self.call(server, tool, arguments)

                    parts = [namespace + tool_name, tool_name, original, name]
                    parts.extend(
                        text.strip()
                        for text in (
                            tool.get("title"),
                            tool.get("description"),
                            server.instructions,
                            *self.plugin_names.get(name, []),
                        )
                        if isinstance(text, str) and text.strip()
                    )
                    properties = tool.get("inputSchema", {}).get("properties", {})
                    parts.extend(
                        sorted(properties) if isinstance(properties, dict) else []
                    )
                    router.register(
                        f"{namespace}__{tool_name}",
                        spec,
                        call,
                        parallel=config.get("supports_parallel_tool_calls", False)
                        or (tool.get("annotations") or {}).get("readOnlyHint", False),
                        deferred=True,
                        search_text=" ".join(parts),
                        source_info={
                            "name": name.strip(),
                            "description": instructions or None,
                        },
                    )
            except (ValueError, KeyError):
                await server.close()
                raise
            except Exception as error:
                await server.close()
                self.emit(
                    {
                        "type": "warning",
                        "message": f"MCP client for `{name}` failed to start: {error}",
                    }
                )
                if config.get("required", False):
                    raise McpError(
                        f"required MCP server {name!r} failed to start: {error}"
                    ) from error
        if self.servers:
            specs = json.loads(
                (
                    Path(self.home)
                    / "python_core/resource_assets/mcp_resource_tools.json"
                ).read_text()
            )
            for name, method, key in (
                ("list_mcp_resources", "resources/list", "resources"),
                (
                    "list_mcp_resource_templates",
                    "resources/templates/list",
                    "resourceTemplates",
                ),
                ("read_mcp_resource", "resources/read", "contents"),
            ):

                async def resource(arguments, method=method, key=key):
                    return await self.resource(method, key, arguments)

                router.register(name, specs[name], resource)

    async def resource(self, method, key, arguments):
        target = (arguments.get("server") or "").strip()
        cursor = (arguments.get("cursor") or "").strip()
        if method == "resources/read":
            uri = (arguments.get("uri") or "").strip()
            if not target or not uri:
                raise ValueError("server and uri must be provided")
            if target not in self.servers:
                raise ValueError(f"unknown MCP server {target!r}")
            result = await self.servers[target].request(method, {"uri": uri})
            return {
                "output": _json({"server": target, "uri": uri, **result}),
                "success": True,
            }
        if cursor and not target:
            raise ValueError("cursor can only be used when a server is specified")
        if target:
            if target not in self.servers:
                raise ValueError(f"unknown MCP server {target!r}")
            result = await self.servers[target].request(
                method, {"cursor": cursor} if cursor else None
            )
            payload = {
                "server": target,
                key: [{"server": target, **entry} for entry in result.get(key, [])],
            }
            if result.get("nextCursor"):
                payload["nextCursor"] = result["nextCursor"]
        else:
            entries = []
            for name, server in sorted(self.servers.items()):
                try:
                    values = await server.list(method, key)
                except Exception as error:
                    self.emit(
                        {
                            "type": "warning",
                            "message": f"Failed to list {key} for MCP server '{name}': {error}",
                        }
                    )
                    continue
                entries.extend({"server": name, **entry} for entry in values)
            payload = {key: entries}
        return {"output": _json(payload), "success": True}

    async def call(self, server, tool, arguments):
        config = server.config
        mode = (
            config.get("tools", {})
            .get(tool["name"], {})
            .get("approval_mode", config.get("default_tools_approval_mode", "auto"))
        )
        annotation = tool.get("annotations") or {}
        read_only = annotation.get("readOnlyHint", False)
        requires = (
            mode == "prompt"
            or (mode == "writes" and not read_only)
            or (
                mode == "auto"
                and (
                    annotation.get("destructiveHint") is True
                    or (
                        not read_only
                        and (
                            annotation.get("destructiveHint", True)
                            or annotation.get("openWorldHint", True)
                        )
                    )
                )
            )
        )
        auto = mode == "approve" or (
            self.settings.get("approval_policy") == "never"
            and self.settings.get("sandbox_mode", "danger-full-access")
            in {"danger-full-access", "external-sandbox"}
        )
        if requires and not auto:
            allowed, rejection = False, None
            if self.hooks is not None:
                _, decisions = await self.hooks.run(
                    "PermissionRequest",
                    matcher_input=f"mcp__{server.name}__{tool['name']}",
                    tool_name=f"mcp__{server.name}__{tool['name']}",
                    tool_input=arguments,
                )
                for result in decisions:
                    decision = result.get("decision")
                    if not isinstance(decision, dict):
                        continue
                    if (
                        decision.get("interrupt")
                        or "updatedInput" in decision
                        or "updatedPermissions" in decision
                    ):
                        self.emit(
                            {
                                "type": "warning",
                                "message": "PermissionRequest hook returned unsupported permission rewrite",
                            }
                        )
                        continue
                    if decision.get("behavior") == "deny":
                        rejection = (
                            decision.get("message") or ""
                        ).strip() or "user rejected MCP tool call"
                        break
                    allowed |= decision.get("behavior") == "allow"
            if rejection or not allowed:
                return {
                    "output": rejection or "user rejected MCP tool call",
                    "success": False,
                }
        started = time.monotonic()
        try:
            result = await server.request(
                "tools/call", {"name": tool["name"], "arguments": arguments}
            )
        except Exception as error:
            return {"output": f"MCP tool call failed: {error}", "success": False}
        content = result.get("structuredContent")
        if content is None:
            content = result.get("content", [])
        output = _json(content)
        if isinstance(content, list) and any(
            item.get("type") in {"image", "audio"} for item in content
        ):
            converted = []
            for item in content:
                kind = item.get("type")
                if kind == "text":
                    converted.append({"type": "input_text", "text": item["text"]})
                elif kind in {"image", "audio"}:
                    key = "image_url" if kind == "image" else "audio_url"
                    url = item["data"]
                    if not url.startswith("data:"):
                        url = f"data:{item.get('mimeType', 'application/octet-stream')};base64,{url}"
                    converted.append(
                        {
                            "type": "input_" + kind,
                            key: url,
                            **({"detail": "high"} if kind == "image" else {}),
                        }
                    )
                else:
                    converted.append({"type": "input_text", "text": _json(item)})
            output = converted
        header = f"Wall time: {time.monotonic() - started:.4f} seconds\nOutput:"
        if isinstance(output, list):
            output.insert(0, {"type": "input_text", "text": header})
        else:
            output = header + ("\n" + output if output else "")
        return {
            "output": output,
            "success": result.get("isError") is not True,
            "mcp_result": result,
        }

    async def close(self):
        await asyncio.gather(*(server.close() for server in self.servers.values()))
