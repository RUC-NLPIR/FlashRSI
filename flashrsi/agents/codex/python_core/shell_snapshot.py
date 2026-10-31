"""Shell startup snapshots from Codex rust-v0.147.0 (be6e8eac).

Sources: core/src/shell_snapshot.rs, environment_selection.rs,
session/turn_context.rs, tools/runtimes/mod.rs, shell-command/src/shell_detect.rs.
Snapshot building is background work: shell execution only peeks at a completed
result, never waits for startup capture. Runtime files stay outside Snapshot.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

SNAPSHOT_TIMEOUT = 10
SNAPSHOT_RETENTION = 3 * 24 * 60 * 60
PROXY_ACTIVE = "CODEX_NETWORK_PROXY_ACTIVE"
PROXY_KEYS = (
    PROXY_ACTIVE,
    "CODEX_NETWORK_PROXY_CREDENTIAL_BROKER_ACTIVE",
    "CODEX_NETWORK_PROXY_BROKERED_CREDENTIALS",
    "CODEX_NETWORK_ALLOW_LOCAL_BINDING",
    "CODEX_NETWORK_PROXY_ATTRIBUTION",
    "ELECTRON_GET_USE_PROXY",
    "NODE_USE_ENV_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "YARN_HTTP_PROXY",
    "YARN_HTTPS_PROXY",
    "npm_config_http_proxy",
    "npm_config_https_proxy",
    "npm_config_proxy",
    "NPM_CONFIG_HTTP_PROXY",
    "NPM_CONFIG_HTTPS_PROXY",
    "NPM_CONFIG_PROXY",
    "BUNDLE_HTTP_PROXY",
    "BUNDLE_HTTPS_PROXY",
    "PIP_PROXY",
    "DOCKER_HTTP_PROXY",
    "DOCKER_HTTPS_PROXY",
    "WS_PROXY",
    "WSS_PROXY",
    "ws_proxy",
    "wss_proxy",
    "NO_PROXY",
    "no_proxy",
    "npm_config_noproxy",
    "NPM_CONFIG_NOPROXY",
    "YARN_NO_PROXY",
    "BUNDLE_NO_PROXY",
    "ALL_PROXY",
    "all_proxy",
    "FTP_PROXY",
    "ftp_proxy",
    "CODEX_CA_CERTIFICATE",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "GIT_SSL_CAINFO",
    "CARGO_HTTP_CAINFO",
    "PIP_CERT",
    "BUNDLE_SSL_CA_CERT",
    "npm_config_cafile",
    "NPM_CONFIG_CAFILE",
)


def shell_type(path):
    name = str(path)
    while True:
        if name in {"zsh", "bash", "sh", "pwsh", "powershell", "cmd"}:
            return {"pwsh": "powershell"}.get(name, name)
        stem = Path(name).stem
        if stem == name:
            return None
        name = stem


def user_shell_path():
    if os.name == "posix":
        import pwd

        try:
            return pwd.getpwuid(os.getuid()).pw_shell
        except KeyError:
            pass
    return None


def get_shell(kind, provided=None):
    """shell_detect::get_shell_path: provided, passwd, PATH, fixed fallback."""
    if provided and Path(provided).is_file():
        return str(provided)
    account_shell = user_shell_path()
    if (
        account_shell
        and shell_type(account_shell) == kind
        and Path(account_shell).is_file()
    ):
        return account_shell
    names = ("pwsh", "powershell") if kind == "powershell" else (kind,)
    fallbacks = {
        "zsh": ("/bin/zsh",),
        "bash": ("/bin/bash", "/usr/bin/bash"),
        "sh": ("/bin/sh",),
        "powershell": ("/usr/local/bin/pwsh",),
        "cmd": (),
    }
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return next(
        (path for path in fallbacks.get(kind, ()) if Path(path).is_file()), None
    )


def default_shell():
    account_shell = user_shell_path()
    kind = shell_type(account_shell) if account_shell else None
    order = (kind, "zsh", "bash") if sys.platform == "darwin" else (kind, "bash", "zsh")
    for candidate in order:
        if candidate and (path := get_shell(candidate)):
            return path
    return "cmd.exe" if os.name == "nt" else "/bin/sh"


def model_shell(path):
    kind = shell_type(path)
    return (get_shell(kind, path) if kind else None) or (
        "cmd.exe" if os.name == "nt" else "/bin/sh"
    )


def snapshot_script(kind):
    return json.loads(
        Path(__file__)
        .with_name("tool_assets")
        .joinpath("shell_snapshot_scripts.json")
        .read_text()
    )[kind]


def strip_snapshot_preamble(output):
    start = output.find("# Snapshot file")
    if start < 0:
        raise ValueError("Snapshot output missing marker # Snapshot file")
    return output[start:]


async def run_script(
    shell, script, cwd, environment, *, login=True, timeout=SNAPSHOT_TIMEOUT
):
    process = None
    output_complete = False
    try:
        process = await asyncio.create_subprocess_exec(
            shell,
            "-lc" if login else "-c",
            script,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        output, error = await asyncio.wait_for(process.communicate(), timeout)
        output_complete = True
        if process.returncode:
            raise ValueError(
                f"Snapshot command exited with status {process.returncode}: "
                + error.decode("utf-8", "replace")
            )
        return output.decode("utf-8", "replace")
    finally:
        if process is not None and not output_complete:
            # Native Command::kill_on_drop kills this shell PID and drops the
            # output pipes. Successful startup may intentionally leave a
            # redirected service alive; do not terminate its process group.
            # Close the transport on cancellation so an inherited pipe in a
            # surviving child cannot keep process.wait pending indefinitely.
            process._transport.close()
            await process.wait()


def snapshot_session_id(name):
    stem, separator, extension = name.rpartition(".")
    if not separator:
        return None
    if extension in {"sh", "ps1"}:
        return stem.split(".", 1)[0]
    if extension.startswith("tmp-"):
        return stem
    return None


def cleanup_stale_snapshots(home, active_session, *, now=None, stop=None):
    """Filesystem rollout lookup; the Python core currently has no state DB."""
    directory = Path(home) / "shell_snapshots"
    if not directory.exists():
        return
    now = time.time() if now is None else now
    for entry in directory.iterdir():
        if stop is not None and stop.is_set():
            return
        if entry.is_symlink() or not entry.is_file():
            continue
        session = snapshot_session_id(entry.name)
        if session == str(active_session):
            continue
        if session is None:
            entry.unlink(missing_ok=True)
            continue
        # Native rollout lookup rejects an invalid thread UUID.
        uuid.UUID(session)
        rollout = None
        directories = [Path(home) / "sessions"]
        while directories:
            if stop is not None and stop.is_set():
                return
            directory = directories.pop()
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                if stop is not None and stop.is_set():
                    return
                if path.is_dir() and not path.is_symlink():
                    directories.append(path)
                elif path.name.startswith("rollout-") and path.name.endswith(
                    f"-{session}.jsonl"
                ):
                    rollout = path
                    break
            if rollout is not None:
                break
        if rollout is None:
            entry.unlink(missing_ok=True)
            continue
        try:
            modified = rollout.stat().st_mtime
        except OSError:
            continue
        if now - modified >= SNAPSHOT_RETENTION:
            entry.unlink(missing_ok=True)


class ShellSnapshot:
    def __init__(self, home, session, cwd, shell, environment):
        self.home, self.session, self.cwd = Path(home), str(session), Path(cwd)
        self.shell, self.environment = shell, dict(environment)
        self.path = None
        self.failure = None
        self._owners = 1
        self._cleanup_stop = threading.Event()
        self.cleanup_task = asyncio.create_task(self._cleanup())
        self.task = asyncio.create_task(self._build())

    async def _cleanup(self):
        try:
            await asyncio.to_thread(
                cleanup_stale_snapshots,
                self.home,
                self.session,
                stop=self._cleanup_stop,
            )
        except (OSError, ValueError):
            pass

    async def _build(self):
        temporary = None
        try:
            kind = shell_type(self.shell)
            if kind not in {"bash", "zsh", "sh"}:
                return None
            capture_shell = get_shell(kind)
            if not capture_shell:
                return None
            directory = self.home / "shell_snapshots"
            nonce = time.time_ns()
            temporary = directory / f"{self.session}.tmp-{nonce}"
            path = directory / f"{self.session}.{nonce}.sh"
            raw = await run_script(
                capture_shell, snapshot_script(kind), self.cwd, self.environment
            )
            text = strip_snapshot_preamble(raw)
            directory.mkdir(parents=True, exist_ok=True)
            temporary.write_text(text)
            try:
                await run_script(
                    self.shell,
                    f'set -e; . "{temporary}"',
                    self.cwd,
                    self.environment,
                    login=False,
                )
            except (OSError, ValueError, TimeoutError):
                self.failure = "validation_failed"
                return None
            temporary.rename(path)
            self.path = path
            return path
        except (OSError, ValueError, TimeoutError):
            self.failure = "write_failed"
            return None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def peek(self, cwd):
        if Path(cwd) != self.cwd or not self.task.done() or self.task.cancelled():
            return None
        return self.task.result()

    def retain(self):
        # ThreadEnvironments reuses the shared task/file for child agents.
        # Keep the file until the last owning shell releases it, as Arc does.
        if self._owners == 0:
            raise RuntimeError("shell snapshot has already been released")
        self._owners += 1
        return self

    async def close(self):
        if self._owners == 0:
            return
        self._owners -= 1
        if self._owners:
            return
        self._cleanup_stop.set()
        if not self.cleanup_task.done():
            self.cleanup_task.cancel()
        if not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, self.cleanup_task, return_exceptions=True)
        if self.path is not None:
            self.path.unlink(missing_ok=True)


def _quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _exports(prefix, keys):
    captures, restores = [], []
    for index, key in enumerate(sorted(set(keys))):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", key):
            continue
        set_var, value_var = f"{prefix}_SET_{index}", f"{prefix}_{index}"
        captures.append(f'{set_var}="${{{key}+x}}"\n{value_var}="${{{key}-}}"')
        restores.append(
            f'if [ -n "${{{set_var}}}" ]; then export {key}="${{{value_var}}}"; else unset {key}; fi'
        )
    return "\n".join(captures), "\n".join(restores)


def wrap_with_snapshot(
    command, session_shell, snapshot, explicit_overrides, environment, path_prepends=()
):
    """tools::runtimes::maybe_wrap_shell_lc_with_snapshot (POSIX branch)."""
    if (
        os.name != "posix"
        or snapshot is None
        or not Path(snapshot).exists()
        or len(command) < 3
        or command[1] != "-lc"
    ):
        return command
    overrides = dict(explicit_overrides)
    for key in ("CODEX_THREAD_ID", "CODEX_PERMISSION_PROFILE"):
        if key in environment:
            overrides[key] = environment[key]
    captures, restores = _exports(
        "__CODEX_SNAPSHOT_OVERRIDE", (*overrides, "CODEX_PERMISSION_PROFILE")
    )
    proxy_captures, proxy_restores = _exports(
        "__CODEX_SNAPSHOT_PROXY_OVERRIDE", PROXY_KEYS
    )
    captures += (
        f'\n{proxy_captures}\n__CODEX_SNAPSHOT_PROXY_ENV_SET="${{{PROXY_ACTIVE}+x}}"'
    )
    restores += (
        f'\nif [ -n "$__CODEX_SNAPSHOT_PROXY_ENV_SET" ] || [ -n "${{{PROXY_ACTIVE}+x}}" ]; then\n'
        + proxy_restores
        + "\nfi"
    )
    if sys.platform == "darwin":
        key = "GIT_SSH_COMMAND"
        marker = r"CODEX_PROXY_GIT_SSH_COMMAND=1\ *"
        captures += (
            f'\n__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_SET="${{{key}+x}}"\n'
            f'__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND="${{{key}-}}"\n'
            'case "$__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND" in\n'
            f"  {marker}) __CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_LIVE_MARKED=1 ;;\n"
            "  *) __CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_LIVE_MARKED= ;;\nesac"
        )
        restores += (
            f'\ncase "${{{key}-}}" in\n'
            f"  {marker}) __CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_AFTER_MARKED=1 ;;\n"
            "  *) __CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_AFTER_MARKED= ;;\nesac\n"
            'if [ -n "$__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_LIVE_MARKED" ]; then\n'
            f'  if [ -z "${{{key}+x}}" ] || [ -n "$__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_AFTER_MARKED" ]; then\n'
            f'    export {key}="$__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND"\n  fi\n'
            'elif [ -n "$__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_AFTER_MARKED" ]; then\n'
            '  if [ -n "$__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND_SET" ]; then\n'
            f'    export {key}="$__CODEX_SNAPSHOT_PROXY_GIT_SSH_COMMAND"\n'
            f"  else\n    unset {key}\n  fi\nfi"
        )
    if "PATH" not in explicit_overrides:
        for entry in path_prepends:
            if entry:
                entry = _quote(str(entry))
                restores += f'\nif [ -n "${{PATH:-}}" ]; then export PATH={entry}:"$PATH"; else export PATH={entry}; fi'
    script = (
        captures
        + f"\n\nif . {_quote(str(snapshot))} >/dev/null 2>&1; then :; fi\n\n"
        + restores
        + f"\n\nexec {_quote(command[0])} -c {_quote(command[2])}"
        + "".join(" " + _quote(arg) for arg in command[3:])
    )
    return [session_shell, "-c", script]
