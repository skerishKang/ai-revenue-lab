"""ModelScope DeepSeek V4.1 Flash offline wire/secret/identity gate.

The new ModelScope provider is NOT the DeepSeek direct API. No paid model
request, credentials or Prod deploy are performed by these tests.
"""
from __future__ import annotations
import asyncio
import json
import tomllib
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.gateway import _InvalidBody, _validate_body
from app.pilot.model_registry_file import read_registry
from app.pilot.model_native_parameters import validate_native_parameters
from app.pilot.platform import call_platform_chat_completions, stream_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider, resolve_secret
from app.pilot.router_core import resolve_manual_route
from app.pilot.errors import PilotNotConfigured, UpstreamRateLimited

MID = "modelscope/deepseek-ai/DeepSeek-V4.1-Flash"
UPSTREAM = "deepseek-ai/DeepSeek-V4.1-Flash"
ORIGIN = "https://api-inference.modelscope.cn/v1"
BINDING = "PADIEM_MODELSCOPE_API_KEY"
SYNTHETIC_KEY = "synthetic-modelscope-private-token-no-real-api"


@pytest.fixture
def isolated_provider(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, SYNTHETIC_KEY)
    return monkeypatch


def test_exact_modelscope_provider_identity_price_and_future_quota_unknown():
    d = read_registry()
    ids = [x["id"] for x in d["models"]]
    assert len(ids) == 12 and len(set(ids)) == 12
    assert len(d["providers"]) == 9
    assert MID == ids[-1]
    assert ids[10] == "kira/qwen3.8-flash-free"
    assert d["groups"] == {"plus": [], "pro": [], "max": []}
    row = d["models"][-1]
    assert row["provider_id"] == "modelscope"
    assert row["upstream_model"] == UPSTREAM
    assert row["capabilities"] == ["chat"]
    # ModelScope account quota/serving context are not manufacturer limits.
    assert row["context_window"] == 0
    assert row["input_price_usd_per_1m"] is None
    assert row["output_price_usd_per_1m"] is None
    assert "modelscope.cn/models/deepseek-ai/DeepSeek-V4.1-Flash" in row["source"]
    p = d["providers"]["modelscope"]
    assert p["base_origin"] == ORIGIN
    assert p["allowed_hosts"] == ["api-inference.modelscope.cn"]
    assert p["credential_source"] == "platform_secret"
    assert p["credential_binding_name"] == BINDING


def test_registered_route_manual_no_key_or_model_substitution():
    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/models")
    assert response.status_code == 200
    routes = response.json()["registered_routes"]
    assert len(routes) == 12
    item = next(x for x in routes if x["id"] == MID)
    assert item["upstream_model"] == UPSTREAM
    assert item["provider_id"] == "modelscope"
    assert item["explicit_only"] is True
    assert item["auto_eligible"] is False
    assert item["owner_excluded"] is False
    assert BINDING not in response.text
    assert SYNTHETIC_KEY not in response.text


def test_source_wrangler_worker_binding_metadata_unique_only():
    root = Path(__file__).resolve().parents[1]
    wr = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf8"))
    bindings = wr["secrets_store_secrets"]
    ours = [x for x in bindings if x["binding"] == BINDING]
    assert len(ours) == 1
    assert ours[0]["secret_name"] == BINDING
    assert ours[0]["store_id"] == "f0b09ca04a7b43248154c773704a5616"
    assert len({x["binding"] for x in bindings}) == len(bindings)
    assert BINDING in (root / "worker.py").read_text(encoding="utf8")
    assert all(set(x) == {"binding", "store_id", "secret_name"} for x in bindings)
    spec = get_platform_provider("modelscope")
    assert spec is not None and spec.credential_binding_name == BINDING


def test_missing_modelscope_secret_denied_before_network(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(BINDING, raising=False)
    monkeypatch.setenv("PADIEM_KIRAAI_API_KEY", "synthetic-kira-not-borrowable")
    spec = get_platform_provider("modelscope")
    assert resolve_secret(spec) == ""
    calls = []
    def unexpected(request):
        calls.append(request)
        raise AssertionError("No ModelScope token but transport was called")
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call_platform_chat_completions(
            model_id=MID, upstream_model=UPSTREAM, provider="ModelScope",
            platform_provider_id="modelscope",
            messages=[{"role":"user","content":"synthetic"}],
            transport=httpx.MockTransport(unexpected)))
    assert calls == []


def test_manual_identity_route_no_fallback(isolated_provider):
    d = resolve_manual_route(MID, allow_external_fallback=False)
    assert d.selected_model == MID
    assert d.platform_provider_id == "modelscope"
    assert d.selected_upstream_model == UPSTREAM
    assert not d.fallback_allowed
    assert d.eligible_fallback == [] or not d.eligible_fallback


def test_native_unspecified_fields_remain_omitted():
    data = _validate_body({
        "model":MID, "messages":[{"role":"user","content":"hello"}]})
    assert data["max_tokens"] is None
    assert data["temperature"] is None
    assert data["model_parameters"] == {}
    assert validate_native_parameters(MID, {}) == {}
    with pytest.raises(_InvalidBody,match="not documented"):
        _validate_body({
            "model":MID, "messages":[{"role":"user","content":"hello"}],
            "reasoning_effort":"high"})


def test_exact_modelscope_completed_json_and_secret_isolation(isolated_provider):
    calls=[]
    def handler(req):
        calls.append(str(req.url))
        assert str(req.url) == ORIGIN + "/chat/completions"
        assert req.headers["Authorization"] == "Bearer "+SYNTHETIC_KEY
        assert json.loads(req.content) == {
            "model":UPSTREAM, "messages":[{"role":"user","content":"ok"}]
        }
        return httpx.Response(200,json={
            "id":"mock-1","model":UPSTREAM,
            "choices":[{"message":{"role":"assistant","content":"OK"},
                        "finish_reason":"stop"}]})
    result = asyncio.run(call_platform_chat_completions(
        model_id=MID, upstream_model=UPSTREAM, provider="ModelScope",
        platform_provider_id="modelscope",
        messages=[{"role":"user","content":"ok"}],
        transport=httpx.MockTransport(handler)))
    assert calls == [ORIGIN + "/chat/completions"]
    assert result["model"] == UPSTREAM
    assert SYNTHETIC_KEY not in repr(result)


def test_modelscope_streaming_keeps_exact_model_and_no_hidden_options(isolated_provider):
    calls=[]
    def handler(req):
        calls.append(str(req.url))
        assert req.headers["Authorization"] == "Bearer "+SYNTHETIC_KEY
        assert json.loads(req.content) == {
            "model":UPSTREAM,"messages":[{"role":"user","content":"ok"}],"stream":True
        }
        return httpx.Response(200,content=(
            'data: {"id":"synthetic","model":"'+UPSTREAM+
            '","choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n').encode())
    async def run():
        return [x async for x in stream_platform_chat_completions(
            model_id=MID, upstream_model=UPSTREAM, provider="ModelScope",
            platform_provider_id="modelscope",
            messages=[{"role":"user","content":"ok"}],
            transport=httpx.MockTransport(handler))]
    stream = asyncio.run(run())
    assert calls == [ORIGIN + "/chat/completions"]
    assert stream[0].model == UPSTREAM
    assert stream[-1].done is True
    assert all(SYNTHETIC_KEY not in repr(x) for x in stream)


def test_modelscope_upstream_quota_429_never_falls_back(isolated_provider):
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(429,json={"error":{"code":"quota_exceeded"}})
    with pytest.raises(UpstreamRateLimited):
        asyncio.run(call_platform_chat_completions(
            model_id=MID, upstream_model=UPSTREAM, provider="ModelScope",
            platform_provider_id="modelscope",
            messages=[{"role":"user","content":"ok"}],
            transport=httpx.MockTransport(handler)))
    assert len(calls) == 1
