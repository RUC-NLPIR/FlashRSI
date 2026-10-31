from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from flashrsi.agents.codex.python_core.apply_patch import apply_patch_sync, parse_patch
from flashrsi.agents.codex.python_core.shell import (
    Process,
    Sandbox,
    Shell,
    ToolError,
    create_environment,
    truncate,
)
from flashrsi.agents.codex.python_core.tools import (
    ToolRouter,
    exec_spec,
    image_spec,
    plan_spec,
    shell_spec,
)


def run(awaitable):
    return asyncio.run(awaitable)


def router(tmp_path, **settings):
    model = SimpleNamespace(
        info={
            "shell_type": "default",
            "apply_patch_tool_type": "freeform",
            "input_modalities": ["text", "image"],
            "truncation_policy": {"mode": "tokens", "limit": 10000},
        }
    )
    return ToolRouter(
        {"sandbox_mode": "danger-full-access", **settings},
        tmp_path,
        model,
        lambda event: None,
    )


def call(name, **arguments):
    return {
        "type": "function_call",
        "name": name,
        "call_id": "call-1",
        "arguments": json.dumps(arguments),
    }


def test_process_capacity_uses_lru_exited_preference_and_interaction_locks(tmp_path):
    async def scenario():
        shell = Shell({"sandbox_mode": "danger-full-access"}, tmp_path, {})

        def populate(exited=()):
            shell.sessions = {
                index: Process(
                    SimpleNamespace(returncode=0 if index in exited else None),
                    False,
                    None,
                    last_used=float(index),
                )
                for index in range(64)
            }

        populate()
        first = shell.sessions[0]
        first.last_used = 1000
        expected = shell.sessions[1]
        assert shell._prune_processes_if_needed() is expected
        assert 0 in shell.sessions and 1 not in shell.sessions
        assert shell._prune_processes_if_needed() is None

        populate(exited=(10, 63))
        assert shell._prune_processes_if_needed() is not None
        assert 10 not in shell.sessions and 0 in shell.sessions and 63 in shell.sessions

        populate(exited=(10, 20))
        await shell.sessions[10].interaction.acquire()
        expected = shell.sessions[20]
        assert shell._prune_processes_if_needed() is expected
        assert 10 in shell.sessions

        populate(exited=(10,))
        await shell.sessions[10].interaction.acquire()
        # A pending terminal publication may temporarily exceed the soft cap;
        # native Codex preserves live sessions in this case.
        assert shell._prune_processes_if_needed() is None
        assert len(shell.sessions) == 64
        shell.sessions.clear()
        await shell.close()

    run(scenario())


def test_specs_match_explicit_native_oracle_if_present():
    oracle = Path(__file__).parents[1] / ".cache/codex-python/gpt-5.4-request.json"
    if not oracle.exists():
        pytest.skip("explicit local native oracle capture not present")
    body = json.loads(oracle.read_text())["body"]
    body = json.loads(body) if isinstance(body, str) else body
    specs = {tool.get("name"): tool for tool in body["tools"]}
    assert shell_spec() == specs["shell_command"]
    assert plan_spec() == specs["update_plan"]
    assert image_spec(original=True) == specs["view_image"]


def test_tool_selection_features_and_hidden_shell(tmp_path):
    r = router(tmp_path)
    assert [tool.get("name", tool["type"]) for tool in r.specs][:3] == [
        "exec_command",
        "write_stdin",
        "update_plan",
    ]
    assert "shell_command" not in [tool.get("name") for tool in r.specs]
    assert r.supports_parallel(call("exec_command", cmd="true"))
    assert not r.supports_parallel(call("shell_command", command="true"))
    r = router(tmp_path, features={"unified_exec": False})
    assert r.specs[0] == shell_spec()
    r = router(tmp_path, features={"shell_tool": False, "view_image": False})
    assert "exec_command" not in [tool.get("name") for tool in r.specs]
    assert "view_image" not in [tool.get("name") for tool in r.specs]
    assert "login" not in exec_spec(login=False)["parameters"]["properties"]
    assert (
        "additional_permissions"
        in exec_spec(additional=True)["parameters"]["properties"]
    )


def test_shell_exit_workdir_environment_and_timeout(tmp_path):
    # Use the process API to exercise exact environment overrides separately.
    async def direct():
        shell = Shell(
            {"sandbox_mode": "danger-full-access"},
            tmp_path,
            {},
            {"RSI_TEST": "present", "PATH": os.defpath},
        )
        output = await shell.shell_command(
            {"command": "printf '%s:' \"$RSI_TEST\"; pwd; exit 7", "login": False}
        )
        timeout = await shell.shell_command(
            {"command": "printf start; sleep 10", "timeout_ms": 40, "login": False}
        )
        await shell.close()
        return output, timeout

    output, timeout = run(direct())
    assert "Exit code: 7" in output and f"present:{tmp_path}" in output
    assert (
        "Exit code: 124" in timeout
        and "command timed out after" in timeout
        and "start" in timeout
    )


def test_exec_sessions_poll_and_pipe_stdin_refusal(tmp_path):
    async def scenario():
        shell = Shell({"sandbox_mode": "danger-full-access"}, tmp_path, {})
        initial = await shell.exec_command(
            {
                "cmd": "printf first; sleep .4; printf last",
                "yield_time_ms": 1,
                "login": False,
            }
        )
        session = initial["session_id"]
        with pytest.raises(ToolError, match="stdin is closed"):
            await shell.write_stdin({"session_id": session, "chars": "x"})
        final = await shell.write_stdin({"session_id": session})
        with pytest.raises(ToolError, match="Unknown process id"):
            await shell.write_stdin({"session_id": session})
        await shell.close()
        return initial, final

    initial, final = run(scenario())
    assert initial["output"] == "first"
    assert final["output"] == "last" and final["exit_code"] == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX PTY test")
def test_real_pty_and_interactive_stdin(tmp_path):
    async def scenario():
        shell = Shell({"sandbox_mode": "danger-full-access"}, tmp_path, {})
        initial = await shell.exec_command(
            {
                "cmd": "test -t 0 && printf tty; read answer; printf 'got:%s' \"$answer\"",
                "tty": True,
                "yield_time_ms": 250,
                "login": False,
            }
        )
        final = await shell.write_stdin(
            {
                "session_id": initial["session_id"],
                "chars": "hello\n",
                "yield_time_ms": 250,
            }
        )
        await shell.close()
        return initial, final

    initial, final = run(scenario())
    assert "tty" in initial["output"]
    assert "got:hello" in final["output"] and final["exit_code"] == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group test")
def test_cancel_and_close_kill_process_groups(tmp_path):
    async def scenario():
        shell = Shell({"sandbox_mode": "danger-full-access"}, tmp_path, {})
        task = asyncio.create_task(
            shell.exec_command(
                {
                    "cmd": "sleep 30 & echo $! > child.pid; wait",
                    "yield_time_ms": 10000,
                    "login": False,
                }
            )
        )
        for _ in range(100):
            if (tmp_path / "child.pid").exists():
                break
            await asyncio.sleep(0.01)
        child_pid = int((tmp_path / "child.pid").read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not shell.sessions
        # macOS reaps orphaned descendants promptly; Linux may expose zombies.
        for _ in range(100):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            proc = Path(f"/proc/{child_pid}/stat")
            if proc.exists() and proc.read_text().split()[2] == "Z":
                break
            await asyncio.sleep(0.01)
        else:
            os.kill(child_pid, signal.SIGKILL)
            pytest.fail("cancel left a live descendant")
        await shell.close()

    run(scenario())


def test_restricted_sandbox_never_silently_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "unsupported")
    sandbox = Sandbox(
        {
            "sandbox_mode": "workspace-write",
            "sandbox_workspace_write": {
                "exclude_slash_tmp": True,
                "exclude_tmpdir_env_var": True,
            },
        },
        tmp_path,
    )
    with pytest.raises(ToolError, match="refusing to execute"):
        sandbox.wrap(["/bin/sh", "-c", "true"])
    with pytest.raises(PermissionError):
        sandbox.authorize_file(tmp_path.parent / "outside", True)
    with pytest.raises(PermissionError):
        sandbox.authorize_file(tmp_path / ".git/config", True)
    target = tmp_path.parent / "target-outside"
    target.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError):
        sandbox.authorize_file(tmp_path / "escape/file", True)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt test")
def test_seatbelt_enforces_outside_writes(tmp_path):
    async def scenario():
        settings = {
            "sandbox_mode": "workspace-write",
            "sandbox_workspace_write": {
                "exclude_slash_tmp": True,
                "exclude_tmpdir_env_var": True,
            },
        }
        shell = Shell(settings, tmp_path, {})
        outside = tmp_path.parent / "seatbelt-outside"
        output = await shell.shell_command(
            {
                "command": f"printf inside > '{tmp_path / 'inside'}'; printf outside > '{outside}'",
                "login": False,
            }
        )
        await shell.close()
        assert (tmp_path / "inside").read_text() == "inside"
        assert not outside.exists()
        assert "operation not permitted" in output.lower()

    run(scenario())


def test_environment_policy_stages(monkeypatch):
    monkeypatch.setenv("RSI_SECRET", "secret")
    monkeypatch.setenv("RSI_KEEP", "keep")
    policy = {
        "ignore_default_excludes": False,
        "exclude": ["rsi_keep"],
        "set": {"RSI_OVERRIDE": "yes"},
        "include_only": ["RSI_*", "CODEX_THREAD_ID"],
    }
    env = create_environment(
        {"shell_environment_policy": policy, "thread_id": "thread"}
    )
    assert env == {"RSI_OVERRIDE": "yes", "CODEX_THREAD_ID": "thread"}


def test_patch_add_update_move_delete_unicode_eof(tmp_path):
    output, success = apply_patch_sync(
        "*** Begin Patch\n*** Add File: a\n+header\n+say “hi”\n+tail\n*** Add File: gone\n+delete\n*** End Patch",
        tmp_path,
    )
    assert success and "A a\nA gone\n" in output
    patch = '*** Begin Patch\n*** Update File: a\n*** Move to: sub/b\n@@ header\n-say "hi"\n+changed\n tail\n*** End of File\n*** Delete File: gone\n*** End Patch'
    output, success = apply_patch_sync(patch, tmp_path)
    assert success and output.endswith("M sub/b\nD gone\n")
    assert (tmp_path / "sub/b").read_text() == "header\nchanged\ntail\n"
    assert not (tmp_path / "a").exists() and not (tmp_path / "gone").exists()


def test_patch_verification_prevents_earlier_writes(tmp_path):
    (tmp_path / "source").write_text("actual\n")
    patch = "*** Begin Patch\n*** Add File: new\n+must not appear\n*** Update File: source\n@@\n-missing\n+replacement\n*** End Patch"
    output, success = apply_patch_sync(patch, tmp_path)
    assert not success and "Failed to find expected lines" in output
    assert not (tmp_path / "new").exists()
    assert (tmp_path / "source").read_text() == "actual\n"


def test_patch_parser_native_errors_and_heredoc(tmp_path):
    output, success = apply_patch_sync("bad", tmp_path)
    assert (
        not success
        and output
        == "apply_patch verification failed: invalid patch: The first line of the patch must be '*** Begin Patch'"
    )
    with pytest.raises(ValueError, match="Update file hunk for path 'a' is empty"):
        parse_patch("*** Begin Patch\n*** Update File: a\n*** End Patch")
    text = "<<'EOF'\n*** Begin Patch\n*** Add File: empty\n*** End Patch\nEOF"
    assert apply_patch_sync(text, tmp_path)[1]
    assert (tmp_path / "empty").read_bytes() == b""


def test_unknown_payload_plan_image_and_registration(tmp_path):
    async def scenario():
        r = router(tmp_path)
        unknown = await r.execute(call("no_tool"))
        assert unknown == {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "unsupported call: no_tool",
        }
        wrong = await r.execute(call("apply_patch"))
        assert wrong["output"] == "apply_patch handler received unsupported payload"
        bad = await r.execute(
            {
                "type": "function_call",
                "name": "update_plan",
                "call_id": "bad",
                "arguments": "{",
            }
        )
        assert bad["output"].startswith("failed to parse function arguments:")
        assert (
            await r.execute(
                call("update_plan", plan=[{"step": "one", "status": "completed"}])
            )
        )["output"] == "Plan updated"
        image = tmp_path / "image.png"
        data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl9sAAAAASUVORK5CYII="
        )
        image.write_bytes(data)
        result = await r.execute(call("view_image", path=str(image), detail="original"))
        assert result["output"][0]["detail"] == "high"
        assert (
            base64.b64decode(result["output"][0]["image_url"].split(",", 1)[1]) == data
        )

        async def echo(args):
            return {"echo": args["value"]}

        spec = {
            "type": "namespace",
            "name": "mcp__probe",
            "tools": [
                {"type": "function", "name": "echo", "parameters": {"type": "object"}}
            ],
        }
        r.register("mcp__probe.echo", spec, echo)
        result = await r.execute({**call("echo", value=7), "namespace": "mcp__probe"})
        assert json.loads(result["output"]) == {"echo": 7}
        await r.close()

    run(scenario())


def test_router_exec_returns_native_responses_text(tmp_path):
    async def scenario():
        r = router(tmp_path)
        result = await r.execute(call("exec_command", cmd="printf result", login=False))
        await r.close()
        return result

    result = run(scenario())
    assert re.fullmatch(
        r"Chunk ID: [a-f0-9]{6}\nWall time: [0-9.]+ seconds\nProcess exited with code 0\nOriginal token count: 2\nOutput:\nresult",
        result["output"],
    )


def test_utf8_truncation_matches_native_marker():
    assert (
        truncate("abcdefghij", {"mode": "bytes", "limit": 4})
        == "ab…6 chars truncated…ij"
    )
    assert (
        truncate("abcdefghij", {"mode": "tokens", "limit": 1})
        == "ab…2 tokens truncated…ij"
    )
    assert (
        truncate("你好世界", {"mode": "bytes", "limit": 6}) == "你…2 chars truncated…界"
    )


def test_process_reset_preserves_environment_and_reaps_tools(tmp_path):
    async def scenario():
        r = router(tmp_path)
        initial = await r.shell.exec_command(
            {"cmd": "sleep 20", "yield_time_ms": 250, "login": False}
        )
        previous = r.shell
        process = previous.sessions[initial["session_id"]].process
        await r.reset_processes()
        assert process.returncode is not None and not previous.sessions
        assert not r.shell.closed
        result = await r.execute(call("exec_command", cmd="printf reused", login=False))
        assert result["output"].endswith("Output:\nreused")
        assert initial["session_id"] not in r.shell.sessions
        await r.close()

    run(scenario())


def test_native_hook_payload_rewrite_and_background_completion(tmp_path):
    async def scenario():
        events = []
        extra = {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": "hook context"}],
        }

        class Hooks:
            async def before_tool(self, name, arguments, *, call_id, aliases):
                events.append(("before", name, arguments, call_id, aliases))
                if arguments.get("command") == "old":
                    return {"command": "printf new"}, [extra]
                return arguments, []

            async def after_tool(self, name, arguments, output, *, call_id, aliases):
                events.append(("after", name, arguments, call_id, aliases))
                return output, []

        r = router(tmp_path)
        r.hooks = Hooks()
        rewritten = await r.execute(call("shell_command", command="old", login=False))
        assert rewritten["output"].endswith("Output:\nnew")
        assert rewritten["extra_items"] == [extra]
        assert events[0][1:4] == ("Bash", {"command": "old"}, "call-1")
        assert events[1][1:4] == ("Bash", {"command": "printf new"}, "call-1")
        events.clear()
        first = await r.execute(
            call(
                "exec_command",
                cmd="sleep .4; printf done",
                yield_time_ms=250,
                login=False,
            )
        )
        session_id = int(re.search(r"session ID (\d+)", first["output"])[1])
        assert [event[0] for event in events] == ["before"]
        final = await r.execute(
            {**call("write_stdin", session_id=session_id), "call_id": "poll-id"}
        )
        assert final["output"].endswith("Output:\ndone")
        assert [event[0] for event in events] == ["before", "after"]
        assert events[-1][1:4] == (
            "Bash",
            {"command": "sleep .4; printf done"},
            "call-1",
        )
        await r.close()

    run(scenario())


@pytest.mark.parametrize(
    "name,key", [("exec_command", "cmd"), ("shell_command", "command")]
)
def test_shell_patch_interception_uses_pre_hook_rewrite_and_skips_post_hook(
    tmp_path, name, key
):
    async def scenario():
        events = []
        (tmp_path / "sub dir").mkdir()
        patch = "*** Begin Patch\n*** Add File: inside\n+rewritten\n*** End Patch"
        command = "cd 'sub dir' &&\napplypatch <<'PATCH'\n" + patch + "\nPATCH"

        class Hooks:
            async def before_tool(self, name, arguments, *, call_id, aliases):
                events.append(("before", name, arguments, aliases))
                return {"command": command}, []

            async def after_tool(self, *args, **kwargs):
                events.append(("after",))
                return "unexpected post hook", []

        r = router(tmp_path)
        r.hooks = Hooks()
        result = await r.execute(call(name, **{key: "placeholder", "login": False}))
        assert "Success. Updated the following files:\nA inside\n" in result["output"]
        assert (tmp_path / "sub dir/inside").read_text() == "rewritten\n"
        assert events == [("before", "Bash", {"command": "placeholder"}, ())]
        await r.close()

    run(scenario())


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt patch test")
@pytest.mark.parametrize("cwd_argument", ["workdir", "cd"])
def test_shell_patch_selected_cwd_retains_original_sandbox_policy(
    tmp_path, cwd_argument
):
    async def scenario():
        r = router(
            tmp_path,
            sandbox_mode="workspace-write",
            sandbox_workspace_write={
                "exclude_slash_tmp": True,
                "exclude_tmpdir_env_var": True,
            },
        )
        (tmp_path / "nested").mkdir()

        def patch_call(path):
            patch = f"*** Begin Patch\n*** Add File: {path}\n+value\n*** End Patch"
            command = "apply_patch <<'PATCH'\n" + patch + "\nPATCH"
            arguments = {"login": False}
            if cwd_argument == "workdir":
                arguments["workdir"] = str(tmp_path / "nested")
            else:
                command = "cd nested &&\n" + command
            return call("exec_command", cmd=command, **arguments)

        inside = await r.execute(patch_call("inside"))
        assert "Success. Updated" in inside["output"]
        assert (tmp_path / "nested/inside").read_text() == "value\n"
        rejected = await r.execute(patch_call("../../outside"))
        assert "filesystem sandbox denied" in rejected["output"]
        assert not (tmp_path.parent / "outside").exists()
        await r.close()

    run(scenario())


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt patch test")
def test_restricted_patch_executes_python_inside_os_sandbox(tmp_path):
    async def scenario():
        r = router(
            tmp_path,
            sandbox_mode="workspace-write",
            sandbox_workspace_write={
                "exclude_slash_tmp": True,
                "exclude_tmpdir_env_var": True,
            },
        )
        inside = await r.execute(
            {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": "inside",
                "input": "*** Begin Patch\n*** Add File: inside\n+allowed\n*** End Patch",
            }
        )
        assert inside["output"].startswith("Exit code: 0\nWall time: ")
        assert inside["output"].endswith(
            "\nOutput:\nSuccess. Updated the following files:\nA inside\n"
        )
        assert (tmp_path / "inside").read_text() == "allowed\n"
        outside = tmp_path.parent / "patch-outside"
        rejected = await r.execute(
            {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": "outside",
                "input": f"*** Begin Patch\n*** Add File: {outside}\n+denied\n*** End Patch",
            }
        )
        assert "filesystem sandbox denied" in rejected["output"]
        assert not outside.exists()
        await r.close()

    run(scenario())
