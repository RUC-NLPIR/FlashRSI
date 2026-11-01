"""Offline oracle replay for Pi branch summaries and persistent navigation."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.branch_summary import (
    collect_entries_for_branch_summary,
    generate_branch_summary,
    navigate,
    prepare_branch_entries,
)
from flashrsi.agents.pi_agent.runtime.pi_native.compaction import content_text
from flashrsi.agents.pi_agent.runtime.pi_native.session import Session

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_branch_summary_upstream.json").read_text()
)
ZERO = {
    "input": 0,
    "output": 0,
    "cacheRead": 0,
    "cacheWrite": 0,
    "totalTokens": 0,
    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
}


def _session(tmp_path, *, persistent=False):
    entries = copy.deepcopy(ORACLE["treeEntries"])
    if not persistent:
        session = Session(tmp_path)
        session.entries = entries
        session.leaf_id = "old-leaf"
        return session
    path = tmp_path / "session.jsonl"
    header = {
        "type": "session",
        "version": 3,
        "id": "oracle",
        "cwd": str(tmp_path),
        "timestamp": "2026-11-01T00:00:00.000Z",
    }
    path.write_text("\n".join(json.dumps(e) for e in [header, *entries]) + "\n")
    return Session(tmp_path, path, "old-leaf")


def _reply(reason="stop"):
    return {
        "role": "assistant",
        "stopReason": reason,
        "usage": ZERO,
        "content": (
            [{"type": "toolCall", "id": "bad", "name": "write", "arguments": {}}]
            if reason == "toolUse"
            else [{"type": "text", "text": "branch checkpoint"}]
        ),
        **({"errorMessage": "invalid request"} if reason == "error" else {}),
    }


@pytest.mark.parametrize("case", ORACLE["collections"])
def test_pi_branch_collection_matches_actual_upstream(case, tmp_path):
    session = _session(tmp_path)
    source = case["input"]
    assert (
        collect_entries_for_branch_summary(
            session, source["oldLeafId"], source["targetId"]
        )
        == case["expected"]
    )


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda c: c["input"]["name"])
def test_pi_branch_preparation_and_summary_replay_actual_upstream(case):
    source, expected = case["input"], case["expected"]
    entries = copy.deepcopy(source["entries"])
    assert prepare_branch_entries(entries, source["budget"]) == expected["preparation"]
    requests = []

    async def summarize(messages, max_tokens):
        requests.append(messages)
        assert max_tokens == 4096
        return _reply(source.get("reason", "stop"))

    options = source["options"]
    actual = asyncio.run(
        generate_branch_summary(
            entries,
            summarize,
            context_window=options.get("contextWindow", 128000),
            model_max_tokens=4096,
            reserve_tokens=options.get("reserveTokens", 16384),
            custom_instructions=options.get("customInstructions"),
            replace_instructions=options.get("replaceInstructions", False),
        )
    )
    assert actual == expected["result"]
    assert len(requests) == len(expected["requests"])
    for actual_messages, original in zip(requests, expected["requests"], strict=True):
        original_messages = original["messages"]
        assert actual_messages[0]["content"] == original_messages[0]["content"]
        assert actual_messages[1]["content"] == content_text(
            original_messages[1]["content"]
        )
    assert entries == source["entries"]


def test_pi_branch_navigation_commits_at_target_and_restores_checkpoint(tmp_path):
    session = _session(tmp_path, persistent=True)
    original = copy.deepcopy(session.entries)
    requests = []

    async def summarize(messages, max_tokens):
        requests.append(messages)
        return _reply()

    result = asyncio.run(navigate(session, "target", summarize, label="checkpoint"))
    assert result["cancelled"] is False
    entry = result["summaryEntry"]
    assert entry["parentId"] == "target"
    assert entry["fromId"] == "old-leaf"
    assert entry["type"] == "branch_summary"
    assert entry["details"] == {
        "readFiles": ["inherited.py", "seen.py"],
        "modifiedFiles": ["changed.py", "written.py"],
    }
    assert len(requests) == 1
    assert session.entries[: len(original)] == original
    restored = Session(tmp_path, session.path)
    messages = restored.messages()
    assert any(
        m.get("role") == "branchSummary" and "branch checkpoint" in m["summary"]
        for m in messages
    )
    assert any(
        m.get("role") == "assistant"
        and "chosen branch" in content_text(m.get("content", []))
        for m in messages
    )
    assert not any(
        m.get("role") == "user"
        and "explore a branch" in content_text(m.get("content", []))
        for m in messages
    )


@pytest.mark.parametrize("reason", ["length", "error", "toolUse"])
def test_pi_branch_summary_failure_keeps_original_leaf_and_file(tmp_path, reason):
    session = _session(tmp_path, persistent=True)
    before = session.path.read_bytes()

    async def summarize(messages, max_tokens):
        return _reply(reason)

    with pytest.raises(RuntimeError, match="Branch summarization"):
        asyncio.run(navigate(session, "target", summarize))
    assert session.leaf_id == "old-leaf"
    assert session.path.read_bytes() == before


def test_pi_branch_cancel_during_summary_keeps_original_leaf_and_file(tmp_path):
    session = _session(tmp_path, persistent=True)
    before = session.path.read_bytes()

    async def scenario():
        cancel = asyncio.Event()

        async def summarize(messages, max_tokens):
            cancel.set()
            await asyncio.Event().wait()

        result = await navigate(session, "target", summarize, cancel_event=cancel)
        assert result == {"cancelled": True, "aborted": True}

    asyncio.run(scenario())
    assert session.leaf_id == "old-leaf"
    assert session.path.read_bytes() == before


def test_pi_branch_aborted_reply_keeps_original_leaf(tmp_path):
    session = _session(tmp_path)

    async def summarize(messages, max_tokens):
        return _reply("aborted")

    result = asyncio.run(navigate(session, "target", summarize))
    assert result == {"cancelled": True, "aborted": True}
    assert session.leaf_id == "old-leaf"


def test_pi_branch_selecting_user_returns_editor_text_and_summarizes_before_parent(
    tmp_path,
):
    session = _session(tmp_path)

    async def summarize(messages, max_tokens):
        return _reply()

    result = asyncio.run(navigate(session, "old-user", summarize))
    assert result["editorText"] == "explore a branch"
    assert result["summaryEntry"]["parentId"] == "root"
    assert result["summaryEntry"]["fromId"] == "old-leaf"


def test_pi_branch_navigation_without_summary_never_calls_provider(tmp_path):
    session = _session(tmp_path)

    async def summarize(messages, max_tokens):
        raise AssertionError("navigation without summarization must not call the model")

    before = len(session.entries)
    result = asyncio.run(
        navigate(session, "old-user", summarize, summarize_branch=False)
    )
    assert result == {"cancelled": False, "editorText": "explore a branch"}
    assert session.leaf_id == "root"
    assert len(session.entries) == before


def test_pi_branch_summary_retries_transient_error_and_emits_branch_events(tmp_path):
    session = _session(tmp_path)
    calls = []
    events = []

    async def summarize(messages, max_tokens):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stopReason": "error",
                "content": [],
                "errorMessage": "stream was interrupted",
            }
        return _reply()

    result = asyncio.run(
        navigate(
            session,
            "target",
            summarize,
            retry_policy={
                "enabled": True,
                "maxRetries": 1,
                "baseDelayMs": 0,
                "maxAgentDelayMs": 0,
            },
            events=events,
        )
    )
    assert result["cancelled"] is False
    assert len(calls) == 2
    assert [e["type"] for e in events] == [
        "summarization_retry_scheduled",
        "summarization_retry_attempt_start",
        "summarization_retry_finished",
    ]
    assert events[1]["source"] == "branchSummary"
