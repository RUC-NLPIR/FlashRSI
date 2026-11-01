"""Pi v1.4.0's provider retry policy, with cancellable Python HTTP requests.

Source: ``packages/ai/src/utils/provider-retry.ts`` at the revision in
UPSTREAM.md. Provider errors keep their status, headers and body for callers.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import re
import time
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

import httpx


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        headers: httpx.Headers | None = None,
        body: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.headers = headers
        self.body = body


def _retryable(error: ProviderRequestError) -> bool:
    should_retry = error.headers.get("x-should-retry") if error.headers else None
    if should_retry == "true":
        return True
    if should_retry == "false":
        return False
    return (
        error.status is None or error.status in {408, 409, 429} or error.status >= 500
    )


def _parse_float(value: str) -> float:
    # Match Number.parseFloat: a valid numeric prefix is enough.
    match = re.match(
        r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)",
        value.lstrip(),
    )
    return float(match[0]) if match else math.nan


def _delay(
    error: ProviderRequestError, retry_index: int, maximum: float | None
) -> float:
    headers = error.headers or {}
    delay_ms = math.nan
    retry_after_ms = headers.get("retry-after-ms")
    if retry_after_ms:
        delay_ms = _parse_float(retry_after_ms)
    if not math.isfinite(delay_ms):
        retry_after = headers.get("retry-after")
        if retry_after:
            seconds = _parse_float(retry_after)
            if math.isnan(seconds):
                try:
                    delay_ms = (
                        parsedate_to_datetime(retry_after).timestamp() - time.time()
                    ) * 1000
                except (TypeError, ValueError, OverflowError):
                    delay_ms = math.nan
            else:
                delay_ms = seconds * 1000
    if math.isfinite(delay_ms):
        maximum = 60.0 if maximum is None else maximum
        if maximum > 0 and delay_ms > maximum * 1000:
            raise RuntimeError(
                f"Server requested {math.ceil(delay_ms / 1000)}s retry delay "
                f"(max: {math.ceil(maximum)}s). {error}"
            ) from error
        return max(0, delay_ms / 1000)
    return (0.5 * 2 ** min(retry_index, 4)) * (1 - random.random() * 0.25)


async def request_json(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    retries: int = 0,
    *,
    timeout: float | None = None,
    max_retry_delay: float | None = 60.0,
    no_retry_statuses: tuple[int, ...] = (),
) -> dict[str, Any]:
    """Issue a JSON request using Pi's header, status and backoff decisions."""
    for attempt in range(max(0, retries) + 1):
        try:
            serialized = json.dumps(payload, ensure_ascii=False)
            options = {"timeout": timeout} if timeout is not None else {}
            if re.search(r"[\ud800-\udfff]", serialized):
                # JSON.stringify escapes lone UTF-16 units from tool truncation.
                response = await client.post(
                    url,
                    headers=dict(headers),
                    content=json.dumps(payload, ensure_ascii=True).encode("ascii"),
                    **options,
                )
            else:
                response = await client.post(
                    url, headers=dict(headers), json=dict(payload), **options
                )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProviderRequestError(
                    f"{response.status_code}: {response.text}",
                    status=response.status_code,
                    headers=response.headers,
                    body=response.text,
                ) from exc
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("provider returned a non-object JSON response")
            return body
        except httpx.RequestError as exc:
            error = ProviderRequestError(str(exc))
            error.__cause__ = exc
        except ProviderRequestError as exc:
            error = exc
        # Successful malformed JSON and programming errors are not SDK request
        # failures and must not consume retries. CancelledError also propagates.
        if (
            attempt >= max(0, retries)
            or not _retryable(error)
            or error.status in no_retry_statuses
        ):
            raise error
        await asyncio.sleep(_delay(error, attempt, max_retry_delay))
    raise AssertionError("unreachable")
