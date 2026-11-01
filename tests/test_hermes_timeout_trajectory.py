"""An adapter deadline must retain completed work and settle native cleanup."""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx

from flashrsi.agents.hermes import Hermes


def test_timeout_keeps_completed_tool_events_usage_and_persisted_history(
    tmp_path, monkeypatch
):
    calls = 0

    async def reply(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "saving result",
                                "tool_calls": [
                                    {
                                        "id": "write",
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": json.dumps(
                                                {
                                                    "path": "result.txt",
                                                    "content": "saved",
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 23, "completion_tokens": 7},
                },
            )
        await asyncio.Event().wait()

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: original(
            *a, **kw, transport=httpx.MockTransport(reply), trust_env=False
        ),
    )
    agent = Hermes(
        {
            "timeout": 0.5,
            "session_file": "session.json",
            "compression": {"enabled": False},
            "llm": {
                "model_name": "test",
                "api_key": "deadline-test-secret",
                "base_url": "https://local.invalid/v1",
            },
        }
    )
    result = asyncio.run(agent.run("write the result", tmp_path))
    assert calls == 2
    assert result.status == "error"
    assert "timed out" in result.error_message
    assert result.usage["input"] == 23
    assert result.usage["output"] == 7
    assert (tmp_path / "result.txt").read_text() == "saved"
    assert any(event["type"] == "tool_execution_end" for event in result.messages)
    assert any(
        event["type"] == "hermes_result" and event.get("aborted")
        for event in result.messages
    )
    saved = json.loads((tmp_path / "session.json").read_text())
    assert any(message["role"] == "tool" for message in saved["messages"])


def test_timeout_preserves_old_snapshot_run_signature(tmp_path, monkeypatch):
    import flashrsi.agents.hermes as adapter

    async def old_run(config, prompt, cwd, snapshot_root):
        await asyncio.Event().wait()

    @contextmanager
    def snapshot_runtime(root):
        yield SimpleNamespace(run=old_run)

    monkeypatch.setattr(adapter, "_native_runtime", snapshot_runtime)
    agent = Hermes(
        {
            "timeout": 0.01,
            "llm": {"model_name": "test", "api_key": "secret"},
        }
    )
    result = asyncio.run(agent.run("hello", tmp_path))
    assert result.status == "error"
    assert "timed out" in result.error_message
