"""Exercise the native shell and its real MiniAgent subprocess lifecycle."""

import asyncio
import fcntl
import json
import os
import shlex
import signal
import sys
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_miniagent import (
    _chat_reply,
    _config,
    _copy_source,
    _responses_reply,
)
from test_miniagent import (
    model_server as model_server,
)

from flashrsi.agents import MiniAgent
from flashrsi.agents.miniagent.tools.shell import call


def _command(code):
    return shlex.join([sys.executable, "-c", code])


def _locking_child(directory):
    """A live descendant owns a lock; even an unreaped zombie releases it."""
    lock = directory / "child.lock"
    ready = directory / "child.ready"
    return _command(
        "import fcntl,time; from pathlib import Path; "
        f"f=open({str(lock)!r}, 'w'); fcntl.flock(f, fcntl.LOCK_EX); "
        f"Path({str(ready)!r}).touch(); time.sleep(30)"
    )


async def _assert_child_stopped(directory):
    assert (directory / "child.ready").exists(), "child never started"
    async with asyncio.timeout(2):
        with (directory / "child.lock").open() as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return
                except BlockingIOError:
                    await asyncio.sleep(0.01)


def test_shell_cwd_output_and_exit_code(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    before = Path.cwd()
    result = json.loads(
        asyncio.run(
            call(
                {
                    "command": "printf saved > answer.txt; "
                    "printf 'stdout\\n'; printf 'stderr\\n' >&2; exit 7",
                    "cwd": "child",
                },
                SimpleNamespace(working_dir=tmp_path),
            )
        )
    )
    assert result == {
        "exit_code": 7,
        "output": "stdout\nstderr\n",
        "timed_out": False,
        "truncated": False,
    }
    assert (child / "answer.txt").read_text() == "saved"
    assert Path.cwd() == before


def test_shell_drains_large_output_without_blocking(tmp_path):
    result = json.loads(
        asyncio.run(
            call(
                {
                    "command": _command("import os; os.write(1, b'x' * 2000000)"),
                    "timeout": 5,
                },
                SimpleNamespace(working_dir=tmp_path),
            )
        )
    )
    assert result["exit_code"] == 0 and not result["timed_out"]
    assert result["truncated"] and len(result["output"]) == 32768


def test_continuous_output_does_not_starve_timeout(tmp_path):
    async def scenario():
        result = json.loads(
            await asyncio.wait_for(
                call(
                    {
                        "command": _command(
                            "import os\nwhile True: os.write(1, b'x' * 65536)"
                        ),
                        "timeout": 0.2,
                    },
                    SimpleNamespace(working_dir=tmp_path),
                ),
                timeout=3,
            )
        )
        assert result["timed_out"] and result["truncated"]
        assert len(result["output"]) == 32768

    asyncio.run(scenario())


def test_successful_shell_keeps_background_service_running(tmp_path):
    async def scenario():
        ctx = SimpleNamespace(working_dir=tmp_path)
        command = (
            "echo $$ > shell.pid; nohup "
            + _locking_child(tmp_path)
            + " >child.log 2>&1 & "
            "until test -f child.ready; do sleep 0.01; done"
        )
        try:
            result = json.loads(await call({"command": command}, ctx))
            assert result["exit_code"] == 0 and not result["timed_out"]
            assert (
                json.loads(await call({"command": "printf next"}, ctx))["output"]
                == "next"
            )
            with (tmp_path / "child.lock").open() as lock:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            if (tmp_path / "shell.pid").exists():
                with suppress(ProcessLookupError):
                    os.killpg(int((tmp_path / "shell.pid").read_text()), signal.SIGKILL)

    asyncio.run(scenario())


def test_detached_child_stdout_does_not_hold_call_open(tmp_path):
    child = (
        "import time; from pathlib import Path; "
        "Path('child.ready').touch(); time.sleep(30)"
    )
    command = _command(
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); "
        "Path('child.pid').write_text(str(p.pid))\n"
        "while not Path('child.ready').exists(): time.sleep(0.01)"
    )

    async def scenario():
        try:
            result = json.loads(
                await asyncio.wait_for(
                    call(
                        {"command": command, "timeout": 1},
                        SimpleNamespace(working_dir=tmp_path),
                    ),
                    timeout=2,
                )
            )
            assert result["exit_code"] == 0 and not result["timed_out"]
            os.kill(int((tmp_path / "child.pid").read_text()), 0)
            assert asyncio.all_tasks() == {asyncio.current_task()}
        finally:
            if (tmp_path / "child.pid").exists():
                with suppress(ProcessLookupError):
                    os.killpg(int((tmp_path / "child.pid").read_text()), signal.SIGKILL)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_shell_reaps_active_command_group_on_timeout_or_cancel(tmp_path, mode):
    async def scenario():
        running = asyncio.create_task(
            call(
                {
                    "command": _locking_child(tmp_path) + " & wait",
                    "timeout": 0.5 if mode == "timeout" else 5,
                },
                SimpleNamespace(working_dir=tmp_path),
            )
        )
        if mode == "cancel":
            async with asyncio.timeout(5):
                while not (tmp_path / "child.ready").exists():
                    await asyncio.sleep(0.01)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            result = json.loads(await running)
            assert result["timed_out"] is (mode == "timeout")
        await _assert_child_stopped(tmp_path)

    asyncio.run(scenario())


def test_cancellation_during_process_acquisition_reaps_shell_group(
    tmp_path, monkeypatch
):
    async def scenario():
        create_subprocess = asyncio.create_subprocess_exec
        acquired = asyncio.Event()
        release = asyncio.Event()

        async def delayed_acquisition(*args, **kwargs):
            process = await create_subprocess(*args, **kwargs)
            acquired.set()
            await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_acquisition)
        running = asyncio.create_task(
            call(
                {
                    "command": "echo $$ > shell.pid; "
                    + _locking_child(tmp_path)
                    + " & wait"
                },
                SimpleNamespace(working_dir=tmp_path),
            )
        )
        try:
            async with asyncio.timeout(5):
                await acquired.wait()
                while not (tmp_path / "child.ready").exists():
                    await asyncio.sleep(0.01)
            running.cancel()
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(running, timeout=3)
            await _assert_child_stopped(tmp_path)
        finally:
            release.set()
            if (tmp_path / "shell.pid").exists():
                with suppress(ProcessLookupError):
                    os.killpg(int((tmp_path / "shell.pid").read_text()), signal.SIGKILL)
            if not running.done():
                running.cancel()
            with suppress(asyncio.CancelledError):
                await running

    asyncio.run(scenario())


@pytest.mark.parametrize("model_name", ["custom-model", "gpt-5"])
def test_native_shell_round_trip_and_snapshot(model_server, tmp_path, model_name):
    def reply(request):
        body = request["body"]
        first = len(model_server.requests) == 1
        args = {"command": "printf SOLVED > answer.txt; cat answer.txt"}
        if request["path"].endswith("/responses"):
            response = _responses_reply(body, "done")
            if first:
                response["output"] = [
                    {
                        "type": "function_call",
                        "id": "fc_shell",
                        "call_id": "call_shell",
                        "name": "shell",
                        "arguments": json.dumps(args),
                        "status": "completed",
                    }
                ]
        else:
            response = _chat_reply(
                body, "done", tool=("shell", args) if first else None
            )
        return 200, response

    model_server.reply = reply
    agent = MiniAgent(_config(model_server, llm={"model_name": model_name}))
    before = agent.snapshot
    result = asyncio.run(agent.run("Solve the task", working_dir=tmp_path))
    assert result.status == "finished", result.error_message
    assert (tmp_path / "answer.txt").read_text() == "SOLVED"
    assert agent.snapshot is before
    assert before.files["tools/shell.py"].component == "tool"
    assert before.files["tool_descriptions/shell.json"].component == "tool"
    output = next(
        message["content"]
        for message in result.messages
        if message.get("role") == "tool"
    )
    assert json.loads(output)["output"] == "SOLVED"
    schema = model_server.requests[0]["body"]["tools"][0]
    assert (schema.get("function") or schema)["name"] == "shell"


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_adapter_shutdown_reaps_active_shell_group(model_server, tmp_path, mode):
    def reply(request):
        return 200, _chat_reply(
            request["body"],
            tool=("shell", {"command": _locking_child(tmp_path) + " & wait"}),
        )

    model_server.reply = reply
    agent = MiniAgent(_config(model_server, timeout=3 if mode == "timeout" else 15))

    async def scenario():
        running = asyncio.create_task(agent.run("Run command", working_dir=tmp_path))
        async with asyncio.timeout(10):
            while not (tmp_path / "child.ready").exists():
                await asyncio.sleep(0.01)
        if mode == "cancel":
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            result = await asyncio.wait_for(running, timeout=10)
            assert result.status == "error" and "timed out" in result.error_message
        await _assert_child_stopped(tmp_path)

    asyncio.run(scenario())


def test_shell_can_be_disabled_in_selected_snapshot(model_server, tmp_path):
    source = _copy_source(tmp_path)
    agent_yaml = source / "agent.yaml"
    agent_yaml.write_text(
        agent_yaml.read_text().replace("tools:\n  - shell", "tools: []")
    )

    def reply(request):
        tool = (
            ("shell", {"command": "touch should-not-exist"})
            if len(model_server.requests) == 1
            else None
        )
        return 200, _chat_reply(request["body"], "done", tool=tool)

    model_server.reply = reply
    result = asyncio.run(
        MiniAgent(_config(model_server, source_dir=source)).run(
            "task", working_dir=tmp_path
        )
    )
    assert result.status == "finished", result.error_message
    assert not (tmp_path / "should-not-exist").exists()
    assert any(
        message.get("content") == "Unavailable tool: shell"
        for message in result.messages
    )
