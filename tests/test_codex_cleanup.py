"""Bound native startup and close tool sessions on timeout or cancellation."""

import asyncio
import json
import os
import shlex
import signal
import sys
import time
from contextlib import suppress

import pytest
from test_codex import _agent
from test_codex import native_cli as native_cli
from test_codex import source as source
from test_codex_native import _config, _events, _shell_call
from test_codex_native import codex_binary as codex_binary
from test_codex_native import responses_server as responses_server

import flashrsi.agents.codex as adapter


@pytest.mark.skipif(
    os.name != "posix", reason="Native tool process groups require POSIX"
)
@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_native_interrupt_closes_independent_tool_session(
    responses_server, codex_binary, tmp_path, mode
):
    task = tmp_path / "task"
    task.mkdir()
    pidfile = task / "tool-process.json"
    script = (
        "import json,os,time;from pathlib import Path;"
        "Path('tool-process.json').write_text(json.dumps({"
        "'pid':os.getpid(),'pgid':os.getpgid(0),"
        "'parent_pgid':os.getpgid(os.getppid()),"
        "'home':os.environ['CODEX_HOME']}));"
        "time.sleep(45)"
    )
    command = shlex.quote(sys.executable) + " -c " + shlex.quote(script)

    def reply(request):
        name, arguments = _shell_call(request["body"], command)
        arguments["yield_time_ms"] = 10000
        return _events(call=(name, arguments), response_id="resp_sleep")

    responses_server.reply = reply
    agent = adapter.Codex(
        _config(
            responses_server,
            codex_binary,
            timeout=5 if mode == "timeout" else 30,
            sandbox="danger-full-access",
        )
    )

    async def scenario():
        running = asyncio.create_task(
            agent.run("Run the command and wait.", working_dir=task)
        )
        try:
            if mode == "timeout":
                result = await asyncio.wait_for(running, timeout=12)
                assert result.status == "error"
                assert "timed out" in result.error_message
            else:
                async with asyncio.timeout(10):
                    while not pidfile.exists():
                        await asyncio.sleep(0.02)
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(running, timeout=8)
        finally:
            if not running.done():
                running.cancel()
                with suppress(asyncio.CancelledError):
                    await running

    try:
        asyncio.run(scenario())
        child = json.loads(pidfile.read_text())
        assert child["pgid"] != child["parent_pgid"]
        with pytest.raises(ProcessLookupError):
            os.kill(child["pid"], 0)
        assert not os.path.exists(child["home"])
    finally:
        if pidfile.exists():
            child = json.loads(pidfile.read_text())
            with suppress(ProcessLookupError):
                os.kill(child["pid"], signal.SIGKILL)


def test_timeout_includes_native_process_startup(source, native_cli, monkeypatch):
    original = asyncio.create_subprocess_exec
    launch_started = False

    async def slow_launch(*args, **kwargs):
        nonlocal launch_started
        launch_started = True
        await asyncio.sleep(2)
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_launch)
    agent = _agent(source, native_cli, timeout=0.3)
    started = time.monotonic()

    result = asyncio.run(agent.run("question"))

    assert launch_started
    assert result.status == "error"
    assert "timed out" in result.error_message
    assert time.monotonic() - started < 1.5
    assert not native_cli[1].exists()


def test_invalid_timeout_returns_error_before_launch(source, native_cli):
    result = asyncio.run(_agent(source, native_cli, timeout="invalid").run("question"))
    assert result.status == "error"
    assert result.error_message
    assert not native_cli[1].exists()


def test_cleanup_failure_returns_error_with_native_trace(
    source, native_cli, monkeypatch
):
    async def failed_cleanup(process):
        raise RuntimeError("process was not reaped")

    monkeypatch.setattr(adapter, "_stop", failed_cleanup)

    result = asyncio.run(_agent(source, native_cli).run("question"))

    assert result.status == "error"
    assert "Codex cleanup failed: process was not reaped" in result.error_message
    assert any(message["type"] == "turn.completed" for message in result.messages)


@pytest.mark.skipif(os.name != "posix", reason="POSIX cleanup escalation")
def test_forced_termination_wait_is_bounded(monkeypatch):
    class StalledProcess:
        pid = 123
        returncode = None

        async def wait(self):
            await asyncio.Future()

    original = asyncio.wait_for

    async def short_wait(awaitable, timeout):
        return await original(awaitable, timeout=min(timeout, 0.01))

    monkeypatch.setattr(asyncio, "wait_for", short_wait)
    monkeypatch.setattr(os, "killpg", lambda *_: None)

    async def scenario():
        async with asyncio.timeout(0.5):
            with pytest.raises(RuntimeError, match="forced termination"):
                await adapter._stop(StalledProcess())

    asyncio.run(scenario())
