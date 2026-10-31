"""Fixed framework adapter; the selected Snapshot supplies the Python Codex core."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import signal
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote_from_bytes, urlsplit

from flashrsi.core import Agent, Snapshot, Task, Trajectory
from flashrsi.core.agent import _Execution


def _runtime_home():
    """Keep per-run executable resources outside the system temporary tree."""
    configured = os.environ.get("XDG_CACHE_HOME")
    cache = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ("Library/Caches" if sys.platform == "darwin" else ".cache")
    )
    parent = cache / "flashrsi/codex"
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent.chmod(0o700)
    return TemporaryDirectory(prefix="flashrsi-codex-", dir=parent)


class Codex(Agent):
    """Run the selected Python core in an isolated process for each call."""

    name = "codex"
    description = "Codex with a pinned Python core port, instructions and extensions."
    instruction_file = "AGENTS.md"
    _container_dependencies = (
        "httpx",
        "pillow",
        "tree-sitter",
        "tree-sitter-bash",
    )

    async def rollout(
        self, tasks: Iterable[Task], *, snapshot: Snapshot | None = None
    ) -> tuple[Trajectory, ...]:
        # Keep benchmark inputs independent of online notes. This call-local
        # config also crosses the existing container config transport; a bare
        # ContextVar flag would be lost when Harbor creates a fresh adapter.
        execution = self._execution.get()
        config = copy.deepcopy(self.config)
        config["_codex_evaluation"] = True
        token = self._execution.set(
            _Execution(
                execution.snapshot if execution is not None else self._snapshot,
                None,
                config,
            )
        )
        try:
            return await super().rollout(tasks, snapshot=snapshot)
        finally:
            self._execution.reset(token)

    def _check_container(self) -> None:
        super()._check_container()
        if self.config.get("cli_path"):
            raise ValueError(
                "Codex is implemented entirely in Python; cli_path is unsupported"
            )

    async def _run(self, prompt: str, working_dir: Path | None = None) -> Trajectory:
        if self.config.get("cli_path"):
            raise ValueError(
                "Codex is implemented entirely in Python; cli_path is unsupported"
            )
        from ._python import run

        return await run(self, prompt, working_dir)


def _settings(config, resource_home, task_dir, *, source_root=None):
    llm = config["llm"]
    unsupported = set(llm) - {
        "model_name",
        "api_key",
        "base_url",
        "auth",
        "reasoning_effort",
        "provider_name",
    }
    if unsupported:
        raise ValueError(
            "Unsupported Codex llm fields: " + ", ".join(sorted(unsupported))
        )
    if "max_turns" in config:
        raise ValueError("Codex exec has no max_turns limit; use timeout")
    if "auth_dir" in config:
        raise ValueError(
            "Codex credentials come from llm.api_key; auth_dir is unsupported"
        )
    provider_name = llm.get("provider_name")
    if "provider_name" in llm and (
        not isinstance(provider_name, str) or not provider_name.strip()
    ):
        raise ValueError("Codex llm.provider_name must be a nonempty string")
    base_url = llm.get("base_url") or "https://api.openai.com/v1"
    if provider_name is None:
        hostname = urlsplit(base_url).hostname or ""
        if hostname == "api.openai.com":
            provider_name = "OpenAI"
        elif hostname.endswith((".openai.azure.com", ".services.ai.azure.com")):
            provider_name = "Azure"
        else:
            provider_name = "FlashRSI endpoint"
    native_path = resource_home / "config.toml"
    native = (
        tomllib.loads(native_path.read_text(encoding="utf-8"))
        if native_path.exists()
        else {}
    )
    reserved = {
        "model",
        "model_provider",
        "model_providers",
        "model_reasoning_effort",
        "cli_auth_credentials_store",
        "forced_login_method",
        "sqlite_home",
        "log_dir",
        "chatgpt_base_url",
    }
    if conflicts := reserved & native.keys():
        raise ValueError(
            "config.toml cannot set runtime fields: " + ", ".join(sorted(conflicts))
        )
    # Inherited Codex app/daemon/provider settings must not redirect this role.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CODEX_")
        and key not in {"OPENAI_API_KEY", "OPENAI_BASE_URL"}
    }
    env["CODEX_HOME"] = str(resource_home)
    env["CODEX_SQLITE_HOME"] = str(resource_home.parent / "state")
    task_path = task_dir.resolve()
    task_roots = (task_path, *task_path.parents)
    projects = dict(native.get("projects", {}))
    # Native trust may be selected by the Git/project root instead of the exact
    # cwd. Project config/hooks remain outside the selected harness version;
    # task AGENTS.md and .agents/skills are still ordinary native task inputs.
    for path in task_roots:
        projects[str(path)] = {
            **projects.get(str(path), {}),
            "trust_level": "untrusted",
        }
    overrides = {
        "approval_policy": "never",
        "cli_auth_credentials_store": "file",
        "log_dir": str(resource_home.parent / "logs"),
        "history.persistence": "none",
        "projects": projects,
    }
    # Codex 0.147 has no stdio MCP cwd field. Only explicit paths name resources:
    # a bare identifier may instead be a Python module or an option's value.
    # Overrides apply only to this run; Snapshot config stays portable.
    env["FLASHRSI_TASK_DIR"] = str(task_dir)
    source_root = (
        Path(source_root or config.get("source_dir", Path(__file__).parent))
        .expanduser()
        .resolve()
    )
    mapped_servers = {}
    for name, server in native.get("mcp_servers", {}).items():
        mapped = dict(server)
        if server.get("command"):
            command = server["command"]
            mapped["command"] = _resource_path(command, source_root, resource_home)
            args = server.get("args", [])
            mapped["args"] = [
                _resource_path(arg, source_root, resource_home) for arg in args
            ]
        mapped_servers[name] = mapped
    if mapped_servers:
        # Native dotted overrides split on '.', including inside quoted keys.
        # Pass the whole table so arbitrary server names remain intact.
        overrides["mcp_servers"] = mapped_servers
    # Isolate unrelated host installations, while leaving task project skills
    # available to native discovery. Explicit Snapshot disables still apply.
    ambient = {
        Path.home() / ".agents" / "skills",
        Path.home() / ".codex" / "skills",
        Path("/etc/codex/skills"),
    }
    disabled = [
        {"path": str(path), "enabled": False} for path in _ambient_skills(ambient)
    ]
    configured = [
        {
            **entry,
            "path": _resource_path(entry["path"], source_root, resource_home),
        }
        if "path" in entry
        else dict(entry)
        for entry in native.get("skills", {}).get("config", [])
    ]
    if configured or disabled:
        overrides["skills.config"] = [*configured, *disabled]
    if llm.get("reasoning_effort") is not None:
        overrides["model_reasoning_effort"] = llm["reasoning_effort"]
    auth = llm.get("auth", "api_key")
    if auth == "api_key":
        key = llm.get("api_key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Codex requires the framework role's llm.api_key")
        env["FLASHRSI_CODEX_API_KEY"] = key
        overrides.update(
            {
                "model_provider": "flashrsi",
                "model_providers.flashrsi.name": provider_name,
                "model_providers.flashrsi.base_url": base_url,
                "model_providers.flashrsi.env_key": "FLASHRSI_CODEX_API_KEY",
                "model_providers.flashrsi.wire_api": "responses",
                "model_providers.flashrsi.requires_openai_auth": False,
                "model_providers.flashrsi.supports_websockets": False,
            }
        )
    else:
        raise ValueError(
            "Codex uses framework llm.api_key; native login is not supported"
        )
    return overrides, env, native


def _resource_path(value, source_root, resource_home):
    """Relocate explicit references to files in the selected resource version."""
    path = Path(value)
    if path.is_absolute():
        try:
            relative = path.resolve().relative_to(source_root)
        except ValueError:
            return value  # External executables and dependencies keep their paths.
    elif "/" in value:
        relative = path
    else:
        return value
    target = (resource_home / relative).resolve()
    if target.is_relative_to(resource_home) and (path.is_absolute() or target.exists()):
        return str(target)
    return value


def _ambient_skills(roots):
    """Match native skill discovery, including symlinked skill installations."""
    files = set()
    for root in sorted(roots):
        try:
            if not root.is_dir():
                continue
            root = root.resolve()
            visited = {root}
        except (OSError, RuntimeError):
            continue
        stack, directories, entries, response_bytes = [(root, 0)], 1, 0, 0
        while stack:
            directory, depth = stack.pop(0)
            try:
                children = sorted(directory.iterdir())
            except OSError:
                continue
            for path in children:
                if entries == 20_000:
                    stack.clear()
                    break
                entries += 1
                try:
                    is_directory = path.is_dir()
                    if path.is_symlink() and not is_directory:
                        continue
                    if not is_directory and not path.is_file():
                        continue
                    uri = "file://" + quote_from_bytes(
                        os.fsencode(path), safe="/!$&'()*+,-.:;=@_~"
                    )
                    response_bytes += len(uri.encode()) + 64
                    if response_bytes > 4 * 1024 * 1024:
                        stack.clear()
                        break
                    if path.name == "SKILL.md" and not is_directory:
                        files.add(path.resolve())
                    if is_directory and depth < 6 and not path.name.startswith("."):
                        identity = path.resolve()
                        if identity in visited:
                            continue
                        visited.add(identity)
                        if directories < 2000:
                            directories += 1
                            stack.append((path, depth + 1))
                except (OSError, RuntimeError):
                    continue
    return sorted(files)


def _toml(value):
    """Encode the small native CLI override values, including inline tables."""
    if isinstance(value, dict):
        return "{" + ",".join(f"{_toml(k)}={_toml(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_toml(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


async def _wait_for_group_exit(pid, timeout):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # A child can still be completing exec/sandbox transitions.
            # Signal failures remain errors if the group outlives the wait.
            pass
        await asyncio.sleep(0.05)
    return False


async def _stop(process, *, interrupt_timeout=2):
    """Reap the native process and its children before removing resource files."""
    if os.name == "posix" and process.returncode is not None:
        # Native notify hooks intentionally outlive the main process. Give them
        # a bounded opportunity to finish before tearing down their group/home.
        if await _wait_for_group_exit(process.pid, 2):
            return
    if os.name == "posix" and process.returncode is None:
        # Codex shell tools run in their own process groups. Let the native
        # interrupt handler close those sessions before terminating the CLI.
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=interrupt_timeout)
        except TimeoutError:
            pass
    group_finished = False
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Waiting only for the already-exited parent misses surviving children.
        # Let TERM finish the group before deciding whether KILL is necessary.
        group_finished = await _wait_for_group_exit(process.pid, 2)
    elif process.returncode is None:
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        pass
    if os.name == "posix" and not group_finished:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if not await _wait_for_group_exit(process.pid, 2):
            raise RuntimeError("Codex process group survived forced termination")
    elif os.name != "posix" and process.returncode is None:
        process.kill()
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError as exc:
        raise RuntimeError(
            "Codex process did not exit after forced termination"
        ) from exc
