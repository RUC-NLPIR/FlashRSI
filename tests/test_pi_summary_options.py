"""Actual upstream provider requests and Python-only headless integration."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.provider_options import (
    anthropic_options,
    clamp_max_tokens,
    estimate_context_tokens,
    estimate_message_tokens,
)
from flashrsi.agents.pi_agent.runtime.pi_native.resources import ResourceBundle
from flashrsi.agents.pi_agent.runtime.pi_native.session import Session

ORACLE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "pi_summary_options_upstream.json"
    ).read_text()
)


@pytest.mark.parametrize(
    "case", ORACLE["tokens"], ids=lambda case: case["input"]["name"]
)
def test_pi_provider_estimation_and_output_cap_match_original_source(case):
    source, expected = case["input"], case["expected"]
    messages = source["context"]["messages"]
    assert estimate_context_tokens(messages) == expected["estimate"]
    assert [estimate_message_tokens(m) for m in messages] == expected["messageTokens"]
    assert (
        clamp_max_tokens(source["model"]["contextWindow"], messages, source["output"])
        == expected["clamped"]
    )


@pytest.mark.parametrize(
    "case", ORACLE["providers"], ids=lambda case: case["input"]["name"]
)
def test_pi_native_anthropic_request_options_match_original_actual_provider(case):
    source, expected = case["input"], case["expected"]
    cfg = {
        "llm": {
            "model_name": f"anthropic/{source['id']}",
            "api_key": "explicit-role-key",
            "base_url": "https://offline.invalid",
            "max_retries": 0,
        },
        "thinking": source["thinkingLevel"],
        "context_window": source["model"]["contextWindow"],
        "model_max_tokens": source["model"]["maxTokens"],
    }
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "offline summary"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await loop._provider_call(
                client,
                cfg,
                "anthropic",
                source["id"],
                loop._transport_messages(source["context"]["messages"]),
                [],
                context_messages=source["context"]["messages"],
            )

    reply = asyncio.run(invoke())
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    original = expected["requests"][0]
    for key in ("max_tokens", "thinking", "output_config", "fallbacks"):
        assert body.get(key) == original["body"].get(key)
    assert requests[0].headers.get("anthropic-beta") == original["headers"].get(
        "anthropic-beta"
    )
    assert requests[0].headers["x-api-key"] == "explicit-role-key"
    actual_markers = [m for m in body["messages"] if m["role"] == "system"]
    original_markers = [
        m for m in original["body"]["messages"] if m["role"] == "system"
    ]
    assert actual_markers == original_markers
    assert reply.raw.get("_provider_thinking_level") == expected.get(
        "providerThinkingLevel"
    )


def _config(path=None, **updates):
    result = {
        "llm": {
            "model_name": "anthropic/claude-sonnet-4-5",
            "api_key": "explicit-role-key",
            "base_url": "https://offline.invalid",
            "max_retries": 0,
        },
        "thinking": "high",
        "tools": [],
        "compaction": False,
    }
    if path:
        result["session_file"] = str(path)
    result.update(updates)
    return result


def _run(tmp_path, config, prompt):
    return asyncio.run(
        loop.run(
            config,
            prompt,
            tmp_path,
            tmp_path,
            ResourceBundle(system_prompt="system", tool_schemas=[]),
        )
    )


def _transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        loop.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        ),
    )


def test_pi_main_anthropic_signed_thinking_survives_persistent_resume(
    tmp_path, monkeypatch
):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["max_tokens"] == 64000
        assert payload["thinking"]["budget_tokens"] == 16384
        if len(requests) == 2:
            prior = next(m for m in payload["messages"] if m["role"] == "assistant")
            assert prior["content"][0] == {
                "type": "thinking",
                "thinking": "private reasoning",
                "signature": "signed-token",
            }
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "private reasoning",
                        "signature": "signed-token",
                    },
                    {"type": "text", "text": "done"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    _transport(monkeypatch, handler)
    path = tmp_path / "session.jsonl"
    assert _run(tmp_path, _config(path), "first").output == "done"
    saved = Session(tmp_path, path).entries[-1]["message"]
    assert saved["content"][0]["thinkingSignature"] == "signed-token"
    assert _run(tmp_path, _config(path), "continue").output == "done"
    assert len(requests) == 2


@pytest.mark.parametrize(
    "api", ["openai-completions", "openai-responses", "anthropic-messages"]
)
def test_pi_summary_output_context_clamp_reaches_all_native_routes(
    api, tmp_path, monkeypatch
):
    main_oracle = json.loads(
        (Path(__file__).parent / "fixtures" / "pi_compaction_upstream.json").read_text()
    )
    entries = copy.deepcopy(main_oracle["cases"][0]["input"]["entries"])
    path = tmp_path / "session.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(item)
            for item in [
                {
                    "type": "session",
                    "version": 3,
                    "id": "fixture",
                    "cwd": str(tmp_path),
                },
                *entries,
            ]
        )
        + "\n"
    )
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        cap = payload.get(
            "max_tokens",
            payload.get("max_completion_tokens", payload.get("max_output_tokens")),
        )
        # The fixed original summary prompt alone exhausts this small window.
        assert cap == (16 if api == "openai-responses" else 1)
        if api == "anthropic-messages":
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "checkpoint"}],
                    "stop_reason": "end_turn",
                },
            )
        if api == "openai-responses":
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "checkpoint"}],
                        }
                    ],
                    "status": "completed",
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "checkpoint"}, "finish_reason": "stop"}
                ]
            },
        )

    _transport(monkeypatch, handler)
    cfg = _config(
        path,
        context_window=4096,
        model_max_tokens=4096,
        compaction={"keepRecentTokens": 11},
    )
    cfg["llm"].update(model_name="openai/oracle", model_api=api)
    result = _run(tmp_path, cfg, "/compact")
    assert result.status == "finished"
    assert len(requests) == 1


def test_pi_anthropic_main_context_usage_limits_output_and_answer_room():
    cfg = _config(context_window=10000, model_max_tokens=64000, max_tokens=2000)
    messages = [
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "done"}],
            "stopReason": "stop",
            "timestamp": 1,
            "usage": {"input": 5000, "output": 100, "totalTokens": 5100},
        }
    ]
    options, _, _ = anthropic_options(cfg, messages, "high")
    assert options["max_tokens"] == 804
    assert options["thinking"]["budget_tokens"] == 1024  # Pi's original || fallback
    cfg["thinking"] = "off"
    options, _, _ = anthropic_options(cfg, messages, None)
    assert options == {"max_tokens": 804, "thinking": {"type": "disabled"}}


@pytest.mark.parametrize(
    "command,expected_type", [("/compact", "enabled"), ("/tree e2", "disabled")]
)
def test_pi_branch_summary_omits_main_thinking_but_compaction_inherits_it(
    command, expected_type, tmp_path, monkeypatch
):
    main_oracle = json.loads(
        (Path(__file__).parent / "fixtures" / "pi_compaction_upstream.json").read_text()
    )
    path = tmp_path / "session.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(item)
            for item in [
                {
                    "type": "session",
                    "version": 3,
                    "id": "fixture",
                    "cwd": str(tmp_path),
                },
                *main_oracle["cases"][0]["input"]["entries"],
            ]
        )
        + "\n"
    )
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["thinking"]["type"] == expected_type
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "checkpoint"}],
                "stop_reason": "end_turn",
            },
        )

    _transport(monkeypatch, handler)
    cfg = _config(path, compaction={"keepRecentTokens": 11})
    result = _run(tmp_path, cfg, command)
    assert result.status == "finished"
    assert len(requests) == 1


def test_pi_managed_effort_and_explicit_beta_headers_survive_main_resume(
    tmp_path, monkeypatch
):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.headers.get_list("anthropic-beta") == ["caller-beta"]
        markers = [
            m["output_config"]["effort"]
            for m in payload["messages"]
            if m["role"] == "system"
        ]
        assert markers == (["low"] if len(requests) == 1 else ["low", "max"])
        assert payload["thinking"]["block_binding"] == {
            "prefix_mismatch_behavior": "drop_block"
        }
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
            },
        )

    _transport(monkeypatch, handler)
    path = tmp_path / "session.jsonl"
    cfg = _config(path, thinking="low")
    # Lookup must normalize exactly as _model does; preserve caller header casing.
    cfg["llm"].update(
        model_name=" Anthropic/claude-fable-5-1 ",
        headers={"Anthropic-Beta": "caller-beta"},
    )
    assert _run(tmp_path, cfg, "first").output == "done"
    assert (
        Session(tmp_path, path).entries[-1]["message"]["providerThinkingLevel"] == "low"
    )
    cfg["thinking"] = "max"
    assert _run(tmp_path, cfg, "continue").output == "done"
    assert len(requests) == 2
