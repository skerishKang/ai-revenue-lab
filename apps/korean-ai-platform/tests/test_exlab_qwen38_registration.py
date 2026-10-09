"""B14 ExLab model-source registration, privacy admission and last egress gate."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.errors import NoSafeRoute, PilotNotConfigured
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


def test_customer_manual_route_refused_during_model_policy_review(live_env):
    with pytest.raises(NoSafeRoute) as e:
        resolve_manual_route(MODEL, allow_external_fallback=True)
    assert e.value.reason_code=="model_data_policy_pending"
    assert e.value.upstream_called is False


@pytest.mark.parametrize("model_id,upstream",[
    (MODEL,UPSTREAM),
    ("safe-fixture/model",UPSTREAM),
])
def test_nonstream_pre_egress_fails_before_secret_and_network(live_env,model_id,upstream):
    calls=[]
    def unexpected(req):
        calls.append(req)
        raise AssertionError("model must not reach upstream")
    async def do():
        return await call_platform_chat_completions(
            model_id=model_id,
            upstream_model=upstream,
            provider="Experiential Labs",
            platform_provider_id="experiential",
            messages=[{"role":"user","content":"synthetic fixture only"}],
            transport=httpx.MockTransport(unexpected),
        )
    with pytest.raises(PilotNotConfigured,match="data-policy clearance"):
        asyncio.run(do())
    assert calls==[]


def test_stream_pre_egress_fails_before_secret_and_network(live_env):
    calls=[]
    def unexpected(req):
        calls.append(req)
        raise AssertionError("stream must not reach upstream")
    async def do():
        async for _ in stream_platform_chat_completions(
            model_id=MODEL,
            upstream_model=UPSTREAM,
            provider="Experiential Labs",
            platform_provider_id="experiential",
            messages=[{"role":"user","content":"synthetic fixture only"}],
            transport=httpx.MockTransport(unexpected),
        ):
            pass
    with pytest.raises(PilotNotConfigured,match="data-policy clearance"):
        asyncio.run(do())
    assert calls==[]
