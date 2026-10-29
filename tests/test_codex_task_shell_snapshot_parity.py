"""Actual shell snapshot restoration through the pinned CLI and Python core."""

from __future__ import annotations

import asyncio
import shlex
import sys
import time
from pathlib import Path

import pytest
from test_codex_core_parity import _events, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_task_exec_parity import _normalize_exec_trace

from flashrsi.agents import Codex


class _SnapshotScript(list):
    def __init__(self, task, mode):
        self.task = task
        command = "printf 'snapshot-value=%s\\n' \"$RSI_SNAPSHOT_VALUE\""
        args = {"cmd" if mode in {"unified", "model-bash"} else "command": command}
        if mode == "model-bash":
            args["shell"] = "/bin/bash"
        if mode == "no-login":
            args["login"] = False
        if mode == "other-cwd":
            args["workdir"] = str(task / "other")
        if mode == "normalized-cwd":
            args["workdir"] = "does-not-exist/.."
        super().__init__(
            [
                (
                    200,
                    _events(
                        call=(
                            "exec_command"
                            if mode in {"unified", "model-bash"}
                            else "shell_command",
                            args,
                        )
                    ),
                ),
                (200, _events(text="SNAPSHOT_RESTORED")),
            ]
        )
        self.first = True

    def pop(self, index=0):
        if self.first:
            self.first = False
            marker = self.task / "snapshot-home"
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                try:
                    home = Path(marker.read_text())
                    ready = home.is_dir() and any(
                        (home / "shell_snapshots").glob("*.sh")
                    )
                except OSError:
                    ready = False
                if ready:
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("background shell snapshot did not finish")
        return super().pop(index)


@pytest.mark.skipif(
    sys.platform != "darwin", reason="native account shell is zsh on macOS"
)
@pytest.mark.parametrize(
    "mode",
    [
        "classic",
        "unified",
        "model-bash",
        "no-login",
        "other-cwd",
        "normalized-cwd",
        "explicit-env",
    ],
)
def test_shell_snapshot_restores_zshrc_export_like_pinned_native(
    parity_source, upstream_codex, tmp_path, monkeypatch, mode
):
    startup = tmp_path / "startup"
    startup.mkdir()
    task = tmp_path / "task"
    task.mkdir()
    (task / "other").mkdir()
    monkeypatch.setenv("ZDOTDIR", str(startup))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    (startup / ".zshrc").write_text(
        "export RSI_SNAPSHOT_VALUE=captured-by-native-snapshot\n"
        + "printf '%s' \"$CODEX_HOME\" > "
        + shlex.quote(str(task / "snapshot-home"))
        + "\n"
    )
    (parity_source / "config.toml").write_text(
        (
            '[shell_environment_policy]\nset={RSI_SNAPSHOT_VALUE="explicit-policy"}\n'
            if mode == "explicit-env"
            else ""
        )
        + "[features]\nplugins=false\nremote_plugin=false\n"
        + f"unified_exec={'true' if mode in {'unified', 'model-bash'} else 'false'}\nshell_snapshot=true\n"
    )
    traces = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            (task / "snapshot-home").unlink(missing_ok=True)
            replay.reset([])
            replay.steps = _SnapshotScript(task, mode)
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-snapshot-test-key",
                    "base_url": replay.base_url,
                },
                "sandbox": "danger-full-access",
                "timeout": 30,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Read the snapshot environment value.", working_dir=task
                )
            )
            assert not replay.errors, (replay.errors, result.error_message)
            assert result.status == "finished", result.error_message
            assert not replay.steps
            output = [
                item["output"]
                for item in replay.requests[-1]["body"]["input"]
                if item.get("type") == "function_call_output"
            ]
            assert len(output) == 1
            expected = (
                ""
                if mode in {"no-login", "other-cwd"}
                else "explicit-policy"
                if mode == "explicit-env"
                else "captured-by-native-snapshot"
            )
            assert f"snapshot-value={expected}\n" in output[0], (
                binary,
                output,
            )
            traces.append(_normalize_exec_trace(replay.requests, tmp_path))
    assert traces[0] == traces[1]
