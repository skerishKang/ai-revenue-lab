"""#7156: the last completed candidate is not cut at the streaming first-byte bound.

A completed (non-streaming) provider response sends its first body byte only
after the whole answer, reasoning included, is generated. The first-byte clock is
therefore a total-generation clock on that path. Cutting at it is right while a
fallback candidate remains (the chain moves on sooner), but on the last candidate
it only turns a slow answer into a 504: the nightly Pro grade smoke on
2026-11-07 failed with ``upstream_timeout`` / ``first_byte`` at 15.04 s while the
same model answered the other paid grades in 10.6 s and 14.6 s that night.

Pinned here:

* outside the final completed attempt nothing changes (first-byte cut, httpx
  read = stream idle);
* inside it, a late first byte inside the attempt budget is returned, a first
  byte past the attempt budget is still cut (``attempt_total``), and connect
  stays bound by the first-byte value;
* the gateway marks only the last candidate of the chain.

No provider is contacted.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.pilot import router_core
from app.pilot.b14_timeout_policy import (
    ATTEMPT_TIMEOUT_ENV,
    CHAIN_BUDGET_ENV,
    FIRST_BYTE_TIMEOUT_ENV,
    STREAM_IDLE_TIMEOUT_ENV,
    ProviderAttemptTimeout,
    build_provider_http_timeout,
    effective_first_byte_seconds,
    final_completed_attempt,
    first_byte_bound_is_attempt_total,
    get_timeout_policy,
    iter_provider_response_bytes,
    send_provider_request,
)
from app.pilot.errors import UpstreamServerError
from app.pilot.tier_fallback import TIER_DEFAULT_B14_MODEL, TIER_FALLBACK_B14_MODELS


class _DelayedByteStream(httpx.AsyncByteStream):
    def __init__(self, pieces: list[tuple[float, bytes]]) -> None:
        self.pieces = pieces

    async def __aiter__(self):
        for delay, chunk in self.pieces:
            if delay:
                await asyncio.sleep(delay)
            yield chunk


@pytest.fixture(autouse=True)
def _clear_overrides(monkeypatch):
    for name in (FIRST_BYTE_TIMEOUT_ENV, ATTEMPT_TIMEOUT_ENV,
                 STREAM_IDLE_TIMEOUT_ENV, CHAIN_BUDGET_ENV):
        monkeypatch.delenv(name, raising=False)


def _policy(monkeypatch, *, first, attempt, idle, chain):
    monkeypatch.setenv(FIRST_BYTE_TIMEOUT_ENV, str(first))
    monkeypatch.setenv(ATTEMPT_TIMEOUT_ENV, str(attempt))
    monkeypatch.setenv(STREAM_IDLE_TIMEOUT_ENV, str(idle))
    monkeypatch.setenv(CHAIN_BUDGET_ENV, str(chain))


async def _read(pieces):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=_DelayedByteStream(pieces))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response, started_at = await send_provider_request(
            client, "POST", "https://synthetic-provider.example/chat",
            json={"input": "offline fixture"},
        )
        try:
            return b"".join([
                chunk async for chunk in iter_provider_response_bytes(
                    response, started_at=started_at,
                )
            ])
        finally:
            await response.aclose()


# --------------------------------------------------------------- policy level
def test_the_flag_is_off_by_default_and_resets_after_the_block():
    assert first_byte_bound_is_attempt_total() is False
    with final_completed_attempt(True):
        assert first_byte_bound_is_attempt_total() is True
        with final_completed_attempt(False):
            assert first_byte_bound_is_attempt_total() is False
        assert first_byte_bound_is_attempt_total() is True
    assert first_byte_bound_is_attempt_total() is False


def test_effective_first_byte_is_the_attempt_budget_only_on_the_final_attempt():
    policy = get_timeout_policy()
    assert effective_first_byte_seconds(policy) == policy.first_byte_seconds == 15.0
    with final_completed_attempt(True):
        assert effective_first_byte_seconds(policy) == policy.attempt_seconds == 40.0


@pytest.mark.asyncio
async def test_a_late_whole_answer_is_cut_when_a_fallback_remains(monkeypatch):
    """Unchanged behavior: a candidate with a fallback after it is cut early."""
    _policy(monkeypatch, first=0.05, attempt=0.50, idle=0.20, chain=1.0)
    with pytest.raises(ProviderAttemptTimeout) as raised:
        await _read([(0.15, b'{"choices":[]}')])
    assert raised.value.reason == "first_byte"


@pytest.mark.asyncio
async def test_a_late_whole_answer_is_returned_on_the_final_attempt(monkeypatch):
    """The same late answer is kept when no candidate remains after it."""
    _policy(monkeypatch, first=0.05, attempt=0.50, idle=0.20, chain=1.0)
    with final_completed_attempt(True):
        body = await _read([(0.15, b'{"choices":'), (0.0, b'[]}')])
    assert body == b'{"choices":[]}'


@pytest.mark.asyncio
async def test_the_final_attempt_is_still_bounded_by_the_attempt_budget(monkeypatch):
    _policy(monkeypatch, first=0.05, attempt=0.20, idle=0.10, chain=1.0)
    with final_completed_attempt(True):
        with pytest.raises(ProviderAttemptTimeout) as raised:
            await _read([(0.40, b'{"choices":[]}')])
    assert raised.value.reason == "attempt_total"


async def _read_after_header_delay(delay: float):
    async def respond(request):
        await asyncio.sleep(delay)
        return httpx.Response(200, content=b'{"choices":[]}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        response, started_at = await send_provider_request(
            client, "POST", "https://synthetic-provider.example/chat",
            json={"input": "offline fixture"},
        )
        try:
            return b"".join([
                chunk async for chunk in iter_provider_response_bytes(
                    response, started_at=started_at,
                )
            ])
        finally:
            await response.aclose()


@pytest.mark.asyncio
async def test_late_response_headers_follow_the_same_rule(monkeypatch):
    """A provider that holds its headers until the answer is done is treated alike."""
    _policy(monkeypatch, first=0.05, attempt=0.50, idle=0.20, chain=1.0)
    with pytest.raises(ProviderAttemptTimeout) as raised:
        await _read_after_header_delay(0.15)
    assert raised.value.reason == "first_byte"
    with final_completed_attempt(True):
        assert await _read_after_header_delay(0.15) == b'{"choices":[]}'


def test_the_socket_read_wait_follows_the_attempt_budget_but_connect_stays_bound():
    default = build_provider_http_timeout("any/model")
    assert (default.connect, default.read) == (15.0, 20.0)
    with final_completed_attempt(True):
        final = build_provider_http_timeout("any/model")
    assert (final.connect, final.read) == (15.0, 40.0)
    assert (final.write, final.pool) == (default.write, default.pool)


# -------------------------------------------------------------- gateway level
def _ok(upstream_model: str) -> dict:
    return {
        "id": "cmpl-7156",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        "_live": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


def test_the_gateway_marks_only_the_last_candidate_of_a_fallback_chain(client, monkeypatch):
    from app.pilot import b14_runtime_config as rcfg
    from app.pilot import platform as plat

    rcfg.provider_mode = "live"
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_03", "sk-free-google-0123456789abcdef")
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)
    roster = [TIER_DEFAULT_B14_MODEL, *TIER_FALLBACK_B14_MODELS["free"]]
    seen: list[tuple[str, bool]] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        seen.append((model_id, first_byte_bound_is_attempt_total()))
        if len(seen) < len(roster):
            raise UpstreamServerError()
        return _ok(upstream_model)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    response = client.post("/api/pilot/v1/chat/completions", json={
        "model": TIER_DEFAULT_B14_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "business14": {"product_tier": "free"},
    })

    assert response.status_code == 200
    assert [model for model, _ in seen] == roster
    assert [flag for _, flag in seen] == [False] * (len(roster) - 1) + [True]
    assert first_byte_bound_is_attempt_total() is False


def test_a_single_candidate_route_is_its_own_last_candidate(client, monkeypatch):
    """A route with no fallback (every paid grade today) is marked final."""
    from app.pilot import platform as plat

    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_01", "sk-fixture-agnes-retry-0123456789")
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen: list[bool] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        seen.append(first_byte_bound_is_attempt_total())
        return _ok(upstream_model)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    response = client.post("/api/pilot/v1/chat/completions", json={
        "model": "agnes-ai/agnes-3.0-flash",
        "messages": [{"role": "user", "content": "hi"}],
    })

    assert response.status_code == 200
    assert seen == [True]
