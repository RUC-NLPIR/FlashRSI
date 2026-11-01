"""Execute canonical Anthropic builders against actual original source captures."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.anthropic_messages import (
    anthropic_response,
    build_anthropic_payload,
)
from flashrsi.agents.pi_agent.runtime.pi_native.compaction import _model_catalog

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_anthropic_upstream.json").read_text()
)


def config(source, monkeypatch):
    if source.get("overrides"):
        monkeypatch.setitem(
            _model_catalog(), f"anthropic/{source['id']}", source["model"]
        )
    result = {
        "llm": {
            "model_name": f"anthropic/{source['id']}",
            "api_key": "sk-ant-oat-fixture-only"
            if source.get("oauth")
            else "fixture-only",
            "headers": source.get("headers", {}),
        }
    }
    if "maxTokens" in source:
        result["max_tokens"] = source["maxTokens"]
    return result


def response_data(source):
    return {
        "id": "offline",
        "model": source.get("responseModel", source["id"]),
        "content": source.get(
            "replyContent", [{"type": "text", "text": "offline answer"}]
        ),
        "stop_reason": "end_turn",
        **source.get("reply", {}),
        "usage": source.get(
            "usage",
            {
                "input_tokens": 7,
                "output_tokens": 3,
                "cache_read_input_tokens": 11,
                "cache_creation_input_tokens": 13,
                "cache_creation": {"ephemeral_1h_input_tokens": 5},
                "output_tokens_details": {"thinking_tokens": 2},
            },
        ),
    }


@pytest.mark.parametrize(
    "case", ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_pi_anthropic_complete_request_matches_actual_original_source(
    case, monkeypatch
):
    source, expected = case["input"], case["expected"]
    cfg = config(source, monkeypatch)
    messages = copy.deepcopy(source["messages"])
    if not expected["requests"]:
        with pytest.raises(ValueError) as exc:
            build_anthropic_payload(cfg, messages, source.get("reasoning"))
        assert str(exc.value) == expected["reply"]["errorMessage"]
        return
    for index, original in enumerate(expected["requests"]):
        actual, betas, _ = build_anthropic_payload(
            cfg,
            messages,
            source.get("reasoning"),
            cache_retention=source.get("cacheRetention"),
            disable_preferred_strict=index > 0,
        )
        assert {**actual, "stream": True} == original["body"]
        assert (",".join(betas) or None) == original["headers"].get("anthropic-beta")
    assert messages == source["messages"]


@pytest.mark.parametrize(
    "case",
    [c for c in ORACLE["cases"] if c["expected"]["requests"]],
    ids=lambda case: case["input"]["name"],
)
def test_pi_anthropic_canonical_reply_usage_and_errors_match_original_source(
    case, monkeypatch
):
    source, expected = case["input"], case["expected"]
    cfg = config(source, monkeypatch)
    _, _, managed = build_anthropic_payload(
        cfg,
        source["messages"],
        source.get("reasoning"),
        cache_retention=source.get("cacheRetention"),
    )
    expected_message = {
        key: value for key, value in expected["reply"].items() if key != "diagnostics"
    }
    assert (
        anthropic_response(
            cfg,
            response_data(source),
            context=source["messages"],
            managed_effort=managed,
        )
        == expected_message
    )


@pytest.mark.parametrize(
    "case", ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_pi_anthropic_native_provider_boundary_matches_complete_source_capture(
    case, monkeypatch
):
    source, expected = case["input"], case["expected"]
    cfg = config(source, monkeypatch)
    cfg["llm"].update(base_url="https://offline.invalid", max_retries=0)
    cfg["thinking"] = source.get("reasoning")
    cfg["cache_retention"] = source.get("cacheRetention", "short")
    captured = []

    def handler(request):
        captured.append(request)
        if source.get("strictRejection") and len(captured) == 1:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": source["strictRejection"],
                    },
                },
            )
        return httpx.Response(200, json=response_data(source))

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await loop._provider_call(
                client,
                cfg,
                "anthropic",
                source["id"],
                loop._transport_messages(source["messages"]),
                [],
                context_messages=source["messages"],
            )

    if not expected["requests"]:
        with pytest.raises(ValueError) as exc:
            asyncio.run(invoke())
        assert str(exc.value) == expected["reply"]["errorMessage"]
        assert not captured
        return
    reply = asyncio.run(invoke())
    assert len(captured) == len(expected["requests"])
    for request, original in zip(captured, expected["requests"], strict=True):
        assert {**json.loads(request.content), "stream": True} == original["body"]
        for name in ("anthropic-beta", "x-api-key", "authorization", "x-app"):
            assert request.headers.get(name) == original["headers"].get(name)
        if source.get("oauth"):
            assert request.headers["user-agent"] == original["headers"]["user-agent"]
    canonical = loop._assistant_event_message(
        reply,
        provider="anthropic",
        model=source["id"],
        api="anthropic-messages",
        timestamp=0,
    )
    canonical.pop("timestamp")
    for diagnostic in canonical.get("diagnostics", []):
        assert isinstance(diagnostic.get("timestamp"), int)
        diagnostic["timestamp"] = 0
    assert canonical == expected["reply"]
