"""Pinned shell snapshot capture, restore, and background lifecycle behavior."""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import time
import uuid
from pathlib import Path

import pytest
from test_codex_core_parity import _events, _responses_server
from test_codex_python_resources import home as home

from flashrsi.agents.codex.python_core import shell_snapshot as snapshot
from flashrsi.agents.codex.python_core.loop import close_session, run_session
from flashrsi.agents.codex.python_core.shell import Shell


def run(awaitable):
    return asyncio.run(awaitable)


def environment(tmp_path, **extra):
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "ZDOTDIR": str(tmp_path),
        **extra,
    }


def test_snapshot_preamble_and_legacy_generation_names():
    assert (
        snapshot.strip_snapshot_preamble("noise\n# Snapshot file\nexport X=1\n")
        == "# Snapshot file\nexport X=1\n"
    )
    with pytest.raises(ValueError, match="missing marker"):
        snapshot.strip_snapshot_preamble("missing")
    session = str(uuid.uuid4())
    for suffix in (".sh", ".123.sh", ".tmp-123", ".123.ps1"):
        assert snapshot.snapshot_session_id(session + suffix) == session
    assert snapshot.snapshot_session_id("unrecognized.txt") is None


@pytest.mark.parametrize("kind", ["bash", "sh", "zsh"])
def test_actual_capture_sections_and_multiline_exports(tmp_path, monkeypatch, kind):
    shell = snapshot.get_shell(kind)
    if shell is None:
        pytest.skip(f"{kind} is not installed")
    if kind == "sh":
        original = snapshot.run_script

        async def without_system_login_profile(*args, **kwargs):
            # This case checks the pinned POSIX capture script and exports.
            # A host /etc/profile may contain Bash-only syntax. Login startup
            # remains covered by the real Bash/Zsh and native parity cases.
            kwargs["login"] = False
            return await original(*args, **kwargs)

        monkeypatch.setattr(snapshot, "run_script", without_system_login_profile)

    async def scenario():
        value = (
            "plain-sh-export"
            if kind == "sh"
            else "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----"
        )
        env = environment(tmp_path, BASH_ENV="/dev/null", MULTILINE_CERT=value)
        result = snapshot.ShellSnapshot(tmp_path, uuid.uuid4(), tmp_path, shell, env)
        path = await result.task
        assert result.failure is None
        text = path.read_text()
        assert text.startswith("# Snapshot file")
        for marker in ("# Functions", "# aliases ", "# setopts ", "# exports "):
            assert marker in text
        assert not any(
            line.startswith(("export PWD=", "declare -x PWD=", "export OLDPWD="))
            for line in text.splitlines()
        )
        restored = await snapshot.run_script(
            shell,
            f'. {shlex.quote(str(path))}; printf "%s" "$MULTILINE_CERT"',
            tmp_path,
            env,
            login=False,
        )
        assert restored == value
        await result.close()
        assert not path.exists()

    run(scenario())


def test_bash_capture_filters_invalid_exports(tmp_path):
    async def scenario():
        output = await snapshot.run_script(
            "/bin/bash",
            snapshot.snapshot_script("bash"),
            tmp_path,
            environment(
                tmp_path,
                BASH_ENV="/dev/null",
                VALID_NAME="ok",
                **{
                    "BAD-NAME": "broken",
                    "NEXTEST_BIN_EXE_codex-write-config-schema": "bad",
                },
            ),
            login=False,
        )
        assert 'VALID_NAME="ok"' in output
        assert "BAD-NAME" not in output
        assert "NEXTEST_BIN_EXE_codex-write-config-schema" not in output

    run(scenario())


@pytest.mark.skipif(not Path("/bin/zsh").is_file(), reason="zsh not installed")
def test_zsh_snapshot_preserves_tied_path_and_omits_readonly_path(tmp_path):
    expected = f"{tmp_path}/with spaces/bin:/usr/bin:/bin"
    (tmp_path / ".zshrc").write_text(
        f"export -UT PATH path=({shlex.quote(str(tmp_path / 'with spaces/bin'))} /usr/bin /bin)\n"
    )

    async def scenario():
        env = environment(tmp_path, PATH="/usr/bin:/bin")
        result = snapshot.ShellSnapshot(
            tmp_path, uuid.uuid4(), tmp_path, "/bin/zsh", env
        )
        path = await result.task
        assert path is not None, result.failure
        actual = await snapshot.run_script(
            "/bin/zsh",
            f'. {shlex.quote(str(path))}; printf "%s" "$PATH"',
            tmp_path,
            env,
            login=False,
        )
        assert actual == expected
        assert "export -UT PATH path=" in path.read_text()
        await result.close()
        (tmp_path / ".zshrc").write_text("readonly PATH\n")
        other = snapshot.ShellSnapshot(
            tmp_path, uuid.uuid4(), tmp_path, "/bin/zsh", env
        )
        path = await other.task
        assert path is not None, other.failure
        assert "export -rT PATH path=" not in path.read_text()
        await other.close()

    run(scenario())


def test_snapshot_captures_stdin_as_eof(tmp_path):
    async def scenario():
        status = tmp_path / "stdin-status"
        (tmp_path / ".bashrc").write_text(
            f"read -t 1 -r ignored\nprintf '%s' \"$?\" > {shlex.quote(str(status))}\n"
        )
        script = (
            f"HOME={shlex.quote(str(tmp_path))}; export HOME; "
            + snapshot.snapshot_script("bash")
        )
        output = await snapshot.run_script(
            "/bin/bash", script, tmp_path, environment(tmp_path), timeout=2
        )
        assert status.read_text() == "1"
        assert "# Snapshot file" in output

    run(scenario())


def test_background_snapshot_is_nonblocking_and_cwd_specific(tmp_path, monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = snapshot.run_script

        async def blocked(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(snapshot, "run_script", blocked)
        shell = Shell(
            {"sandbox_mode": "danger-full-access"}, tmp_path, {}, environment(tmp_path)
        )
        shell.start_snapshot(tmp_path / "home")
        await entered.wait()
        command, _ = shell._command({"command": "true"}, "shell_command")
        assert command[1] == "-lc"
        assert shell.snapshot.peek(tmp_path) is None
        release.set()
        await shell.snapshot.task
        command, _ = shell._command({"command": "true"}, "shell_command")
        assert command[1] == "-c"
        command, _ = shell._command(
            {"command": "true", "login": False}, "shell_command"
        )
        assert command == [shell.session_shell, "-c", "true"]
        command, _ = shell._command(
            {"command": "true", "workdir": "different"}, "shell_command"
        )
        assert command[1] == "-lc"
        # Patch interception sees the original argv, before the runtime wrapper.
        command, _ = shell._command(
            {"command": "true"}, "shell_command", sandboxed=False
        )
        assert command[1] == "-lc"
        path = shell.snapshot.path
        await shell.reset_processes()
        assert path.exists()
        await shell.close()
        assert not path.exists()

    run(scenario())


def test_cleanup_runs_independently_from_capture_and_can_stop(tmp_path, monkeypatch):
    async def scenario():
        import threading

        entered = threading.Event()

        def blocked(home, active, *, stop):
            entered.set()
            stop.wait(10)

        monkeypatch.setattr(snapshot, "cleanup_stale_snapshots", blocked)
        result = snapshot.ShellSnapshot(
            tmp_path, uuid.uuid4(), tmp_path, "/bin/bash", environment(tmp_path)
        )
        path = await asyncio.wait_for(result.task, 2)
        assert entered.is_set() and path.exists()
        await asyncio.wait_for(result.close(), 1)
        assert not path.exists()

    run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_cancellation_reap_capture_shell(tmp_path, cancel):
    async def scenario():
        pid_path = tmp_path / "pid"
        command = f"printf '%s' $$ > {shlex.quote(str(pid_path))}; sleep 30"
        task = asyncio.create_task(
            snapshot.run_script(
                "/bin/sh",
                command,
                tmp_path,
                environment(tmp_path),
                login=False,
                timeout=0.15 if not cancel else 30,
            )
        )
        deadline = time.monotonic() + 2
        pid = None
        while time.monotonic() < deadline:
            try:
                pid = int(pid_path.read_text())
                break
            except (OSError, ValueError):
                await asyncio.sleep(0.01)
        assert pid is not None
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    run(scenario())


@pytest.mark.parametrize("failure", ["write_failed", "validation_failed"])
def test_failed_snapshot_falls_back_and_removes_temporary_file(
    tmp_path, monkeypatch, failure
):
    async def failed(shell, script, cwd, env, *, login=True, **kwargs):
        if failure == "write_failed" or not login:
            raise ValueError("capture or validation failed")
        return "noise\n# Snapshot file\nexport RSI_TEST=ok\n"

    async def scenario():
        monkeypatch.setattr(snapshot, "run_script", failed)
        result = snapshot.ShellSnapshot(
            tmp_path, uuid.uuid4(), tmp_path, "/bin/sh", environment(tmp_path)
        )
        assert await result.task is None
        assert result.failure == failure
        assert result.peek(tmp_path) is None
        assert not list((tmp_path / "shell_snapshots").glob("*"))
        await result.close()

    run(scenario())


def test_cleanup_retains_active_and_recent_rollouts_only(tmp_path):
    directory = tmp_path / "shell_snapshots"
    directory.mkdir()
    sessions = [str(uuid.uuid4()) for _ in range(4)]
    active, live, stale, orphan = sessions
    for session in sessions:
        (directory / f"{session}.123.sh").write_text("snapshot")
    for session in (active, live, stale):
        rollout = (
            tmp_path
            / "sessions/2025/01/01"
            / f"rollout-2025-01-01T00-00-00-{session}.jsonl"
        )
        rollout.parent.mkdir(parents=True, exist_ok=True)
        rollout.write_text("")
        age = 60 if session == live else snapshot.SNAPSHOT_RETENTION + 60
        os.utime(rollout, (time.time() - age,) * 2)
    (directory / "invalid.txt").write_text("invalid")
    snapshot.cleanup_stale_snapshots(tmp_path, active)
    assert {path.name for path in directory.iterdir()} == {
        f"{active}.123.sh",
        f"{live}.123.sh",
    }


@pytest.mark.parametrize("original_shell", ["/bin/bash", "/bin/sh"])
def test_wrapper_preserves_explicit_environment_thread_and_trailing_args(
    tmp_path, original_shell
):
    path = tmp_path / "snapshot 'quoted'.sh"
    path.write_text(
        "export RSI_SNAPSHOT=old\nexport RSI_SNAPSHOT_ONLY=retained\nexport CODEX_THREAD_ID=stale\nexport CODEX_PERMISSION_PROFILE=stale\nexport PATH=/stale\n"
    )
    env = environment(
        tmp_path,
        RSI_SNAPSHOT="explicit",
        CODEX_THREAD_ID="current",
        PATH="/usr/bin:/bin",
    )
    command = [
        original_shell,
        "-lc",
        'printf "%s|%s|%s|%s|%s|%s" "$RSI_SNAPSHOT" "$RSI_SNAPSHOT_ONLY" "$CODEX_THREAD_ID" "${CODEX_PERMISSION_PROFILE-unset}" "$0" "$1"',
        "arg0 'value'",
        "arg1",
    ]
    wrapped = snapshot.wrap_with_snapshot(
        command, "/bin/sh", path, {"RSI_SNAPSHOT": "explicit"}, env, ["/usr/bin"]
    )
    assert wrapped[:2] == ["/bin/sh", "-c"]

    async def scenario():
        process = await asyncio.create_subprocess_exec(
            *wrapped, cwd=tmp_path, env=env, stdout=asyncio.subprocess.PIPE
        )
        output, _ = await process.communicate()
        assert process.returncode == 0
        assert output.decode() == "explicit|retained|current|unset|arg0 'value'|arg1"

    run(scenario())


def test_wrapper_restores_managed_proxy_and_respects_explicit_path(tmp_path):
    path = tmp_path / "snapshot.sh"
    path.write_text(
        "export CODEX_NETWORK_PROXY_ACTIVE=old\nexport HTTPS_PROXY=stale\nexport SSL_CERT_FILE=stale\nexport PATH=/stale\n"
    )
    env = environment(
        tmp_path,
        CODEX_NETWORK_PROXY_ACTIVE="1",
        HTTPS_PROXY="http://live",
        SSL_CERT_FILE="/live",
        PATH="/usr/bin:/bin",
    )
    command = [
        "/bin/sh",
        "-lc",
        'printf "%s|%s|%s" "$HTTPS_PROXY" "$SSL_CERT_FILE" "$PATH"',
    ]
    wrapped = snapshot.wrap_with_snapshot(
        command, "/bin/sh", path, {"PATH": env["PATH"]}, env, ["/ignored"]
    )

    async def scenario():
        process = await asyncio.create_subprocess_exec(
            *wrapped, env=env, stdout=asyncio.subprocess.PIPE
        )
        output, _ = await process.communicate()
        assert output.decode() == "http://live|/live|/usr/bin:/bin"

    run(scenario())
    path.unlink()
    assert snapshot.wrap_with_snapshot(command, "/bin/sh", path, {}, env) == command


def test_default_shell_uses_account_shell_and_model_override_falls_back(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/fish")
    monkeypatch.setattr(snapshot, "user_shell_path", lambda: "/bin/bash")
    assert snapshot.default_shell() == "/bin/bash"
    assert snapshot.model_shell("/does/not/exist/fish") == "/bin/sh"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/bin/bash.wrapper.sh", "bash"),
        ("/usr/bin/zsh.wrapper.exe", "zsh"),
        ("powershell.wrapper.exe", "powershell"),
        ("/bin/fish.wrapper.sh", None),
        (".bashrc", None),
    ],
)
def test_shell_detection_recurses_through_filename_suffixes(path, expected):
    # Detection strips suffixes only until the first recognized shell name.
    assert snapshot.shell_type(path) == expected


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("parent_closes_first", [False, True])
def test_spawned_agents_share_parent_snapshot_and_file_lifetime(
    tmp_path, home, monkeypatch, version, parent_closes_first
):
    monkeypatch.setattr(snapshot, "user_shell_path", lambda: "/bin/bash")

    async def scenario(replay):
        cache = {}
        settings = {
            "sandbox_mode": "danger-full-access",
            "features": {
                "unified_exec": False,
                "multi_agent_v2": version == "v2",
            },
        }
        env = environment(tmp_path, RSI_SNAPSHOT_VALUE="parent-capture")
        request = {
            "home": str(home),
            "cwd": str(tmp_path),
            "settings": settings,
            "llm": {
                "model_name": "gpt-5.4",
                "api_key": "local-snapshot-test-key",
                "base_url": replay.base_url,
            },
            "environment": env,
            "prompt": "Prepare the parent shell environment.",
            "_session_cache": cache,
        }
        replay.reset([(200, _events(text="PARENT_READY"))])
        try:
            parent = await run_session(request, lambda event: None)
            assert parent["status"] == "finished", parent
            router, manager = cache["router"], cache["subagents"]
            captured = router.shell.snapshot
            path = await captured.task
            assert path is not None, captured.failure
            # A new capture would observe the changed environment and shell;
            # inherited ready environments retain the parent's values instead.
            env["RSI_SNAPSHOT_VALUE"] = "new-capture-would-be-wrong"
            monkeypatch.setattr(snapshot, "user_shell_path", lambda: "/bin/sh")
            replay.reset(
                [
                    (
                        200,
                        _events(
                            call=(
                                "shell_command",
                                {"command": 'printf "%s" "$RSI_SNAPSHOT_VALUE"'},
                            )
                        ),
                    ),
                    (200, _events(text="CHILD_READY")),
                ]
            )
            arguments = {"message": "Read the captured shell environment."}
            if version == "v2":
                arguments.update(task_name="worker", fork_turns="none")
            spawned = await manager.spawn_agent(arguments)
            child = (
                manager._target(spawned["task_name"])
                if version == "v2"
                else manager.tree[spawned["agent_id"]]
            )
            await child.task
            assert child.status == {"completed": "CHILD_READY"}
            child_shell = child.request["_session_cache"]["router"].shell
            assert child_shell.snapshot is captured
            assert child_shell.session_shell == "/bin/bash"
            output = next(
                item["output"]
                for item in replay.requests[-1]["body"]["input"]
                if item.get("type") == "function_call_output"
            )
            assert "parent-capture" in output
            assert "new-capture-would-be-wrong" not in output
            if version == "v2":
                # Eviction releases the child's shell actor; reload must retain
                # the still-live parent task rather than use a dead file or
                # execute startup capture again.
                manager.config["max_concurrent_threads_per_session"] = 2
                replay.reset([(200, _events(text="EVICTOR_READY"))])
                evictor = await manager.spawn_agent(
                    {"task_name": "evictor", "message": "Wait", "fork_turns": "none"}
                )
                await manager._target(evictor["task_name"]).task
                assert not child.loaded and child_shell.closed
                assert path.exists()
                replay.reset(
                    [
                        (
                            200,
                            _events(
                                call=(
                                    "shell_command",
                                    {"command": 'printf "%s" "$RSI_SNAPSHOT_VALUE"'},
                                )
                            ),
                        ),
                        (200, _events(text="CHILD_RELOADED")),
                    ]
                )
                await manager.followup_task(
                    {"target": "worker", "message": "Read the environment again."}
                )
                await child.task
                assert child.status == {"completed": "CHILD_RELOADED"}
                child_shell = child.request["_session_cache"]["router"].shell
                assert child_shell.snapshot is captured
                assert "parent-capture" in next(
                    item["output"]
                    for item in replay.requests[-1]["body"]["input"]
                    if item.get("type") == "function_call_output"
                )
            if parent_closes_first:
                await router.close()
                await router.close()
                survivor = child_shell
            else:
                await manager._close(child)
                await child_shell.close()
                survivor = router.shell
            assert path.exists(), "the surviving actor still owns the snapshot"
            assert (
                await survivor.shell_command(
                    {"command": 'printf "%s" "$RSI_SNAPSHOT_VALUE"'}
                )
            ).endswith("Output:\nparent-capture")
            await survivor.close()
            assert not path.exists(), "last owner removes the snapshot file"
            assert not replay.errors and not replay.steps
        finally:
            await close_session(cache)

    with _responses_server() as replay:
        run(scenario(replay))


def test_lexical_workdir_normalization_restores_snapshot_without_following_symlinks(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(snapshot, "user_shell_path", lambda: "/bin/bash")

    async def scenario():
        shell = Shell(
            {"sandbox_mode": "danger-full-access"},
            tmp_path,
            {},
            environment(tmp_path, RSI_SNAPSHOT_VALUE="captured"),
        )
        shell.start_snapshot(tmp_path / "home")
        try:
            await shell.snapshot.task
            shell.environment["RSI_SNAPSHOT_VALUE"] = "uncaptured"
            # The nonexistent component must be removed before chdir, just as
            # PathUri::join does. Snapshot lookup sees the normalized parent cwd.
            result = await shell.shell_command(
                {
                    "command": 'printf "%s" "$RSI_SNAPSHOT_VALUE"',
                    "workdir": "does-not-exist/..",
                }
            )
            assert result.endswith("Output:\ncaptured")
            outside = tmp_path / "outside"
            outside.mkdir()
            linked = tmp_path / "linked"
            linked.symlink_to(outside, target_is_directory=True)
            _, cwd = shell._command(
                {"command": "pwd", "workdir": "linked"}, "shell_command"
            )
            assert cwd == linked
        finally:
            await shell.close()

    run(scenario())


def test_successful_capture_preserves_redirected_startup_service(tmp_path):
    async def scenario():
        service = tmp_path / "service.pid"
        command = f"sleep 30 >/dev/null 2>&1 & printf '%s' $! > {shlex.quote(str(service))}; printf done"
        pid = None
        try:
            assert (
                await snapshot.run_script(
                    "/bin/sh", command, tmp_path, environment(tmp_path), login=False
                )
                == "done"
            )
            pid = int(service.read_text())
            os.kill(pid, 0)
        finally:
            if pid is not None:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_interrupted_capture_only_kills_shell_and_drops_child_pipes(tmp_path, cancel):
    async def scenario():
        service = tmp_path / "service.pid"
        parent = tmp_path / "shell.pid"
        command = f"sleep 30 & printf '%s' $! > {shlex.quote(str(service))}; printf '%s' $$ > {shlex.quote(str(parent))}; wait"
        task = asyncio.create_task(
            snapshot.run_script(
                "/bin/sh",
                command,
                tmp_path,
                environment(tmp_path),
                login=False,
                timeout=30 if cancel else 0.15,
            )
        )
        pid = None
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    pid = int(service.read_text())
                    shell_pid = int(parent.read_text())
                    break
                except (OSError, ValueError):
                    await asyncio.sleep(0.01)
            assert pid is not None
            if cancel:
                task.cancel()
            with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
                await asyncio.wait_for(task, 1)
            with pytest.raises(ProcessLookupError):
                os.kill(shell_pid, 0)
            # Tokio kill_on_drop kills the shell itself, not its detached group.
            os.kill(pid, 0)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if pid is not None:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    run(scenario())


@pytest.mark.parametrize("empty_temp", [False, True])
def test_arg0_release_temp_guard_continues_without_helpers(tmp_path, empty_temp):
    async def scenario():
        home = tmp_path / "codex"
        env = environment(
            tmp_path, CODEX_HOME=str(home), TMPDIR="" if empty_temp else str(tmp_path)
        )
        shell = Shell({"sandbox_mode": "danger-full-access"}, tmp_path, {}, env)
        assert shell._patch_helpers is None
        assert shell._helper_dir is None
        assert shell.environment["PATH"] == env["PATH"]
        assert not (home / "tmp/arg0").exists()
        output = await shell.shell_command({"command": "printf ready", "login": False})
        assert "Exit code: 0" in output and output.endswith("ready")
        await shell.close()

    run(scenario())


def test_arg0_temp_guard_does_not_resolve_aliases(tmp_path):
    async def scenario():
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        home = tmp_path / "codex"
        shell = Shell(
            {"sandbox_mode": "danger-full-access"},
            tmp_path,
            {},
            environment(tmp_path, CODEX_HOME=str(home), TMPDIR=str(alias)),
        )
        assert shell._helper_dir.is_dir()
        assert (home / "tmp/arg0").stat().st_mode & 0o777 == 0o700
        await shell.close()

    run(scenario())


def test_arg0_helper_setup_failure_is_best_effort(tmp_path, monkeypatch):
    async def scenario():
        def denied(*args, **kwargs):
            raise PermissionError("arg0 setup denied")

        monkeypatch.setattr(
            "flashrsi.agents.codex.python_core.shell.tempfile.TemporaryDirectory",
            denied,
        )
        shell = Shell(
            {"sandbox_mode": "danger-full-access"}, tmp_path, {}, environment(tmp_path)
        )
        assert shell._patch_helpers is None and shell._helper_dir is None
        output = await shell.shell_command({"command": "printf ready", "login": False})
        assert output.endswith("ready")
        await shell.close()

    run(scenario())
