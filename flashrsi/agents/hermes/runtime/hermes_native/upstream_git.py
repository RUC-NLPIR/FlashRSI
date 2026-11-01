"""Original Hermes read-only Git isolation policy with a stdlib process bridge.

Only the probe plumbing used by coding-context workspace rendering is retained.
RESOURCE_SOURCES.json records the original definitions and bridge adaptation.
Git is optional: missing commands/timeouts yield an empty probe as upstream.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

IS_WINDOWS = sys.platform == "win32"

_CREATE_NO_WINDOW = 0x08000000


def windows_hide_flags() -> int:
    """Win32 creationflags hiding the child's console without detaching it; 0 elsewhere.

    For short-lived synchronous helpers (``taskkill``, ``where``, version probes): no flash, but the
    child stays in the parent's process group and job so Ctrl+C and job teardown still propagate.
    Stdio is inherited, so ``capture_output=True`` works.
    """
    return _CREATE_NO_WINDOW if IS_WINDOWS else 0


NO_LAZY_FETCH_ENV = {"GIT_NO_LAZY_FETCH": "1"}

_GIT_CONFIG_INJECT_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

_GIT_CONFIG_OVERRIDES = {
    "credential.helper": "",
    "core.askPass": "",
    "core.fsmonitor": "false",
    "core.untrackedCache": "false",
    "core.hooksPath": os.devnull,
    "core.pager": "cat",
    "core.editor": "true",
    "sequence.editor": "true",
    "diff.external": "",
    # ssh itself bypasses stdin=DEVNULL/GIT_TERMINAL_PROMPT and opens /dev/tty directly — an
    # unknown host key (or password auth) prompts there and steals the caller's terminal (#104591).
    # BatchMode makes ssh fail instead of prompting; a working ssh-agent still succeeds. Injected
    # at the config layer so an explicit user GIT_SSH_COMMAND (env) still takes precedence.
    "core.sshCommand": "ssh -o BatchMode=yes",
}


def _safe_directory_cache_key(env: Mapping[str, str]) -> tuple:
    """Everything that decides which files ``git config --system/--global`` reads, plus the
    global candidates' mtimes so an edit to ``~/.gitconfig`` is picked up without a restart."""
    home = env.get("HOME", "")
    xdg = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    candidates = (
        env.get("GIT_CONFIG_SYSTEM") or "/etc/gitconfig",
        env.get("GIT_CONFIG_GLOBAL") or os.path.join(home, ".gitconfig"),
        os.path.join(xdg, "git", "config"),
    )
    stamps = []
    for path in candidates:
        try:
            stamps.append(os.stat(path).st_mtime_ns)
        except OSError:
            stamps.append(None)
    return (
        env.get("GIT_CONFIG_GLOBAL"),
        env.get("GIT_CONFIG_SYSTEM"),
        env.get("GIT_CONFIG_NOSYSTEM"),
        home,
        env.get("XDG_CONFIG_HOME"),
        env.get("PATH"),
        *stamps,
    )


_safe_directory_cache: dict[tuple, list[str]] = {}


def _user_safe_directories(base_env: Mapping[str, str]) -> list[str]:
    """The user's configured ``safe.directory`` values, in git's own effective order.

    Read with ``git config -z --get-all`` under *base_env* (the caller's untouched environment) so
    an explicit ``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM`` still points at the file the user means.
    Best-effort: any failure (git missing, malformed config, timeout) yields no entries and leaves
    the caller exactly as it behaved before. Memoised per process on the inputs that select the
    config files (and the global file's mtime): ``noninteractive_git_env()`` runs on every internal
    git call, including the startup banner probe, and two ``git config`` children per call is
    ~10 ms against ~0.2 ms for the rest of the function.

    ``safe.directory`` is an *ordered* multi-valued setting and an empty value resets every entry
    seen so far, so a user can revoke a system-wide ``safe.directory=*`` and then name only the
    repositories they actually trust. Order and empty resets are therefore policy, not formatting:
    scopes are read lowest-precedence first (system, then global) and every value is preserved
    verbatim -- no de-duplication (it is a sequence, not a set) and no dropping of the reset
    marker, either of which would resurrect a revoked wildcard and widen trust. ``-z`` keeps a
    value containing whitespace or a newline as the single entry git reads it as.
    """
    cache_key = _safe_directory_cache_key(base_env)
    cached = _safe_directory_cache.get(cache_key)
    if cached is not None:
        return list(cached)
    env = dict(base_env)
    # --get-all itself must not be derailed by ambient injection or an interactive prompt.
    for key in list(env):
        if key == "GIT_CONFIG_PARAMETERS" or key.startswith(
            _GIT_CONFIG_INJECT_PREFIXES
        ):
            env.pop(key, None)
    env.pop("GIT_CONFIG_COUNT", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    values: list[str] = []
    for scope in ("--system", "--global"):
        try:
            proc = subprocess.run(
                ["git", "config", scope, "-z", "--get-all", "safe.directory"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                stdin=subprocess.DEVNULL,
                env=env,
                check=False,
                creationflags=windows_hide_flags(),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0:
            continue
        # -z terminates every value with NUL, so the trailing split field is always empty and is
        # not a config entry; interior empty fields are real reset markers and must survive.
        records = proc.stdout.split("\0")
        if records and records[-1] == "":
            records.pop()
        values.extend(records)
    _safe_directory_cache[cache_key] = list(values)
    return values


def noninteractive_git_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for *internal* git invocations that must never prompt.

    Copy of ``base`` (default ``os.environ``) with ``GIT_TERMINAL_PROMPT=0`` (fail instead of
    prompting), ``GCM_INTERACTIVE=Never`` (no Git Credential Manager dialog), and isolated git
    config: inherited ``GIT_CONFIG_*`` injection, global/system config, pagers, editors, fsmonitor,
    external diff and hooks are all disabled so a user's repo/global config cannot hang or mutate
    Hermes's plumbing calls. ``core.sshCommand`` is pinned to ``ssh -o BatchMode=yes`` so the ssh
    child of a fetch/ls-remote fails instead of prompting — ssh bypasses ``stdin=DEVNULL`` and
    opens ``/dev/tty`` directly (#104591); an agent-authenticated ssh still succeeds, and an
    explicit user ``GIT_SSH_COMMAND`` env var still takes precedence over this config-layer pin.
    ``GIT_ASKPASS``/``SSH_ASKPASS`` env vars are left alone, but OpenSSH BatchMode disables
    passphrase/password prompts, including SSH askpass. Usable keys and ssh-agent authentication
    still work; Git's own working askpass helper is unaffected. Pair with
    ``stdin=subprocess.DEVNULL``. Internal plumbing only — the agent-facing terminal tool has its
    own policy layer and visible PTY.

    Hermes shells out to git from many non-interactive contexts — MCP catalog installs, plugin
    install/update, profile distribution staging, worktree base fetches, desktop review-pane fetch/push.
    When the remote is private, misconfigured, or requires auth, git's default behavior is to prompt on the
    inherited terminal (or via an askpass helper), which silently hangs the operation until its timeout — or
    forever at call sites without one. Ported from openai/codex#34540 / #34612 ("detach non-interactive
    subprocesses from stdin"): a background tool invocation must fail fast with a readable error, not wait
    for input nobody can type.
    """
    env = dict(base if base is not None else os.environ)
    # Captured before the isolation below rewrites GIT_CONFIG_GLOBAL/SYSTEM to /dev/null --
    # reading after that point would resolve the user's config to an empty file.
    safe_directories = _user_safe_directories(base if base is not None else os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    # Drop caller-supplied config injection; the GIT_CONFIG_COUNT block is rebuilt below so
    # ambient -c values cannot re-enable pagers, hooks, fsmonitor, editors or credential prompts.
    for key in list(env):
        if key == "GIT_CONFIG_PARAMETERS" or key.startswith(
            _GIT_CONFIG_INJECT_PREFIXES
        ):
            env.pop(key, None)
    env.pop("GIT_CONFIG_COUNT", None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_PAGER"] = "cat"
    env["PAGER"] = "cat"
    env["GIT_EDITOR"] = "true"
    overrides = list(_GIT_CONFIG_OVERRIDES.items())
    # safe.directory is honoured ONLY from global/system config (git rejects it from repo-level
    # config so a hostile repo cannot self-authorise), and both are blanked just above. Without
    # re-injection every internal git call fails "detected dubious ownership" on any repo whose
    # st_uid != geteuid() -- NFS/CIFS mounts without idmapping, shared checkouts, containers with
    # a remapped uid -- even though the user's own `git config --global --add safe.directory` is
    # correctly set and their interactive git works fine. Carried over the GIT_CONFIG_KEY_n
    # channel, which survives GIT_CONFIG_GLOBAL=/dev/null. Read-only and non-widening: the values
    # are replayed in git's own effective order, empty reset markers included (see
    # _user_safe_directories), so a global reset still revokes a system-wide wildcard exactly as it
    # does for the user's interactive git. Appended last, but the hardening overrides above are
    # distinct keys, so they are unaffected by ordering within safe.directory.
    overrides.extend(("safe.directory", value) for value in safe_directories)
    env["GIT_CONFIG_COUNT"] = str(len(overrides))
    for idx, (key, value) in enumerate(overrides):
        env[f"GIT_CONFIG_KEY_{idx}"] = key
        env[f"GIT_CONFIG_VALUE_{idx}"] = value
    return env


_FILTER_COMMAND_KEY = re.compile(
    r"^filter\..+\.(?:clean|smudge|process)$", re.IGNORECASE
)

_INCLUDE_IF_KEY = re.compile(r"^includeif\..*\.path$", re.IGNORECASE)

_INCLUDE_KEY = re.compile(r"^include(?:if\..*)?\.path$", re.IGNORECASE)

_DISCOVERY_KEYS_REGEXP = (
    r"^(filter\..*\.(clean|smudge|process)|include\.path|includeif\..*\.path)$"
)

_MAX_INCLUDE_TARGETS = 16

_MAX_FILTER_KEYS = 256


def noninteractive_repo_git_env(
    cwd: str | os.PathLike[str],
    base: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    """Harden internal git for one repository, including named clean/smudge/process filters.

    The static environment can pin fixed config keys such as core.fsmonitor and
    core.hooksPath, but a repository chooses filter driver names through .gitattributes.
    Discover the effective filter command keys for this checkout and append empty command
    overrides plus required=false to the already-isolated config block. Discovery is
    bounded and fail-closed: if filter discovery cannot be trusted, callers skip the
    automatic git operation instead of running with only partial hardening.
    """
    env = noninteractive_git_env(base)
    # bounded_probe_run, not subprocess.run: Windows' post-timeout communicate() can deadlock and
    # a bare spawn flashes a console. (Not bounded_git_probe: rc 1 = "no filters" is a verdict.)
    # One probe lists the filter keys and the include paths with their origin file: -z --show-origin
    # yields "file:<origin>", "<key>\n<value>" pairs.
    proc = bounded_probe_run(
        [
            "git",
            "-C",
            str(cwd),
            "config",
            "--includes",
            "--show-origin",
            "-z",
            "--get-regexp",
            _DISCOVERY_KEYS_REGEXP,
        ],
        timeout=2,
        env=env,
    )
    if proc is None or proc.returncode not in (0, 1):
        return None
    names: list[str] = []
    targets: set[Path] = set()
    toplevel: Path | None = None
    fields = proc.stdout.split("\0")
    for origin, entry in zip(fields[0::2], fields[1::2]):
        key, _, value = entry.partition("\n")
        if not _INCLUDE_IF_KEY.fullmatch(key):
            names.append(key)
            continue
        if not origin.startswith("file:"):
            return None
        origin_path = Path(origin[len("file:") :])
        if not origin_path.is_absolute():
            # git prints repo-local origins relative to the worktree top level, not to *cwd*; with a
            # caller-set GIT_DIR/GIT_WORK_TREE they are relative to something else, so refuse.
            if env.get("GIT_DIR") or env.get("GIT_WORK_TREE"):
                return None
            if toplevel is None:
                top = bounded_probe_run(
                    ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                    timeout=2,
                    env=env,
                )
                if top is None or top.returncode != 0:
                    return None
                toplevel = Path(
                    top.stdout.rstrip("\r\n")
                )  # a checkout path may end in a space
            origin_path = toplevel / origin_path
        # A relative include path resolves against the directory of the config file naming it.
        target = (origin_path.parent / os.path.expanduser(value)).resolve()
        if target in targets or not target.exists():
            continue  # already read, or missing (git skips a missing include file)
        if not target.is_file() or len(targets) >= _MAX_INCLUDE_TARGETS:
            return None  # a FIFO/device/directory, or too many targets to read on every call
        targets.add(target)
        probe = bounded_probe_run(
            [
                "git",
                "config",
                "--file",
                str(target),
                "--name-only",
                "-z",
                "--get-regexp",
                _DISCOVERY_KEYS_REGEXP,
            ],
            timeout=2,
            env=env,
        )
        if probe is None or probe.returncode not in (0, 1):
            return None
        found = probe.stdout.split("\0")
        # An include inside an include target would need the same walk again; refuse instead.
        if any(_INCLUDE_KEY.fullmatch(name) for name in found):
            return None
        names.extend(found)

    keys: list[str] = []
    required: list[str] = []
    seen: set[str] = set()
    # Dedup on the exact key name git prints: section and variable lowercased, subsection case kept,
    # and ``[filter "Evil"]`` is a different driver from ``[filter "evil"]``.
    for raw in names:
        key = raw.strip()
        if not key or key in seen or not _FILTER_COMMAND_KEY.fullmatch(key):
            continue
        seen.add(key)
        keys.append(key)
        if len(keys) > _MAX_FILTER_KEYS:
            return None
        required_key = key.rsplit(".", 1)[0] + ".required"
        if required_key not in seen:
            seen.add(required_key)
            required.append(required_key)

    start = int(env["GIT_CONFIG_COUNT"])  # always set by noninteractive_git_env
    overrides = [(key, "") for key in keys] + [(key, "false") for key in required]
    for offset, (key, value) in enumerate(overrides):
        env[f"GIT_CONFIG_KEY_{start + offset}"] = key
        env[f"GIT_CONFIG_VALUE_{start + offset}"] = value
    env["GIT_CONFIG_COUNT"] = str(start + len(overrides))
    return env


def _legacy_kill_process_tree(proc: subprocess.Popen) -> None:
    """Local tree-kill fallback when agent.deadline is unavailable (partial install, cycle)."""
    if not IS_WINDOWS:
        # Verify the child leads its own process group before signalling, never a shared group.
        try:
            import signal as _signal

            pgid = os.getpgid(proc.pid)
            if pgid == proc.pid:
                os.killpg(
                    pgid, _signal.SIGKILL
                )  # windows-footgun: ok — inside `if not IS_WINDOWS` gate
        except Exception:
            pass
    try:
        proc.kill()
    except OSError:
        pass
    if IS_WINDOWS:
        # No identity guard on purpose: *proc* is our own retained Popen handle, so the PID cannot
        # be recycled while we hold it. The fail-closed ``pid_is_hermes`` guard is for BARE pids.
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                timeout=2,
                check=False,
                creationflags=windows_hide_flags(),
            )
        except Exception:
            pass


def kill_and_drain(proc: subprocess.Popen, seconds: float) -> tuple | None:
    """Tree-kill *proc* (:func:`kill_process_tree`), then read what its pipes still hold for at
    most *seconds*: ``(stdout, stderr)``, or ``None`` when a descendant the kill missed still
    holds them. Those pipes are left to ``communicate()``'s reader threads, never closed
    (closing a pipe a thread is reading blocks; a ``with Popen`` exit would close them)."""
    kill_process_tree(proc)
    try:
        return proc.communicate(timeout=seconds)
    except (OSError, ValueError, subprocess.SubprocessError):
        proc.stdin = proc.stdout = proc.stderr = None
        return None


def bounded_git_probe(
    argv: Sequence[str], *, timeout: float, env: Mapping[str, str] | None = None
) -> str:
    """Run a short ``git`` probe and return stripped stdout, or ``""`` on ANY failure.

    On Windows ``run()``'s post-timeout cleanup calls an unbounded ``communicate()``; a suspended
    descendant git.exe holding the pipe handles then blocks forever. Here: bounded ``communicate``,
    tree-kill plus a 1s drain, then abandon the pipes; on POSIX the probe gets its own process
    group so cleanup also takes down credential/remote helpers.

    Security (GHSA-7x36-8jrh-v4pw): these probes run automatically against whatever directory the
    session sits in, before any tool call or trust prompt, and an index refresh executes the
    repo-configured ``core.fsmonitor`` program. Every probe therefore runs under
    :func:`noninteractive_git_env`; diff-rendering callers additionally pass
    :data:`NO_DRIVER_DIFF_FLAGS` (attribute-scoped drivers can't be disabled via env).

    Killing the PATH-resolved launcher can leave a suspended descendant ``git.exe`` holding duplicates of
    the captured stdout/stderr handles, so the pipes never reach EOF and the reader-thread join blocks
    forever. On the Desktop agent-build path (``_start_agent_build → _session_info → branch() → run_git``)
    that turned an optional branch label into ``agent initialization timed out`` (issues #68609 / #66037).
    The normal-path spawn contract mirrors the previous ``run`` call byte-for-byte: PIPE/PIPE/DEVNULL,
    ``text`` with UTF-8 ``errors="replace"`` decoding, and the hidden-window ``creationflags`` on Windows
    only. On POSIX the probe is additionally placed in its own process group (``process_group=0``, Python
    ≥3.11) so timeout cleanup can take down descendants — credential helpers, ``git-remote-https``, hook
    children — with the launcher instead of orphaning them (see :func:`kill_process_tree`; port of
    openai/codex#36793). ``process_group`` only changes which group the child belongs to; it does not detach
    the terminal or alter the fast path.
    """
    result = bounded_probe_run(
        argv,
        timeout=timeout,
        env={**(env or noninteractive_git_env()), **NO_LAZY_FETCH_ENV},
    )
    if result is None or result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def kill_process_tree(proc):
    """Retained stdlib tree cleanup; no installed Hermes deadline service."""
    _legacy_kill_process_tree(proc)


def bounded_probe_run(
    argv,
    *,
    timeout,
    errors="replace",
    env=None,
    cwd=None,
    raise_on_spawn_failure=False,
    input=None,
):
    """Bridge upstream probe I/O directly to stdlib Popen, without PM/runtime services."""
    kwargs = (
        {"creationflags": windows_hide_flags()} if IS_WINDOWS else {"process_group": 0}
    )
    try:
        proc = subprocess.Popen(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors=errors,
            env=dict(env) if env is not None else None,
            cwd=cwd,
            **kwargs,
        )
    except (OSError, ValueError):
        if raise_on_spawn_failure:
            raise
        return None
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except Exception:
        kill_and_drain(proc, 1)
        return None
    return subprocess.CompletedProcess(list(argv), proc.returncode, stdout, stderr)
