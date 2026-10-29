"""Actual Linux task execution boundaries and selected installed Python core."""

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml
from test_codex_core_parity import _events, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_task_exec_parity import _normalize_exec_trace
from test_codex_task_shell_snapshot_parity import _SnapshotScript

from flashrsi.agents import Codex
from flashrsi.core import Snapshot, Task

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Actual Linux acceptance"
)


def _config(source, replay, **extra):
    return {
        "source_dir": source,
        "sandbox": "danger-full-access",
        "timeout": 30,
        "llm": {
            "model_name": "gpt-5.4",
            "api_key": "local-linux-test-key",
            "base_url": replay.base_url,
        },
        **extra,
    }


def test_linux_selected_python_core_survives_save_load_rollout_and_update(
    parity_source, tmp_path
):
    with _responses_server() as replay:
        agent = Codex(_config(parity_source, replay))
        agent.set_scope({"code": "rw"})
        baseline = agent.snapshot
        wrapper = """
_linux_original_run_session = run_session
async def run_session(request, emit):
    result = await _linux_original_run_session(request, emit)
    result["output"] = "LINUX_CANDIDATE:" + result["output"]
    return result
"""
        with baseline.check_out() as directory:
            path = directory / "python_core/loop.py"
            path.write_text(path.read_text() + wrapper)
            candidate = baseline.commit(directory)
        saved = tmp_path / "candidate.json"
        candidate.save(saved)
        candidate = Snapshot.load(saved)

        async def run(snapshot=None):
            replay.reset([(200, _events("INSTALLED_CORE"))])
            (result,) = await agent.rollout(
                [Task("linux-core", "Follow the localhost replay.")], snapshot=snapshot
            )
            assert result.status == "finished", result.error_message
            assert not replay.steps and not replay.errors
            return result.output

        assert asyncio.run(run(candidate)) == "LINUX_CANDIDATE:INSTALLED_CORE"
        assert agent.snapshot.id == baseline.id
        agent.update(candidate)
        assert asyncio.run(run()) == "LINUX_CANDIDATE:INSTALLED_CORE"
        agent.update(baseline)
        assert asyncio.run(run()) == "INSTALLED_CORE"

        with baseline.check_out() as directory:
            path = directory / "python_core/loop.py"
            path.write_text(path.read_text() + "\nthis is invalid Python;\n")
            broken = baseline.commit(directory)
        replay.reset([])
        (result,) = asyncio.run(
            agent.rollout(
                [Task("linux-broken", "Must not reach HTTP.")], snapshot=broken
            )
        )
        assert result.status == "error" and "invalid syntax" in result.error_message
        assert not replay.requests


def test_linux_restricted_execution_does_not_silently_run_unrestricted(
    parity_source, tmp_path
):
    (parity_source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\nshell_snapshot=false\nunified_exec=true\n"
    )
    target = tmp_path / "must-not-exist"
    task = tmp_path / "task"
    task.mkdir()
    with _responses_server() as replay:
        replay.reset(
            [
                (
                    200,
                    _events(
                        call=(
                            "exec_command",
                            {
                                "cmd": "printf UNRESTRICTED > "
                                + shlex.quote(str(target)),
                                "shell": "/bin/sh",
                                "login": False,
                            },
                        )
                    ),
                ),
                (200, _events("EXPLICIT_LINUX_BOUNDARY")),
            ]
        )
        result = asyncio.run(
            Codex(_config(parity_source, replay, sandbox="workspace-write")).run(
                "Attempt the supplied local command.", working_dir=task
            )
        )
        assert result.status == "finished", result.error_message
        assert result.output == "EXPLICIT_LINUX_BOUNDARY"
        assert not target.exists()
        assert not replay.errors and not replay.steps
        feedback = [
            item["output"]
            for item in replay.requests[-1]["body"]["input"]
            if item.get("type") == "function_call_output"
        ]
        assert "sandbox enforcement is unavailable on linux" in json.dumps(feedback)


def test_linux_container_entrypoint_executes_serialized_candidate(
    parity_source, tmp_path
):
    task = tmp_path / "container-task"
    task.mkdir()
    request_path = task / "request.json"
    output_path = task / "trajectory.json"
    with _responses_server() as replay:
        config = _config(parity_source, replay)
        agent = Codex(config)
        agent.set_scope({"code": "rw"})
        baseline = agent.snapshot
        with baseline.check_out() as directory:
            path = directory / "python_core/loop.py"
            path.write_text(
                path.read_text() + "\n_container_original_run_session = run_session\n"
                "async def run_session(request, emit):\n"
                "    result = await _container_original_run_session(request, emit)\n"
                "    result['output'] = 'CONTAINER_CANDIDATE:' + result['output']\n"
                "    return result\n"
            )
            candidate = baseline.commit(directory)
        snapshot_path = tmp_path / "container-snapshot.json"
        candidate.save(snapshot_path)
        config.pop("source_dir")
        config["_codex_evaluation"] = True
        runtime_memory = tmp_path / "must-not-touch-runtime-memory"
        config["memory_dir"] = str(runtime_memory)
        request_path.write_text(
            json.dumps(
                {
                    "agent_class": "flashrsi.agents.codex:Codex",
                    "config_yaml": yaml.safe_dump(config),
                    "snapshot_path": str(snapshot_path),
                    "prompt": "Verify the container transport and local shell.",
                }
            )
        )
        replay.reset(
            [
                (
                    200,
                    _events(
                        call=(
                            "shell_command",
                            {
                                "command": "test ! -e request.json && printf CONTAINER_REQUEST_REMOVED",
                                "login": False,
                            },
                        )
                    ),
                ),
                (200, _events("TRANSPORT_VERIFIED")),
            ]
        )
        process = subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "flashrsi.integrations._container",
                str(request_path),
                str(output_path),
            ],
            cwd=task,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert process.returncode == 0, (process.stdout, process.stderr)
        record = json.loads(output_path.read_text())
        assert record["status"] == "finished", record.get("error_message")
        assert record["output"] == "CONTAINER_CANDIDATE:TRANSPORT_VERIFIED"
        assert not request_path.exists()
        assert not replay.errors and not replay.steps
        assert "CONTAINER_REQUEST_REMOVED" in json.dumps(replay.requests[-1])
        manifest = next(
            item
            for item in record["messages"]
            if item.get("type") == "CodexRunEnvironment"
        )
        assert manifest["snapshot_id"] == candidate.id
        assert manifest["mode"] == "evaluation"
        assert manifest["runtime_memory_ignored"] is True
        assert not runtime_memory.exists()


@pytest.mark.parametrize("blocked", [True, False])
def test_linux_patch_helper_obeys_native_temporary_home_guard(
    blocked, parity_source, upstream_codex, tmp_path, monkeypatch
):
    """Release native arg0 refuses helpers under its lexical temp directory."""
    native_temp = tmp_path / "native-temp"
    adapter_temp = native_temp if blocked else tmp_path / "adapter-runtime"
    native_temp.mkdir()
    adapter_temp.mkdir(exist_ok=True)
    # The private factory chooses the adapter home; each child independently
    # reads TMPDIR. Different roots exercise the actual helper implementation
    # without bypassing the release guard inside either child.
    monkeypatch.setattr(
        "flashrsi.agents.codex._runtime_home",
        lambda: tempfile.TemporaryDirectory(prefix="flashrsi-codex-", dir=adapter_temp),
    )
    monkeypatch.setenv("TMPDIR", str(native_temp))
    (parity_source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\nshell_snapshot=false\nunified_exec=true\n"
    )
    task = tmp_path / "task"
    command = (
        "printf 'prefix\\n'; apply_patch <<'PATCH'\n"
        "*** Begin Patch\n*** Add File: proof.txt\n+LINUX_HELPER_PROOF\n"
        "*** End Patch\nPATCH"
    )
    traces = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            shutil.rmtree(task, ignore_errors=True)
            task.mkdir()
            replay.reset(
                [
                    (
                        200,
                        _events(
                            call=(
                                "exec_command",
                                {"cmd": command, "shell": "/bin/sh", "login": False},
                            )
                        ),
                    ),
                    (200, _events("LINUX_HELPER_GUARD_VERIFIED")),
                ]
            )
            config = _config(parity_source, replay)
            if binary is not None:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run("Follow the local helper task.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert not replay.errors and not replay.steps
            feedback = [
                item["output"]
                for item in replay.requests[-1]["body"]["input"]
                if item.get("type") == "function_call_output"
            ]
            if blocked:
                assert not (task / "proof.txt").exists()
                assert "apply_patch: not found" in feedback[-1]
                assert "Process exited with code 127" in feedback[-1]
            else:
                assert (task / "proof.txt").read_text() == "LINUX_HELPER_PROOF\n"
                assert "Success. Updated the following files:" in feedback[-1]
            traces.append(
                _normalize_exec_trace(
                    {
                        "requests": replay.requests,
                        "status": result.status,
                        "output": result.output,
                        "usage": dict(result.usage),
                        "files": {
                            path.name: path.read_text() for path in task.iterdir()
                        },
                    },
                    tmp_path,
                )
            )
    assert traces[0] == traces[1]


@pytest.mark.parametrize(
    "mode", ["classic", "unified", "no-login", "other-cwd", "explicit-env"]
)
def test_linux_bash_snapshot_restores_capture_only_environment(
    mode, parity_source, upstream_codex, tmp_path, monkeypatch
):
    import pwd

    try:
        account_shell = pwd.getpwuid(os.getuid()).pw_shell
    except KeyError:
        account_shell = "/bin/bash"
    if Path(account_shell).name != "bash":
        pytest.skip("This native account uses a shell other than Bash")
    task = tmp_path / "task"
    task.mkdir()
    (task / "other").mkdir()
    startup = tmp_path / "capture-startup.sh"
    startup.write_text(
        'case "$BASH_EXECUTION_STRING" in *"# Snapshot file"*)\n'
        "export RSI_SNAPSHOT_VALUE=captured-by-native-snapshot\n"
        + "printf '%s' \"$CODEX_HOME\" > "
        + shlex.quote(str(task / "snapshot-home"))
        + "\n;; esac\n"
    )
    # BASH_ENV is normal Bash startup input. It sets the value only for capture;
    # a later ordinary command can observe it only through snapshot restoration.
    monkeypatch.setenv("BASH_ENV", str(startup))
    (parity_source / "config.toml").write_text(
        (
            '[shell_environment_policy]\nset={RSI_SNAPSHOT_VALUE="explicit-policy"}\n'
            if mode == "explicit-env"
            else ""
        )
        + "[features]\nplugins=false\nremote_plugin=false\nshell_snapshot=true\n"
        + f"unified_exec={'true' if mode == 'unified' else 'false'}\n"
    )
    traces = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            (task / "snapshot-home").unlink(missing_ok=True)
            replay.reset([])
            replay.steps = _SnapshotScript(task, mode)
            config = _config(parity_source, replay)
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run("Read the shell snapshot value.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert not replay.errors and not replay.steps
            feedback = [
                item["output"]
                for item in replay.requests[-1]["body"]["input"]
                if item.get("type") == "function_call_output"
            ]
            expected = (
                ""
                if mode in {"no-login", "other-cwd"}
                else "explicit-policy"
                if mode == "explicit-env"
                else "captured-by-native-snapshot"
            )
            assert f"snapshot-value={expected}\n" in feedback[-1], feedback
            traces.append(_normalize_exec_trace(replay.requests, tmp_path))
    assert traces[0] == traces[1]
