"""Local plugin resources, ported from Codex v0.147.0 (be6e8...).

The store is the resource Snapshot's store; discovery never installs or fetches
plugins and never reads an unrelated host Codex home.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Plugin:
    config_name: str
    name: str
    root: Path
    manifest: dict
    environment: dict[str, str]
    skill_roots: list[Path] = field(default_factory=list)
    hook_sources: list[dict] = field(default_factory=list)
    mcp_servers: dict = field(default_factory=dict)


def _resource(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"plugin resource is outside its package: {value}")
    return path


def _expand(value, environment):
    if isinstance(value, str):
        for key, replacement in environment.items():
            value = value.replace("${" + key + "}", replacement)
        return value
    if isinstance(value, list):
        return [_expand(entry, environment) for entry in value]
    if isinstance(value, dict):
        return {key: _expand(entry, environment) for key, entry in value.items()}
    return value


def _version_key(value):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([^+]+))?(?:\+.*)?", value)
    if match:
        return (
            1,
            *map(int, match.group(1, 2, 3)),
            match.group(4) is None,
            match.group(4) or "",
        )
    return (0, value)


def load_plugins(home: Path, settings: dict) -> list[Plugin]:
    if not settings.get("features", {}).get("plugins", True):
        return []
    plugins = []
    for config_name, config in sorted(settings.get("plugins", {}).items()):
        if not isinstance(config, dict) or not config.get("enabled", False):
            continue
        if not re.fullmatch(r"[\w.-]+@[\w.-]+", config_name):
            raise ValueError(f"invalid plugin configuration name: {config_name}")
        name, marketplace = config_name.split("@")
        base = home / "plugins/cache" / marketplace / name
        versions = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
        if not versions:
            raise ValueError(
                f"enabled plugin {config_name!r} is not installed in the resource Snapshot"
            )
        root = next((p for p in versions if p.name == "local"), None)
        root = (root or max(versions, key=lambda p: _version_key(p.name))).resolve()
        manifest_path = None
        agent_manifest = root / "plugin.json"
        agent_format = False
        if agent_manifest.exists():
            if agent_manifest.is_symlink() or not agent_manifest.is_file():
                raise ValueError(f"invalid plugin manifest: {agent_manifest}")
            value = json.loads(agent_manifest.read_text())
            schema = value.get("$schema", "")
            if schema.startswith("https://agent-plugins.org/schemas/"):
                if (
                    schema
                    != "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
                ):
                    raise ValueError(f"unsupported Agent Plugin schema: {schema}")
                manifest_path, agent_format = agent_manifest, True
        if manifest_path is None:
            manifest_path = next(
                (
                    root / p
                    for p in (
                        ".codex-plugin/plugin.json",
                        ".claude-plugin/plugin.json",
                        ".cursor-plugin/plugin.json",
                    )
                    if (root / p).is_file()
                ),
                None,
            )
        if manifest_path is None:
            raise ValueError(
                f"enabled plugin {config_name!r} has no recognized manifest"
            )
        manifest = json.loads(manifest_path.read_text())
        plugin_name = manifest.get("name", "").strip()
        if not plugin_name:
            raise ValueError(f"plugin name is missing: {manifest_path}")
        data = home / "plugins/data" / f"{name}-{marketplace}"
        if agent_format:
            digest = hashlib.sha256((marketplace + "\0" + name).encode()).hexdigest()[
                :32
            ]
            data = home / "plugins/data/agent-plugins" / digest
        data.mkdir(parents=True, exist_ok=True)
        environment = {
            "PLUGIN_ROOT": str(root),
            "PLUGIN_DATA": str(data),
            "CLAUDE_PLUGIN_ROOT": str(root),
            "CLAUDE_PLUGIN_DATA": str(data),
        }
        plugin = Plugin(config_name, plugin_name, root, manifest, environment)
        paths = manifest.get("skills", ["skills"])
        if isinstance(paths, str):
            paths = [paths]
        for value in paths:
            path = _resource(root, value)
            if path.exists():
                plugin.skill_roots.append(path)
        hooks = manifest.get("hooks", "hooks/hooks.json")
        if isinstance(hooks, (str, dict)):
            hooks = [hooks]
        for value in hooks:
            if isinstance(value, str):
                path = _resource(root, value)
                if not path.is_file():
                    continue
                value = json.loads(path.read_text())
            plugin.hook_sources.append(value)
        servers = manifest.get("mcpServers", ".mcp.json")
        if isinstance(servers, str):
            path = _resource(root, servers)
            servers = json.loads(path.read_text()) if path.is_file() else {}
        servers = servers.get("mcpServers", servers)
        for server_name, server in _expand(servers, environment).items():
            if server_name in plugin.mcp_servers:
                raise ValueError(f"duplicate plugin MCP server: {server_name}")
            server.setdefault("env", {}).update(environment)
            # The native loader resolves relative plugin commands in the package.
            command = server.get("command")
            if command and (root / command).is_file():
                server["command"] = str(root / command)
            plugin.mcp_servers[server_name] = server
        if manifest.get("apps") or (root / ".app.json").exists():
            raise ValueError(
                "Python Codex core does not yet support plugin app connectors"
            )
        plugins.append(plugin)
    return plugins
