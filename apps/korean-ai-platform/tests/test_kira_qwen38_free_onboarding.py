"""#4018 Kira exact-serving Qwen3.8 Flash Free: offline end-to-end contracts.

The route this suite covers is the owner-onboarded promotional free route: one
single-route provider whose one model is chat-only, carries no evidenced zero
price while the promotion runs, and whose context window is the largest the
registry declares. Those four facts are the selector; the provider, model,
upstream identity, origin and credential slot are all read back from the
registry row it points at, so no deployment value is written here.
"""
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

from _registry_values import model_rows, provider_row, requires_owner_document


def _single_route_provider_models() -> list[dict]:
    """The one model of every provider registered with exactly one route."""
    rows = model_rows()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["provider_id"]] = counts.get(row["provider_id"], 0) + 1
    return [row for row in rows if counts[row["provider_id"]] == 1]


def _onboarded_row() -> dict:
    """The owner-onboarded promotional free route this suite covers.

    It is a single-route provider's one model, chat-only (no demonstrated image
    or tool capability), priced on no evidenced value because the promotion is
    not a fixed free price, and served on the widest non-empty window among
    chat-only routes. The route with a fixed per-token price is excluded by
    requiring that no evidenced price was claimed.
    """
    candidates = [
        row for row in _single_route_provider_models()
        if row["capabilities"] == ["chat"]
        and row["input_price_usd_per_1m"] is None
        and row["output_price_usd_per_1m"] is None
        and row["context_window"] > 0
    ]
    assert candidates
    widest = max(row["context_window"] for row in candidates)
    selected = [row for row in candidates if row["context_window"] == widest]
    assert len(selected) == 1
    return selected[0]


ROW = _onboarded_row()
MODEL = ROW["id"]
UPSTREAM = ROW["upstream_model"]
PROVIDER = ROW["provider_id"]
PROVIDER_ROW = provider_row(PROVIDER)
ORIGIN = PROVIDER_ROW["base_origin"]
BINDING = PROVIDER_ROW["credential_binding_name"]
SECRET_NAME = BINDING
#: The completion path this adapter appends to the provider origin. The origin
#: already ends in the version segment, so the request path is the one segment
#: that names the surface.
COMPLETIONS_PATH = "/chat" + "/completions"
CHAT_URL = ORIGIN + COMPLETIONS_PATH
# A Providers' key slot that must never be borrowed: any other platform binding.
OTHER_BINDING = next(
    name for name in (
        row["credential_binding_name"] for row in read_registry()["providers"].values()
    ) if name != BINDING
)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, "synthetic-private-onboarding-fixture")
    yield


@requires_owner_document
def test_exact_registry_append_preserves_ten_predecessors():
    data=read_registry()
    assert len(data["models"])>=11
    assert len(data["providers"])>=8
    ids=[m["id"] for m in data["models"]]
    # The onboarded route was appended after the ten routes that preceded it.
    assert ids[10]==MODEL
    assert len(set(ids))==len(ids)
    assert data["groups"]=={"plus":[],"pro":[],"max":[]}
    row=next(row for row in data["models"] if row["id"]==MODEL)
    assert row["provider_id"]==PROVIDER
    assert row["upstream_model"]==UPSTREAM
    # The route claims the widest non-empty window among chat-only routes.
    assert row["context_window"] == max(
        m["context_window"] for m in data["models"] if m["capabilities"] == ["chat"]
    )
    assert row["capabilities"]==["chat"]  # image/tools not yet demonstrated
    assert row["input_price_usd_per_1m"] is None  # promo expiry, not fixed free price
    p=data["providers"][PROVIDER]
    assert p["base_origin"]==ORIGIN
    assert p["allowed_hosts"]==provider_row(PROVIDER)["allowed_hosts"]
    assert p["credential_binding_name"]==BINDING
    assert p["credential_source"]=="platform_secret"


@requires_owner_document
def test_public_catalog_exact_manual_only_and_secret_free():
    with TestClient(create_app()) as c:
        r=c.get("/api/pilot/admin/models")
    assert r.status_code==200
    data=r.json()
    catalog={m["id"]:m for m in data["registered_routes"]}
    assert len(catalog)==len(read_registry()["models"])
    item=catalog[MODEL]
    assert item["upstream_model"]==UPSTREAM
    assert item["provider_id"]==PROVIDER
    assert item["explicit_only"] is True
    assert item["auto_eligible"] is False
    assert item["owner_excluded"] is False
    assert BINDING not in r.text
    assert "Authorization" not in r.text


@requires_owner_document
def test_manual_route_cannot_select_another_provider(live):
    route=resolve_manual_route(MODEL)
    assert route.selected_model==MODEL
    assert route.selected_upstream_model==UPSTREAM
    assert route.platform_provider_id==PROVIDER
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


@requires_owner_document
def test_store_binding_is_metadata_only_and_registered_in_worker():
    root=Path(__file__).resolve().parents[1]
    toml=(root/"wrangler.toml").read_text(encoding="utf8")
    import tomllib
    bindings=tomllib.loads(toml)["secrets_store_secrets"]
    assert len(bindings)>=10
    assert len({b["binding"] for b in bindings})==len(bindings)
    assert toml.count('binding = "'+BINDING+'"')==1
    assert toml.count('secret_name = "'+SECRET_NAME+'"')==1
    # The store is one account store: every slot points at the store this
    # deployment declares, which the file names once per slot.
    store_ids={b["store_id"] for b in bindings}
    assert len(store_ids)==1
    assert toml.count('store_id = "'+next(iter(store_ids))+'"')==len(bindings)
    # The Worker derives its request scope from the registry, so the name being
    # in that scope is the fact this onboarding must keep true; worker.py no
    # longer hand-lists a Provider credential.
    from app.pilot.model_registry_file import credential_binding_names
    assert BINDING in credential_binding_names()
    spec=get_platform_provider(PROVIDER)
    assert spec is not None and spec.credential_binding_name==BINDING
    assert resolve_secret(spec)==""  # no live key is ever loaded by this test


@requires_owner_document
def test_exact_kira_completed_http_body_and_credential_isolated(live):
    key="synthetic-private-onboarding-fixture"
    seen={}
    def handler(req):
        seen["url"]=str(req.url)
        assert str(req.url)==CHAT_URL
        assert req.headers["Authorization"]=="Bearer "+key
        body=json.loads(req.content)
        assert body=={"model":UPSTREAM,"messages":[{"role":"user","content":"OK"}]}
        return httpx.Response(200,json={
            "id":"synthetic", "model":UPSTREAM,
            "choices":[{"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":2,"completion_tokens":1},
        })
    result=asyncio.run(call_platform_chat_completions(
        model_id=MODEL,upstream_model=UPSTREAM,provider=ROW["provider_name"],
        platform_provider_id=PROVIDER,messages=[{"role":"user","content":"OK"}],
        transport=httpx.MockTransport(handler),
    ))
    assert seen["url"]==CHAT_URL
    assert result["model"]==UPSTREAM
    assert result["choices"][0]["message"]["content"]=="OK"
    assert key not in repr(result)


@requires_owner_document
def test_exact_kira_streaming_upstream_model_and_omitted_defaults(live):
    key="synthetic-private-onboarding-fixture"
    def handler(req):
        assert str(req.url)==CHAT_URL
        assert req.headers["Authorization"]=="Bearer "+key
        body=json.loads(req.content)
        # #6812 stage 2: the streamed body also asks for its usage report.
        assert body=={"model":UPSTREAM,"messages":[{"role":"user","content":"OK"}],"stream":True,"stream_options":{"include_usage":True}}
        events=(
            'data: {"id":"synthetic","model":"'+UPSTREAM+'",'
            '"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200,content=events.encode("utf8"))
    async def collect():
        return [e async for e in stream_platform_chat_completions(
            model_id=MODEL,upstream_model=UPSTREAM,provider=ROW["provider_name"],
            platform_provider_id=PROVIDER,messages=[{"role":"user","content":"OK"}],
            transport=httpx.MockTransport(handler),
        )]
    events=asyncio.run(collect())
    assert events[0].model==UPSTREAM
    assert events[-1].done is True
    assert all(key not in repr(e) for e in events)


@requires_owner_document
@pytest.mark.parametrize("status,exception", [(401, __import__("app.pilot.errors",fromlist=["UpstreamAuthFailed"]).UpstreamAuthFailed),
                                              (429, UpstreamRateLimited)])
def test_upstream_failures_do_not_change_model(live,status,exception):
    def handler(req):
        assert str(req.url)==CHAT_URL
        return httpx.Response(status,json={"error":{"code":"synthetic"}})
    with pytest.raises(exception):
        asyncio.run(call_platform_chat_completions(
            model_id=MODEL,upstream_model=UPSTREAM,provider=ROW["provider_name"],
            platform_provider_id=PROVIDER,messages=[{"role":"user","content":"OK"}],
            transport=httpx.MockTransport(handler),
        ))


@requires_owner_document
def test_missing_free_secret_never_uses_another_providers_credentials(live,monkeypatch):
    monkeypatch.delenv(BINDING)
    monkeypatch.setenv(OTHER_BINDING,"synthetic-never-borrow")
    def handler(req):
        raise AssertionError("No outbound request without this route's exact binding")
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call_platform_chat_completions(
            model_id=MODEL,upstream_model=UPSTREAM,provider=ROW["provider_name"],
            platform_provider_id=PROVIDER,messages=[{"role":"user","content":"OK"}],
            transport=httpx.MockTransport(handler),
        ))
