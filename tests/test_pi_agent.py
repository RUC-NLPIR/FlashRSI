"""Contract tests for the pure-Python Pi Target harness."""

import asyncio
import json
from pathlib import Path

from flashrsi.agents.pi_agent import Pi
from flashrsi.agents.pi_agent.runtime.pi_native import loop


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _Client:
    responses = []
    requests = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        type(self).requests = []
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, headers, json):
        type(self).requests.append((url, headers, json))
        return type(self).responses.pop(0)


def test_pi_snapshot_contains_only_python_runtime():
    agent = Pi({"llm": {"model_name": "openai/gpt-5", "api_key": "secret"}})
    assert "runtime/pi_native/loop.py" in agent.snapshot.files
    assert "runtime/pi_native/tools.py" in agent.snapshot.files
    assert ".pi/agent/settings.json" in agent.snapshot.files
    assert not any(path.startswith("runtime/pi/") for path in agent.snapshot.files)


def test_pi_native_loop_emits_tool_lifecycle_and_usage(tmp_path, monkeypatch):
    (tmp_path / "note.txt").write_text("before\n", encoding="utf-8")
    first = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "edit",
                                "arguments": json.dumps(
                                    {
                                        "path": "note.txt",
                                        "edits": [
                                            {"oldText": "before", "newText": "after"}
                                        ],
                                    }
                                ),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }
    second = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "done"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 2},
    }
    _Client.responses = [_Response(first), _Response(second)]
    monkeypatch.setattr(loop.httpx, "AsyncClient", _Client)
    config = {
        "timeout": 10,
        "llm": {
            "model_name": "openai/gpt-4o",
            "api_key": "secret",
            "base_url": "https://provider.test/v1",
            "model_api": "openai-completions",
        },
        "max_turns": 4,
    }

    result = asyncio.run(
        loop.run(
            config,
            "update the note",
            tmp_path,
            Path(__file__).parents[1] / "flashrsi" / "agents" / "pi_agent",
        )
    )

    assert result.status == "finished"
    assert result.output == "done"
    assert result.usage["input"] == 22
    assert result.usage["output"] == 6
    assert result.usage["total_tokens"] == 28
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "after\n"
    types = [event["type"] for event in result.events]
    assert types[0] == "session"
    assert result.events[0]["version"] == 3
    assert result.events[0]["cwd"] == str(tmp_path)
    assert types.count("message_start") >= 4  # user, two assistants, tool result
    assert types.count("message_end") >= 4
    updates = [event for event in result.events if event["type"] == "message_update"]
    assert any(
        event["assistantMessageEvent"]["type"] == "toolcall_end" for event in updates
    )
    assert types.count("tool_execution_start") == 1
    assert types.count("tool_execution_end") == 1
    turn_with_tool = next(
        event for event in result.events if event["type"] == "turn_end"
    )
    assert turn_with_tool["toolResults"][0]["role"] == "toolResult"
    assert types[-1] == "agent_settled"
    assert _Client.requests[0][0].endswith("/chat/completions")
    assert _Client.requests[0][2]["tools"]


def test_pi_native_loop_requires_model_and_api_key(tmp_path):
    try:
        asyncio.run(
            loop.run(
                {"llm": {"model_name": "openai/gpt-5"}},
                "hello",
                tmp_path,
                Path(__file__).parents[1] / "flashrsi" / "agents" / "pi_agent",
            )
        )
    except ValueError as exc:
        assert "api_key" in str(exc)
    else:
        raise AssertionError("missing API key should fail before making a request")


def test_pi_usage_matches_upstream_cached_token_accounting():
    openai = loop._pi_usage(
        {
            "prompt_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens": 4,
        }
    )
    assert openai["input"] == 7
    assert openai["cacheRead"] == 3
    assert openai["totalTokens"] == 14

    anthropic = loop._pi_usage(
        {"input_tokens": 10, "cache_read_input_tokens": 3, "output_tokens": 4}
    )
    assert anthropic["input"] == 10
    assert anthropic["cacheRead"] == 3
    assert anthropic["totalTokens"] == 17


def test_pi_adapter_executes_selected_snapshot_runtime(tmp_path, monkeypatch):
    _Client.responses = [
        _Response(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "native"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            }
        )
    ]
    monkeypatch.setattr(loop.httpx, "AsyncClient", _Client)
    agent = Pi(
        {
            "llm": {
                "model_name": "openai/gpt-4o",
                "api_key": "secret",
                "base_url": "https://provider.test/v1",
                "model_api": "openai-completions",
            }
        }
    )
    result = asyncio.run(agent.run("hello", tmp_path))
    assert result.status == "finished"
    assert result.output == "native"
    assert result.usage["input"] == 2
    assert result.usage["output"] == 3


def test_pi_explicit_responses_api(tmp_path, monkeypatch):
    _Client.responses = [
        _Response(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "reasoned"}],
                    }
                ],
                "status": "completed",
                "usage": {"input_tokens": 5, "output_tokens": 7},
            }
        )
    ]
    monkeypatch.setattr(loop.httpx, "AsyncClient", _Client)
    result = asyncio.run(
        loop.run(
            {
                "llm": {
                    "model_name": "openai/gpt-5",
                    "model_api": "openai-responses",
                    "api_key": "secret",
                    "base_url": "https://provider.test/v1",
                }
            },
            "hello",
            tmp_path,
            Path(__file__).parents[1] / "flashrsi" / "agents" / "pi_agent",
        )
    )
    assert result.status == "finished"
    assert result.output == "reasoned"
    assert result.usage["input"] == 5
    assert result.usage["output"] == 7
    assert _Client.requests[0][0].endswith("/responses")


def test_pi_responses_api_tool_loop_preserves_function_outputs(tmp_path, monkeypatch):
    _Client.responses = [
        _Response(
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "write",
                        "arguments": json.dumps(
                            {"path": "result.txt", "content": "native"}
                        ),
                    }
                ],
                "status": "completed",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            }
        ),
        _Response(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
                "status": "completed",
                "usage": {"input_tokens": 4, "output_tokens": 1},
            }
        ),
    ]
    monkeypatch.setattr(loop.httpx, "AsyncClient", _Client)
    result = asyncio.run(
        loop.run(
            {
                "llm": {
                    "model_name": "openai/gpt-5",
                    "model_api": "openai-responses",
                    "api_key": "secret",
                    "base_url": "https://provider.test/v1",
                },
                "max_turns": 2,
            },
            "write a file",
            tmp_path,
            Path(__file__).parents[1] / "flashrsi" / "agents" / "pi_agent",
        )
    )
    assert result.status == "finished"
    assert result.output == "done"
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "native"
    assert _Client.requests[1][2]["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "Successfully wrote to result.txt",
    }


def test_pi_length_truncated_tool_call_is_reported_without_execution(
    tmp_path, monkeypatch
):
    target = tmp_path / "note.txt"
    target.write_text("before\n", encoding="utf-8")
    _Client.responses = [
        _Response(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-truncated",
                                    "type": "function",
                                    "function": {
                                        "name": "edit",
                                        "arguments": json.dumps(
                                            {
                                                "path": "note.txt",
                                                "edits": [
                                                    {
                                                        "oldText": "before",
                                                        "newText": "after",
                                                    }
                                                ],
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "length",
                    }
                ]
            }
        ),
        _Response(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "retry"},
                        "finish_reason": "stop",
                    }
                ]
            }
        ),
    ]
    monkeypatch.setattr(loop.httpx, "AsyncClient", _Client)
    result = asyncio.run(
        loop.run(
            {
                "llm": {
                    "model_name": "openai/gpt-4o",
                    "api_key": "secret",
                    "base_url": "https://provider.test/v1",
                    "model_api": "openai-completions",
                },
                "max_turns": 2,
            },
            "update the note",
            tmp_path,
            Path(__file__).parents[1] / "flashrsi" / "agents" / "pi_agent",
        )
    )

    assert result.status == "finished"
    assert result.output == "retry"
    assert target.read_text(encoding="utf-8") == "before\n"
    execution_end = next(
        event for event in result.events if event["type"] == "tool_execution_end"
    )
    assert execution_end["isError"] is True
    assert "output token limit" in execution_end["result"]["content"][0]["text"]
    assert "durationMs" not in execution_end


def test_pi_provider_error_completes_turn_before_settlement(tmp_path, monkeypatch):
    _Client.responses = [_Response({}, status_code=503)]
    monkeypatch.setattr(loop.httpx, "AsyncClient", _Client)
    result = asyncio.run(
        loop.run(
            {
                "llm": {
                    "model_name": "openai/gpt-4o",
                    "api_key": "secret",
                    "base_url": "https://provider.test/v1",
                    "model_api": "openai-completions",
                    "max_retries": 0,
                },
                "retry": {"enabled": False},
            },
            "hello",
            tmp_path,
            Path(__file__).parents[1] / "flashrsi" / "agents" / "pi_agent",
        )
    )

    assert result.status == "error"
    types = [event["type"] for event in result.events]
    assert types[-3:] == ["turn_end", "agent_end", "agent_settled"]
    assert result.events[-3]["message"]["stopReason"] == "error"


def test_pi_anthropic_provider_uses_single_messages_endpoint(tmp_path, monkeypatch):
    _Client.responses = [
        _Response(
            {
                "content": [{"type": "text", "text": "anthropic"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 4},
            }
        )
    ]
    monkeypatch.setattr(loop.httpx, "AsyncClient", _Client)
    config = {
        "llm": {
            "model_name": "anthropic/claude-sonnet",
            "api_key": "secret",
            "base_url": "https://api.anthropic.test",
        }
    }
    result = asyncio.run(
        loop.run(
            config,
            "hello",
            tmp_path,
            Path(__file__).parents[1] / "flashrsi" / "agents" / "pi_agent",
        )
    )
    assert result.status == "finished"
    assert result.output == "anthropic"
    assert _Client.requests[0][0] == "https://api.anthropic.test/v1/messages"
