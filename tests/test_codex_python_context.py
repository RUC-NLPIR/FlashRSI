"""Context byte fidelity, including fixed-version native localhost oracles."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core.context import (
    initial_context,
    message,
    permissions,
    request_metadata,
    writable_roots,
)
from flashrsi.agents.codex.python_core.models import Model


@pytest.mark.parametrize("mode", ["read-only", "workspace-write"])
def test_native_context_request_parity(mode, parity_source, upstream_codex, tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    traces = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset([(200, _events())])
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "sandbox": mode,
                "timeout": 30,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run("Inspect the context.", working_dir=task)
            )
            assert result.status == "finished", result.error_message
            assert len(replay.requests) == 1 and not replay.errors
            traces.append(_normalize(replay.requests, tmp_path))
    assert traces[0] == traces[1]


def test_custom_permission_templates_preserve_whitespace(tmp_path):
    model = Model("gpt-5", {})
    model.info["model_messages"] = {
        "permissions": {"read_only": "custom {{ network_access }}\n\n"},
        "approvals": {"never": "approval\n\n"},
    }
    assert permissions({"sandbox_mode": "read-only"}, tmp_path, model) == (
        "<permissions instructions>\ncustom restricted\n\napproval\n\n</permissions instructions>"
    )
    model.info["model_messages"]["permissions"]["read_only"] = ""
    assert permissions({"sandbox_mode": "read-only"}, tmp_path, model) == (
        "<permissions instructions>\napproval\n\n</permissions instructions>"
    )


def test_writable_roots_canonicalize_and_ignore_relative_tmpdir(tmp_path, monkeypatch):
    root = tmp_path / "real"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    monkeypatch.setenv("TMPDIR", "relative/tmp")
    roots = writable_roots(
        alias, {"sandbox_workspace_write": {"writable_roots": [str(alias)]}}
    )
    assert roots == sorted(
        {
            str(root.resolve()),
            *({str(Path("/tmp").resolve())} if os.name == "posix" else set()),
        }
    )


def test_hook_fragment_is_separate_but_mention_is_ordinary_content(tmp_path):
    hook = message("user", '<hook_prompt hook_run_id="test">notice</hook_prompt>')
    ordinary = message("user", "Use <hook_prompt> in the XML example.")
    result = initial_context([ordinary, hook], {}, tmp_path, Model("gpt-5", {}))
    assert result[-1] == hook
    assert result[1]["content"][0]["text"] == ordinary["content"][0]["text"]


def test_metadata_tracks_window_and_subagent_identity():
    settings = {
        "_thread_id": "child",
        "_turn_id": "turn",
        "_installation_id": "installation",
        "_started_at_unix_ms": 5,
        "_window_number": 2,
        "_parent_thread_id": "parent",
        "_parent_turn_id": "parent-turn",
        "_forked_from_thread_id": "fork",
        "sandbox_mode": "danger-full-access",
    }
    result = request_metadata(settings)
    metadata = json.loads(result["x-codex-turn-metadata"])
    assert result["x-codex-window-id"] == "child:2"
    assert result["x-codex-parent-thread-id"] == "parent"
    assert result["parent_turn_id"] == "parent-turn"
    assert result["x-openai-subagent"] == "collab_spawn"
    assert metadata["forked_from_thread_id"] == "fork"
    assert metadata["subagent_kind"] == "thread_spawn"
    assert metadata["thread_source"] == "subagent"
    assert metadata["sandbox"] == "none"


@pytest.mark.parametrize(
    "key,value",
    [
        ("model_reasoning_summary", "bogus"),
        ("model_verbosity", "verbose"),
        ("personality", "confident"),
        ("model_reasoning_effort", ""),
        ("model_reasoning_effort", 42),
    ],
)
def test_invalid_model_enums_rejected_before_http(
    key, value, parity_source, upstream_codex
):
    config_file = parity_source / "config.toml"
    config_file.write_text(f"{key} = {json.dumps(value)}\n" + config_file.read_text())
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "test",
                    "base_url": replay.base_url,
                },
                "timeout": 20,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(Codex(config).run("Never send a request."))
            assert result.status == "error"
            assert not replay.requests


def test_future_custom_reasoning_effort_keeps_native_open_enum():
    from flashrsi.agents.codex.python_core.client import ResponsesClient

    model = Model("gpt-5", {"model_reasoning_effort": "future-effort"})
    client = ResponsesClient(
        {},
        model,
        {"model_reasoning_effort": "future-effort"},
        "thread",
        lambda event: None,
    )
    assert client.request([], [])["reasoning"]["effort"] == "future-effort"
    with pytest.raises(ValueError, match="non-empty string"):
        ResponsesClient(
            {"reasoning_effort": ""}, model, {}, "thread", lambda event: None
        )
