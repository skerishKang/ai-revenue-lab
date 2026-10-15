"""#4483 S3-A1: the final dispatch guard must keep provider POSTs at zero.

These tests exercise the guard through the real ``app.b14_client.B14Client``
dispatch boundaries (service-binding completion and streaming transport) with
synthetic providers only. A denial must surface as an existing
``ChatRuntimeError`` while the provider binding receives zero requests, and the
guard's ``last_decision`` keeps the precise negative code for the host/logs.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from padiem_control_plane.model_assignment_policy import (
    ModelChange,
    ModelPolicySnapshot,
)

from app.b14_client import B14Client, ChatRuntimeError
from app.central_model_final_dispatch_guard import (
    DENIAL_REASONS,
    DispatchSessionContext,
    FinalDispatchDenied,
    FinalDispatchGuard,
    GuardedHTTPTransport,
    GuardedServiceTransport,
)
from app.central_model_pre_dispatch_advice import (
    GLOBAL_WORKSPACE,
    VerifiedProductModelSelection,
)
from app.config import Settings

MODEL = "test-provider/model-a"
OTHER = "test-provider/model-b"
USER = "usr_" + "a" * 32
OTHER_USER = "usr_" + "b" * 32
URL = "https://b14.internal/quote"
MESSAGES = [{"role": "user", "content": "synthetic final dispatch guard"}]


class CanonicalPolicy:
    def __init__(self, rules=None, *, revision=1, failure=False):
        self.rules = tuple(rules if rules is not None else [
            ModelChange("central", "PRO", MODEL, "allow"),
            ModelChange("chat", "PRO", MODEL, "allow"),
        ])
        self.revision = revision
        self.failure = failure
        self.calls = []

    async def snapshot(self, workspace_id):
        self.calls.append(workspace_id)
        if self.failure:
            raise RuntimeError("D1 offline / signer unverifiable")
        return ModelPolicySnapshot(workspace_id, self.revision, self.rules)


class B14Catalog:
    def __init__(self, *, enabled=True, excluded=False, selectable=True, broken=False):
        self.enabled = enabled
        self.excluded = excluded
        self.selectable = selectable
        self.broken = broken
        self.registered_calls = 0
        self.selectable_calls = 0

    async def list_registered_models(self):
        self.registered_calls += 1
        if self.broken:
            return [{"model_id": MODEL, "owner_excluded": False}]
        return [
            {"model_id": MODEL, "b14_enabled": self.enabled,
             "owner_excluded": self.excluded, "capabilities": ["chat"]},
        ]

    async def list_selectable_models(self):
        self.selectable_calls += 1
        return [{"model_id": MODEL, "name": "Test"}] if self.selectable else []


class RecordingBinding:
    """Synthetic Worker service binding; counts every delegated provider POST."""

    def __init__(self, status=200, body=None, error=None):
        self.calls = []
        self.status = status
        self.error = error
        self.body = body if body is not None else json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "final-guard-answer"}}],
            "business14": {"route_mode": "manual", "selected_model": MODEL, "request_id": "req_1"},
        }).encode()

    async def post_json(self, url, payload):
        self.calls.append((url, payload))
        if self.error is not None:
            raise self.error
        return self.status, self.body


def sse_body(chunks=("안녕", "하세요")):
    frames = []
    for chunk in chunks:
        frames.append("data: " + json.dumps({
            "object": "chat.completion.chunk",
            "id": "resp_1",
            "model": MODEL,
            "business14": {"route_mode": "manual", "selected_model": MODEL},
            "choices": [{"delta": {"content": chunk}}],
        }) + "\n\n")
    frames.append("data: [DONE]\n\n")
    return "".join(frames).encode()


class RecordingSSETransport(httpx.AsyncBaseTransport):
    """Synthetic real-httpx transport for the Core streaming client."""

    def __init__(self, body=None, status=200, content_type="text/event-stream"):
        self.requests = []
        self.body = body if body is not None else sse_body()
        self.status = status
        self.content_type = content_type

    async def handle_async_request(self, request):
        body = await request.aread()
        self.requests.append((str(request.url), json.loads(body or b"{}")))
        return httpx.Response(
            self.status,
            headers={"content-type": self.content_type},
            content=self.body,
            request=request,
        )


def settings(**overrides):
    values = dict(runtime_mode="b14", b14_base_url="https://b14.internal", live_enabled=True)
    values.update(overrides)
    return Settings(**values)


def selection(*, product="chat", tier="PRO", model=MODEL, user=USER):
    return VerifiedProductModelSelection(
        canonical_user_id=user, workspace_id=GLOBAL_WORKSPACE,
        product_id=product, tier=tier, exact_model_id=model,
        authority_ref="canonical-product-session",
    )


def session(*, user=USER, workspace=GLOBAL_WORKSPACE, product="chat", tier="PRO", capability=True):
    return DispatchSessionContext(
        canonical_user_id=user, workspace_id=workspace,
        product_id=product, member_tier=tier,
        product_capability_verified=capability,
    )


def make_guard(*, selection_value=None, session_value=..., policy=..., catalog=..., revision=1, session_reader=...):
    if session_reader is ...:
        async def session_reader():
            return session() if session_value is ... else session_value
    return FinalDispatchGuard(
        selection=selection_value if selection_value is not None else selection(),
        current_session_reader=session_reader,
        store=CanonicalPolicy() if policy is ... else policy,
        b14_catalog_source=B14Catalog() if catalog is ... else catalog,
        authorized_revision=revision,
    )


def authorize(guard):
    return asyncio.run(guard.authorize())


def run_completion(client, model=MODEL):
    return asyncio.run(client.complete_registered_quote_model(MESSAGES, model=model))


async def collect_stream(client, model=MODEL):
    return [event async for event in client.stream_text_preview(MESSAGES, model=model)]


# --- guard decision unit tests -------------------------------------------------

def test_authorize_allows_only_exact_bound_authority():
    guard = make_guard()
    decision = authorize(guard)
    assert decision.allowed is True
    assert decision.reason == "allowed"
    assert decision.revision == 1
    assert decision.model_id == MODEL and decision.product_id == "chat" and decision.tier == "PRO"
    assert decision.enforcement == "final_dispatch_guard"
    assert guard.last_decision is decision


def test_missing_verified_selection_denies_without_policy_read():
    policy, catalog = CanonicalPolicy(), B14Catalog()
    guard = make_guard(selection_value=object(), policy=policy, catalog=catalog)
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == "missing_verified_selection"
    assert policy.calls == [] and catalog.registered_calls == 0 and catalog.selectable_calls == 0


def test_missing_session_authority_denies_without_policy_read():
    policy = CanonicalPolicy()
    guard = make_guard(session_value=None, policy=policy)
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == "missing_session_authority"
    assert policy.calls == []


@pytest.mark.parametrize(("session_value", "reason"), [
    (session(user=OTHER_USER), "user_binding_mismatch"),
    (session(workspace="site-42"), "workspace_binding_mismatch"),
    (session(product="b66"), "product_binding_mismatch"),
    (session(tier="FREE"), "tier_binding_mismatch"),
    (session(capability=False), "product_capability_unverified"),
])
def test_session_binding_mismatch_denies_before_any_policy_read(session_value, reason):
    policy, catalog = CanonicalPolicy(), B14Catalog()
    guard = make_guard(session_value=session_value, policy=policy, catalog=catalog)
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == reason
    assert policy.calls == [] and catalog.registered_calls == 0


def test_missing_authorized_revision_denies_without_policy_read():
    policy = CanonicalPolicy()
    guard = make_guard(policy=policy, revision=None)
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == "missing_authorized_revision"
    assert policy.calls == []


def test_revision_changed_after_earlier_advice_denies_cas_drift():
    policy = CanonicalPolicy(revision=2)
    guard = make_guard(policy=policy, revision=1)
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == "policy_revision_changed"
    assert decision.revision == 2


def test_policy_revision_changed_does_not_claim_session_revocation():
    policy = CanonicalPolicy(revision=7)
    guard = make_guard(policy=policy, revision=5)
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == "policy_revision_changed"
    assert decision.model_id == MODEL and decision.revision == 7


def test_stale_session_revision_never_becomes_fresh_again():
    policy = CanonicalPolicy(revision=3)
    guard = make_guard(policy=policy, revision=3)
    assert authorize(guard).allowed is True
    policy.revision = 4
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == "policy_revision_changed"


@pytest.mark.parametrize(("selection_value", "session_value", "policy", "catalog", "reason"), [
    (selection(), session(), CanonicalPolicy([
        ModelChange("central", "PRO", MODEL, "block"),
        ModelChange("chat", "PRO", MODEL, "allow"),
    ]), B14Catalog(), "central_blocked"),
    (selection(), session(), CanonicalPolicy([
        ModelChange("central", "PRO", MODEL, "allow"),
        ModelChange("chat", "PRO", MODEL, "block"),
    ]), B14Catalog(), "product_blocked"),
    (selection(tier="MAX"), session(tier="MAX"), CanonicalPolicy(), B14Catalog(), "central_unassigned"),
    (selection(product="b66"), session(product="b66"), CanonicalPolicy(), B14Catalog(), "product_unassigned"),
    (selection(), session(), CanonicalPolicy(), B14Catalog(enabled=False, selectable=False), "b14_model_offline"),
    (selection(), session(), CanonicalPolicy(), B14Catalog(excluded=True, selectable=False), "b14_owner_not_allowed"),
    (selection(), session(), CanonicalPolicy(), B14Catalog(broken=True), "b14_catalog_invalid"),
])
def test_policy_and_catalog_negatives_flow_through_as_denial_codes(
    selection_value, session_value, policy, catalog, reason
):
    guard = make_guard(
        selection_value=selection_value, session_value=session_value,
        policy=policy, catalog=catalog,
    )
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == reason


def test_unknown_retired_model_cannot_fallback_to_a_live_one():
    guard = make_guard(selection_value=selection(model=OTHER))
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == "b14_model_unknown"
    assert decision.model_id == OTHER


@pytest.mark.parametrize(("policy", "catalog", "reason"), [
    (CanonicalPolicy(failure=True), B14Catalog(), "model_policy_evaluation_unavailable"),
    (None, B14Catalog(), "model_policy_source_unavailable"),
    (CanonicalPolicy(), None, "model_policy_source_unavailable"),
])
def test_expired_or_missing_policy_source_blocks_without_honest_allow(policy, catalog, reason):
    guard = make_guard(policy=policy, catalog=catalog)
    decision = authorize(guard)
    assert decision.allowed is False and decision.reason == reason


def test_guard_native_codes_are_tracked_for_host_observability():
    assert "tier_binding_mismatch" in DENIAL_REASONS
    assert "policy_revision_changed" in DENIAL_REASONS
    assert "dispatch_model_mismatch" in DENIAL_REASONS


@pytest.mark.parametrize("bad", [
    {"canonical_user_id": "browser supplied"},
    {"workspace_id": "bad workspace"},
    {"product_id": "central"},
    {"member_tier": "owner"},
    {"product_capability_verified": 1},
])
def test_client_shaped_session_cannot_backfill_missing_authority(bad):
    values = dict(
        canonical_user_id=USER, workspace_id=GLOBAL_WORKSPACE,
        product_id="chat", member_tier="PRO", product_capability_verified=True,
    )
    values.update(bad)
    with pytest.raises(ValueError):
        DispatchSessionContext(**values)


def test_session_reader_missing_or_unavailable_blocks_before_policy_read():
    policy = CanonicalPolicy()
    assert authorize(make_guard(session_reader=None, policy=policy)).reason == "missing_session_authority"

    async def unavailable():
        raise RuntimeError("canonical server session reader unavailable")

    assert authorize(make_guard(session_reader=unavailable, policy=policy)).reason == "missing_session_authority"
    assert policy.calls == []


def test_revoked_session_with_unchanged_model_policy_never_reaches_provider():
    # Genuine distinction from policy-revision drift: model revision remains 1
    # while the authoritative session reader starts returning None.
    latest = {"value": session()}
    calls = []

    async def read_fresh_session():
        calls.append(True)
        return latest["value"]

    guard = make_guard(session_reader=read_fresh_session)
    assert authorize(guard).allowed is True
    latest["value"] = None  # trusted CP session authority reports revoked

    binding = RecordingBinding()
    client = B14Client(settings(), service_transport=guard.authorized_service_transport(binding))
    with pytest.raises(ChatRuntimeError):
        run_completion(client)
    assert binding.calls == []
    assert guard.last_decision.reason == "missing_session_authority"
    assert len(calls) >= 2


# --- transport wrappers --------------------------------------------------------

def test_denied_guard_blocks_before_service_transport_delegation():
    policy = CanonicalPolicy(revision=2)
    guard = make_guard(policy=policy, revision=1)
    binding = RecordingBinding()
    transport = guard.authorized_service_transport(binding)
    with pytest.raises(FinalDispatchDenied) as caught:
        asyncio.run(transport.post_json(URL, {"model": MODEL}))
    assert caught.value.reason == "policy_revision_changed"
    assert binding.calls == []
    assert guard.last_decision is not None and guard.last_decision.reason == "policy_revision_changed"


def test_service_transport_pins_the_exact_authorized_model():
    guard = make_guard()
    binding = RecordingBinding()
    transport = guard.authorized_service_transport(binding)
    assert isinstance(transport, GuardedServiceTransport)
    for payload in ({"model": OTHER}, {"not_model": MODEL}, {}):
        with pytest.raises(FinalDispatchDenied) as caught:
            asyncio.run(transport.post_json(URL, payload))
        assert caught.value.reason == "dispatch_model_mismatch"
    assert binding.calls == []
    payload = {"model": MODEL}
    status, _ = asyncio.run(transport.post_json(URL, payload))
    assert status == 200
    assert len(binding.calls) == 1 and binding.calls[0][1] is payload


def test_transport_wrappers_require_real_bindings():
    guard = make_guard()
    with pytest.raises(ValueError, match="service_transport_binding_required"):
        guard.authorized_service_transport(object())
    with pytest.raises(ValueError, match="http_transport_binding_required"):
        guard.authorized_http_transport(object())


def test_guarded_http_transport_denies_without_inner_request():
    guard = make_guard()
    inner = RecordingSSETransport()
    wrapper = guard.authorized_http_transport(inner)
    assert isinstance(wrapper, GuardedHTTPTransport)
    request = httpx.Request("POST", URL, json={"model": OTHER})
    with pytest.raises(FinalDispatchDenied) as caught:
        asyncio.run(wrapper.handle_async_request(request))
    assert caught.value.reason == "dispatch_model_mismatch"
    assert inner.requests == []


def test_guarded_http_transport_delegates_intact_body_once_allowed():
    guard = make_guard()
    inner = RecordingSSETransport()
    wrapper = guard.authorized_http_transport(inner)
    request = httpx.Request("POST", URL, json={"model": MODEL})
    response = asyncio.run(wrapper.handle_async_request(request))
    assert response.status_code == 200
    assert len(inner.requests) == 1
    assert inner.requests[0][1] == {"model": MODEL}


def test_guarded_http_transport_rejects_unparseable_body():
    guard = make_guard()
    inner = RecordingSSETransport()
    wrapper = guard.authorized_http_transport(inner)
    request = httpx.Request("POST", URL, content=b"{not json")
    with pytest.raises(FinalDispatchDenied) as caught:
        asyncio.run(wrapper.handle_async_request(request))
    assert caught.value.reason == "dispatch_model_mismatch"
    assert inner.requests == []


# --- real B14Client dispatch boundaries (synthetic provider only) ---------------

def test_completion_allowed_posts_exactly_once_with_the_authorized_model():
    guard = make_guard()
    binding = RecordingBinding()
    client = B14Client(settings(), service_transport=guard.authorized_service_transport(binding))
    result = run_completion(client)
    assert result["answer"] == "final-guard-answer"
    assert result["route"]["mode"] == "manual"
    assert len(binding.calls) == 1
    assert binding.calls[0][1]["model"] == MODEL


@pytest.mark.parametrize(("guard", "model", "reason"), [
    (make_guard(session_value=None), MODEL, "missing_session_authority"),
    (make_guard(session_value=session(tier="FREE")), MODEL, "tier_binding_mismatch"),
    (make_guard(session_value=session(capability=False)), MODEL, "product_capability_unverified"),
    (make_guard(policy=CanonicalPolicy(revision=2), revision=1), MODEL, "policy_revision_changed"),
    (make_guard(policy=CanonicalPolicy(failure=True)), MODEL, "model_policy_evaluation_unavailable"),
    (make_guard(selection_value=selection(model=OTHER), catalog=B14Catalog()), MODEL, "b14_model_unknown"),
    (make_guard(), OTHER, "dispatch_model_mismatch"),
])
def test_completion_denials_never_reach_the_provider(guard, model, reason):
    binding = RecordingBinding()
    client = B14Client(settings(), service_transport=guard.authorized_service_transport(binding))
    with pytest.raises(ChatRuntimeError) as caught:
        run_completion(client, model=model)
    assert caught.value.code == "upstream_unavailable"
    assert binding.calls == []
    assert guard.last_decision is not None and guard.last_decision.reason == reason


def test_stream_allowed_yields_answer_with_one_guarded_request():
    guard = make_guard()
    inner = RecordingSSETransport()
    client = B14Client(settings(), stream_transport=guard.authorized_http_transport(inner))
    events = asyncio.run(collect_stream(client))
    assert "".join(e.delta_content or "" for e in events) == "안녕하세요"
    assert events[-1].done is True
    assert len(inner.requests) == 1
    payload = inner.requests[0][1]
    assert payload["model"] == MODEL and payload["stream"] is True


@pytest.mark.parametrize(("guard", "model", "reason"), [
    (make_guard(policy=CanonicalPolicy(revision=2), revision=1), MODEL, "policy_revision_changed"),
    (make_guard(session_value=session(tier="FREE")), MODEL, "tier_binding_mismatch"),
    (make_guard(), OTHER, "dispatch_model_mismatch"),
])
def test_stream_denials_make_zero_requests(guard, model, reason):
    inner = RecordingSSETransport()
    client = B14Client(settings(), stream_transport=guard.authorized_http_transport(inner))

    async def run():
        with pytest.raises(ChatRuntimeError) as caught:
            async for _ in client.stream_text_preview(MESSAGES, model=model):
                pass
        return caught.value

    error = asyncio.run(run())
    assert error.code == "upstream_execution_failed"
    assert inner.requests == []
    assert guard.last_decision is not None and guard.last_decision.reason == reason


def test_differential_without_the_guard_the_same_context_reaches_the_provider():
    # Same drifted-revision context as the denial tests: the provider POST that
    # the guard blocks does reach the synthetic provider when the guard is not
    # composed, proving the interception (not an unrelated failure) is the
    # thing keeping NEGATIVE_PROVIDER_POSTS at zero.
    binding = RecordingBinding()
    client = B14Client(settings(), service_transport=binding)
    result = run_completion(client)
    assert result["answer"] == "final-guard-answer"
    assert len(binding.calls) == 1
