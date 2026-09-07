"""OpenRouter retirement contract (#1933 S2-b).

The OpenRouter call path, provider policy helper, and live smoke are removed.
Non-platform catalog routes fail closed with InvalidRequest and never reach
an upstream transport. The SSE dataclasses in openrouter_stream are preserved
for the platform streaming executor.
"""

from __future__ import annotations

import importlib.util

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.openrouter_stream import OpenRouterStreamEvent, OpenRouterStreamUsage
from app.pilot.schemas import ChatMessage, PilotChatRequest


def test_openrouter_call_module_removed():
    assert importlib.util.find_spec("app.pilot.openrouter") is None


def test_openrouter_smoke_module_removed():
    assert importlib.util.find_spec("app.pilot.smoke_live") is None


def test_openrouter_stream_primitive_removed_but_events_preserved():
    import app.pilot.openrouter_stream as stream_mod

    assert not hasattr(stream_mod, "stream_openrouter_chat_completions")
    # §3 preserved: SSE dataclasses + frame parser stay for platform streaming.
    assert hasattr(stream_mod, "_parse_sse_frame")
    assert hasattr(stream_mod, "_pop_sse_frames")
    assert OpenRouterStreamEvent(done=True).done is True
    assert OpenRouterStreamUsage(1, 2, 3).total_tokens == 3


def test_caller_schema_rejects_provider_field():
    with pytest.raises(TypeError):
        PilotChatRequest(
            model="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
            messages=[ChatMessage(role="user", content="안녕하세요")],
            provider={"data_collection": "allow"},  # type: ignore[call-arg]
        )


def _openrouter_catalog_model():
    from app.pilot.catalog import CatalogModel

    return CatalogModel(
        model_id="test/openrouter-retired",
        upstream_model="test/retired",
        display_name="Retired OpenRouter route (test only)",
        provider="Retired",
        provider_type="external",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1000,
        korean_score=1,
        latency_ms=100,
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=999,
        credential_source="openrouter",
        platform_provider_id="",
    )


@pytest.fixture()
def retired_openrouter_route(monkeypatch):
    import app.pilot.catalog as cat

    original_models = cat.CATALOG_MODELS
    original_by_id = cat.CATALOG_BY_ID
    extra = _openrouter_catalog_model()
    cat.CATALOG_MODELS = [*original_models, extra]
    cat.CATALOG_BY_ID = {m.model_id: m for m in cat.CATALOG_MODELS}
    try:
        yield extra
    finally:
        cat.CATALOG_MODELS = original_models
        cat.CATALOG_BY_ID = original_by_id


def test_non_platform_route_fails_closed_before_network(retired_openrouter_route):
    client = TestClient(create_app())
    resp = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": "test/openrouter-retired",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "invalid_request"
    assert "OpenRouter retired" in body["error"]["message"]


def test_stream_preview_rejects_non_platform_route(retired_openrouter_route):
    client = TestClient(create_app())
    resp = client.post(
        "/api/pilot/v1/chat/completions/stream-preview",
        json={
            "model": "test/openrouter-retired",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_platform_adapter_has_no_openrouter_policy(monkeypatch):
    # The platform adapter never sends an OpenRouter provider policy.
    from app.pilot import platform as plat

    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.get_json() if hasattr(request, "get_json") else None
        import json as _json

        seen["parsed"] = _json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "r1",
                "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    from app.pilot.openrouter_config import openrouter_config as orcfg

    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    monkeypatch.setattr(orcfg, "provider_mode", "live")
    monkeypatch.setattr(orcfg, "api_key", "")
    result = await plat.call_platform_chat_completions(
        model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        upstream_model="nvidia/nemotron-3-ultra-550b-a55b:free",
        provider="Kilo Gateway / NVIDIA",
        platform_provider_id="kilo",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert result["_live"] is True
    assert "provider" not in seen["parsed"]
