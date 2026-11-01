"""Compare native provider boundaries with the pinned original SDK execution."""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.compaction import _model_catalog
from flashrsi.agents.pi_agent.runtime.pi_native.openai_provider import (
    build_payload,
    response_message,
)

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_openai_dynamic_upstream.json").read_text()
)


def configured(source, monkeypatch):
    config = copy.deepcopy(source["config"])
    config["thinking"] = source.get("reasoning")
    monkeypatch.setitem(
        _model_catalog(), config["llm"]["model_name"], copy.deepcopy(source["model"])
    )
    return config


def semantic_request(payload):
    result = copy.deepcopy(payload)
    # The native runtime collects complete JSON replies. These transport and
    # session-cache fields do not alter the semantic model request.
    for key in ("stream", "stream_options", "prompt_cache_key"):
        result.pop(key, None)
    return result


@pytest.mark.parametrize(
    "case", ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_pi_openai_dynamic_request_matches_actual_original_source(case, monkeypatch):
    source, expected = case["input"], case["expected"]
    config = configured(source, monkeypatch)
    context = copy.deepcopy(source["context"])
    if not expected["requests"]:
        with pytest.raises(ValueError) as exc:
            build_payload(config, context, source["api"], source.get("reasoning"))
        assert str(exc.value) == expected["reply"]["errorMessage"]
    else:
        actual, _ = build_payload(
            config, context, source["api"], source.get("reasoning")
        )
        assert len(expected["requests"]) == 1
        assert semantic_request(actual) == semantic_request(
            expected["requests"][0]["body"]
        )
    assert context == source["context"]


@pytest.mark.parametrize(
    "case",
    [case for case in ORACLE["cases"] if case["expected"]["requests"]],
    ids=lambda case: case["input"]["name"],
)
def test_pi_openai_dynamic_canonical_reply_matches_actual_original_source(
    case, monkeypatch
):
    source = case["input"]
    config = configured(source, monkeypatch)
    _, managed = build_payload(
        config, source["context"], source["api"], source.get("reasoning")
    )
    response = copy.deepcopy(source["response"])
    actual = response_message(
        config,
        response,
        source["api"],
        managed_effort=managed,
        context=source["context"],
    )
    assert actual == case["expected"]["reply"]
    assert response == source["response"]


@pytest.mark.parametrize(
    "case", ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_pi_openai_native_provider_boundary_matches_actual_original_source(
    case, monkeypatch
):
    source, expected = case["input"], case["expected"]
    config = configured(source, monkeypatch)
    provider, model = config["llm"]["model_name"].split("/", 1)
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=source["response"])

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await loop._provider_call(
                client,
                config,
                provider,
                model,
                loop._transport_messages(source["context"]),
                [],
                context_messages=source["context"],
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
        assert request.url.path == (
            "/v1/chat/completions"
            if source["api"] == "openai-completions"
            else "/v1/responses"
        )
        assert request.headers["authorization"] == "Bearer sk-offline-fixture"
        assert semantic_request(json.loads(request.content)) == semantic_request(
            original["body"]
        )
    canonical = loop._assistant_event_message(
        reply,
        provider=provider,
        model=model,
        api=source["api"],
        timestamp=0,
    )
    canonical.pop("timestamp")
    assert canonical == expected["reply"]


def test_pi_openai_dynamic_oracle_uses_pinned_source_and_offline_sdk_transport():
    assert ORACLE["baseline"] == ("v1.4.0@4a080252f06caf63a525d7873c5d94d3c23887e0")
    assert "deterministic offline SSE" in ORACLE["method"]
    assert "packages/ai/src/utils/transcript.ts" in ORACLE["source_sha256"]
