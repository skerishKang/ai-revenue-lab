"""#4018 Kira exact-serving Qwen3.8 Flash Free: offline end-to-end contracts."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.gateway import _InvalidBody, _validate_body
from app.pilot.model_registry_file import read_registry
from app.pilot.model_native_parameters import (
    UnsupportedModelParameter, validate_native_parameters,
)
from app.pilot.platform import (
    call_platform_chat_completions, stream_platform_chat_completions,
)
from app.pilot.platform_secrets import (
    get_platform_provider, resolve_secret,
)
from app.pilot.router_core import resolve_manual_route
from app.pilot.errors import PilotNotConfigured, UpstreamRateLimited

MODEL="kira/qwen3.8-flash-free"
UPSTREAM="qwen3.8-flash-free"
ORIGIN="https://kiraai.vn/api/v1"
BINDING="PADIEM_KIRAAI_API_KEY"

@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, "synthetic-private-kira-fixture-0987")
    yield

def test_exact_registry_append_preserves_ten_predecessors():
    data=read_registry()
    assert len(data["models"])>=11
    assert len(data["providers"])>=8
    ids=[m["id"] for m in data["models"]]
    assert ids[10]==MODEL
    assert "experiential/qwen3.8-flash-next-uncensored" in ids
    assert "b14/auto" not in ids
    assert len(set(ids))==len(ids)
    assert data["groups"]=={"plus":[],"pro":[],"max":[]}
    row=next(row for row in data["models"] if row["id"]==MODEL)
    assert row["provider_id"]=="kira"
    assert row["upstream_model"]==UPSTREAM
    assert row["context_window"]==1000000
    assert row["capabilities"]==["chat"]  # image/tools not yet demonstrated
    assert row["input_price_usd_per_1m"] is None  # promo expiry, not fixed free price
    p=data["providers"]["kira"]
    assert p["base_origin"]==ORIGIN
    assert p["allowed_hosts"]==["kiraai.vn"]
    assert p["credential_binding_name"]==BINDING
    assert p["credential_source"]=="platform_secret"

def test_public_catalog_exact_manual_only_and_secret_free():
    with TestClient(create_app()) as c:
        r=c.get("/api/pilot/models")
    assert r.status_code==200
    data=r.json()
    catalog={m["id"]:m for m in data["registered_routes"]}
    assert len(catalog)==len(read_registry()["models"])
    item=catalog[MODEL]
    assert item["upstream_model"]==UPSTREAM
    assert item["provider_id"]=="kira"
    assert item["explicit_only"] is True
    assert item["auto_eligible"] is False
    assert item["owner_excluded"] is False
    assert BINDING not in r.text
    assert "Authorization" not in r.text

def test_manual_route_cannot_select_another_provider(live):
    route=resolve_manual_route(MODEL,allow_external_fallback=False)
    assert route.selected_model==MODEL
    assert route.selected_upstream_model==UPSTREAM
    assert route.platform_provider_id=="kira"
    assert route.fallback_allowed is False
    assert not route.eligible_fallback

def test_model_native_defaults_omitted_and_unverified_options_rejected():
    b=_validate_body({"model":MODEL,"messages":[{"role":"user","content":"ok"}]})
    assert b["temperature"] is None
    assert b["max_tokens"] is None
    assert b["model_parameters"]=={}
    assert validate_native_parameters(MODEL,{})=={}
    with pytest.raises(_InvalidBody,match="not documented"):
        _validate_body({"model":MODEL,
                        "messages":[{"role":"user","content":"ok"}],
                        "reasoning_effort":"low"})
    with pytest.raises(UnsupportedModelParameter):
        validate_native_parameters(MODEL,{"thinking":{"type":"enabled"}})

def test_store_binding_is_metadata_only_and_registered_in_worker():
    root=Path(__file__).resolve().parents[1]
    toml=(root/"wrangler.toml").read_text(encoding="utf8")
    worker=(root/"worker.py").read_text(encoding="utf8")
    import tomllib
    bindings=tomllib.loads(toml)["secrets_store_secrets"]
    assert len(bindings)>=10
    assert len({b["binding"] for b in bindings})==len(bindings)
    assert toml.count('binding = "'+BINDING+'"')==1
    assert toml.count('secret_name = "'+BINDING+'"')==1
    assert 'store_id = "f0b09ca04a7b43248154c773704a5616"' in toml
    assert '"'+BINDING+'"' in worker
    spec=get_platform_provider("kira")
    assert spec is not None and spec.credential_binding_name==BINDING
    assert resolve_secret(spec)==""  # no live key is ever loaded by this test

def test_exact_kira_completed_http_body_and_credential_isolated(live):
    key="synthetic-private-kira-fixture-0987"
    seen={}
    def handler(req):
        seen["url"]=str(req.url)
        assert str(req.url)==ORIGIN+"/chat/completions"
        assert req.headers["Authorization"]=="Bearer "+key
        body=json.loads(req.content)
        assert body=={"model":UPSTREAM,"messages":[{"role":"user","content":"OK"}]}
        return httpx.Response(200,json={
            "id":"synthetic", "model":UPSTREAM,
            "choices":[{"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":2,"completion_tokens":1},
        })
    result=asyncio.run(call_platform_chat_completions(
        model_id=MODEL,upstream_model=UPSTREAM,provider="Kira AI",
        platform_provider_id="kira",messages=[{"role":"user","content":"OK"}],
        transport=httpx.MockTransport(handler),
    ))
    assert seen["url"]==ORIGIN+"/chat/completions"
    assert result["model"]==UPSTREAM
    assert result["choices"][0]["message"]["content"]=="OK"
    assert key not in repr(result)

def test_exact_kira_streaming_upstream_model_and_omitted_defaults(live):
    key="synthetic-private-kira-fixture-0987"
    def handler(req):
        assert str(req.url)==ORIGIN+"/chat/completions"
        assert req.headers["Authorization"]=="Bearer "+key
        body=json.loads(req.content)
        assert body=={"model":UPSTREAM,"messages":[{"role":"user","content":"OK"}],"stream":True}
        events=(
            'data: {"id":"synthetic","model":"'+UPSTREAM+'",'
            '"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200,content=events.encode("utf8"))
    async def collect():
        return [e async for e in stream_platform_chat_completions(
            model_id=MODEL,upstream_model=UPSTREAM,provider="Kira AI",
            platform_provider_id="kira",messages=[{"role":"user","content":"OK"}],
            transport=httpx.MockTransport(handler),
        )]
    events=asyncio.run(collect())
    assert events[0].model==UPSTREAM
    assert events[-1].done is True
    assert all(key not in repr(e) for e in events)

@pytest.mark.parametrize("status,exception", [(401, __import__("app.pilot.errors",fromlist=["UpstreamAuthFailed"]).UpstreamAuthFailed),
                                              (429, UpstreamRateLimited)])
def test_upstream_failures_do_not_change_model(live,status,exception):
    def handler(req):
        assert str(req.url)==ORIGIN+"/chat/completions"
        return httpx.Response(status,json={"error":{"code":"synthetic"}})
    with pytest.raises(exception):
        asyncio.run(call_platform_chat_completions(
            model_id=MODEL,upstream_model=UPSTREAM,provider="Kira AI",
            platform_provider_id="kira",messages=[{"role":"user","content":"OK"}],
            transport=httpx.MockTransport(handler),
        ))

def test_missing_kira_secret_never_uses_exlab_credentials(live,monkeypatch):
    monkeypatch.delenv(BINDING)
    monkeypatch.setenv("PADIEM_EXLAB_API_KEY","synthetic-exlab-never-borrow")
    def handler(req):
        raise AssertionError("No outbound request without exact Kira binding")
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call_platform_chat_completions(
            model_id=MODEL,upstream_model=UPSTREAM,provider="Kira AI",
            platform_provider_id="kira",messages=[{"role":"user","content":"OK"}],
            transport=httpx.MockTransport(handler),
        ))
