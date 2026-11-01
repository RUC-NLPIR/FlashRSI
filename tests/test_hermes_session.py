"""Durability and concurrent resume checks for explicitly selected sessions."""

import asyncio
import json

import pytest

from flashrsi.agents.hermes.runtime.hermes_native.session import Session


def test_concurrent_session_resume_observes_previous_writer(tmp_path):
    path = tmp_path / "shared.json"

    async def scenario():
        first, second = Session(path), Session(path)
        await first.open()
        first.save([{"role": "user", "content": "first"}], {}, {})
        waiting = asyncio.create_task(second.open())
        await asyncio.sleep(0.02)
        assert not waiting.done()
        first.close()
        await asyncio.wait_for(waiting, 2)
        try:
            messages = second.state["messages"]
            messages.append({"role": "assistant", "content": "second"})
            second.save(messages, {}, {})
        finally:
            second.close()

    asyncio.run(scenario())
    assert [row["content"] for row in json.loads(path.read_text())["messages"]] == [
        "first",
        "second",
    ]


def test_failed_replace_keeps_previous_session_and_releases_temporary_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "atomic.json"

    async def scenario():
        session = Session(path)
        await session.open()
        try:
            session.save([{"role": "user", "content": "original"}], {}, {})
            original = path.read_bytes()

            def fail(*_):
                raise OSError("synthetic write failure")

            monkeypatch.setattr(
                "flashrsi.agents.hermes.runtime.hermes_native.session.os.replace", fail
            )
            with pytest.raises(OSError, match="synthetic"):
                session.save([{"role": "user", "content": "replacement"}], {}, {})
            assert path.read_bytes() == original
            assert not list(tmp_path.glob("*.tmp"))
        finally:
            session.close()

    asyncio.run(scenario())


def test_interrupted_tool_round_is_paired_without_reexecuting_actions(tmp_path):
    path = tmp_path / "interrupted.json"

    async def scenario():
        session = Session(path)
        await session.open()
        try:
            session.save(
                [
                    {"role": "user", "content": "make a change"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "pending",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path":"note","content":"x"}',
                                },
                            }
                        ],
                    },
                ],
                {},
                {},
            )
        finally:
            session.close()

    asyncio.run(scenario())
    history = json.loads(path.read_text())["messages"]
    assert history[-2]["role"] == "tool" and history[-2]["tool_call_id"] == "pending"
    assert "interrupted" in history[-2]["content"].lower()
    assert history[-1]["role"] == "assistant"
    assert not (tmp_path / "note").exists()


def test_recovery_scaffolding_is_excluded_from_durable_history(tmp_path):
    path = tmp_path / "scaffolding.json"

    async def scenario():
        session = Session(path)
        await session.open()
        try:
            session.save(
                [
                    {"role": "user", "content": "real request"},
                    {
                        "role": "assistant",
                        "content": "prefill",
                        "_thinking_prefill": True,
                    },
                    {
                        "role": "user",
                        "content": "retry",
                        "_empty_recovery_synthetic": True,
                    },
                    {
                        "role": "user",
                        "content": "dropped",
                        "_dropped_toolcall_nudge": True,
                    },
                    {"role": "assistant", "content": "real answer"},
                ],
                {},
                {},
            )
        finally:
            session.close()

    asyncio.run(scenario())
    assert [row["content"] for row in json.loads(path.read_text())["messages"]] == [
        "real request",
        "real answer",
    ]
