"""Exercise real HTTP dispatch against the pinned original Pi retry oracle."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import provider_retry

_ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_provider_retry_upstream.json").read_text()
)


@pytest.mark.parametrize("case", _ORACLE["cases"], ids=lambda case: case["name"])
def test_provider_http_retry_matches_original_pi(case, monkeypatch):
    calls, delays = [], []

    def handler(request):
        calls.append(request)
        if len(calls) > case.get("failures", 1):
            return httpx.Response(200, json={"ok": True})
        if case.get("network"):
            raise httpx.ConnectError("fixture failure", request=request)
        if case.get("nonProvider"):
            raise ValueError("fixture failure")
        return httpx.Response(
            case["status"], text="fixture failure", headers=case.get("headers", {})
        )

    async def sleep(delay):
        delays.append(delay * 1000)

    monkeypatch.setattr(provider_retry.asyncio, "sleep", sleep)
    monkeypatch.setattr(provider_retry.time, "time", lambda: _ORACLE["fixedNow"] / 1000)
    monkeypatch.setattr(provider_retry.random, "random", lambda: _ORACLE["fixedRandom"])

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            options = {}
            if "maxRetryDelayMs" in case:
                options["max_retry_delay"] = case["maxRetryDelayMs"] / 1000
            if "noRetryStatuses" in case:
                options["no_retry_statuses"] = tuple(case["noRetryStatuses"])
            return await provider_retry.request_json(
                client,
                "https://offline.invalid/messages",
                {"x-api-key": "fixture-only"},
                {"prompt": "hello"},
                case.get("retries", 0),
                **options,
            )

    expected = case["expected"]
    if "error" in expected:
        with pytest.raises((RuntimeError, ValueError)) as error:
            asyncio.run(scenario())
        assert str(error.value) == expected["error"]
    else:
        assert asyncio.run(scenario()) == expected["output"]
    assert len(calls) == expected["calls"]
    assert delays == pytest.approx(expected["delaysMs"])
    assert all(request.headers["x-api-key"] == "fixture-only" for request in calls)
    assert all(json.loads(request.content) == {"prompt": "hello"} for request in calls)


def test_provider_error_retains_http_status_headers_and_body():
    async def scenario():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                400, text="invalid context", headers={"x-detail": "fixture"}
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await provider_retry.request_json(client, "https://offline.invalid", {}, {})

    with pytest.raises(provider_retry.ProviderRequestError) as error:
        asyncio.run(scenario())
    assert error.value.status == 400
    assert error.value.headers["x-detail"] == "fixture"
    assert error.value.body == "invalid context"
    assert str(error.value) == "400: invalid context"


@pytest.mark.parametrize("content", [b"{", b"[]", b'"not an object"'])
def test_successful_malformed_response_is_not_retried(content):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=content)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await provider_retry.request_json(
                client, "https://offline.invalid", {}, {}, retries=3
            )

    with pytest.raises(ValueError):
        asyncio.run(scenario())
    assert len(calls) == 1


def test_lone_surrogate_json_escapes_and_explicit_timeout_are_preserved():
    calls = []
    payload = {"text": "cut\ud800"}

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider_retry.request_json(
                client, "https://offline.invalid", {}, payload, timeout=1.25
            )

    assert asyncio.run(scenario()) == {"ok": True}
    assert b"\\ud800" in calls[0].content
    assert json.loads(calls[0].content) == payload
    assert set(calls[0].extensions["timeout"].values()) == {1.25}


def test_external_cancellation_interrupts_retry_sleep_and_prevents_next_request(
    monkeypatch,
):
    calls = []

    async def scenario():
        sleeping = asyncio.Event()
        never = asyncio.Event()

        async def sleep(delay):
            assert delay == 10
            sleeping.set()
            await never.wait()

        monkeypatch.setattr(provider_retry.asyncio, "sleep", sleep)

        def handler(request):
            calls.append(request)
            return httpx.Response(429, text="busy", headers={"retry-after": "10"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            pending = asyncio.create_task(
                provider_retry.request_json(
                    client, "https://offline.invalid", {}, {}, retries=3
                )
            )
            await sleeping.wait()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending

    asyncio.run(scenario())
    assert len(calls) == 1
