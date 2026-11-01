"""Differential checks against the pinned original billing and empty guard."""

import asyncio
import dataclasses
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from flashrsi.agents.hermes.runtime.hermes_native import loop, pricing, retry
from flashrsi.agents.hermes.runtime.hermes_native.upstream_loop import (
    empty_response_guard,
)
from flashrsi.agents.hermes.runtime.hermes_native.upstream_pricing import (
    usage_pricing,
)

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures/hermes_pricing_upstream.json").read_text()
)


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@pytest.mark.parametrize("case", REFERENCE["cases"], ids=lambda case: case["name"])
def test_cost_and_usage_match_actual_original(case, monkeypatch):
    monkeypatch.setattr(
        usage_pricing,
        "_UTC_NOW",
        lambda: datetime.fromisoformat("2026-10-01T00:00:00+00:00"),
    )
    usage = usage_pricing.normalize_usage(
        case["raw"], provider=case["route"]["provider"], api_mode=case["mode"]
    )
    assert plain(usage) == case["usage"]
    actual = pricing.estimate_usage_cost(
        usage=usage,
        **case["route"],
        pricing_metadata=REFERENCE["metadata"],
    )
    assert plain(actual) == case["expected"]


@pytest.mark.parametrize("case", REFERENCE["guards"], ids=lambda case: case["name"])
def test_cost_guard_matches_original_retry_budget_and_accumulation(case):
    host = SimpleNamespace(
        model=case["model"],
        provider=case["provider"],
        base_url="",
        api_mode="chat_completions",
        _empty_content_retries=0,
        _pricing_metadata=REFERENCE["metadata"],
    )
    response = SimpleNamespace(usage=case["raw"])
    empty_response_guard.record_empty_attempt(
        host, finish_reason="stop", response=response
    )
    assert empty_response_guard.empty_retry_budget(host, response) == case["budget"]
    assert plain(empty_response_guard.streak_cost_usd(host)) == case["streak"]


@pytest.mark.parametrize("provider,expected_calls", [("openai", 2), ("custom", 4)])
def test_expensive_empty_guard_is_wired_into_real_http_loop(
    provider, expected_calls, monkeypatch, tmp_path
):
    requests = []
    monkeypatch.setattr(retry, "sleep", AsyncMock())

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ],
                # Ambiguous empty with billed generation does not trip the
                # separate deterministic-zero-output guard.
                "usage": {"prompt_tokens": 100000, "completion_tokens": 1000},
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: client_type(
            *args, **kwargs, transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    monkeypatch.setattr(
        loop,
        "load_resources",
        lambda root, cwd, config: SimpleNamespace(
            system_prompt="You are helpful.",
            enabled_tools=["read_file"],
            diagnostics=[],
            settings=config,
        ),
    )
    result = asyncio.run(
        loop.run(
            {
                "llm": {
                    "model_name": "gpt-6-astra",
                    "provider": provider,
                    "api_key": "fixture-key",
                    "base_url": "http://oracle.invalid/v1",
                },
                "compression": {"enabled": False},
                "max_iterations": 10,
            },
            "Give the answer.",
            tmp_path,
            tmp_path,
        )
    )
    assert len(requests) == expected_calls, result
    assert "No reply" in result.output
    assert result.messages[-1]["content"] == "(empty)"
