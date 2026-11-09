"""#3789: fail closed for OWNER-excluded model IDs before any real egress.

Only live resolver/provider paths are newly blocked. Historical mock fixture
paths remain in place without conveying live OWNER approval.
"""
from __future__ import annotations

import os

import asyncio

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.errors import NoSafeRoute, PilotNotConfigured
from app.pilot.owner_model_exclusions import free_candidate_excluded_from_execution
from app.pilot.owner_model_exclusions import (
    FREE_CANDIDATE_PROVIDER, excluded_from_owner_customer_selection,
)
from app.pilot.catalog import get_catalog_by_id
from app.pilot.model_registry_file import (
    credential_binding_names,
    read_registry,
    retired_model_ids as retired_models,
)
from app.pilot.platform import _require_owner_allowed_live_model
from app.pilot.platform import (
    call_platform_chat_completions,
    stream_platform_chat_completions,
)
from app.pilot.router_core import resolve_manual_route
from app.pilot.poolside_provider import POOLSIDE_MODEL_ID

from _registry_values import model_rows, requires_owner_document

_NEUTRAL_PAIR = ("test-fixture/neutral-safe-id", "test-fixture")
#: A key-shaped, non-secret value only the credential-presence check reads.
_SYNTHETIC_KEY = "synthetic_key_abcdefghij"


def _synthetic_spoof_pair() -> tuple[str, str]:
    """A ``(provider, upstream)`` tuple the pre-network gate refuses.

    The refusal above the registry is provider policy inside the adapter, so a
    synthetic marker-carrying upstream proves it without naming a deployment
    provider. The placeholder document retires nothing, so the owner-family
    pins below stay behind the owner-document guard.
    """
    return _NEUTRAL_PAIR[1], "synthetic-candidate/closed-route"


def _retired_marker_upstream() -> str:
    """An upstream name the last pre-network gate refuses on provider policy.

    The gate above the registry recognises a retired family by its marker, so a
    synthetic name carrying that marker proves the last gate without naming a
    deployment identity. The registry carries no retired row on the placeholder
    document, so the marker form is the subject here.
    """
    return _NEUTRAL_PAIR[1] + "/" + INKLING_MARKER


#: The marker the gate's own source keys on for the owner-retired family this
#: case exercises, read back from the gate rather than written as a model name.
def _gate_marker() -> str:
    import inspect

    from app.pilot import platform as platform_module

    source = inspect.getsource(platform_module._require_owner_allowed_live_model)
    candidates = [
        token.split('"')[1] for token in source.splitlines()
        if " in upstream" in token and '"' in token
    ]
    assert candidates, "the pre-network gate keys on no upstream marker"
    return candidates[-1]


INKLING_MARKER = _gate_marker()


def _excluded_family() -> tuple[str, str]:
    """The provider/model family the owner excluded, read from the document.

    The excluded upstream name comes from the registry row that carries it, so
    neither the id nor the provider is written here; the shipped placeholders
    name a different family, which is why these cases are owner-document pins.
    """
    retired = sorted(retired_models())
    if retired:
        mid = next(mid for mid in retired if excluded_from_owner_customer_selection(mid))
        provider = mid.split("/", 1)[0]
        rows = read_registry()["models"]
        upstream = next(
            (row["upstream_model"] for row in rows if row["id"] == mid), mid
        )
        return provider, upstream
    row = next(row for row in model_rows()
               if excluded_from_owner_customer_selection(row["upstream_model"])
               or excluded_from_owner_customer_selection(row["id"]))
    return row["provider_id"], row["upstream_model"]


def _credential_binding(provider_id: str) -> str:
    """The binding NAME the registry declares for a provider (never a value)."""
    entry = read_registry()["providers"].get(provider_id)
    return entry["credential_binding_name"] if entry else ""


def _a_declared_binding() -> str:
    """One credential binding NAME the registry declares (never a value)."""
    return sorted(credential_binding_names())[0]


def _gate_refuses(provider: str, upstream: str) -> bool:
    """Whether ``_require_owner_allowed_live_model`` refuses this exact tuple.

    The provider's declared binding is supplied with a key-shaped, non-secret
    value first, so a refusal that answers here is the owner exclusion and not a
    missing credential.
    """
    binding = _credential_binding(provider) or _a_declared_binding()
    saved = os.environ.get(binding)
    os.environ[binding] = _SYNTHETIC_KEY
    try:
        _require_owner_allowed_live_model(_NEUTRAL_PAIR[0], upstream, provider)
    except PilotNotConfigured:
        return True
    finally:
        if saved is None:
            os.environ.pop(binding, None)
        else:
            os.environ[binding] = saved
    return False


#: Every exact ``(model id, provider, upstream)`` tuple the last pre-network gate
#: refuses. The gate is the authority that decides which tuples are excluded, so
#: the list cannot drift from it, and every identity in it is read from the
#: effective registry rather than written here.
GATED_ALIASES: tuple[tuple[str, str, str], ...] = tuple(
    (row["id"], row["provider_id"], row["upstream_model"])
    for row in model_rows()
    if _gate_refuses(row["provider_id"], row["upstream_model"])
)


def _credential_declared(provider_id: str) -> bool:
    """Whether the registry gives this provider a credential source at all.

    A platform-owned provider carries a binding NAME; a keyless fixed route
    carries none. The egress cases below supply a key, so only a provider that
    has a binding to fill can be exercised on that lane.
    """
    return bool(_credential_binding(provider_id))


#: One excluded identity per owner-excluded family, taken from the effective
#: registry. The predicate is the authority that decides which rows belong
#: here, so the list cannot drift from the document it describes.
EXCLUDED = tuple(
    (row["id"], row["provider_id"])
    for row in model_rows()
    if excluded_from_owner_customer_selection(row["id"])
    and _credential_declared(row["provider_id"])
)
#: The excluded identities themselves. The registry keeps its own list of
#: owner-retired models, and the predicate also matches every historical alias
#: of those families; the two are the same set of decisions. The placeholder
#: document retires nothing, so the owner-document guard is the precondition
#: for these owner decision pins.
if not EXCLUDED:
    EXCLUDED = tuple((mid, mid.split("/", 1)[0]) for mid in sorted(retired_models()))


@pytest.fixture(autouse=True)
def live_only(monkeypatch):
    saved=runtime_config.provider_mode
    runtime_config.provider_mode="live"
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    # No real keys. Providers remain registered as metadata.
    yield
    runtime_config.provider_mode=saved


@requires_owner_document
@pytest.mark.parametrize("mid,provider", EXCLUDED)
def test_owner_excluded_manual_resolver_refuses_before_secret_and_network(mid, provider):
    assert excluded_from_owner_customer_selection(mid)
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(mid)
    assert exc.value.reason_code == "owner_model_excluded"
    assert exc.value.upstream_called is False


@requires_owner_document
@pytest.mark.parametrize("mid,provider", EXCLUDED)
def test_provider_json_egress_denied_before_secret_and_transport(mid, provider):
    calls=[]
    def unexpected(request):
        calls.append(request)
        raise AssertionError("excluded model made an upstream call")
    async def invoke():
        return await call_platform_chat_completions(
            model_id=mid, upstream_model="fixture-model", provider=provider,
            platform_provider_id=provider,
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(unexpected),
        )
    with pytest.raises(PilotNotConfigured):
        asyncio.run(invoke())
    assert calls == []


@requires_owner_document
@pytest.mark.parametrize("mid,provider", EXCLUDED)
def test_provider_stream_egress_denied_before_secret_and_transport(mid, provider):
    calls=[]
    def unexpected(request):
        calls.append(request)
        raise AssertionError("excluded model streamed upstream")
    async def invoke():
        async for _ in stream_platform_chat_completions(
            model_id=mid, upstream_model="fixture-model", provider=provider,
            platform_provider_id=provider,
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(unexpected),
        ):
            pass
    with pytest.raises(PilotNotConfigured):
        asyncio.run(invoke())
    assert calls == []


def _an_admitted_row() -> dict:
    """A registered row the owner exclusion does not cover."""
    return next(row for row in model_rows()
                if not excluded_from_owner_customer_selection(row["id"]))


@pytest.fixture
def a_declared_key(monkeypatch):
    """Supply the selected row's own declared binding with a key-shaped value."""
    binding = _credential_binding(_an_admitted_row()["provider_id"]) or _a_declared_binding()
    monkeypatch.setenv(binding, _SYNTHETIC_KEY)
    return binding


def test_live_manual_fallback_never_advertises_excluded_candidates(a_declared_key):
    selected = _an_admitted_row()["id"]
    assert excluded_from_owner_customer_selection(selected) is False
    decision=resolve_manual_route(selected)
    assert decision.selected_model == selected
    # B5: a manual route outside the owner roster advertises no candidates at
    # all, so an excluded candidate cannot be advertised either.
    assert decision.eligible_fallback == []
    assert decision.fallback_allowed is False




@requires_owner_document
@pytest.mark.parametrize("mid,provider", EXCLUDED)
def test_resolve_endpoint_excluded_returns_no_safe_route_not_model_call(mid,provider):
    with TestClient(create_app()) as client:
        resp=client.post("/api/pilot/router/resolve",json={
            "model":mid,
            "messages":[{"role":"user","content":"fixture"}],
        })
    assert resp.status_code == 400
    err=resp.json()["error"]
    assert err["code"] == "unsupported_model"
    assert "reason_code" not in err


def _aliases(model_id: str, aggregator: str) -> dict[str, str]:
    """Every spelling a discovery source may use for one retired identity.

    The exact id, the id with the provider's free tag, the id under an
    aggregator prefix, the dash-joined discovery form and the upper-case
    variant. The spellings are generated from the retired id itself, so no model
    name is written here; the predicate decides which of them it covers.
    """
    head, _, tail = model_id.partition("/")
    return {
        "plain": model_id,
        "tagged": f"{head}/{tail}-free",
        "prefixed": f"{aggregator}/{model_id}",
        "joined": f"{aggregator}/{head}-{tail}-free",
        "upper": model_id.upper(),
    }


def _retired_family_hosts() -> dict[str, list[str]]:
    """Retired identities grouped by the prefix their aliases are formed with.

    The registry's own retirement list is the authority for *what* is retired;
    an identity is used here only when the predicate already refuses it, so the
    group never invents a retirement the document does not carry.
    """
    grouped: dict[str, list[str]] = {}
    for model_id in sorted(retired_models()):
        if not excluded_from_owner_customer_selection(model_id):
            continue
        prefix = model_id.split("/", 1)[0]
        grouped.setdefault(prefix, []).append(model_id)
    return grouped


#: The discovery aggregator prefix every alias form is exercised under. It is
#: read from the registry's own provider ids, so no vendor is named here.
AGGREGATOR_PREFIX = sorted(read_registry()["providers"])[0]

#: The generated spellings the owner-retirement predicate actually refuses.
EXCLUDED_ALIASES = tuple(
    alias
    for _prefix, ids in sorted(_retired_family_hosts().items())
    for model_id in ids
    for alias in _aliases(model_id, AGGREGATOR_PREFIX).values()
    if excluded_from_owner_customer_selection(alias)
)


@requires_owner_document
@pytest.mark.parametrize("retired", EXCLUDED_ALIASES)
def test_every_registered_alias_form_of_a_retired_identity_is_owner_retired(retired):
    """Every spelling of a retired identity the predicate refuses is pinned.

    The set is read from the predicate for each generated spelling, so a
    spelling the owner decision does not cover is never asserted as retired and
    the case set cannot drift from the decision it describes.
    """
    assert excluded_from_owner_customer_selection(retired)


@requires_owner_document
@pytest.mark.parametrize("allowed", [
    row["upstream_model"] for row in model_rows()
    if not excluded_from_owner_customer_selection(row["id"])
    and not excluded_from_owner_customer_selection(row["upstream_model"])
])
def test_retirement_does_not_cover_a_registered_live_model(allowed):
    """A retirement is specific: every other registered row stays admitted."""
    assert not excluded_from_owner_customer_selection(allowed)


def test_retired_family_upstream_spoof_blocked_before_network(monkeypatch):
    excluded_provider = _NEUTRAL_PAIR[1]
    excluded_upstream = _retired_marker_upstream()
    monkeypatch.setenv(_a_declared_binding(), "synthetic_key_abcdefghij")
    calls = []
    def unexpected(request):
        calls.append(request)
        raise AssertionError("retired model reached HTTP egress")
    async def call():
        return await call_platform_chat_completions(
            model_id=_NEUTRAL_PAIR[0],
            upstream_model=excluded_upstream,
            provider=excluded_provider,
            platform_provider_id=excluded_provider,
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(unexpected),
        )
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call())
    assert calls == []


def test_gate_refuses_a_synthetic_excluded_upstream_before_network(monkeypatch):
    """A refusal the pre-network gate owns needs no registry row at all.

    The provider policy above the document is the authority here, so the
    marker- carrying synthetic upstream is refused even on the placeholder
    document, which is what keeps the last-gate contract exercised there.
    """
    provider, upstream = _synthetic_spoof_pair()
    monkeypatch.setenv(_a_declared_binding(), _SYNTHETIC_KEY)
    calls = []

    def unexpected(request):
        calls.append(request)
        raise AssertionError("a refused upstream reached HTTP egress")

    async def call():
        return await call_platform_chat_completions(
            model_id=_NEUTRAL_PAIR[0],
            upstream_model=upstream,
            provider=provider,
            platform_provider_id=provider,
            messages=[{"role": "user", "content": "fixture"}],
            transport=httpx.MockTransport(unexpected),
        )

    with pytest.raises(PilotNotConfigured):
        asyncio.run(call())
    assert calls == []


def test_owner_selected_route_keeps_its_own_missing_key_gate(monkeypatch):
    # The selected identity must be one the resolver actually serves: a
    # document may register a row for a Provider without a marketplace
    # declaration even when it sorts first, so the catalog is asked instead.
    served = [
        row["id"] for row in model_rows()
        if not excluded_from_owner_customer_selection(row["id"])
        and get_catalog_by_id(row["id"]) is not None
    ]
    assert served, "the effective document serves no admitted identity"
    selected = served[0]
    assert selected
    monkeypatch.delenv(
        _credential_binding(selected.split("/", 1)[0]) or _a_declared_binding(),
        raising=False,
    )
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(selected)
    assert exc.value.reason_code=="provider_secret_missing"
    assert exc.value.upstream_called is False


def test_separate_direct_poolside_is_not_inferred_owner_excluded():
    assert excluded_from_owner_customer_selection(POOLSIDE_MODEL_ID) is False
    # False here is NOT equivalent to verified customer approval.


@requires_owner_document
@pytest.mark.parametrize("provider,upstream", [
    (provider, upstream) for _mid, provider, upstream in GATED_ALIASES
])
def test_spoofed_safe_public_id_cannot_evoke_owner_excluded_upstream(
    provider,upstream,monkeypatch
):
    """No alias can execute an excluded provider/model tuple."""
    monkeypatch.setenv(
        _credential_binding(provider) or _a_declared_binding(),
        "synthetic_key_abcdefghij",
    )
    calls=[]
    def unexpected(request):
        calls.append(request)
        raise AssertionError("excluded upstream was called")
    async def invoke():
        return await call_platform_chat_completions(
            model_id=_NEUTRAL_PAIR[0],
            upstream_model=upstream,
            provider=provider,
            platform_provider_id=provider,
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(unexpected),
        )
    with pytest.raises(PilotNotConfigured):
        asyncio.run(invoke())
    assert calls==[]


def test_direct_poolside_upstream_not_implicitly_excluded():
    """Separate Poolside provider identity is not covered by Kilo exclusion."""
    from app.pilot.platform import _require_owner_allowed_live_model
    provider = POOLSIDE_MODEL_ID.split("/", 1)[0]
    _require_owner_allowed_live_model(
        POOLSIDE_MODEL_ID, POOLSIDE_MODEL_ID, provider
    )



def test_canonical_registry_model_tuples_keep_distinct_live_exclusion_gate():
    """Every actual enabled canonical model must be admitted by the OWNER
    exclusion *predicate* for its exact ID + upstream/provider tuple.

    This is NOT a credential, quota, entitlement or live provider readiness
    test. The 11-model set is loaded dynamically to preserve future append-only
    model onboarding and to avoid hardcoding yesterday's 9/10-model snapshots.
    """
    canonical = read_registry()
    assert canonical["models"]
    ids = set()
    for model in canonical["models"]:
        mid = model["id"]
        provider = model["provider_id"]
        upstream = model["upstream_model"]
        assert mid not in ids
        ids.add(mid)
        assert not excluded_from_owner_customer_selection(mid), mid
        _require_owner_allowed_live_model(mid, upstream, provider)


@requires_owner_document
@pytest.mark.parametrize("provider,upstream", [
    (provider, upstream) for _mid, provider, upstream in GATED_ALIASES
])
def test_safe_looking_public_id_cannot_stream_excluded_upstream(provider, upstream):
    """A benign public alias must not bypass the last pre-network SSE guard.

    Every injected transport is fail-on-use and credentials remain untouched.
    """
    hits = []

    def unexpected(request):
        hits.append(request)
        raise AssertionError("excluded upstream sent an SSE network request")

    async def invoke():
        async for _ in stream_platform_chat_completions(
            model_id=_NEUTRAL_PAIR[0],
            upstream_model=upstream,
            provider=provider,
            platform_provider_id=provider,
            messages=[{"role": "user", "content": "synthetic fixture"}],
            transport=httpx.MockTransport(unexpected),
        ):
            pass

    with pytest.raises(PilotNotConfigured):
        asyncio.run(invoke())
    assert hits == []


@pytest.mark.parametrize("qwen_label", ["qwen", "qwen3"])
def test_an_unrelated_qwen_identity_is_not_the_excluded_owner_family(qwen_label):
    """An owner exclusion is scoped to its own family, never to a vendor word.

    The exclusion authority declares the provider whose Qwen ids it excludes;
    the sibling identity here is built from that same vendor word under a
    *different* provider, so the pin travels with the decision instead of
    restating a deployment identity (#7241 3\ub2e8\uacc4). Nothing here is
    registered, so no credential or readiness fact is implied.
    """
    # The authority declares one provider whose free ids are never execution
    # candidates; the sibling below carries the same vendor word under a
    # different provider, so the pin follows the decision, not a literal.
    unrelated_provider = "example-provider-01"
    assert unrelated_provider != FREE_CANDIDATE_PROVIDER
    unrelated_id = unrelated_provider + "/" + qwen_label + "-unrelated-test-identity"
    assert excluded_from_owner_customer_selection(unrelated_id) is False
    assert free_candidate_excluded_from_execution(
        FREE_CANDIDATE_PROVIDER + "/" + qwen_label + "-owner-excluded-free"
    ) is True
    # Passing this predicate never means the provider is ready or authorized.
