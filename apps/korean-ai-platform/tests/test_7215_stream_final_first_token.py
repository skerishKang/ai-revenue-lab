"""#7215: a streaming chain's last candidate waits the attempt budget for its first token.

A streamed answer's first visible token is the equivalent of the completed answer
on the non-streaming path (#7156/#7212). While a fallback candidate remains, the
15 s first-byte bound is right: the chain moves on sooner. On the last candidate
there is nothing to fall back to, and cutting at 15 s only turns a slow first
token into a 504.

Pinned here:

* the first token may arrive between the first-byte bound and the attempt budget
  on the last candidate (16–39 s at production values; scaled here), and a token
  past the attempt budget is still cut (``attempt_total``);
* a candidate with a fallback behind it keeps the 15 s first-byte cut;
* the post-first-token idle limit is unchanged on the last candidate;
* the streaming gateway marks only the last candidate of the chain.

No provider is contacted: MockTransport and a monkeypatched adapter only.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import router_core, stream_gateway
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.b14_timeout_policy import (
    ATTEMPT_TIMEOUT_ENV,
    CHAIN_BUDGET_ENV,
    FIRST_BYTE_TIMEOUT_ENV,
    STREAM_IDLE_TIMEOUT_ENV,
    ProviderAttemptTimeout,
    final_completed_attempt,
    first_byte_bound_is_attempt_total,
    iter_provider_response_bytes,
    send_provider_request,
)
from app.pilot.errors import UpstreamServerError

from _pilot_lane_paths import chat_surface
from _registry_values import (
    a_dispatchable_row,
    provider_of,
    provider_row,
    registry,
)


def provider_ids_in_registry() -> set[str]:
    return set(registry()["providers"])


#: The gateway's own preview surface, read from the mounted router.
URL = chat_surface() + "/stream-preview"

#: The streamed route this contract drives: a registered row whose Provider
#: credential can be supplied from an environment binding, so the lane's own
#: readiness gate is satisfied without dialing anything. Which identity that is
#: lives in the effective registry, not in this file (#7241 3a).
ROW = a_dispatchable_row()
assert ROW is not None, "the effective registry serves no dispatchable row"
MODEL = ROW["id"]
PROVIDER_ID = provider_of(MODEL)
BINDING = provider_row(PROVIDER_ID)["credential_binding_name"]
#: A second declared slot, cleared so the case never inherits an operator key.
OTHER_BINDING = next(
    provider_row(provider_id)["credential_binding_name"]
    for provider_id in sorted(provider_ids_in_registry())
    if provider_id != PROVIDER_ID
)


class _DelayedStream(httpx.AsyncByteStream):
    def __init__(self, pieces: list[tuple[float, bytes]]) -> None:
        self.pieces = pieces

    async def __aiter__(self):
        for delay, chunk in self.pieces:
            if delay:
                await asyncio.sleep(delay)
            yield chunk


@pytest.fixture(autouse=True)
def _policy(monkeypatch):
    """Scaled production policy: 15 s / 40 s / 20 s becomes 0.15 / 1.0 / 0.25."""
    monkeypatch.setenv(FIRST_BYTE_TIMEOUT_ENV, "0.15")
    monkeypatch.setenv(ATTEMPT_TIMEOUT_ENV, "1.0")
    monkeypatch.setenv(STREAM_IDLE_TIMEOUT_ENV, "0.25")
    monkeypatch.setenv(CHAIN_BUDGET_ENV, "4.0")
    old_mode = rcfg.provider_mode
    rcfg.provider_mode = "live"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, "synthetic-credential-not-a-secret")
    monkeypatch.delenv(OTHER_BINDING, raising=False)
    yield
    rcfg.provider_mode = old_mode


async def _read(pieces):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=_DelayedStream(pieces))
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


# ------------------------------------------------------------- byte level
@pytest.mark.asyncio
async def test_a_late_first_token_is_returned_on_the_last_candidate():
    """0.3 s is past the 0.15 s first-byte bound and inside the 1.0 s attempt."""
    with final_completed_attempt(True):
        body = await _read([(0.3, b"data: first-token\n\n")])
    assert body == b"data: first-token\n\n"


@pytest.mark.asyncio
async def test_a_late_first_token_is_cut_when_a_fallback_remains():
    with pytest.raises(ProviderAttemptTimeout) as raised:
        await _read([(0.3, b"data: first-token\n\n")])
    assert raised.value.reason == "first_byte"


@pytest.mark.asyncio
async def test_the_last_candidate_is_still_bounded_by_the_attempt_budget():
    with final_completed_attempt(True):
        with pytest.raises(ProviderAttemptTimeout) as raised:
            await _read([(1.5, b"data: first-token\n\n")])
    assert raised.value.reason == "attempt_total"


@pytest.mark.asyncio
async def test_the_idle_limit_after_the_first_token_is_unchanged():
    """0.5 s of silence after the first token still exceeds the 0.25 s idle limit."""
    with final_completed_attempt(True):
        with pytest.raises(ProviderAttemptTimeout) as raised:
            await _read([(0.0, b"data: first-token\n\n"), (0.5, b"data: late\n\n")])
    assert raised.value.reason == "attempt_total"


# ---------------------------------------------------------- gateway level
def _request(tier: str = "free") -> dict:
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": "synthetic offline fixture"}],
        "stream": True,
        "business14": {"product_tier": tier},
    }


def _run(monkeypatch):
    seen: list[bool] = []

    def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
             temperature=0.2, max_tokens=300, transport=None, **kwargs):
        async def gen():
            seen.append(first_byte_bound_is_attempt_total())
            raise UpstreamServerError()
            yield  # pragma: no cover - never reached
        return gen()

    monkeypatch.setattr(stream_gateway, "stream_platform_chat_completions", fake)
    # Every declared candidate is credential-eligible here; no provider is called.
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)
    app = create_app()
    with TestClient(app) as client:
        response = client.post(URL, json=_request())
    return seen, response


def test_the_gateway_marks_only_the_last_streaming_candidate(monkeypatch):
    seen, response = _run(monkeypatch)

    assert response.status_code == 502
    # A route whose roster has one candidate is its own last candidate; a chain
    # marks every candidate before it as non-final. #6724 retries that final
    # attempt once, so it is observed twice and both are final.
    assert seen[-2:] == [True, True], seen
    assert not any(seen[:-2]), seen
    # The flag never leaks past the attempt.
    assert first_byte_bound_is_attempt_total() is False


def test_the_last_candidate_uses_the_attempt_budget_for_its_first_token(monkeypatch):
    seen, _ = _run(monkeypatch)

    assert seen[-1] is True
    # #6724: the final attempt's same-route retry is final too.
    assert not any(seen[:-2])


def test_the_error_contract_is_unchanged_for_a_first_byte_timeout(monkeypatch):
    seen, response = _run(monkeypatch)

    body = response.json()
    assert seen[-1] is True
    assert response.status_code == 502
    assert body.get("error", {}).get("code") == "upstream_server_error"
