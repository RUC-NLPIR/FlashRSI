"""Keep executable helper resources in private cache, tasks in system temp."""

import asyncio
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

import pytest
from test_codex import _requests
from test_codex import native_cli as native_cli
from test_codex_core_parity import _events, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex
from flashrsi.agents import codex as adapter


@pytest.mark.parametrize(
    ("platform", "relative_cache"),
    [("linux", ".cache"), ("darwin", "Library/Caches"), ("win32", ".cache")],
)
def test_runtime_home_uses_platform_cache_and_cleans_each_private_run(
    tmp_path, monkeypatch, platform, relative_cache
):
    home, system_temp = tmp_path / "user", tmp_path / "system-temp"
    home.mkdir()
    system_temp.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(adapter.sys, "platform", platform)
    monkeypatch.setattr(tempfile, "tempdir", str(system_temp))
    parent = home / relative_cache / "flashrsi/codex"
    previous = None
    for _ in range(2):
        with adapter._runtime_home() as directory:
            runtime = Path(directory)
            assert runtime.parent == parent
            assert not runtime.is_relative_to(system_temp)
            assert runtime != previous
            assert stat.S_IMODE(parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
            (runtime / "private-state").write_text("RUN_ONLY")
        assert not runtime.exists()
        previous = runtime
    assert not list(parent.iterdir())


def test_runtime_home_respects_xdg_cache_and_tightens_existing_parent(
    tmp_path, monkeypatch
):
    cache = tmp_path / "xdg-cache"
    parent = cache / "flashrsi/codex"
    parent.mkdir(parents=True, mode=0o755)
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    with adapter._runtime_home() as directory:
        assert Path(directory).parent == parent
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert not Path(directory).exists()


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "source"
    (source / "python_core").mkdir(parents=True)
    (source / "components.yaml").write_text("code: [python_core/**]\n")
    (source / "python_core/__init__.py").write_text("")
    (source / "python_core/loop.py").write_text(
        "import json\n"
        "async def run_session(request, emit):\n"
        "    return {'status':'finished','usage':{},'output':json.dumps({\n"
        "        'home':request['home'],'cwd':request['cwd']})}\n"
    )
    return source


@pytest.mark.parametrize("native", [False, True])
def test_both_adapters_use_cache_resources_and_keep_default_task_in_system_temp(
    source, native_cli, tmp_path, monkeypatch, native
):
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    seen = []
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        if args[0] in {sys.executable, str(native_cli[0])}:
            home = Path(kwargs["env"]["CODEX_HOME"])
            seen.append(
                {
                    "home": home,
                    "cwd": Path(kwargs["cwd"]),
                    "parent_mode": stat.S_IMODE(home.parent.parent.stat().st_mode),
                    "run_mode": stat.S_IMODE(home.parent.stat().st_mode),
                }
            )
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    config = {
        "source_dir": source,
        "llm": {"model_name": "offline-test", "api_key": "local-test-only"},
    }
    if native:
        config["cli_path"] = str(native_cli[0])
    result = asyncio.run(Codex(config).run("Report runtime paths."))
    assert result.status == "finished", result.error_message
    assert len(seen) == 1
    record = seen[0]
    home, task = record["home"], record["cwd"]
    assert home.parent.parent == cache / "flashrsi/codex"
    assert record["parent_mode"] == record["run_mode"] == 0o700
    assert task.parent.parent == Path(tempfile.gettempdir()).resolve()
    assert not task.is_relative_to(cache)
    assert not home.parent.exists() and not task.parent.exists()
    actual = _requests(native_cli)[0] if native else json.loads(result.output)
    assert actual["home"] == str(home) and actual["cwd"] == str(task)


def test_cache_creation_failure_does_not_fall_back_to_system_temp(
    tmp_path, monkeypatch
):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("BLOCK_CACHE_CREATION")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
    with pytest.raises(OSError):
        adapter._runtime_home()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX executable helpers")
@pytest.mark.parametrize("native", [False, True])
def test_default_temporary_task_uses_real_compound_patch_helper_from_cache(
    parity_source, upstream_codex, monkeypatch, native
):
    normal_home = Path.home()
    if normal_home.is_relative_to(Path(os.environ.get("TMPDIR", "/tmp"))):
        pytest.skip("This account's home is inside the native helper refusal tree")
    (parity_source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\n"
        "shell_snapshot=false\nunified_exec=true\n"
    )
    command = (
        "printf 'COMPOUND_PREFIX\\n'; apply_patch <<'PATCH'\n"
        "*** Begin Patch\n*** Add File: helper-proof.txt\n+CACHE_HELPER_WORKED\n"
        "*** End Patch\nPATCH\ncat helper-proof.txt\n"
        "printf '\\nTASK_CWD='; pwd\n"
        "printf '\\nRESOURCE_HOME=%s\\n' \"$CODEX_HOME\""
    )
    with tempfile.TemporaryDirectory(
        prefix=".flashrsi-codex-home-test-", dir=normal_home
    ) as isolated:
        home = Path(isolated)
        (home / "AGENTS.md").write_text("HOST_HOME_ANCESTOR_MUST_NOT_ENTER_TASK")
        cache = home / ".cache"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        with _responses_server() as replay:
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
                    (200, _events("CACHE_HELPER_VERIFIED")),
                ]
            )
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "timeout": 30,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-test-only",
                    "base_url": replay.base_url,
                },
            }
            if native:
                config["cli_path"] = upstream_codex
            result = asyncio.run(Codex(config).run("Follow the localhost replay."))
            assert result.status == "finished", result.error_message
            assert not replay.errors and not replay.steps
            feedback = next(
                item["output"]
                for item in replay.requests[-1]["body"]["input"]
                if item.get("type") == "function_call_output"
            )
            assert "Success. Updated the following files:" in feedback
            assert "CACHE_HELPER_WORKED" in feedback
            assert "HOST_HOME_ANCESTOR_MUST_NOT_ENTER_TASK" not in json.dumps(
                replay.requests[0]["body"]
            )
            resource_home = Path(re.search(r"RESOURCE_HOME=([^\n]+)", feedback)[1])
            task = Path(re.search(r"TASK_CWD=([^\n]+)", feedback)[1])
            assert resource_home.parent.parent == cache / "flashrsi/codex"
            assert task.parent.parent == Path(tempfile.gettempdir()).resolve()
            assert not resource_home.parent.exists() and not task.parent.exists()
