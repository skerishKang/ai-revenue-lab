from __future__ import annotations

import asyncio

import pytest

from app.pilot.openrouter_stream import OpenRouterStreamEvent
from app.pilot.router_core import RouteDecision
from app.pilot.streaming_router import stream_routed_chat_completions


def _decision() -> RouteDecision:
    return RouteDecision(
        route_mode="auto",
        selected_provider="Stealth",
        selected_model="stealth/ox-alpha",
        selected_upstream_model="stealth/ox-alpha",
        selected_route_id="openrouter:stealth/ox-alpha",
        reason_codes=["capabilities:free"],
        fallback_allowed=True,
        eligible_fallback=[],
        excluded_candidates=[],
        credential_available=True,
        credential_status="key_available",
        evidence_status="resolved_not_called",
        request_id="b14req_cancel",
        provider_mode="live",
        max_attempts=1,
    )


@pytest.mark.asyncio
async def test_task_cancellation_propagates_and_closes_provider_iterator():
    entered = asyncio.Event()
    closed = asyncio.Event()

    async def provider_stream():
        try:
            entered.set()
            await asyncio.sleep(3600)
            yield OpenRouterStreamEvent(delta_content="unreachable")
        finally:
            closed.set()

    async def consume():
        async for _ in stream_routed_chat_completions(
            decision=_decision(),
            messages=[{"role": "user", "content": "안녕하세요"}],
            temperature=0.2,
            max_tokens=64,
            stream_call=lambda **kwargs: provider_stream(),
        ):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(closed.wait(), timeout=1)
