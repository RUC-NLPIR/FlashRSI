"""Provider cooldown limits and cancellation at Hermes's async HTTP boundary."""

import asyncio

import httpx
import pytest

from flashrsi.agents.hermes.runtime.hermes_native import retry


@pytest.mark.parametrize(
    "header,body",
    [
        ("900", {"error": {"message": "overloaded"}}),
        (None, {"error": {"message": "overloaded", "retry_after": 900}}),
    ],
)
def test_provider_cooldown_capped_before_async_wait(monkeypatch, header, body):
    delays = []

    async def record(seconds):
        delays.append(seconds)

    monkeypatch.setattr(retry, "sleep", record)
    budget = retry.RetryBudget({}, {"provider": "custom"}, lambda _: None)
    response = httpx.Response(503, headers={"Retry-After": header} if header else {})
    assert asyncio.run(budget.recover(retry.ProviderError(response, body)))
    assert delays == [600.0]


def test_retry_wait_cancels_before_any_followup_request(monkeypatch):
    async def scenario():
        started = asyncio.Event()
        followup = []

        async def wait(_):
            started.set()
            await asyncio.Future()

        monkeypatch.setattr(retry, "sleep", wait)
        budget = retry.RetryBudget({}, {"provider": "custom"}, lambda _: None)
        error = retry.ProviderError(
            httpx.Response(503), {"error": {"message": "overloaded"}}
        )

        async def request():
            if await budget.recover(error):
                followup.append("must not run after cancellation")

        task = asyncio.create_task(request())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert followup == []

    asyncio.run(scenario())
