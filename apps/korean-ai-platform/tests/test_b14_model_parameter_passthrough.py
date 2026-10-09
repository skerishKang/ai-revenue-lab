"""B14 model-specific parameter passthrough + non-stream/stream parity (#3977).

These tests assert the actual outgoing provider JSON for both the completed and
streaming platform adapters, using httpx.MockTransport only (no network, no
credentials, no paid API call).
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.errors import InvalidParameterValue, UnsupportedParameter
from app.pilot.gateway import _validate_body
from app.pilot.platform import (
    call_platform_chat_completions,
    stream_platform_chat_completions,
)

GEMINI_MODEL = "google/gemini-3.5-flash-lite"
GEMINI_UPSTREAM = "gemini-3.5-flash-lite"

_SSE_OK = (
    b'data: {"id":"s1","model":"gemini-3.5-flash-lite",'
    b'"choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
    b"data: [DONE]\n\n"
)


@pytest.fixture(autouse=True)
def _keyless_google_fixture(monkeypatch):
    """Isolated keyless providers: fixed origins, no credential, no network."""
    from app.pilot import platform_secrets as ps

    for provider_id, origin, host in (
        ("google", "https://generativelanguage.googleapis.com/v1beta/openai", "generativelanguage.googleapis.com"),
        ("poolside", "https://inference.poolside.ai/v1", "inference.poolside.ai"),
    ):
        spec = ps.PlatformProviderSpec(
            provider_id=provider_id,
            credential_source=ps.CredentialSource.NONE,
            credential_binding_name="",
            base_origin=origin,
            allowed_hosts=(host,),
        )
        monkeypatch.setitem(ps._PLATFORM_PROVIDERS, provider_id, spec)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    yield


def _completed_ok(model: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "cmpl-1",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    )


# ---------------------------------------------------------------------------
# Completed (non-stream) payload shape
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_omitted_parameters_are_omitted_from_the_provider_request() -> None:
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _completed_ok(GEMINI_UPSTREAM)

    await call_platform_chat_completions(
        model_id=GEMINI_MODEL,
        upstream_model=GEMINI_UPSTREAM,
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )

    assert seen["body"] == {
        "model": GEMINI_UPSTREAM,
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert "temperature" not in seen["body"]
    assert "max_tokens" not in seen["body"]


@pytest.mark.asyncio
async def test_supported_option_is_delivered_in_the_exact_upstream_shape() -> None:
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _completed_ok(GEMINI_UPSTREAM)

    await call_platform_chat_completions(
        model_id=GEMINI_MODEL,
        upstream_model=GEMINI_UPSTREAM,
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.7,
        max_tokens=1024,
        parameters={"top_p": 0.9, "reasoning_effort": "minimal"},
        transport=httpx.MockTransport(handler),
    )

    assert seen["body"]["model"] == GEMINI_UPSTREAM  # exact upstream id preserved
    assert seen["body"]["temperature"] == 0.7
    assert seen["body"]["max_tokens"] == 1024
    assert seen["body"]["top_p"] == 0.9
    assert seen["body"]["reasoning_effort"] == "minimal"


@pytest.mark.asyncio
async def test_nested_thinking_maps_to_chat_template_kwargs() -> None:
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _completed_ok("poolside/laguna-s-2.1")

    await call_platform_chat_completions(
        model_id="poolside/laguna-s-2.1",
        upstream_model="poolside/laguna-s-2.1",
        provider="Poolside",
        platform_provider_id="poolside",
        messages=[{"role": "user", "content": "hi"}],
        parameters={"thinking": True},
        transport=httpx.MockTransport(handler),
    )

    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": True}


# ---------------------------------------------------------------------------
# Streaming parity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stream_carries_the_same_parameter_payload_as_non_stream() -> None:
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_SSE_OK,
        )

    events = []
    async for event in stream_platform_chat_completions(
        model_id=GEMINI_MODEL,
        upstream_model=GEMINI_UPSTREAM,
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.7,
        max_tokens=1024,
        parameters={"top_p": 0.9, "reasoning_effort": "minimal"},
        transport=httpx.MockTransport(handler),
    ):
        events.append(event)

    assert seen["body"]["stream"] is True
    assert seen["body"]["model"] == GEMINI_UPSTREAM
    assert seen["body"]["temperature"] == 0.7
    assert seen["body"]["max_tokens"] == 1024
    assert seen["body"]["top_p"] == 0.9
    assert seen["body"]["reasoning_effort"] == "minimal"
    assert any(getattr(event, "done", False) for event in events)


@pytest.mark.asyncio
async def test_stream_omits_unspecified_parameters() -> None:
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_SSE_OK,
        )

    async for _ in stream_platform_chat_completions(
        model_id=GEMINI_MODEL,
        upstream_model=GEMINI_UPSTREAM,
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    ):
        pass

    assert seen["body"] == {
        "model": GEMINI_UPSTREAM,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }


# ---------------------------------------------------------------------------
# Gateway validation contract (fail-closed)
# ---------------------------------------------------------------------------
def _body(**overrides):
    body = {
        "model": GEMINI_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
    }
    body.update(overrides)
    return body


def test_gateway_preserves_omitted_temperature_as_none() -> None:
    validated = _validate_body(_body())
    assert validated["temperature"] is None
    assert validated["max_tokens"] is None
    assert validated["parameters"] == {}


def test_gateway_accepts_and_collects_supported_options() -> None:
    validated = _validate_body(_body(reasoning_effort="minimal", top_p=0.5))
    assert validated["parameters"] == {"reasoning_effort": "minimal", "top_p": 0.5}


def test_gateway_rejects_an_option_the_exact_model_does_not_document() -> None:
    with pytest.raises(UnsupportedParameter):
        _validate_body(
            {
                "model": "inception/mercury-2.5",
                "messages": [{"role": "user", "content": "hi"}],
                "reasoning_effort": "high",
            }
        )


def test_gateway_rejects_an_invalid_value_for_a_supported_option() -> None:
    with pytest.raises(InvalidParameterValue):
        _validate_body(_body(reasoning_effort="none"))


def test_gateway_rejects_max_tokens_above_the_service_ceiling() -> None:
    with pytest.raises(Exception):
        _validate_body(_body(max_tokens=4097))


def test_gateway_returns_422_for_unsupported_parameter_over_http() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={
                "model": "inception/mercury-2.5",
                "messages": [{"role": "user", "content": "hi"}],
                "thinking": True,
            },
        )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unsupported_parameter"


def test_gateway_does_not_fallback_or_change_model_on_unsupported_option() -> None:
    """An unsupported option must fail closed, never silently switch models."""
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={
                "model": "inception/mercury-2.5",
                "messages": [{"role": "user", "content": "hi"}],
                "top_k": 40,
            },
        )
    body = resp.json()
    assert resp.status_code == 422
    assert body["error"]["code"] == "unsupported_parameter"
    # No route metadata is returned: nothing was executed or substituted.
    assert "business14" not in body
