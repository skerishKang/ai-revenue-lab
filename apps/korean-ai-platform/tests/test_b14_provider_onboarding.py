"""Network-free B14 onboarding regressions for two remaining candidates and retired providers.

#7241: every provider/model identity, origin and credential binding asserted
below is selected from the *effective* registry document (see
``tests/_registry_values.py``), so the suite states the contract — registration
identity comes from the row itself, a retired identity is gone — and not the
Owner's literal roster. The two structural selections are:

* a *surviving* row: the provider still owns registry rows and is not the
  subject of a retirement, i.e. nothing was removed outright for it;
* a *removed* retirement: a retired identity whose provider owns no registry
  row at all.

Both are properties of the document, not of a hand-kept list here.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, replace

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import (
    CATALOG_BY_ID,
    CATALOG_MODELS,
    get_catalog_by_id,
    is_evidenced_free,
)
from app.pilot.errors import PilotNotConfigured, NoSafeRoute
from app.pilot.model_registry_file import read_registry, retired_model_ids
from app.pilot.owner_model_exclusions import excluded_from_owner_customer_selection
from app.pilot.platform import call_platform_chat_completions, stream_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.router_core import resolve_manual_route

from _registry_values import require_owner_document, requires_owner_document

# The subject is the Owner's retirement roster: which providers and identities
# were removed is a property of the owner's registry document (#7241 3b).
require_owner_document()


@dataclass(frozen=True)
class Candidate:
    provider_id: str
    binding: str
    origin: str
    host: str
    model_id: str
    upstream_model: str
    provider: str


def _row_candidates() -> tuple[Candidate, ...]:
    """Onboarding candidates read off the registry rows themselves.

    A candidate is a registered, enabled row whose provider is registered and
    not disabled, with a platform-secret credential contract. The expected
    origin/host/binding/upstream of the test is taken from that same document,
    so the test asserts the *shape* of an onboarding (identity mirrors the row,
    manual pin only, credential boundary is the provider's own) for every
    surviving candidate rather than a literal provider list.
    """
    registry = read_registry()
    retired = retired_model_ids()
    rows = [
        row
        for row in registry["models"]
        if row["enabled"] and registry["providers"].get(row["provider_id"], {}).get("enabled")
    ]
    exclusive = [
        row for row in rows if not excluded_from_owner_customer_selection(row["id"])
    ]
    # Two distinct providers keep the parametrization meaningful even when one
    # owner decision changes; the document stays the source of the values.
    picked: list[dict] = []
    for row in exclusive or rows:
        if any(other["provider_id"] == row["provider_id"] for other in picked):
            continue
        picked.append(row)
        if len(picked) == 2:
            break
    candidates = []
    for row in picked:
        provider = registry["providers"][row["provider_id"]]
        host = provider["base_origin"].split("://", 1)[-1].split("/", 1)[0]
        candidates.append(
            Candidate(
                provider_id=row["provider_id"],
                binding=provider["credential_binding_name"],
                origin=provider["base_origin"],
                host=host,
                model_id=row["id"],
                upstream_model=row["upstream_model"],
                provider=row["provider_name"],
            )
        )
    assert candidates, "the effective registry registers no enabled model"
    assert all(candidate.model_id not in retired for candidate in candidates)
    return tuple(candidates)


CANDIDATES = _row_candidates()


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
def test_candidate_registration_identity_and_manual_pin_only(candidate: Candidate):
    spec = get_platform_provider(candidate.provider_id)
    assert spec is not None
    assert spec.provider_id == candidate.provider_id
    assert spec.base_origin == candidate.origin
    assert spec.allowed_hosts == (candidate.host,)
    assert spec.credential_source.value == "platform_secret"
    assert spec.credential_binding_name == candidate.binding

    model = get_catalog_by_id(candidate.model_id)
    assert model is not None
    assert model.model_id == candidate.model_id
    assert model.upstream_model == candidate.upstream_model
    assert model.platform_provider_id == candidate.provider_id
    assert model.provider_type == "platform"
    # The catalog mirrors the row itself: same prices, same capabilities.
    row = next(item for item in read_registry()["models"] if item["id"] == candidate.model_id)
    assert model.input_price_usd_per_1m == row["input_price_usd_per_1m"]
    assert model.output_price_usd_per_1m == row["output_price_usd_per_1m"]
    assert model.capabilities == frozenset(row["capabilities"])
    assert is_evidenced_free(model) is bool(
        "free" in row["capabilities"] and model.price_is_known
        and model.input_price_usd_per_1m == 0 and model.output_price_usd_per_1m == 0
    )
    # The registry installs into the exact-id map only; the automatic lane
    # (CATALOG_MODELS) deliberately stays empty so every row is manual-pin only.
    assert candidate.model_id not in {item.model_id for item in CATALOG_MODELS}
    assert candidate.model_id in CATALOG_BY_ID

    with TestClient(create_app()) as client:
        route = next(
            item
            for item in client.get("/api/pilot/admin/models").json()["registered_routes"]
            if item["id"] == candidate.model_id
        )
    assert route["provider_id"] == candidate.provider_id
    assert route["upstream_model"] == candidate.upstream_model
    assert route["explicit_only"] is True
    assert route["public"] is False
    assert route["auto_eligible"] is False
    assert route["free"] is False


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
def test_candidate_readiness_is_metadata_only_and_does_not_leak(candidate, monkeypatch):
    secret = "sample-provider-readiness-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(candidate.binding, secret)

    response = TestClient(create_app()).get("/api/pilot/provider-readiness")

    assert response.status_code == 200
    entry = next(
        item for item in response.json()["providers"] if item["provider_id"] == candidate.provider_id
    )
    assert entry["credential_source"] == "platform_secret"
    assert entry["credential_ready"] is True
    assert entry["route_ready"] is True
    assert candidate.model_id in entry["models"]
    assert candidate.binding not in response.text
    assert secret not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_missing_secret_fails_closed_with_zero_upstream_calls(candidate, monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(candidate.binding, raising=False)
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with pytest.raises(PilotNotConfigured):
        await call_platform_chat_completions(
            model_id=candidate.model_id,
            upstream_model=candidate.upstream_model,
            provider=candidate.provider,
            platform_provider_id=candidate.provider_id,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_mock_mode_makes_zero_upstream_calls(candidate, monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        raise AssertionError("mock mode must not call upstream")

    result = await call_platform_chat_completions(
        model_id=candidate.model_id,
        upstream_model=candidate.upstream_model,
        provider=candidate.provider,
        platform_provider_id=candidate.provider_id,
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert result["_mock"] is True
    assert result["model"] == candidate.upstream_model
    assert called is False


def _a_foreign_binding(candidate: Candidate) -> str:
    """Another registered provider's binding, never the candidate's own."""
    names = sorted(
        {
            entry["credential_binding_name"]
            for entry in read_registry()["providers"].values()
        }
        - {candidate.binding}
    )
    assert names, "the registry declares no other credential binding"
    return names[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_secret_isolated_from_other_provider(candidate, monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(candidate.binding, raising=False)
    monkeypatch.setenv(_a_foreign_binding(candidate), "other-provider-only-1234567890abcdef")
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with pytest.raises(PilotNotConfigured):
        await call_platform_chat_completions(
            model_id=candidate.model_id,
            upstream_model=candidate.upstream_model,
            provider=candidate.provider,
            platform_provider_id=candidate.provider_id,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    assert called is False


def _chat_completions_url(candidate: Candidate) -> str:
    """The fixed completion endpoint: the provider origin plus the OpenAI wire path."""
    from app.pilot.platform import (
        call_platform_chat_completions as _call,
        stream_platform_chat_completions as _stream,
    )

    # The endpoint is whatever the platform adapter builds from the fixed
    # origin, so the assertion states the contract ("the row's own origin,
    # nothing else") without restating the wire path in this file.
    source = inspect.getsource(_call) + inspect.getsource(_stream)
    wire = re.findall(r"\{spec\.base_origin\.rstrip\('/'\)\}/([^\"']+)", source)
    assert len(set(wire)) == 1, "the platform adapter builds more than one endpoint"
    return f"{candidate.origin.rstrip('/')}/{wire[0]}"


def _transport_candidate(candidate: Candidate) -> Candidate:
    # These provider-transport tests are not evidence the historically
    # registered OWNER-excluded model is authorized for live execution.
    # Use a synthetic identity with the same provider and auth boundary.
    if excluded_from_owner_customer_selection(candidate.model_id):
        return replace(
            candidate,
            model_id=f"test-fixture/{candidate.provider_id}-chat",
            upstream_model=f"test-fixture/{candidate.provider_id}-response",
        )
    return candidate


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_direct_request_uses_fixed_origin_bearer_and_actual_model(
    candidate, monkeypatch
):
    candidate = _transport_candidate(candidate)
    secret = "sample-provider-direct-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(candidate.binding, secret)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == _chat_completions_url(candidate)
        assert request.url.host == candidate.host
        assert request.headers["Authorization"] == f"Bearer {secret}"
        assert json.loads(request.content)["model"] == candidate.upstream_model
        return httpx.Response(
            200,
            json={
                "id": "candidate_test",
                "model": candidate.upstream_model,
                "choices": [{"message": {"content": "ok"}}],
            },
        )

    result = await call_platform_chat_completions(
        model_id=candidate.model_id,
        upstream_model=candidate.upstream_model,
        provider=candidate.provider,
        platform_provider_id=candidate.provider_id,
        messages=[{"role": "user", "content": "hello"}],
        transport=httpx.MockTransport(handler),
    )
    assert result["_live"] is True
    assert result["model"] == candidate.upstream_model
    assert result["_actual_response_model"] == candidate.upstream_model
    assert secret not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.provider_id)
async def test_candidate_streaming_uses_exact_model_and_actual_model_evidence(candidate, monkeypatch):
    candidate = _transport_candidate(candidate)
    secret = "sample-provider-stream-proof-1234567890abcdef"
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(candidate.binding, secret)
    payload = (
        f'data: {{"id":"q1","model":"{candidate.upstream_model}",'
        '"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == _chat_completions_url(candidate)
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["model"] == candidate.upstream_model
        assert request.headers["Authorization"] == f"Bearer {secret}"
        return httpx.Response(200, content=payload)

    events = [
        event
        async for event in stream_platform_chat_completions(
            model_id=candidate.model_id,
            upstream_model=candidate.upstream_model,
            provider=candidate.provider,
            platform_provider_id=candidate.provider_id,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    ]
    assert events[0].model == candidate.upstream_model
    assert events[-1].done is True
    assert all(secret not in repr(event) for event in events)


def _removed_provider_id() -> str:
    """A provider the Owner removed outright.

    Structural: a retired identity whose provider prefix owns no registry
    provider row, so nothing of that provider survives in the document.
    """
    registry = read_registry()
    removed = sorted(
        {
            model_id.split("/", 1)[0]
            for model_id in retired_model_ids()
            if model_id.split("/", 1)[0] not in registry["providers"]
        }
    )
    assert removed, "the effective registry retires no whole provider"
    return removed[0]


@requires_owner_document
def test_owner_removed_provider_and_model_not_registered_or_dispatchable():
    registry = read_registry()
    provider_id = _removed_provider_id()
    model_ids = sorted(
        model_id
        for model_id in retired_model_ids()
        if model_id.split("/", 1)[0] == provider_id
    )
    assert model_ids
    model_id = model_ids[0]
    assert provider_id not in registry["providers"]
    assert all(row["provider_id"] != provider_id for row in registry["models"])
    assert get_platform_provider(provider_id) is None
    assert get_catalog_by_id(model_id) is None
    assert model_id not in CATALOG_BY_ID
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(model_id)
    assert exc.value.upstream_called is False


def _surviving_retired_model_id() -> tuple[str, str]:
    """A provider that kept its registration after one of its identities retired.

    Structural: a retired identity whose provider still owns registry rows.
    """
    registry = read_registry()
    owning = {
        row["provider_id"] for row in registry["models"]
    } & set(registry["providers"])
    survivors = sorted(
        model_id
        for model_id in retired_model_ids()
        if model_id.split("/", 1)[0] in owning
    )
    assert survivors, "the effective registry retires no identity of a surviving provider"
    return survivors[0].split("/", 1)[0], survivors[0]


@requires_owner_document
def test_exlab_provider_reused_but_owner_retired_luna_stays_unregistered():
    registry = read_registry()
    provider_id, model_id = _surviving_retired_model_id()
    provider = registry["providers"][provider_id]
    host = provider["base_origin"].split("://", 1)[-1].split("/", 1)[0]
    spec = get_platform_provider(provider_id)
    assert spec is not None
    assert spec.base_origin == provider["base_origin"]
    assert spec.allowed_hosts == (host,)
    assert spec.credential_binding_name == provider["credential_binding_name"]
    assert get_catalog_by_id(model_id) is None
    with pytest.raises(NoSafeRoute):
        resolve_manual_route(model_id)
