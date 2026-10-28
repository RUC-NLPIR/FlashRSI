"""Run native Codex exec with the selected version's instructions and extensions."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory

from flashrsi._records import _redact, _secrets
from flashrsi.core import Agent, Trajectory


class Codex(Agent):
    """Use a fresh native CLI process and resource home for every task or edit."""

    name = "codex"
    description = "Codex with versioned native instructions, skills and extensions."
    instruction_file = "AGENTS.md"
    _container_extra = "codex"

    def _check_container(self) -> None:
        super()._check_container()
        if self.config.get("cli_path"):
            raise ValueError("Container execution installs its own CLI; omit cli_path")

    async def _run(self, prompt: str, working_dir: Path | None = None) -> Trajectory:
        config, llm = self.config, self.config["llm"]
        secrets = sorted(
            set(_secrets(os.environ) + _secrets(config)), key=len, reverse=True
        )
        messages = [
            {"type": "RunInput", "prompt": prompt, "snapshot_id": self.snapshot.id}
        ]
        usage, output, error = {}, "", None
        completed = False
        diagnostic_chunks = []
        process = None
        readers = []
        started = asyncio.get_running_loop().time()

        async def events(stream):
            nonlocal usage, output, error, completed
            while True:
                try:
                    line = await stream.readline()
                except ValueError:
                    error = "Codex JSONL event exceeded the stream limit"
                    # Keep draining so process shutdown cannot block on a full
                    # pipe after a malformed or exceptionally large event.
                    while await stream.read(8192):
                        pass
                    return
                if not line:
                    return
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("event must be an object")
                except (ValueError, UnicodeError) as exc:
                    error = f"Invalid Codex JSONL event: {exc}"
                    continue
                messages.append(_redact(event, secrets))
                if event.get("type") == "item.completed":
                    item = event.get("item", {})
                    if not isinstance(item, dict):
                        error = "Invalid Codex item.completed event"
                        continue
                    if item.get("type") == "agent_message":
                        text = item.get("text", "")
                        if not isinstance(text, str):
                            error = "Invalid Codex agent message text"
                            continue
                        output = text
                elif event.get("type") == "turn.completed":
                    completed = True
                    native = event.get("usage") or {}
                    if not isinstance(native, dict):
                        error = "Invalid Codex turn usage"
                        continue
                    # Codex input_tokens already includes cached input. The
                    # framework's prompt_tokens convention preserves that total.
                    usage = {
                        "prompt_tokens": native.get("input_tokens", 0),
                        "completion_tokens": native.get("output_tokens", 0),
                        "prompt_tokens_details": {
                            "cached_tokens": native.get("cached_input_tokens", 0)
                        },
                    }
                elif event.get("type") == "turn.failed":
                    detail = event.get("error")
                    error = (
                        detail.get("message")
                        if isinstance(detail, dict)
                        else str(detail or "")
                    ) or "Codex turn failed"

        async def diagnostics(stream):
            while chunk := await stream.read(8192):
                diagnostic_chunks.append(chunk)

        with TemporaryDirectory(prefix="flashrsi-codex-") as temporary:
            runtime = Path(temporary).resolve()
            resource_home = runtime / "codex"
            task_dir = working_dir or runtime / "task"
            if working_dir is None:
                task_dir.mkdir()
            try:
                deadline = started + config.get("timeout", 300)
                binary, path_dir = _binary(config)
                shutil.copytree(self.files_dir, resource_home)
                overrides, env, native = _settings(
                    config,
                    resource_home,
                    task_dir,
                    source_root=getattr(self, "_container_source_dir", None),
                )
                if path_dir is not None:
                    env["PATH"] = str(path_dir) + os.pathsep + env.get("PATH", "")
                # Native Codex discovers AGENTS.md, skills/ and rules/ in this
                # home. Auth, caches and transcripts are confined to the copy.
                command = [
                    binary,
                    "exec",
                    "--json",
                    "--strict-config",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "--color",
                    "never",
                    "--cd",
                    str(task_dir),
                    "--model",
                    llm["model_name"],
                    "--sandbox",
                    config.get("sandbox", "workspace-write"),
                ]
                # Hooks are executable resources explicitly selected in this
                # Snapshot. Native trust keys include the temporary home, so a
                # prior home's trust records cannot authorize this copy. Task
                # project hooks remain disabled by its untrusted project config.
                if native.get("hooks") or any(resource_home.rglob("hooks.json")):
                    command.append("--dangerously-bypass-hook-trust")
                for key, value in overrides.items():
                    command.extend(["-c", f"{key}={_toml(value)}"])
                command.append("-")
                # Count preparation and process startup toward the same call
                # budget. Synchronous preparation cannot be interrupted, but
                # must not start a native process after its deadline has passed.
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError
                async with asyncio.timeout_at(deadline):
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        cwd=task_dir,
                        env=env,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        start_new_session=os.name == "posix",
                        limit=16 * 1024 * 1024,
                    )
                    readers = [
                        asyncio.create_task(events(process.stdout)),
                        asyncio.create_task(diagnostics(process.stderr)),
                    ]
                    process.stdin.write(prompt.encode("utf-8"))
                    await process.stdin.drain()
                    process.stdin.close()
                    await process.wait()
                    await asyncio.gather(*readers)
                if process.returncode:
                    error = error or f"Codex process exited with {process.returncode}"
                if not completed:
                    failures = [
                        message.get("message")
                        for message in messages
                        if message.get("type") == "error"
                    ]
                    error = error or next(filter(None, reversed(failures)), None)
                    error = error or "Codex ended without turn.completed"
            except TimeoutError:
                error = f"Codex timed out after {config.get('timeout', 300):g}s"
            except Exception as exc:
                error = str(exc) or type(exc).__name__
            finally:
                if process is not None:
                    try:
                        await _stop(process)
                    except Exception as exc:
                        detail = f"Codex cleanup failed: {exc}"
                        error = f"{error}\n{detail}" if error else detail
                for reader in readers:
                    if not reader.done():
                        reader.cancel()
                if readers:
                    await asyncio.gather(*readers, return_exceptions=True)

        diagnostic_text = b"".join(diagnostic_chunks).decode(errors="replace").rstrip()
        if diagnostic_text:
            # Native skill/MCP/rule warnings can accompany a successful turn.
            # Preserve them so the search can see resources that did not load.
            messages.append({"type": "CodexDiagnostics", "text": diagnostic_text})
            if error:
                error += "\nCodex stderr (tail):\n" + diagnostic_text[-8192:]
        return Trajectory(
            status="error" if error else "finished",
            output=_redact(output, secrets) if not error else "",
            messages=_redact(messages, secrets),
            usage=usage,
            error_message=_redact(error, secrets),
        )


def _binary(config):
    if config.get("cli_path"):
        return str(Path(config["cli_path"]).expanduser().resolve()), None
    try:
        from codex_cli_bin import bundled_codex_path, bundled_path_dir
    except ImportError as exc:
        raise ValueError(
            "Install flashrsi-lite[codex], or set cli_path to a native Codex executable"
        ) from exc
    return str(bundled_codex_path()), bundled_path_dir()


def _settings(config, resource_home, task_dir, *, source_root=None):
    llm = config["llm"]
    unsupported = set(llm) - {
        "model_name",
        "api_key",
        "base_url",
        "auth",
        "reasoning_effort",
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
    # cwd. A trusted ancestor must not load resources from the task project.
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
        # The resource home's global AGENTS.md is still read. This disables
        # implicit task-project instruction discovery, including Worker targets.
        "project_doc_max_bytes": 0,
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
    # Native discovery includes both current .agents/skills and legacy
    # .codex/skills roots, even in untrusted projects. Disable those individual
    # skills while keeping discovery in the selected resource home unchanged.
    ambient = {
        Path.home() / ".agents" / "skills",
        Path.home() / ".codex" / "skills",
        Path("/etc/codex/skills"),
    }
    ambient.update(
        parent / directory / "skills"
        for parent in task_roots
        for directory in (".agents", ".codex")
    )
    disabled = [
        {"path": str(path), "enabled": False} for path in _ambient_skills(ambient)
    ]
    configured = [
        {
            **entry,
            "path": _resource_path(entry["path"], source_root, resource_home),
        }
        for entry in native.get("skills", {}).get("config", [])
    ]
    if configured or disabled:
        overrides["skills.config"] = [*configured, *disabled]
    if llm.get("reasoning_effort"):
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
                "model_providers.flashrsi.name": "FlashRSI endpoint",
                "model_providers.flashrsi.base_url": llm.get("base_url")
                or "https://api.openai.com/v1",
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
    files, visited = set(), set()
    for root in sorted(roots):
        for directory, children, names in os.walk(root, followlinks=True):
            resolved = Path(directory).resolve()
            if resolved in visited:
                children.clear()
                continue
            visited.add(resolved)
            if "SKILL.md" in names:
                files.add((resolved / "SKILL.md").resolve())
    return sorted(files)


def _toml(value):
    """Encode the small native CLI override values, including inline tables."""
    if isinstance(value, dict):
        return "{" + ",".join(f"{_toml(k)}={_toml(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_toml(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


async def _stop(process):
    """Reap the native process and its children before removing resource files."""
    if os.name == "posix" and process.returncode is None:
        # Codex shell tools run in their own process groups. Let the native
        # interrupt handler close those sessions before terminating the CLI.
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            pass
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif process.returncode is None:
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        pass
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.returncode is None:
        process.kill()
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError as exc:
        raise RuntimeError(
            "Codex process did not exit after forced termination"
        ) from exc
