"""Explicit Pi API selection must match dispatch, events and validation."""

import asyncio
import json

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.resources import ResourceBundle


@pytest.mark.parametrize("api", ["openai-respones", "unknown", 3, False, {}, []])
def test_pi_unknown_model_api_fails_before_session_side_effects(tmp_path, api):
    path = tmp_path / "not-created" / "session.jsonl"
    config = {
        "llm": {
            "model_name": "openai/mock",
            "api_key": "fixture-only",
            "model_api": api,
        },
        "session_file": str(path),
    }
    with pytest.raises(ValueError, match="llm.model_api"):
        asyncio.run(loop.run(config, "hello", tmp_path, tmp_path))
    assert not path.parent.exists()


@pytest.mark.parametrize(
    ("provider", "api", "endpoint"),
    [
        ("anthropic", "openai-responses", "/responses"),
        ("anthropic", "openai-completions", "/chat/completions"),
        ("openai", "anthropic-messages", "/v1/messages"),
    ],
)
def test_pi_explicit_model_api_controls_dispatch_and_event_api(
    tmp_path, monkeypatch, provider, api, endpoint
):
    requests = []

    def handler(request):
        requests.append((str(request.url), json.loads(request.content)))
        if api == "openai-responses":
            payload = {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "selected"}],
                    }
                ],
            }
        elif api == "anthropic-messages":
            payload = {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "selected"}],
            }
        else:
            payload = {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "selected"},
                    }
                ]
            }
        return httpx.Response(200, json=payload)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        loop.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        ),
    )
    result = asyncio.run(
        loop.run(
            {
                "llm": {
                    "model_name": f"{provider}/mock",
                    "model_api": api,
                    "api_key": "fixture-only",
                    "base_url": "https://offline.invalid",
                    "max_retries": 0,
                },
                "tools": [],
                "compaction": False,
            },
            "hello",
            tmp_path,
            tmp_path,
            ResourceBundle(system_prompt="system", tool_schemas=[]),
        )
    )
    assert result.status == "finished"
    assert result.output == "selected"
    assert len(requests) == 1
    assert requests[0][0].endswith(endpoint)
    assistant = next(
        event["message"]
        for event in result.events
        if event["type"] == "message_end" and event["message"]["role"] == "assistant"
    )
    assert assistant["api"] == api
    assert assistant["provider"] == provider


@pytest.mark.parametrize("api", [None, ""])
@pytest.mark.parametrize(
    ("provider", "expected"),
    [("anthropic", "anthropic-messages"), ("openai", "openai-completions")],
)
def test_pi_empty_model_api_keeps_provider_default(api, provider, expected):
    assert loop._api_name(provider, {"llm": {"model_api": api}}) == expected
