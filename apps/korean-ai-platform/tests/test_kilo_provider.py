"""Network-free contract tests for B14 Provider 03 / Kilo Gateway (#956)."""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import UpstreamRateLimited
from app.pilot.kilo_provider import (
    KILO_BASE_ORIGIN,
    KILO_MODEL_ID,
    KILO_UPSTREAM_MODEL,
)
from app.pilot.router_core import resolve_auto_route, resolve_manual_route


class _Chunk(httpx.AsyncByteStream):
    def __init__(self, data: bytes):
        self.data = data

    async def __aiter__(self):
        for offset in range(0, len(self.data), 19):
            yield self.data[offset:offset + 19]

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _provider_mode(monkeypatch):
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    yield
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)


def test_kilo_explicit_free_model_is_registered_keyless() -> None:
    model = get_catalog_by_id(KILO_MODEL_ID)
    assert model is not None
    assert model.upstream_model == KILO_UPSTREAM_MODEL
    assert model.provider == "Kilo Gateway / NVIDIA"
    assert model.input_price_usd_per_1m == 0.0
    assert model.output_price_usd_per_1m == 0.0
    assert "chat" in model.capabilities
    assert "free" in model.capabilities
    assert model.context_window == 1_000_000
    assert model.source_checked_at == "2026-09-02"

    spec = ps.get_platform_provider("kilo")
    assert spec is not None
    assert spec.credential_source == ps.CredentialSource.NONE
    assert spec.credential_binding_name == ""
    assert spec.base_origin == KILO_BASE_ORIGIN
    assert spec.allowed_hosts == ("api.kilo.ai",)
    assert ps.is_secret_present(spec) is True


def test_kilo_route_is_manual_explicit_only() -> None:
    decision = resolve_manual_route(KILO_MODEL_ID)
    assert decision.selected_model == KILO_MODEL_ID
    assert decision.selected_upstream_model == KILO_UPSTREAM_MODEL
    assert decision.selected_provider == "Kilo Gateway / NVIDIA"
    assert decision.platform_provider_id == "kilo"
    assert decision.credential_available is True
    assert decision.max_attempts == 1
    assert decision.fallback_allowed is False

    auto = resolve_auto_route(
        task_type="general",
        required_capabilities=["chat"],
        optimize_for="balanced",
        allow_external_fallback=True,
    )
    auto_pool = {auto.selected_model, *(item["model_id"] for item in auto.eligible_fallback)}
    assert KILO_MODEL_ID not in auto_pool


@pytest.mark.asyncio
async def test_kilo_completed_call_sends_no_authorization_header(monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("AGNES_API_KEY", "ags_live_abcdefghijklmnopqrstuvwxyz1234")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "kilo-test-1",
                "model": KILO_UPSTREAM_MODEL,
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "테스트 응답"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    response = await plat.call_platform_chat_completions(
        model_id=KILO_MODEL_ID,
        upstream_model=KILO_UPSTREAM_MODEL,
        provider="Kilo Gateway / NVIDIA",
        platform_provider_id="kilo",
        messages=[{"role": "user", "content": "안녕하세요"}],
        max_tokens=None,
        transport=httpx.MockTransport(handler),
    )

    assert captured["url"] == f"{KILO_BASE_ORIGIN}/chat/completions"
    assert captured["auth"] is None
    assert captured["body"]["model"] == KILO_UPSTREAM_MODEL
    assert "max_tokens" not in captured["body"]
    assert response["choices"][0]["message"]["content"] == "테스트 응답"


@pytest.mark.asyncio
async def test_kilo_stream_sends_no_authorization_and_requires_done(monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    captured: dict[str, object] = {}
    payload = (
        b'data: {"id":"k1","model":"nvidia/nemotron-3-ultra-550b-a55b:free","choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\n'
        b'data: {"id":"k1","model":"nvidia/nemotron-3-ultra-550b-a55b:free","choices":[{"delta":{"content":"b"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, stream=_Chunk(payload))

    events = [
        event
        async for event in plat.stream_platform_chat_completions(
            model_id=KILO_MODEL_ID,
            upstream_model=KILO_UPSTREAM_MODEL,
            provider="Kilo Gateway / NVIDIA",
            platform_provider_id="kilo",
            messages=[{"role": "user", "content": "안녕하세요"}],
            max_tokens=None,
            transport=httpx.MockTransport(handler),
        )
    ]

    assert captured["url"] == f"{KILO_BASE_ORIGIN}/chat/completions"
    assert captured["auth"] is None
    assert captured["body"]["stream"] is True
    assert "max_tokens" not in captured["body"]
    assert "".join(event.delta_content or "" for event in events) == "ab"
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_kilo_rate_limit_maps_to_bounded_provider_error(monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "do not echo upstream body"})

    with pytest.raises(UpstreamRateLimited):
        await plat.call_platform_chat_completions(
            model_id=KILO_MODEL_ID,
            upstream_model=KILO_UPSTREAM_MODEL,
            provider="Kilo Gateway / NVIDIA",
            platform_provider_id="kilo",
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )


def test_kilo_gateway_dispatches_without_caller_provider_key(monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": KILO_MODEL_ID,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["business14"]["selected_model"] == KILO_MODEL_ID
    assert payload["business14"]["selected_provider"] == "Kilo Gateway / NVIDIA"
    assert payload["business14"]["attempt_count"] == 1
