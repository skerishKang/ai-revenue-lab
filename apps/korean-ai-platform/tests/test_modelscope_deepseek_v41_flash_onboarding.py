"""ModelScope DeepSeek V4.1 Flash offline wire/secret/identity gate.

The new ModelScope provider is NOT the DeepSeek direct API. No paid model
request, credentials or Prod deploy are performed by these tests.

#7241 3단계: the route this suite covers is selected structurally. It is the one
registered route that

* passes the platform adapter's own owner-allowlist gate (so it is an identity
  the execution path really accepts),
* declares exactly chat and is served on no evidenced serving window (the
  onboarding recorded that the account's quota/serving context is not a
  manufacturer limit),
* claims no evidenced per-token price, and
* carries a vendor-namespaced upstream identity — the discriminator from the
  provider's own direct API, which serves bare model names.

The provider id, upstream identity, origin, host allow-list, credential slot
and the model name the wire carries are then read back from the row and the
provider entry the selector points at.
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
from app.pilot.owner_model_exclusions import (
    excluded_from_owner_customer_selection,
    free_candidate_excluded_from_execution,
)
from app.pilot.platform import (
    _require_owner_allowed_live_model,
    call_platform_chat_completions,
    stream_platform_chat_completions,
)
from app.pilot.platform_secrets import get_platform_provider, resolve_secret
from app.pilot.router_core import resolve_manual_route
from app.pilot.errors import PilotNotConfigured, UpstreamRateLimited

from _registry_values import model_rows, provider_row, requires_owner_document


def _accepted_by_the_execution_gate(row: dict) -> bool:
    """Whether the platform adapter's owner gate admits this route."""
    try:
        _require_owner_allowed_live_model(
            row["id"], row["upstream_model"], row["provider_id"]
        )
    except Exception:  # the gate's refusal is its answer, not a test failure
        return False
    return True


def _onboarded_row() -> dict | None:
    """The vendor-namespaced, chat-only onboarding record this suite covers.

    A registry document that admits no such record — e.g. a placeholder fixture
    carrying only example rows — answers ``None``: the pins below are owner
    decisions about a real onboarding, so they are reported as skipped rather
    than silently passing on a record they never selected.
    """
    candidates = [
        row for row in model_rows()
        if _accepted_by_the_execution_gate(row)
        and not excluded_from_owner_customer_selection(row["id"])
        and not free_candidate_excluded_from_execution(row["id"])
        and set(row["capabilities"]) == {"chat"}
        and "/" in row["upstream_model"]
        and row["context_window"] == 0
        and row["input_price_usd_per_1m"] is None
        and row["output_price_usd_per_1m"] is None
        and provider_row(row["provider_id"])["enabled"]
        and row["enabled"]
        and row["id"].split("/", 1)[0] != row["upstream_model"].split("/", 1)[0]
    ]
    assert len(candidates) <= 1, "the vendor-namespaced onboarding record is not unique"
    return candidates[0] if candidates else None


ROW = _onboarded_row()
#: Applied to every pin that reads the selected record: with no such record in
#: the effective document there is nothing to assert.
_NO_RECORD = pytest.mark.skipif(
    ROW is None,
    reason="the effective registry document carries no vendor-namespaced onboarding",
)
if ROW is None:
    MID = UPSTREAM = PROVIDER = PROVIDER_NAME = ORIGIN = BINDING = SECRET_NAME = None
    PROVIDER_ROW = {}
    HOSTS = ()
else:
    MID = ROW["id"]
    UPSTREAM = ROW["upstream_model"]
    PROVIDER = ROW["provider_id"]
    PROVIDER_ROW = provider_row(PROVIDER)
    #: The display name the B14 call surfaces label this provider with.
    PROVIDER_NAME = ROW["provider_name"]
    ORIGIN = PROVIDER_ROW["base_origin"]
    HOSTS = PROVIDER_ROW["allowed_hosts"]
    BINDING = PROVIDER_ROW["credential_binding_name"]
    SECRET_NAME = BINDING
    #: The surface suffix the OpenAI-compatible completion path names.
COMPLETIONS_PATH = "/chat" + "/completions"
CHAT_URL = (ORIGIN or "").rstrip("/") + COMPLETIONS_PATH
SYNTHETIC_KEY = "synthetic-modelscope-private-token-no-real-api"
#: The vendor namespace the wire model name is namespaced by (the discriminator
#: from the provider's own direct API, which serves the bare name).
VENDOR_NAMESPACE = (UPSTREAM or "").split("/", 1)[0]
#: Another provider's credential slot, which must never be borrowed in place of
#: this route's own one.
OTHER_BINDING = next(
    (
        entry["credential_binding_name"]
        for pid, entry in read_registry()["providers"].items()
        if pid != PROVIDER
    ),
    None,
)


@pytest.fixture
def isolated_provider(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, SYNTHETIC_KEY)
    return monkeypatch


@requires_owner_document
@_NO_RECORD
def test_exact_modelscope_provider_identity_price_and_future_quota_unknown():
    d = read_registry()
    ids = [x["id"] for x in d["models"]]
    assert len(ids) >= 14 and len(set(ids)) == len(ids)
    assert len(d["providers"]) >= 10
    assert {m["provider_id"] for m in d["models"]} <= set(d["providers"])
    assert MID in ids  # Preserve original identity, not a fragile append position
    assert d["groups"] == {"plus": [], "pro": [], "max": []}
    row = next(x for x in d["models"] if x["id"] == MID)
    assert row["provider_id"] == PROVIDER
    assert row["upstream_model"] == UPSTREAM
    assert row["capabilities"] == ["chat"]
    # ModelScope account quota/serving context are not manufacturer limits.
    assert row["context_window"] == 0
    assert row["input_price_usd_per_1m"] is None
    assert row["output_price_usd_per_1m"] is None
    # The recorded evidence is the vendor's own model page: the upstream name is
    # namespaced by the vendor, and the source cites that namespaced identity.
    assert row["upstream_model"].split("/", 1)[0] == VENDOR_NAMESPACE
    assert UPSTREAM in row["source"]
    p = d["providers"][PROVIDER]
    assert p["base_origin"] == ORIGIN
    assert p["allowed_hosts"] == HOSTS
    assert p["credential_source"] == "platform_secret"
    assert p["credential_binding_name"] == BINDING


@requires_owner_document
@_NO_RECORD
def test_registered_route_manual_no_key_or_model_substitution():
    with TestClient(create_app()) as client:
        response = client.get("/api/pilot/admin/models")
    assert response.status_code == 200
    routes = response.json()["registered_routes"]
    assert len(routes) == len(read_registry()["models"])
    item = next(x for x in routes if x["id"] == MID)
    assert item["upstream_model"] == UPSTREAM
    assert item["provider_id"] == PROVIDER
    # Off every designated roster, so only the exact id reaches it — and the
    # owner has not excluded it.
    assert item["explicit_only"] is True
    assert item["auto_eligible"] is False
    assert item["owner_excluded"] is False
    assert BINDING not in response.text
    assert SYNTHETIC_KEY not in response.text


@requires_owner_document
@_NO_RECORD
def test_source_wrangler_worker_binding_metadata_unique_only():
    root = Path(__file__).resolve().parents[1]
    wr = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf8"))
    bindings = wr["secrets_store_secrets"]
    ours = [x for x in bindings if x["binding"] == BINDING]
    assert len(ours) == 1
    assert ours[0]["secret_name"] == SECRET_NAME
    # The store is one account store per deployment: the metadata names the
    # store the file itself declares, which every slot points at.
    assert len({x["store_id"] for x in bindings}) == 1
    assert ours[0]["store_id"] == next(iter({x["store_id"] for x in bindings}))
    assert len({x["binding"] for x in bindings}) == len(bindings)
    # Membership in the registry-derived scope is what puts this binding in the
    # Worker's request scope; worker.py no longer hand-lists a Provider credential.
    from app.pilot.model_registry_file import credential_binding_names
    assert BINDING in credential_binding_names()
    assert all(set(x) == {"binding", "store_id", "secret_name"} for x in bindings)
    spec = get_platform_provider(PROVIDER)
    assert spec is not None and spec.credential_binding_name == BINDING


@requires_owner_document
@_NO_RECORD
def test_missing_modelscope_secret_denied_before_network(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(BINDING, raising=False)
    monkeypatch.setenv(OTHER_BINDING, "synthetic-foreign-not-borrowable")
    spec = get_platform_provider(PROVIDER)
    assert resolve_secret(spec) == ""
    calls = []
    def unexpected(request):
        calls.append(request)
        raise AssertionError("No provider token but transport was called")
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call_platform_chat_completions(
            model_id=MID, upstream_model=UPSTREAM, provider=PROVIDER_NAME,
            platform_provider_id=PROVIDER,
            messages=[{"role":"user","content":"synthetic"}],
            transport=httpx.MockTransport(unexpected)))
    assert calls == []


@requires_owner_document
@_NO_RECORD
def test_manual_identity_route_no_fallback(isolated_provider):
    d = resolve_manual_route(MID)
    assert d.selected_model == MID
    assert d.platform_provider_id == PROVIDER
    assert d.selected_upstream_model == UPSTREAM
    assert not d.fallback_allowed
    assert d.eligible_fallback == [] or not d.eligible_fallback


@requires_owner_document
@_NO_RECORD
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


@requires_owner_document
@_NO_RECORD
def test_exact_modelscope_completed_json_and_secret_isolation(isolated_provider):
    calls=[]
    def handler(req):
        calls.append(str(req.url))
        assert str(req.url) == CHAT_URL
        assert req.headers["Authorization"] == "Bearer "+SYNTHETIC_KEY
        assert json.loads(req.content) == {
            "model":UPSTREAM, "messages":[{"role":"user","content":"ok"}]
        }
        return httpx.Response(200,json={
            "id":"mock-1","model":UPSTREAM,
            "choices":[{"message":{"role":"assistant","content":"OK"},
                        "finish_reason":"stop"}]})
    result = asyncio.run(call_platform_chat_completions(
        model_id=MID, upstream_model=UPSTREAM, provider=PROVIDER_NAME,
        platform_provider_id=PROVIDER,
        messages=[{"role":"user","content":"ok"}],
        transport=httpx.MockTransport(handler)))
    assert calls == [CHAT_URL]
    assert result["model"] == UPSTREAM
    assert SYNTHETIC_KEY not in repr(result)


@requires_owner_document
@_NO_RECORD
def test_modelscope_streaming_keeps_exact_model_and_no_hidden_options(isolated_provider):
    calls=[]
    def handler(req):
        calls.append(str(req.url))
        assert req.headers["Authorization"] == "Bearer "+SYNTHETIC_KEY
        # #6812 stage 2: the streamed body also asks for its usage report.
        assert json.loads(req.content) == {
            "model":UPSTREAM,"messages":[{"role":"user","content":"ok"}],"stream":True,
            "stream_options":{"include_usage":True},
        }
        return httpx.Response(200,content=(
            'data: {"id":"synthetic","model":"'+UPSTREAM+
            '","choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n').encode())
    async def run():
        return [x async for x in stream_platform_chat_completions(
            model_id=MID, upstream_model=UPSTREAM, provider=PROVIDER_NAME,
            platform_provider_id=PROVIDER,
            messages=[{"role":"user","content":"ok"}],
            transport=httpx.MockTransport(handler))]
    stream = asyncio.run(run())
    assert calls == [CHAT_URL]
    assert stream[0].model == UPSTREAM
    assert stream[-1].done is True
    assert all(SYNTHETIC_KEY not in repr(x) for x in stream)


@requires_owner_document
@_NO_RECORD
def test_modelscope_upstream_quota_429_never_falls_back(isolated_provider):
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(429,json={"error":{"code":"quota_exceeded"}})
    with pytest.raises(UpstreamRateLimited):
        asyncio.run(call_platform_chat_completions(
            model_id=MID, upstream_model=UPSTREAM, provider=PROVIDER_NAME,
            platform_provider_id=PROVIDER,
            messages=[{"role":"user","content":"ok"}],
            transport=httpx.MockTransport(handler)))
    assert len(calls) == 1
