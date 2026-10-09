"""B14 ExLab model selection and fixed provider transport contract."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.errors import PilotNotConfigured, UpstreamRateLimited, UpstreamAuthFailed
from app.pilot.model_registry_file import read_registry
from app.pilot.platform import (
    call_platform_chat_completions, stream_platform_chat_completions,
)
from app.pilot.router_core import resolve_manual_route

MODEL = "experiential/qwen3.8-flash-next-uncensored"
UPSTREAM = "qwen3.8-flash-next-uncensored"
ORIGIN = "https://api.experientiallabs.ai/v1"
BINDING = "PADIEM_EXLAB_API_KEY"


def test_exlab_catalog_is_manual_only_and_uses_existing_secret_name():
    d=read_registry()
    assert len(d["models"])==10 and len(d["providers"])==7
    p=d["providers"]["experiential"]
    assert p["base_origin"]==ORIGIN
    assert p["allowed_hosts"]==["api.experientiallabs.ai"]
    assert p["credential_source"]=="platform_secret"
    assert p["credential_binding_name"]==BINDING
    m=next(x for x in d["models"] if x["id"]==MODEL)
    assert m["provider_id"]=="experiential"
    assert m["upstream_model"]==UPSTREAM
    assert m["context_window"]==262144
    assert m["capabilities"]==["chat","coding"]
    assert m["input_price_usd_per_1m"] is None
    assert m["output_price_usd_per_1m"] is None
    assert all(not d["groups"][group] for group in ("plus","pro","max"))
    assert "b-ai/qwen3.8-flash" not in {x["id"] for x in d["models"]}
    assert "experiential/gpt-5.6-luna" not in {x["id"] for x in d["models"]}


def test_b14_models_lists_exact_exlab_without_showing_secret():
    with TestClient(create_app()) as client:
        res=client.get("/api/pilot/models")
    assert res.status_code==200
    rows={r["id"]:r for r in res.json()["registered_routes"]}
    assert len(rows)==10
    row=rows[MODEL]
    assert row["provider_id"]=="experiential"
    assert row["upstream_model"]==UPSTREAM
    assert row["explicit_only"] is True
    assert row["auto_eligible"] is False
    assert row["free"] is False  # free promotion is not a permanent model capability
    assert BINDING not in res.text
    assert "Authorization" not in res.text


@pytest.fixture
def live_env(monkeypatch):
    saved=runtime_config.provider_mode
    runtime_config.provider_mode="live"
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setenv(BINDING,"test-fixture-exlab-binding-no-real-secret")
    yield
    runtime_config.provider_mode=saved



def test_owner_selected_model_route_is_available_without_fallback(live_env):
    route = resolve_manual_route(MODEL, allow_external_fallback=False)
    assert route.selected_model == MODEL
    assert route.selected_upstream_model == UPSTREAM
    assert route.platform_provider_id == "experiential"
    assert route.fallback_allowed is False
    assert route.eligible_fallback == []


def test_direct_transport_uses_exact_origin_slug_and_binding(live_env):
    fixture = "test-fixture-exlab-binding-no-real-secret"
    def responder(request):
        assert str(request.url) == ORIGIN + "/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + fixture
        assert json.loads(request.content)["model"] == UPSTREAM
        return httpx.Response(200, json={
            "id": "synthetic", "model": UPSTREAM,
            "choices": [{"message": {"content": "견적 확인 완료"}}],
        })
    result = asyncio.run(call_platform_chat_completions(
        model_id=MODEL, upstream_model=UPSTREAM,
        provider="Experiential Labs", platform_provider_id="experiential",
        messages=[{"role": "user", "content": "합성 견적 확인"}],
        transport=httpx.MockTransport(responder),
    ))
    assert result["model"] == UPSTREAM
    assert result["_live"] is True
    assert fixture not in repr(result)


def test_stream_transport_uses_exact_upstream_slug(live_env):
    fixture = "test-fixture-exlab-binding-no-real-secret"
    def responder(request):
        assert str(request.url) == ORIGIN + "/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + fixture
        assert json.loads(request.content)["model"] == UPSTREAM
        payload = (
            'data: {"id":"test","model":"' + UPSTREAM + '",'
            '"choices":[{"delta":{"content":"확인"},"finish_reason":"stop"}]}\\n\\n'
            'data: [DONE]\\n\\n'
        ).replace('\\n','\n').encode()
        return httpx.Response(200, content=payload)
    async def run():
        return [event async for event in stream_platform_chat_completions(
            model_id=MODEL, upstream_model=UPSTREAM,
            provider="Experiential Labs", platform_provider_id="experiential",
            messages=[{"role": "user", "content": "합성 입력"}],
            transport=httpx.MockTransport(responder),
        )]
    events=asyncio.run(run())
    assert events[0].model == UPSTREAM
    assert events[-1].done is True
    assert all(fixture not in repr(ev) for ev in events)


@pytest.mark.parametrize("code,exception", [
    (401, UpstreamAuthFailed),
    (429, UpstreamRateLimited),
])
def test_upstream_errors_fail_safely(live_env, code, exception):
    def responder(req):
        return httpx.Response(code, json={"error": "synthetic"})
    with pytest.raises(exception):
        asyncio.run(call_platform_chat_completions(
            model_id=MODEL, upstream_model=UPSTREAM,
            provider="Experiential Labs", platform_provider_id="experiential",
            messages=[{"role": "user", "content": "synthetic"}],
            transport=httpx.MockTransport(responder),
        ))


def test_missing_own_secret_fails_before_upstream(live_env, monkeypatch):
    monkeypatch.delenv(BINDING)
    def unexpected(req):
        raise AssertionError("no upstream without ExLab credential")
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call_platform_chat_completions(
            model_id=MODEL, upstream_model=UPSTREAM,
            provider="Experiential Labs", platform_provider_id="experiential",
            messages=[{"role": "user", "content": "synthetic"}],
            transport=httpx.MockTransport(unexpected),
        ))
