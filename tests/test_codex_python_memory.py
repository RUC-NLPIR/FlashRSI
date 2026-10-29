"""Pinned memory read-path behavior, including real native tool execution."""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core.memory import Memories, parse_memory_citation
from flashrsi.agents.codex.python_core.shell import ToolError


def _call(name, arguments, index):
    stream = _events(call=(name, arguments), response_id=f"resp_memory_{index}")
    lines = []
    for line in stream.decode().splitlines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event.get("item", {}).get("type") == "function_call":
                event["item"]["namespace"] = "memories"
            line = "data: " + json.dumps(event)
        lines.append(line)
    return ("\n".join(lines) + "\n").encode()


def _store(home):
    root = home / "memories"
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory_summary.md").write_text("  MEMORY_TASK_CONTEXT\n  ")
    (root / "MEMORY.md").write_text("alpha here\nbeta separator\nALPHA-BETA\n你好\n")
    (root / "rollout_summaries").mkdir(exist_ok=True)
    (root / "rollout_summaries/probe.md").write_text("alpha beta together\nend\n")
    (root / ".hidden").write_text("alpha beta hidden")
    (root / "binary.bin").write_bytes(b"\xffalpha")
    (root / "link").symlink_to(root / "MEMORY.md")
    return root


def _memory(tmp_path, config=None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    assets = home / "python_core/memory_assets"
    assets.parent.mkdir(exist_ok=True)
    shutil.copytree(
        __import__(Memories.__module__, fromlist=["__file__"]).__file__.rsplit("/", 1)[
            0
        ]
        + "/memory_assets",
        assets,
        dirs_exist_ok=True,
    )
    _store(home)
    settings = {"features": {"memories": True}, "memories": {"dedicated_tools": True}}
    settings.update(config or {})
    return Memories(home, settings)


def test_memory_defaults_context_and_versioned_template(tmp_path):
    memory = _memory(tmp_path)
    assert "MEMORY_TASK_CONTEXT" in memory.context()["content"][0]["text"]
    assert Memories(memory.home, {}).context() is None
    assert Memories(memory.home, {"features": {"memory_tool": True}}).context()
    memory.settings["memories"]["use_memories"] = False
    assert memory.context() is None
    memory.settings["memories"]["use_memories"] = True
    template = memory.home / "python_core/memory_assets/read_path.md"
    template.write_text("VERSIONED {{ base_path }} {{ memory_summary }}")
    assert memory.context()["content"][0]["text"].startswith("VERSIONED ")
    (memory.root / "memory_summary.md").write_bytes(b"\xff")
    assert memory.context() is None


def test_memory_backend_pagination_read_windows_and_notes(tmp_path):
    memory = _memory(tmp_path)
    first = memory.list({"max_results": 2})
    assert first["entries"] == [
        {"entry_type": "file", "path": "MEMORY.md"},
        {"entry_type": "file", "path": "binary.bin"},
    ]
    assert first["next_cursor"] == "2"
    second = memory.list({"cursor": first["next_cursor"]})
    assert [entry["path"] for entry in second["entries"]] == [
        "memory_summary.md",
        "rollout_summaries",
    ]
    assert memory.read({"path": "MEMORY.md", "line_offset": 2, "max_lines": 1}) == {
        "path": "MEMORY.md",
        "start_line_number": 2,
        "content": "beta separator\n",
        "truncated": True,
    }
    assert memory.read({"path": "MEMORY.md", "line_offset": 5})["content"] == ""
    filename = "2026-10-28T12-34-56-native-note.md"
    assert (
        memory.add_ad_hoc_note({"filename": filename, "note": "记住 verbatim\n"}) == {}
    )
    assert (
        memory.root / "extensions/ad_hoc/notes" / filename
    ).read_text() == "记住 verbatim\n"
    with pytest.raises(ToolError, match="already exists"):
        memory.add_ad_hoc_note({"filename": filename, "note": "overwrite"})


@pytest.mark.parametrize("path", ["../outside", "/absolute", ".hidden", "link"])
def test_memory_rejects_traversal_hidden_and_symlink_paths(tmp_path, path):
    memory = _memory(tmp_path)
    for action in (memory.list, memory.read, memory.search):
        with pytest.raises(ToolError):
            action(
                {
                    "path": path,
                    **({"queries": ["alpha"]} if action == memory.search else {}),
                }
            )


def test_memory_search_matches_native_window_and_normalization_rules(tmp_path):
    memory = _memory(tmp_path)
    result = memory.search(
        {
            "queries": [" alpha ", "beta"],
            "match_mode": {"type": "all_within_lines", "line_count": 3},
            "path": "MEMORY.md",
            "case_sensitive": False,
        }
    )
    assert [match["match_line_number"] for match in result["matches"]] == [1, 3]
    result = memory.search(
        {"queries": ["alpha_beta"], "normalized": True, "case_sensitive": False}
    )
    assert [match["path"] for match in result["matches"]] == [
        "MEMORY.md",
        "rollout_summaries/probe.md",
    ]
    assert memory.search({"queries": ["你好"]})["matches"][0]["match_line_number"] == 4
    with pytest.raises(ToolError, match="queries must not"):
        memory.search({"queries": ["_-"], "normalized": True})


def test_memory_citation_parser_preserves_entries_and_deduplicates_ids():
    citation = "<citation_entries>\nMEMORY.md:2-4|note=[ first ]\nbad\n</citation_entries><rollout_ids>\na\na\nb\n</rollout_ids>"
    assert parse_memory_citation([citation]) == {
        "entries": [
            {"path": "MEMORY.md", "line_start": 2, "line_end": 4, "note": "first"}
        ],
        "rollout_ids": ["a", "b"],
    }
    assert parse_memory_citation(["bad"]) is None


def test_memory_tools_and_context_match_complete_native_trace(
    parity_source, upstream_codex, tmp_path
):
    config_file = parity_source / "config.toml"
    config_file.write_text(
        config_file.read_text()
        + "shell_snapshot=false\nmemories=true\n[memories]\ndedicated_tools=true\n"
    )
    root = _store(parity_source)
    # Snapshots contain regular files; backend symlinks are covered separately.
    (root / "link").unlink()
    task = tmp_path / "task"
    task.mkdir()
    filename = "2026-10-28T12-34-56-native-note.md"
    calls = [
        ("list", {"max_results": 2}),
        ("list", {"cursor": "2"}),
        ("read", {"path": "MEMORY.md", "line_offset": 2, "max_lines": 1}),
        (
            "search",
            {
                "queries": ["alpha", "beta"],
                "match_mode": {"type": "all_within_lines", "line_count": 3},
                "case_sensitive": False,
                "context_lines": 1,
            },
        ),
        (
            "search",
            {
                "queries": ["alpha_beta"],
                "normalized": True,
                "case_sensitive": False,
                "max_results": 1,
            },
        ),
        ("read", {"path": "../outside"}),
        ("read", {"path": ".hidden"}),
        ("add_ad_hoc_note", {"filename": filename, "note": "REMEMBER_NATIVE_PARITY\n"}),
        ("add_ad_hoc_note", {"filename": filename, "note": "must not overwrite"}),
        ("read", {"path": "extensions/ad_hoc/notes/" + filename}),
        ("read", {"path": "binary.bin"}),
    ]
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            shutil.rmtree(root / "extensions", ignore_errors=True)
            replay.reset(
                [(200, _call(name, args, i)) for i, (name, args) in enumerate(calls)]
                + [(200, _events("MEMORY_VERIFIED"))]
            )
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "timeout": 60,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Please remember the supplied note, then verify it.",
                    working_dir=task,
                )
            )
            assert result.status == "finished", result.error_message
            assert result.output == "MEMORY_VERIFIED"
            assert not replay.errors and not replay.steps
            assert "MEMORY_TASK_CONTEXT" in json.dumps(replay.requests[0])
            final_feedback = replay.requests[-1]["body"]["input"]
            assert any(
                "REMEMBER_NATIVE_PARITY" in str(item)
                for item in final_feedback
                if item.get("type") == "function_call_output"
            )
            assert (
                next(
                    item["output"]
                    for item in final_feedback
                    if item.get("call_id") == "call_resp_memory_10"
                    and item.get("type") == "function_call_output"
                )
                == "aborted"
            )
            observed.append(
                _normalize(
                    {
                        "requests": replay.requests,
                        "usage": dict(result.usage),
                        "output": result.output,
                    },
                    tmp_path,
                )
            )
    for label, trace in zip(("native", "python"), observed, strict=True):
        (tmp_path / f"memory-{label}.json").write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1]
