"""Original-source option captures exercised through native HTTP boundaries.

All transports are httpx.MockTransport: this checks production option plumbing
and snapshot settings, without network requests or model generation.
"""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.compaction import _model_catalog
from flashrsi.agents.pi_agent.runtime.pi_native.resources import ResourceBundle

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_openai_options_upstream.json").read_text()
)
CONTEXT = [
    {"role": "system", "content": "system", "timestamp": 0},
    {"role": "user", "content": "hello", "timestamp": 1},
]
AFFINITY_HEADERS = (
    "session_id",
    "x-session-id",
    "x-client-request-id",
    "x-session-affinity",
)


def configured(model, monkeypatch, **updates):
    model = copy.deepcopy(model)
    provider, name = model["provider"], model["id"]
    key = f"{provider}/{name}"
    monkeypatch.setitem(_model_catalog(), key, model)
    cfg = {
        "llm": {
            "model_name": key,
            "model_api": model["api"],
            "api_key": "sk-offline-fixture",
            "base_url": model["baseUrl"],
            "max_retries": 0,
        },
        "tools": [],
        "compaction": False,
        "retry": {"enabled": False},
    }
    cfg.update(updates)
    return cfg


def reply_body(api, *, tier=None):
    usage = {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "input_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 10},
    }
    if api == "openai-completions":
        return {
            "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
    if api == "anthropic-messages":
        return {
            "id": "msg_fixture",
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    return {
        "id": "resp_fixture",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_fixture",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
            }
        ],
        "service_tier": tier,
        "usage": usage,
    }


def boundary(cfg, context=CONTEXT, *, tier=None):
    captured = []
    api = cfg["llm"]["model_api"]

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=reply_body(api, tier=tier))

    async def invoke():
        provider, model = cfg["llm"]["model_name"].split("/", 1)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as client:
            return await loop._provider_call(
                client,
                cfg,
                provider,
                model,
                loop._transport_messages(context),
                [],
                context_messages=context,
            )

    reply = asyncio.run(invoke())
    assert len(captured) == 1
    return captured[0], reply


@pytest.mark.parametrize("case", ORACLE["bodyCases"], ids=lambda case: case["name"])
def test_native_openai_http_options_match_original_capture(case, monkeypatch):
    cfg = configured(case["model"], monkeypatch)
    if case.get("kind") == "cache":
        cfg.update(cache_retention=case["retention"], _session_id=case["session_id"])
        cfg["llm"]["api_key"] = case["api_key"]
        # The body oracle deliberately uses astral characters to test key
        # truncation. HTTP session headers need byte-compatible values; source
        # request headers can override those independently of the cache key.
        if case["api"] == "openai-responses":
            cfg["llm"]["headers"] = {
                "session_id": "ascii-session",
                "x-client-request-id": "ascii-session",
            }
    else:
        cfg.update(
            thinking=case["level"],
            max_tokens=case["ceiling"],
            thinking_budgets=case["thinking_budgets"],
        )
    request, reply = boundary(cfg)
    assert reply.stop_reason == "stop"
    payload = json.loads(request.content)
    if case.get("kind") == "cache":
        actual = {
            key: value
            for key, value in payload.items()
            if key.startswith("prompt_cache_")
        }
    else:
        for key in (
            "model",
            "messages",
            "stream",
            "stream_options",
            "max_tokens",
            "max_completion_tokens",
            "store",
            "prompt_cache_key",
            "prompt_cache_retention",
        ):
            payload.pop(key, None)
        actual = payload
    assert actual == case["expected"]


@pytest.mark.parametrize("case", ORACLE["headerCases"], ids=lambda case: case["name"])
def test_native_http_session_headers_match_original_capture(case, monkeypatch):
    model = copy.deepcopy(ORACLE["bodyCases"][0]["model"])
    model.update(api=case["api"], compat=case["compat"])
    cfg = configured(model, monkeypatch, _session_id=case["session_id"])
    request, _ = boundary(cfg)
    actual = {
        name: request.headers[name]
        for name in AFFINITY_HEADERS
        if name in request.headers
    }
    assert actual == case["expected"]


@pytest.mark.parametrize("api", ["openai-completions", "openai-responses"])
@pytest.mark.parametrize("format", ["openai", "openrouter"])
def test_native_header_precedence_model_then_session_then_explicit(
    api, format, monkeypatch
):
    original = next(
        case
        for case in ORACLE["headerCases"]
        if case["name"] == f"headers_{api}_{format}_short"
    )
    model = copy.deepcopy(ORACLE["bodyCases"][0]["model"])
    model.update(
        api=api,
        compat=original["compat"],
        headers={name.upper(): "model-value" for name in AFFINITY_HEADERS},
    )
    cfg = configured(model, monkeypatch, _session_id="session-fixture")
    cfg["llm"]["headers"] = {"X-Client-Request-ID": "request-value"}
    request, _ = boundary(cfg)
    expected = {
        **dict.fromkeys(AFFINITY_HEADERS, "model-value"),
        **original["expected"],
        "x-client-request-id": "request-value",
    }
    assert {name: request.headers[name] for name in AFFINITY_HEADERS} == expected


@pytest.mark.parametrize("case", ORACLE["costCases"], ids=lambda case: case["name"])
def test_native_responses_service_tier_cost_matches_original_capture(case, monkeypatch):
    model = copy.deepcopy(ORACLE["bodyCases"][0]["model"])
    model.update(
        api="openai-responses",
        id=case["model_id"],
        cost={"input": 2, "output": 8, "cacheRead": 1, "cacheWrite": 3},
    )
    cfg = configured(model, monkeypatch)
    _, reply = boundary(cfg, tier=case["tier"])
    assert reply.usage["cost"] == pytest.approx(case["expected"]["cost"])
    assert {key: value for key, value in reply.usage.items() if key != "cost"} == {
        key: value for key, value in case["expected"].items() if key != "cost"
    }


def test_native_sampling_parameters_override_named_compatibility_fields(monkeypatch):
    case = next(c for c in ORACLE["bodyCases"] if c["name"] == "budget_default_alias")
    model = copy.deepcopy(case["model"])
    model["samplingParams"] = {"thinking_token_budget": 700, "temperature": 0.1}
    model["samplingParamsByThinkingLevel"] = {"high": {"thinking_token_budget": 800}}
    cfg = configured(model, monkeypatch, thinking="high", temperature=0.2)
    cfg["sampling_params"] = {"thinking_token_budget": 900, "temperature": 0.3}
    request, _ = boundary(cfg)
    body = json.loads(request.content)
    assert body["thinking_token_budget"] == 900
    assert body["temperature"] == 0.3


@pytest.mark.parametrize(
    "case", ORACLE["cacheControlCases"], ids=lambda case: case["name"]
)
def test_native_compatible_cache_boundaries_match_complete_original_body(
    case, monkeypatch
):
    model = copy.deepcopy(ORACLE["bodyCases"][0]["model"])
    model["compat"] = case["compat"]
    context = copy.deepcopy(CONTEXT)
    zero = {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 0,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
    }
    assistant = {
        "role": "assistant",
        "content": [],
        "usage": zero,
        "stopReason": "stop",
        "api": "openai-completions",
        "provider": "fixture",
        "model": "gpt-5",
        "timestamp": 2,
    }
    if "last_assistant_empty_skipped" in case["name"]:
        context.append(assistant)
    elif "last_image_only_user_skipped" in case["name"]:
        context.append(
            {
                "role": "user",
                "content": [
                    {"type": "image", "mimeType": "image/png", "data": "aGVsbG8="}
                ],
                "timestamp": 2,
            }
        )
    elif "last_tool_and_last_tool_definition" in case["name"]:
        tool = {
            "name": "fixture",
            "description": "fixture",
            "parameters": {"type": "object", "properties": {}},
        }
        context[0]["toolsAdded"] = [tool, {**tool, "name": "second"}]
        assistant.update(
            content=[
                {
                    "type": "toolCall",
                    "id": "call_one",
                    "name": "fixture",
                    "arguments": {},
                }
            ],
            stopReason="toolUse",
        )
        context.extend(
            [
                assistant,
                {
                    "role": "toolResult",
                    "toolCallId": "call_one",
                    "toolName": "fixture",
                    "content": [
                        {"type": "text", "text": "first"},
                        {"type": "text", "text": "last"},
                    ],
                    "isError": False,
                    "timestamp": 3,
                },
            ]
        )
    cfg = configured(
        model, monkeypatch, max_tokens=10000, cache_retention=case["retention"]
    )
    request, _ = boundary(cfg, context)
    expected = copy.deepcopy(case["expected"])
    assert json.loads(request.content) == expected


@pytest.mark.parametrize("api", ["openai-completions", "anthropic-messages"])
@pytest.mark.parametrize("override", [None, "thinking_budgets", "thinkingBudgets"])
def test_snapshot_saved_thinking_budgets_reach_main_provider(
    tmp_path, monkeypatch, api, override
):
    snapshot = tmp_path / "snapshot"
    settings = snapshot / ".pi" / "agent" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"thinkingBudgets": {"high": 12000, "low": 1500}}))
    working = tmp_path / "task"
    working.mkdir()
    if api == "openai-completions":
        model = copy.deepcopy(
            next(
                c
                for c in ORACLE["bodyCases"]
                if c["name"] == "budget_xhigh_uses_high_custom"
            )["model"]
        )
        cap = 20000
    else:
        model = copy.deepcopy(_model_catalog()["anthropic/claude-sonnet-4-5"])
        model.update(maxTokens=8192, contextWindow=200000)
        cap = 1
    cfg = configured(model, monkeypatch, thinking="high", max_tokens=cap)
    if override:
        cfg[override] = {"high": 6000}
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=reply_body(api))

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        loop.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        ),
    )
    result = asyncio.run(
        loop.run(
            cfg,
            "hello",
            working,
            snapshot,
            ResourceBundle(system_prompt="system", tool_schemas=[]),
        )
    )
    assert result.status == "finished"
    assert len(captured) == 1
    body = json.loads(captured[0].content)
    if api == "openai-completions":
        source_case = next(
            c
            for c in ORACLE["bodyCases"]
            if c["name"] == "budget_xhigh_uses_high_custom"
        )
        expected = (
            6000 if override else source_case["expected"]["thinking_token_budget"]
        )
        assert body["thinking_token_budget"] == expected
    elif override:
        assert body["max_tokens"] == 6001
        # anthropic-messages.ts:1007 leaves answer room again after the
        # nonadaptive helper has expanded the explicit caller ceiling.
        assert body["thinking"]["budget_tokens"] == 4977
    else:
        source_case = next(
            c
            for c in ORACLE["budgetCases"]
            if c["level"] == "high" and c["budgets"] and c["base"] == 1
        )
        assert body["max_tokens"] == source_case["expected_adjust"]["maxTokens"]
        assert (
            body["thinking"]["budget_tokens"]
            == source_case["expected_adjust"]["thinkingBudget"]
        )


def test_native_private_retention_overrides_role_and_llm_retention(monkeypatch):
    case = next(
        c
        for c in ORACLE["bodyCases"]
        if c["name"] == "cache_openai-responses_none_explicit_true"
    )
    cfg = configured(
        case["model"],
        monkeypatch,
        _cache_retention="none",
        cache_retention="long",
        _session_id="session-fixture",
    )
    cfg["llm"]["cache_retention"] = "long"
    request, _ = boundary(cfg)
    body = json.loads(request.content)
    assert {
        key: value for key, value in body.items() if key.startswith("prompt_cache_")
    } == case["expected"]
    assert not any(name in request.headers for name in AFFINITY_HEADERS)
