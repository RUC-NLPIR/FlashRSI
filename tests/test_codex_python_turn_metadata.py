"""Native request oracle and lifecycle regressions for background Git metadata."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_python_session_resume import _request

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core import context, loop


def git(path, *args):
    return subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()


def metadata(request):
    return json.loads(request["body"]["client_metadata"]["x-codex-turn-metadata"])


class _WaitForEnrichment:
    def __init__(self, replay):
        self.replay = replay

    def __bool__(self):
        return True

    def pop(self, _index):
        count = len(self.replay.requests)
        if count == 1 or (
            not metadata(self.replay.requests[-1]).get("workspaces") and count < 15
        ):
            return 200, _events(
                call=("shell_command", {"command": "sleep 0.1"}),
                response_id=f"metadata_wait_{count}",
            )
        return 200, _events("GIT_METADATA_TASK_DONE")


@pytest.mark.parametrize("state", ["clean", "dirty", "unborn"])
def test_native_git_workspace_enrichment_reaches_later_model_requests(
    state, parity_source, upstream_codex, tmp_path
):
    repo = tmp_path / "repo"
    task = repo / "nested"
    task.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Metadata Test")
    git(repo, "config", "user.email", "metadata@example.invalid")
    git(repo, "remote", "add", "origin", "https://example.invalid/owner/project.git")
    git(repo, "remote", "add", "other", "git@example.invalid:owner/project.git")
    expected = {
        "associated_remote_urls": {
            "origin": "https://example.invalid/owner/project.git",
            "other": "git@example.invalid:owner/project.git",
        },
        "has_changes": state == "dirty",
    }
    if state != "unborn":
        (repo / "tracked.txt").write_text("BASE\n")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-qm", "metadata fixture")
        expected["latest_git_commit_hash"] = git(repo, "rev-parse", "HEAD")
    if state == "dirty":
        (repo / "tracked.txt").write_text("CHANGED\n")
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset([])
            replay.steps = _WaitForEnrichment(replay)
            options = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "timeout": 30,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-metadata-test-key",
                    "base_url": replay.base_url,
                },
            }
            if binary:
                options["cli_path"] = binary
            result = asyncio.run(
                Codex(options).run("Inspect Git metadata.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert not replay.errors
            assert result.output == "GIT_METADATA_TASK_DONE"
            observed.append(metadata(replay.requests[-1]).get("workspaces"))
    assert observed[0] == {str(repo): expected}
    assert observed[1] == observed[0]


_REMOVED_KEYS = re.findall(
    r'key: "([^"]+)",\s*stage: Stage::Removed',
    (
        Path(__file__).parents[1] / "flashrsi/agents/codex/runtime/features/src/lib.rs"
    ).read_text(),
)


@pytest.mark.parametrize(
    "flags",
    [
        {"js_repl": True},
        {"undo": True},
        {"js_repl_tools_only": True},
        dict.fromkeys(_REMOVED_KEYS, True),
        dict.fromkeys(_REMOVED_KEYS, False),
    ],
    ids=["js_repl", "undo", "js_repl_tools_only", "all_true", "all_false"],
)
def test_removed_compatibility_features_are_native_noops(
    flags, parity_source, upstream_codex, tmp_path
):
    config = parity_source / "config.toml"
    config.write_text(
        config.read_text()
        + "".join(f"{key} = {str(value).lower()}\n" for key, value in flags.items())
    )
    task = tmp_path / "task"
    task.mkdir()
    bodies = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset([(200, _events())])
            options = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "timeout": 30,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-metadata-test-key",
                    "base_url": replay.base_url,
                },
            }
            if binary:
                options["cli_path"] = binary
            result = asyncio.run(
                Codex(options).run("Compatibility task.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert not replay.errors
            bodies.append(_normalize(replay.requests[0], tmp_path))
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize("outcome", ["finished", "error", "interrupted"])
def test_pending_enrichment_does_not_block_sampling_and_is_cancelled_each_turn(
    outcome, tmp_path, monkeypatch
):
    async def scenario(replay):
        calls, cancelled, states = [], [], []
        sampled = asyncio.Event()
        blocked = asyncio.Event()
        original = loop.ResponsesClient.response

        async def enrich(cwd, repo):
            calls.append((cwd, repo))
            try:
                await blocked.wait()
            finally:
                cancelled.append(repo)

        async def response(self, inputs, tools, request_metadata, **kwargs):
            # Sampling can be entered before the background task gets its first
            # scheduling slot. Yield once without releasing the blocked query.
            await asyncio.sleep(0)
            assert calls
            assert not blocked.is_set()
            assert "workspaces" not in json.loads(
                request_metadata["x-codex-turn-metadata"]
            )
            states.append(self.settings["_turn_metadata_state"])
            sampled.set()
            if outcome == "interrupted":
                await asyncio.Event().wait()
            return await original(self, inputs, tools, request_metadata, **kwargs)

        monkeypatch.setattr(context, "_workspace_git_metadata", enrich)
        monkeypatch.setattr(loop.ResponsesClient, "response", response)
        cache = {}
        request = _request(tmp_path, replay, _session_cache=cache)
        repo = Path(request["cwd"])
        (repo / ".git").mkdir()
        try:
            for index in range(2):
                sampled.clear()
                task = asyncio.create_task(
                    loop.run_session(request, lambda event: None)
                )
                await asyncio.wait_for(sampled.wait(), 2)
                if outcome == "interrupted":
                    task.cancel()
                result = await asyncio.wait_for(task, 2)
                assert result["status"] == outcome, result["error_message"]
                assert len(cancelled) == index + 1
                assert states[-1].task is None
                request = {**request, "settings": cache["client"].settings}
            assert len(calls) == 2 and states[0] is not states[1]
        finally:
            await loop.close_session(cache)

    with _responses_server() as replay:
        if outcome == "error":
            replay.reset([(400, b'{"error":{"message":"METADATA_TASK_ERROR"}}')] * 2)
        else:
            replay.reset([(200, _events())] * 2)
        asyncio.run(scenario(replay))


@pytest.mark.parametrize("kind", ["nonrepo", "invalidrepo"])
def test_absent_or_failed_git_metadata_is_omitted(kind, tmp_path):
    async def scenario(replay):
        request = _request(tmp_path, replay)
        if kind == "invalidrepo":
            (Path(request["cwd"]) / ".git").mkdir()
        result = await loop.run_session(request, lambda event: None)
        assert result["status"] == "finished", result["error_message"]
        assert "workspaces" not in metadata(replay.requests[-1])

    with _responses_server() as replay:
        replay.reset([(200, _events())])
        asyncio.run(scenario(replay))


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group lifecycle")
@pytest.mark.parametrize("cancel", [False, True])
def test_git_timeout_or_cancellation_reaps_spawned_process_tree(
    cancel, tmp_path, monkeypatch
):
    binary = tmp_path / "git"
    pid_file = tmp_path / "child.pid"
    binary.write_text(f"#!/bin/sh\n/bin/sleep 30 &\necho $! > '{pid_file}'\nwait\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(context, "_GIT_TIMEOUT", 3)

    async def scenario():
        task = asyncio.create_task(context._git_output(tmp_path, ["rev-parse", "HEAD"]))
        async with asyncio.timeout(5):
            while not pid_file.exists():
                await asyncio.sleep(0.01)
        pid = int(pid_file.read_text())
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task is None
        async with asyncio.timeout(2):
            while True:
                # Some Unix hosts briefly retain an adopted zombie after the
                # process-group kill. A zombie cannot execute or hold pipes.
                state = subprocess.run(
                    ["/bin/ps", "-o", "stat=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if not state or state.startswith("Z"):
                    break
                await asyncio.sleep(0.01)

    asyncio.run(scenario())


def test_removed_flags_do_not_make_unknown_active_features_supported():
    with pytest.raises(ValueError, match="not implemented enabled feature"):
        loop.validate({"features": {"js_repl": True, "unknown_active_feature": True}})


def test_concurrent_turns_share_running_status_without_cancelling_each_other(
    tmp_path, monkeypatch
):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        status_calls = []

        async def output(cwd, args, **kwargs):
            if args[0] != "status":
                return None
            status_calls.append(cwd)
            started.set()
            await release.wait()
            return b" M tracked.txt\n"

        monkeypatch.setattr(context, "_git_output", output)
        first = asyncio.create_task(context._workspace_git_metadata(tmp_path, tmp_path))
        second = asyncio.create_task(
            context._workspace_git_metadata(tmp_path, tmp_path)
        )
        await asyncio.wait_for(started.wait(), 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert len(status_calls) == 1 and not second.done()
        release.set()
        assert await second == {"has_changes": True}
        assert not context._GIT_STATUS_RUNS
        assert await context._workspace_git_metadata(tmp_path, tmp_path) == {
            "has_changes": True
        }
        assert len(status_calls) == 2

    asyncio.run(scenario())
