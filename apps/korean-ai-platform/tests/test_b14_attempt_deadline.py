"""B14 provider deadline phases, defaults and environment overrides (offline)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.pilot.b14_timeout_policy import (
    ATTEMPT_TIMEOUT_ENV,
    CHAIN_BUDGET_ENV,
    DEFAULT_ATTEMPT_SECONDS,
    DEFAULT_CHAIN_BUDGET_SECONDS,
    DEFAULT_FIRST_BYTE_SECONDS,
    DEFAULT_STREAM_IDLE_SECONDS,
    FIRST_BYTE_TIMEOUT_ENV,
    ProviderAttemptTimeout,
    STREAM_IDLE_TIMEOUT_ENV,
    get_timeout_policy,
    iter_provider_response_bytes,
    send_provider_request,
)


class _DelayedByteStream(httpx.AsyncByteStream):
    def __init__(self, pieces: list[tuple[float, bytes]]) -> None:
        self.pieces = pieces

    async def __aiter__(self):
        for delay, chunk in self.pieces:
            if delay:
                await asyncio.sleep(delay)
            yield chunk


@pytest.fixture(autouse=True)
def _clear_deadline_overrides(monkeypatch):
    for name in (
        FIRST_BYTE_TIMEOUT_ENV,
        ATTEMPT_TIMEOUT_ENV,
        STREAM_IDLE_TIMEOUT_ENV,
        CHAIN_BUDGET_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _set_policy(monkeypatch, *, first: float, attempt: float,
                idle: float, chain: float) -> None:
    monkeypatch.setenv(FIRST_BYTE_TIMEOUT_ENV, str(first))
    monkeypatch.setenv(ATTEMPT_TIMEOUT_ENV, str(attempt))
    monkeypatch.setenv(STREAM_IDLE_TIMEOUT_ENV, str(idle))
    monkeypatch.setenv(CHAIN_BUDGET_ENV, str(chain))


def test_default_policy_and_environment_overrides(monkeypatch):
    defaults = get_timeout_policy()
    assert defaults.first_byte_seconds == DEFAULT_FIRST_BYTE_SECONDS == 15.0
    assert defaults.attempt_seconds == DEFAULT_ATTEMPT_SECONDS == 40.0
    assert defaults.stream_idle_seconds == DEFAULT_STREAM_IDLE_SECONDS == 20.0
    assert defaults.chain_budget_seconds == DEFAULT_CHAIN_BUDGET_SECONDS == 55.0

    _set_policy(monkeypatch, first=1.5, attempt=4, idle=2, chain=5.5)
    overridden = get_timeout_policy()
    assert (overridden.first_byte_seconds, overridden.attempt_seconds,
            overridden.stream_idle_seconds, overridden.chain_budget_seconds) == (
                1.5, 4.0, 2.0, 5.5,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pieces,policy,expected_reason",
    [
        ([(0.05, b"late")], (0.02, 0.20, 0.10, 0.30), "first_byte"),
        ([(0.0, b"first"), (0.05, b"late")],
         (0.10, 0.20, 0.02, 0.30), "attempt_total"),
        ([(0.0, b"first"), (0.05, b"late")],
         (0.10, 0.02, 0.10, 0.30), "attempt_total"),
    ],
)
async def test_provider_body_wait_is_classified_and_bounded(
    monkeypatch, pieces, policy, expected_reason,
):
    first, attempt, idle, chain = policy
    _set_policy(monkeypatch, first=first, attempt=attempt, idle=idle, chain=chain)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=_DelayedByteStream(pieces))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response, started_at = await send_provider_request(
            client, "POST", "https://synthetic-provider.example/chat",
            json={"input": "offline fixture"},
        )
        with pytest.raises(ProviderAttemptTimeout) as raised:
            async for _ in iter_provider_response_bytes(response, started_at=started_at):
                pass
        assert raised.value.reason == expected_reason
        await response.aclose()


@pytest.mark.asyncio
async def test_normal_provider_body_is_returned_unchanged(monkeypatch):
    _set_policy(monkeypatch, first=0.10, attempt=0.20, idle=0.05, chain=0.30)
    pieces = [(0.0, b'{"choices":'), (0.0, b'[{"text":"ok"}]}')]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=_DelayedByteStream(pieces))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response, started_at = await send_provider_request(
            client, "POST", "https://synthetic-provider.example/chat",
            json={"input": "offline fixture"},
        )
        body = b"".join([
            chunk async for chunk in iter_provider_response_bytes(
                response, started_at=started_at,
            )
        ])
        assert body == b'{"choices":[{"text":"ok"}]}'
        await response.aclose()
