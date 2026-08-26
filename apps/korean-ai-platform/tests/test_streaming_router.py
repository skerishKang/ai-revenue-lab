from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.errors import (
    MalformedUpstreamResponse,
    UpstreamAuthFailed,
    UpstreamClientError,
    UpstreamRateLimited,
    UpstreamResponseTooLarge,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.openrouter_stream import OpenRouterStreamEvent, OpenRouterStreamUsage
from app.pilot.router_core import RouteDecision
from app.pilot.streaming_router import stream_routed_chat_completions


MESSAGES = [{"role": "user", "content": "안녕하세요"}]


def _decision(
    *,
    fallbacks: list[dict[str, str]] | None = None,
    max_attempts: int = 3,
    fallback_allowed: bool = True,
) -> RouteDecision:
    return RouteDecision(
        route_mode="auto",
        selected_provider="Stealth",
        selected_model="stealth/ox-alpha",
        selected_upstream_model="stealth/ox-alpha",
        selected_route_id="openrouter:stealth/ox-alpha",
        reason_codes=["capabilities:free", "selected:stealth/ox-alpha"],
        fallback_allowed=fallback_allowed,
        eligible_fallback=fallbacks
        if fallbacks is not None
        else [
            {
                "model_id": "openrouter/free",
                "upstream_model": "openrouter/free",
                "provider": "OpenRouter",
                "route_id": "openrouter:openrouter/free",
                "reason": "auto_fallback_candidate",
            }
        ],
        excluded_candidates=[
            {
                "model_id": "google/gemini-2.5-flash",
                "upstream_model": "google/gemini-2.5-flash",
                "provider": "Google",
                "reason": "capability_mismatch",
            }
        ],
        credential_available=True,
        credential_status="key_available",
        evidence_status="resolved_not_called",
        request_id="b14req_stream_router",
        provider_mode="live",
        max_attempts=max_attempts,
    )


async def _collect(decision: RouteDecision, stream_call):
    return [
        event
        async for event in stream_routed_chat_completions(
            decision=decision,
            messages=MESSAGES,
            temperature=0.2,
            max_tokens=64,
            stream_call=stream_call,
        )
    ]


def _success_stream(*, model: str = "stealth/ox-alpha"):
    async def iterator():
        yield OpenRouterStreamEvent(response_id="r1", model=model, delta_content="안")
        yield OpenRouterStreamEvent(response_id="r1", model=model, delta_content="녕")
        yield OpenRouterStreamEvent(
            response_id="r1",
            model=model,
            finish_reason="stop",
            usage=OpenRouterStreamUsage(3, 2, 5),
        )
        yield OpenRouterStreamEvent(done=True)

    return iterator()


@pytest.mark.asyncio
async def test_primary_first_visible_content_commits_route():
    calls = []

    def stream_call(**kwargs):
        calls.append(kwargs["model_id"])
        return _success_stream()

    events = await _collect(_decision(), stream_call)

    assert calls == ["stealth/ox-alpha"]
    assert events[0].delta_content == "안"
    assert events[0].committed is True
    assert all(event.selected_model == "stealth/ox-alpha" for event in events)
    assert events[-1].done is True
    assert events[-1].committed is True
    assert events[-1].error_code is None


@pytest.mark.asyncio
async def test_metadata_and_usage_before_content_do_not_commit():
    async def stream():
        yield OpenRouterStreamEvent(
            response_id="r1",
            model="stealth/ox-alpha",
            usage=OpenRouterStreamUsage(prompt_tokens=3),
        )
        yield OpenRouterStreamEvent(
            response_id="r1", model="stealth/ox-alpha", delta_content="첫 토큰"
        )
        yield OpenRouterStreamEvent(done=True)

    events = await _collect(_decision(), lambda **kwargs: stream())

    assert events[0].usage is not None
    assert events[0].committed is False
    assert events[1].delta_content == "첫 토큰"
    assert events[1].committed is True
    assert events[2].done is True
    assert events[2].committed is True


@pytest.mark.asyncio
async def test_429_before_content_uses_only_resolved_fallback():
    calls = []

    def stream_call(**kwargs):
        model = kwargs["model_id"]
        calls.append(model)

        async def stream():
            if model == "stealth/ox-alpha":
                raise UpstreamRateLimited()
            yield OpenRouterStreamEvent(
                response_id="r2", model="openrouter/free", delta_content="fallback"
            )
            yield OpenRouterStreamEvent(done=True)

        return stream()

    events = await _collect(_decision(), stream_call)

    assert calls == ["stealth/ox-alpha", "openrouter/free"]
    visible = [event for event in events if event.delta_content]
    assert len(visible) == 1
    assert visible[0].selected_model == "openrouter/free"
    assert visible[0].attempt == 2
    assert visible[0].fallback_used is True
    assert visible[0].committed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [UpstreamTimeout(), UpstreamServerError()])
async def test_retryable_precontent_failure_allows_bounded_fallback(error):
    calls = []

    def stream_call(**kwargs):
        model = kwargs["model_id"]
        calls.append(model)

        async def stream():
            if len(calls) == 1:
                raise error
            yield OpenRouterStreamEvent(model="openrouter/free", delta_content="ok")
            yield OpenRouterStreamEvent(done=True)

        return stream()

    events = await _collect(_decision(), stream_call)
    assert calls == ["stealth/ox-alpha", "openrouter/free"]
    assert any(event.delta_content == "ok" and event.attempt == 2 for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        UpstreamAuthFailed(),
        UpstreamClientError(422),
        MalformedUpstreamResponse(),
        UpstreamResponseTooLarge(1024),
    ],
)
async def test_nonretryable_precontent_failure_never_falls_back(error):
    calls = []

    def stream_call(**kwargs):
        calls.append(kwargs["model_id"])

        async def stream():
            raise error
            yield  # pragma: no cover

        return stream()

    events = await _collect(_decision(), stream_call)
    assert calls == ["stealth/ox-alpha"]
    assert len(events) == 1
    assert events[0].done is True
    assert events[0].committed is False
    assert events[0].error_code == error.code


@pytest.mark.asyncio
async def test_failure_after_first_content_is_terminal_and_never_falls_back():
    calls = []

    def stream_call(**kwargs):
        calls.append(kwargs["model_id"])

        async def stream():
            yield OpenRouterStreamEvent(model="stealth/ox-alpha", delta_content="부분 응답")
            raise UpstreamRateLimited()

        return stream()

    events = await _collect(_decision(), stream_call)
    assert calls == ["stealth/ox-alpha"]
    assert events[0].delta_content == "부분 응답"
    assert events[0].committed is True
    assert events[-1].done is True
    assert events[-1].committed is True
    assert events[-1].error_code == "upstream_rate_limited"


@pytest.mark.asyncio
async def test_max_attempts_prevents_third_candidate():
    fallbacks = [
        {
            "model_id": "openrouter/free",
            "upstream_model": "openrouter/free",
            "provider": "OpenRouter",
            "route_id": "openrouter:openrouter/free",
            "reason": "auto_fallback_candidate",
        },
        {
            "model_id": "another/free",
            "upstream_model": "another/free",
            "provider": "Another",
            "route_id": "openrouter:another/free",
            "reason": "auto_fallback_candidate",
        },
    ]
    calls = []

    def stream_call(**kwargs):
        calls.append(kwargs["model_id"])

        async def stream():
            raise UpstreamServerError()
            yield  # pragma: no cover

        return stream()

    events = await _collect(_decision(fallbacks=fallbacks, max_attempts=2), stream_call)
    assert calls == ["stealth/ox-alpha", "openrouter/free"]
    assert events[-1].attempt == 2
    assert events[-1].error_code == "upstream_server_error"


@pytest.mark.asyncio
async def test_fallback_disabled_never_uses_resolved_alternative():
    calls = []

    def stream_call(**kwargs):
        calls.append(kwargs["model_id"])

        async def stream():
            raise UpstreamRateLimited()
            yield  # pragma: no cover

        return stream()

    events = await _collect(_decision(fallback_allowed=False), stream_call)
    assert calls == ["stealth/ox-alpha"]
    assert events[-1].fallback_used is False
    assert events[-1].error_code == "upstream_rate_limited"


@pytest.mark.asyncio
async def test_free_only_decision_cannot_widen_to_excluded_paid_catalog_model():
    calls = []

    def stream_call(**kwargs):
        model = kwargs["model_id"]
        calls.append(model)

        async def stream():
            if model == "stealth/ox-alpha":
                raise UpstreamRateLimited()
            yield OpenRouterStreamEvent(model="openrouter/free", delta_content="free fallback")
            yield OpenRouterStreamEvent(done=True)

        return stream()

    events = await _collect(_decision(), stream_call)
    assert calls == ["stealth/ox-alpha", "openrouter/free"]
    assert "google/gemini-2.5-flash" not in calls
    assert all(event.selected_model != "google/gemini-2.5-flash" for event in events)


@pytest.mark.asyncio
async def test_actual_route_evidence_follows_attempt_that_emits_content():
    def stream_call(**kwargs):
        model = kwargs["model_id"]

        async def stream():
            if model == "stealth/ox-alpha":
                raise UpstreamTimeout()
            yield OpenRouterStreamEvent(
                response_id="r-free",
                model="meta-llama/llama-free-concrete",
                delta_content="응답",
            )
            yield OpenRouterStreamEvent(done=True)

        return stream()

    events = await _collect(_decision(), stream_call)
    visible = next(event for event in events if event.delta_content)
    assert visible.selected_model == "openrouter/free"
    assert visible.selected_provider == "OpenRouter"
    assert visible.selected_route_id == "openrouter:openrouter/free"
    assert visible.actual_response_model == "meta-llama/llama-free-concrete"
    assert visible.attempt == 2


@pytest.mark.asyncio
async def test_consumer_close_closes_active_provider_iterator():
    closed = asyncio.Event()

    async def provider_stream():
        try:
            yield OpenRouterStreamEvent(model="stealth/ox-alpha", delta_content="first")
            await asyncio.sleep(3600)
        finally:
            closed.set()

    router_stream = stream_routed_chat_completions(
        decision=_decision(),
        messages=MESSAGES,
        temperature=0.2,
        max_tokens=64,
        stream_call=lambda **kwargs: provider_stream(),
    )
    first = await anext(router_stream)
    assert first.delta_content == "first"
    await router_stream.aclose()
    await asyncio.wait_for(closed.wait(), timeout=1)


@pytest.mark.asyncio
async def test_unknown_exception_is_bounded_and_does_not_leak_secret_or_fallback():
    calls = []
    secret = "sk-or-v1-this-must-never-appear"

    def stream_call(**kwargs):
        calls.append(kwargs["model_id"])

        async def stream():
            raise RuntimeError(f"transport exploded {secret}")
            yield  # pragma: no cover

        return stream()

    events = await _collect(_decision(), stream_call)
    assert calls == ["stealth/ox-alpha"]
    assert events[-1].error_code == "stream_execution_error"
    assert secret not in repr(events)


@pytest.mark.asyncio
async def test_stream_finishing_without_visible_content_is_terminal_not_fallback():
    calls = []

    def stream_call(**kwargs):
        calls.append(kwargs["model_id"])

        async def stream():
            yield OpenRouterStreamEvent(
                model="stealth/ox-alpha",
                finish_reason="stop",
                usage=OpenRouterStreamUsage(2, 0, 2),
            )
            yield OpenRouterStreamEvent(done=True)

        return stream()

    events = await _collect(_decision(), stream_call)
    assert calls == ["stealth/ox-alpha"]
    assert len(events) == 1
    assert events[0].error_code == "empty_stream_answer"
    assert events[0].committed is False


def test_public_gateway_still_rejects_stream_true_after_router_slice():
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": "b14/auto",
            "messages": MESSAGES,
            "stream": True,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"
