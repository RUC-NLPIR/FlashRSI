"""Process, output and sandbox ports from Codex rust-v0.147.0 (be6e8eac).

Sources: core/src/{shell,exec,exec_env}.rs, core/src/unified_exec/*,
protocol/src/shell_environment.rs and sandboxing/src/seatbelt.rs.
No native Codex binary is executed. Restricted shells use the OS sandbox;
unsupported enforcement capabilities raise instead of running unsandboxed.
"""

from __future__ import annotations

import asyncio
import errno
import fnmatch
import json
import os
import random
import shlex
import signal
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .shell_snapshot import (
    ShellSnapshot,
    default_shell,
    model_shell,
    wrap_with_snapshot,
)

OUTPUT_CAP = 1024 * 1024
PROTECTED_NAMES = (".git", ".agents", ".codex")
UNIFIED_EXEC_ENV = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "LANG": "C.UTF-8",
    "LC_CTYPE": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "COLORTERM": "",
    "PAGER": "cat",
    "GIT_PAGER": "cat",
    "GH_PAGER": "cat",
    "CODEX_CI": "1",
}


class ToolError(ValueError):
    pass


def io_error(error: OSError) -> str:
    return (
        f"{os.strerror(error.errno)} (os error {error.errno})"
        if error.errno is not None
        else str(error)
    )


def token_count(text: str | bytes) -> int:
    return (len(text if isinstance(text, bytes) else text.encode("utf-8")) + 3) // 4


def truncate(text: str, policy: dict, *, formatted: bool = False) -> str:
    """utils/{string,output-truncation}: preserve UTF-8 prefix/suffix."""
    data = text.encode("utf-8")
    tokens = policy.get("mode", "tokens") == "tokens"
    budget = max(0, int(policy.get("limit", 10_000))) * (4 if tokens else 1)
    if len(data) <= budget:
        return text
    left = data[: budget // 2].decode("utf-8", "ignore")
    right_budget = budget - budget // 2
    right = data[-right_budget:].decode("utf-8", "ignore") if right_budget else ""
    removed = (
        (len(data) - budget + 3) // 4 if tokens else len(text) - len(left) - len(right)
    )
    result = f"{left}…{removed} {'tokens' if tokens else 'chars'} truncated…{right}"
    if formatted:
        # Rust str::lines does not count a final empty line.
        result = f"Warning: truncated output (original token count: {token_count(data)})\nTotal output lines: {len(text.splitlines())}\n\n{result}"
    return result


def create_environment(settings: dict, base: dict | None = None) -> dict[str, str]:
    """protocol::shell_environment::populate_env (six ordered stages)."""
    policy = settings.get("shell_environment_policy") or settings.get(
        "permissions", {}
    ).get("shell_environment_policy", {})
    inherit = policy.get("inherit", "all")
    core = {
        "PATH",
        "SHELL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "USER",
    }
    environment = {
        key: value
        for key, value in (os.environ if base is None else base).items()
        if inherit == "all" or (inherit == "core" and key.upper() in core)
    }

    def matches(key, patterns):
        return any(
            fnmatch.fnmatchcase(key.lower(), str(pattern).lower())
            for pattern in patterns
        )

    excludes = list(policy.get("exclude", []))
    if not policy.get("ignore_default_excludes", True):
        excludes += ["*KEY*", "*SECRET*", "*TOKEN*"]
    environment = {
        key: value for key, value in environment.items() if not matches(key, excludes)
    }
    environment.update(
        {key: str(value) for key, value in policy.get("set", {}).items()}
    )
    include = policy.get("include_only", [])
    if include:
        environment = {
            key: value for key, value in environment.items() if matches(key, include)
        }
    if settings.get("thread_id"):
        environment["CODEX_THREAD_ID"] = str(settings["thread_id"])
    environment.pop("CODEX_PERMISSION_PROFILE", None)
    return environment


class Sandbox:
    def __init__(self, settings: dict, cwd: Path):
        self.settings = settings
        self.cwd = cwd.resolve()
        configured = settings.get("sandbox_mode", "read-only")
        self.mode = (
            configured.get("type", "read-only")
            if isinstance(configured, dict)
            else configured
        )
        self.options = settings.get("sandbox_workspace_write", {})
        self.network = bool(self.options.get("network_access", False))
        self.write_roots: list[Path] = []
        if self.mode == "workspace-write":
            self.write_roots = [self.cwd] + [
                Path(path).resolve() for path in self.options.get("writable_roots", [])
            ]
            if not self.options.get("exclude_slash_tmp", False):
                self.write_roots.append(Path("/tmp").resolve())
            if not self.options.get("exclude_tmpdir_env_var", False) and os.environ.get(
                "TMPDIR"
            ):
                self.write_roots.append(Path(os.environ["TMPDIR"]).resolve())
        if self.mode not in {
            "read-only",
            "workspace-write",
            "danger-full-access",
            "external-sandbox",
        }:
            raise ToolError(f"unsupported sandbox mode: {self.mode}")
        if self.mode == "external-sandbox":
            raise ToolError(
                "external-sandbox requires an externally enforced sandbox; this Python runtime has no external-sandbox capability"
            )

    def authorize_file(self, path: Path, write: bool):
        """Authorize filesystem operations; shell enforcement is in wrap()."""
        if self.mode == "danger-full-access" or not write:
            return
        resolved = path.resolve()
        for root in self.write_roots:
            if resolved.is_relative_to(root):
                parts = resolved.relative_to(root).parts
                if not parts or parts[0] not in PROTECTED_NAMES:
                    return
        raise PermissionError(f"filesystem sandbox denied write to {path}")

    def permissions(self, args: dict, tool: str):
        permission = args.get("sandbox_permissions", "use_default")
        if permission not in {
            "use_default",
            "require_escalated",
            "with_additional_permissions",
        }:
            raise ToolError(f"unknown sandbox_permissions variant `{permission}`")
        if permission != "use_default":
            policy = self.settings.get("approval_policy", "never")
            native_policy = {
                "never": "Never",
                "on-request": "OnRequest",
                "on-failure": "OnFailure",
                "untrusted": "UnlessTrusted",
            }.get(policy, policy)
            if policy != "on-request":
                wording = "cannot" if tool == "exec_command" else "should not"
                raise ToolError(
                    f"approval policy is {native_policy}; reject command — you {wording} ask for escalated permissions if the approval policy is {native_policy}"
                )
            raise ToolError(
                "command requires approval, but no approval capability is attached to this Python session"
            )
        if args.get("additional_permissions") is not None:
            raise ToolError(
                'additional_permissions requires sandbox_permissions: "with_additional_permissions"'
            )

    def wrap(self, argv: list[str]) -> list[str]:
        if self.mode == "danger-full-access":
            return argv
        if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
            raise ToolError(
                f"{self.mode} sandbox enforcement is unavailable on {sys.platform}; refusing to execute without an OS sandbox"
            )
        if self.settings.get("network") or self.settings.get("permissions", {}).get(
            "file_system"
        ):
            raise ToolError(
                "custom network/filesystem permission profiles are not supported by the Python Seatbelt backend"
            )
        assets = Path(__file__).with_name("tool_assets")
        profile = (assets / "seatbelt_base_policy.sbpl").read_text()
        profile += "\n(allow file-read*)\n"
        for root in self.write_roots:
            # seatbelt::build_seatbelt_access_policy: top-level protected metadata.
            quoted = json.dumps(str(root), ensure_ascii=False)
            restrictions = " ".join(
                f"(require-not (subpath {json.dumps(str(root / name), ensure_ascii=False)}))"
                for name in PROTECTED_NAMES
            )
            profile += (
                f"(allow file-write* (require-all (subpath {quoted}) {restrictions}))\n"
            )
        if self.network:
            profile += (assets / "seatbelt_network_policy.sbpl").read_text()
            profile += "\n(allow network-outbound)\n(allow network-inbound)\n"
        return ["/usr/bin/sandbox-exec", "-p", profile, "--", *argv]


def shell_argv(command: str, shell: str, login: bool) -> list[str]:
    """core::shell::Shell::derive_exec_args."""
    name = Path(shell).stem.lower()
    if name in {"powershell", "pwsh"}:
        return [shell, *([] if login else ["-NoProfile"]), "-Command", command]
    if name == "cmd":
        return [shell, "/c", command]
    return [shell, "-lc" if login else "-c", command]


@dataclass
class Process:
    process: asyncio.subprocess.Process
    tty: bool
    master: int | None
    reader: asyncio.Task | None = None
    output: bytearray = field(default_factory=bytearray)
    omitted: int = 0
    done: asyncio.Event = field(default_factory=asyncio.Event)
    interaction: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)

    def append(self, data: bytes):
        self.output.extend(data)
        if len(self.output) > OUTPUT_CAP:
            excess = len(self.output) - OUTPUT_CAP
            del self.output[OUTPUT_CAP // 2 : OUTPUT_CAP // 2 + excess]
            self.omitted += excess


class Shell:
    """unified_exec::UnifiedExecProcessManager + shell runtime backend."""

    def __init__(
        self,
        settings: dict,
        cwd: Path,
        model_info: dict,
        environment: dict | None = None,
    ):
        self.settings = settings
        self.cwd = cwd.resolve()
        self.model_info = model_info
        # arg0::prepare_path_entry_for_codex_aliases runs before environment
        # policy filtering. Complex scripts use the same patch core through
        # these helpers when invocation.rs deliberately declines interception.
        inherited = dict(os.environ if environment is None else environment)
        helper_home = inherited.get("CODEX_HOME")
        self._patch_helpers = None
        helper_dir = None
        try:
            helper_root = None
            if helper_home:
                # arg0's release guard compares raw paths. Resolving aliases
                # here would change macOS /var versus /private/var behavior.
                temp_value = inherited.get("TMPDIR", "/tmp")
                temp_root = Path(temp_value)
                if not temp_value or Path(helper_home).is_relative_to(temp_root):
                    raise OSError(
                        errno.EINVAL,
                        f"Refusing to create helper binaries under temporary dir {str(temp_root)!r} (codex_home: {helper_home!r})",
                    )
                helper_root = Path(helper_home) / "tmp/arg0"
                helper_root.mkdir(parents=True, exist_ok=True)
                helper_root.chmod(0o700)
            self._patch_helpers = tempfile.TemporaryDirectory(
                prefix="codex-arg0", dir=helper_root
            )
            helper_dir = Path(self._patch_helpers.name)
            executable = helper_dir / "apply_patch"
            executable.write_text(
                "#!/bin/sh\nexec "
                + shlex.quote(sys.executable)
                + " -B "
                + shlex.quote(str(Path(__file__).with_name("apply_patch.py")))
                + ' --standalone "$@"\n'
            )
            executable.chmod(0o700)
            (helper_dir / "applypatch").symlink_to("apply_patch")
            inherited["PATH"] = str(helper_dir) + (
                os.pathsep + inherited["PATH"] if "PATH" in inherited else ""
            )
        except OSError as error:
            print(
                f"WARNING: proceeding, even though we could not create PATH aliases: {error}",
                file=sys.stderr,
            )
            if self._patch_helpers is not None:
                self._patch_helpers.cleanup()
                self._patch_helpers = None
            helper_dir = None
        self.environment = create_environment(settings, inherited)
        self._snapshot_environment = inherited
        self._helper_dir = helper_dir
        self.session_shell = (
            model_shell(settings["shell"]) if settings.get("shell") else default_shell()
        )
        self.snapshot = None
        self.sandbox = Sandbox(settings, self.cwd)
        self.sessions: dict[int, Process] = {}
        self.closed = False

    def start_snapshot(self, home, inherited=None):
        if inherited is not None:
            # Ready parent environments share both the selected shell and the
            # snapshot task, including a disabled snapshot. Do not recapture.
            self.session_shell, snapshot = inherited
            self.snapshot = snapshot.retain() if snapshot is not None else None
            return
        if self.snapshot is None and self.settings.get("features", {}).get(
            "shell_snapshot", True
        ):
            self.snapshot = ShellSnapshot(
                home,
                self.settings.get("thread_id", str(uuid.uuid4())),
                self.cwd,
                self.session_shell,
                self._snapshot_environment,
            )

    def _command(self, args: dict, name: str, *, sandboxed=True):
        self.sandbox.permissions(args, name)
        allow_login = self.settings.get("allow_login_shell", True)
        if args.get("login") is True and not allow_login:
            raise ToolError(
                "login shell is disabled by config; omit `login` or set it to false."
            )
        if self.settings.get("features", {}).get("shell_zsh_fork"):
            raise ToolError(
                "shell_zsh_fork backend is unavailable in the Python runtime"
            )
        # PathUri::join/AbsolutePathBuf::join normalize dots lexically before
        # execution and snapshot lookup; resolving would follow symlinks.
        cwd = Path(os.path.normpath(self.cwd / (args.get("workdir") or "")))
        if name == "shell":
            command = args.get("command")
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(arg, str) for arg in command)
            ):
                raise ToolError(
                    "failed to parse function arguments: command must be an array of strings"
                )
            argv = command
        else:
            key = "cmd" if name == "exec_command" else "command"
            command = args.get(key)
            if not isinstance(command, str):
                raise ToolError(
                    f"failed to parse function arguments: missing field `{key}`"
                )
            shell = (
                model_shell(args["shell"]) if args.get("shell") else self.session_shell
            )
            login = args.get("login")
            argv = shell_argv(command, shell, allow_login if login is None else login)
        if sandboxed and self.snapshot is not None:
            policy = self.settings.get("shell_environment_policy") or self.settings.get(
                "permissions", {}
            ).get("shell_environment_policy", {})
            paths = self.environment.get("PATH", "").split(os.pathsep)
            argv = wrap_with_snapshot(
                argv,
                self.session_shell,
                self.snapshot.peek(cwd),
                policy.get("set", {}),
                self.environment,
                (self._helper_dir,)
                if self._helper_dir is not None and str(self._helper_dir) in paths
                else (),
            )
        return self.sandbox.wrap(argv) if sandboxed else argv, cwd

    async def _start(self, argv, cwd, tty=False, *, unified=False) -> Process:
        if self.closed:
            raise ToolError("shell process manager is closed")
        if os.name != "posix":
            raise ToolError(
                "Python process-group and PTY enforcement is unavailable on this platform"
            )
        master = slave = None
        environment = (
            {**self.environment, **UNIFIED_EXEC_ENV} if unified else self.environment
        )
        try:
            if tty:
                import fcntl
                import pty
                import termios

                master, slave = pty.openpty()
                os.set_blocking(master, False)

                def child_setup():
                    os.setsid()
                    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=cwd,
                    env=environment,
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    preexec_fn=child_setup,
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=cwd,
                    env=environment,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
        except BaseException:
            if master is not None:
                os.close(master)
            raise
        finally:
            if slave is not None:
                os.close(slave)
        entry = Process(process, tty, master)
        entry.reader = asyncio.create_task(self._read(entry))
        return entry

    async def _read(self, entry: Process):
        try:
            if entry.master is None:
                while data := await entry.process.stdout.read(65536):
                    entry.append(data)
            else:
                loop = asyncio.get_running_loop()
                while True:
                    ready = loop.create_future()
                    loop.add_reader(
                        entry.master, lambda: ready.done() or ready.set_result(None)
                    )
                    try:
                        await ready
                        data = os.read(entry.master, 65536)
                    except OSError:
                        break
                    finally:
                        loop.remove_reader(entry.master)
                    if not data:
                        break
                    entry.append(data)
        finally:
            entry.done.set()

    async def _collect(self, entry: Process, milliseconds: int):
        start = time.monotonic()
        waiter = asyncio.create_task(entry.process.wait())
        try:
            await asyncio.wait_for(asyncio.shield(waiter), milliseconds / 1000)
            try:
                await asyncio.wait_for(entry.done.wait(), 0.1)
            except TimeoutError:
                pass
        except TimeoutError:
            pass
        finally:
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        output = bytes(entry.output)
        omitted = entry.omitted
        entry.output.clear()
        entry.omitted = 0
        return output, omitted, time.monotonic() - start

    def _output(self, entry, output, omitted, elapsed, args, session_id=None):
        count = (len(output) + omitted + 3) // 4
        text = output.decode("utf-8", "replace")
        if omitted:
            midpoint = len(text) // 2
            text = (
                text[:midpoint]
                + f"\n... {omitted} bytes omitted ...\n"
                + text[midpoint:]
            )
        requested = args.get("max_output_tokens")
        requested = 10_000 if requested is None else max(0, int(requested))
        policy = self.model_info.get(
            "truncation_policy", {"mode": "tokens", "limit": 10_000}
        )
        policy_tokens = int(policy.get("limit", 10_000)) // (
            4 if policy.get("mode") == "bytes" else 1
        )
        result = {
            "chunk_id": uuid.uuid4().hex[:6],
            "wall_time_seconds": elapsed,
            "original_token_count": count,
            "output": truncate(
                text,
                {"mode": "tokens", "limit": min(requested, policy_tokens)},
                formatted=True,
            ),
        }
        if session_id is not None:
            result["session_id"] = session_id
        else:
            code = entry.process.returncode
            result["exit_code"] = 128 - code if code is not None and code < 0 else code
        return result

    async def exec_command(self, args: dict) -> dict:
        argv, cwd = self._command(args, "exec_command")
        entry = None
        session_id = random.randint(10000, 99999)
        while session_id in self.sessions:
            session_id = random.randint(10000, 99999)
        try:
            entry = await self._start(
                argv, cwd, bool(args.get("tty", False)), unified=True
            )
            pruned = self._prune_processes_if_needed()
            self.sessions[session_id] = entry
            if pruned is not None:
                await self._terminate(pruned)
            output, omitted, elapsed = await self._collect(
                entry, min(30000, max(250, int(args.get("yield_time_ms", 10000))))
            )
            running = entry.process.returncode is None
            result = self._output(
                entry, output, omitted, elapsed, args, session_id if running else None
            )
            if not running:
                self.sessions.pop(session_id, None)
                await self._terminate(entry)
            return result
        except asyncio.CancelledError:
            self.sessions.pop(session_id, None)
            if entry:
                await self._terminate(entry)
            raise
        except OSError as error:
            raise ToolError(
                f"Failed to create unified exec process: {error}"
            ) from error

    def _prune_processes_if_needed(self):
        """Pinned ProcessStore policy: protect eight recent, prefer exited LRU."""
        if len(self.sessions) < 64:
            return None
        candidates = list(self.sessions.items())
        found_locked_exited = False
        while candidates:
            protected = {
                key
                for key, _ in sorted(
                    candidates, key=lambda item: item[1].last_used, reverse=True
                )[:8]
            }
            lru = sorted(
                (item for item in candidates if item[0] not in protected),
                key=lambda item: item[1].last_used,
            )
            if not lru:
                return None
            key, candidate = next(
                (item for item in lru if item[1].process.returncode is not None), lru[0]
            )
            exited = candidate.process.returncode is not None
            if found_locked_exited and not exited:
                return None
            if not candidate.interaction.locked():
                return self.sessions.pop(key)
            found_locked_exited |= exited
            candidates = [
                (item_key, item) for item_key, item in candidates if item_key != key
            ]
        return None

    async def write_stdin(self, args: dict) -> dict:
        session_id = args.get("session_id")
        entry = self.sessions.get(session_id)
        if entry is None:
            raise ToolError(f"write_stdin failed: Unknown process id {session_id}")
        async with entry.interaction:
            entry.last_used = time.monotonic()
            chars = args.get("chars", "")
            if not isinstance(chars, str):
                raise ToolError(
                    "failed to parse function arguments: chars must be a string"
                )
            if chars:
                if not entry.tty:
                    if chars == "\x03":
                        try:
                            os.killpg(entry.process.pid, signal.SIGINT)
                        except ProcessLookupError:
                            pass
                    else:
                        raise ToolError(
                            "write_stdin failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open"
                        )
                else:
                    try:
                        os.write(entry.master, chars.encode("utf-8"))
                        await asyncio.sleep(0.1)
                    except OSError as error:
                        if entry.process.returncode is None:
                            raise ToolError(
                                "write_stdin failed: failed to write to stdin"
                            ) from error
            maximum = int(
                self.settings.get("max_background_terminal_timeout_ms", 300_000)
            )
            milliseconds = int(args.get("yield_time_ms", 250))
            milliseconds = (
                max(5000, min(maximum, milliseconds))
                if not chars
                else max(250, min(30000, milliseconds))
            )
            try:
                output, omitted, elapsed = await self._collect(entry, milliseconds)
                running = entry.process.returncode is None
                result = self._output(
                    entry,
                    output,
                    omitted,
                    elapsed,
                    args,
                    session_id if running else None,
                )
                if not running:
                    self.sessions.pop(session_id, None)
                    await self._terminate(entry)
                return result
            except asyncio.CancelledError:
                self.sessions.pop(session_id, None)
                await self._terminate(entry)
                raise

    async def shell_command(self, args: dict, name="shell_command") -> str:
        argv, cwd = self._command(args, name)
        entry = None
        start = time.monotonic()
        timeout = args.get("timeout_ms", args.get("timeout"))
        timeout = 10000 if timeout is None else int(timeout)
        timed_out = False
        try:
            entry = await self._start(argv, cwd)
            output, omitted, _ = await self._collect(entry, timeout)
            if entry.process.returncode is None:
                timed_out = True
                await self._terminate(entry)
            code = 124 if timed_out else entry.process.returncode
            if code is not None and code < 0:
                if code == -64:
                    code, timed_out = 124, True
                else:
                    raise ToolError(f"execution error: Sandbox(Signal({-code}))")
            elapsed = time.monotonic() - start
            text = output.decode("utf-8", "replace")
            if omitted:
                text = f"... {omitted} bytes omitted ...\n{text}"
            if timed_out:
                text = f"command timed out after {int(elapsed * 1000)} milliseconds\n{text}"
            policy = self.model_info.get(
                "truncation_policy", {"mode": "tokens", "limit": 10_000}
            )
            truncated = truncate(text, policy)
            sections = [
                f"Exit code: {code}",
                f"Wall time: {round(elapsed, 1):g} seconds",
            ]
            if len(truncated.splitlines()) != len(text.splitlines()):
                sections.append(f"Total output lines: {len(text.splitlines())}")
            return "\n".join([*sections, "Output:", truncated])
        finally:
            if entry:
                await self._terminate(entry)

    async def _terminate(self, entry: Process):
        try:
            os.killpg(entry.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await entry.process.wait()
        if entry.reader:
            try:
                await asyncio.wait_for(asyncio.shield(entry.reader), 0.2)
            except TimeoutError:
                entry.reader.cancel()
            await asyncio.gather(entry.reader, return_exceptions=True)
        if entry.master is not None:
            os.close(entry.master)
            entry.master = None

    async def reset_processes(self):
        entries = list(self.sessions.values())
        self.sessions.clear()
        await asyncio.gather(*(self._terminate(entry) for entry in entries))

    async def close(self):
        if self.closed:
            return
        self.closed = True
        await self.reset_processes()
        if self.snapshot is not None:
            await self.snapshot.close()
        if self._patch_helpers is not None:
            self._patch_helpers.cleanup()


def exec_response_text(result: dict) -> str:
    """core::tools::context::ExecCommandToolOutput::response_text."""
    sections = []
    if result.get("chunk_id"):
        sections.append(f"Chunk ID: {result['chunk_id']}")
    sections.append(f"Wall time: {result['wall_time_seconds']:.4f} seconds")
    if "exit_code" in result:
        sections.append(f"Process exited with code {result['exit_code']}")
    if "session_id" in result:
        sections.append(f"Process running with session ID {result['session_id']}")
    if "original_token_count" in result:
        sections.append(f"Original token count: {result['original_token_count']}")
    return "\n".join([*sections, "Output:", result["output"]])
