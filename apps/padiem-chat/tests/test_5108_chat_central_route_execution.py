"""#5108: a centrally applied Chat route must reach the real Chat dispatch.

An administrator applies `chat/<grade>` through the signed Preview->Apply
route contract. The stored route is validated against the live B14 catalog
(registered + live-ready) at apply time, so it never widens the product model
set. Before this fix the Chat pre-dispatch executability gate only knew the
STATIC shared tier declaration, so an applied route to any other live-ready
model was refused with ``model_profile_unassigned`` and the administrator's
applied decision never reached a real Chat request.

These cases keep the gate fail-closed for every model that is neither the
declared tier route nor the route applied to the bound grade.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import Settings
from app.dispatch_quota import DispatchAwareB14Client
from app.model_policy import (
    current_request_route_model,
    current_request_tier_id,
    model_policy_is_executable,
    model_policy_is_request_executable,
    request_tier_context,
    resolve_request_model_policy,
)

ROUTED_MODEL = "opencode-go/muse-spark-1.2-contributor"
DECLARED_MODEL = "opencode-go/muse-spark-1.3-contributor"
NOT_A_ROUTE = "opencode-go/not-a-product-route"


def _run(coro):
    return asyncio.run(coro)


def _live_quota_client():
    return DispatchAwareB14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal", live_enabled=True),
        stream_transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        require_service_binding=True,
    )


def test_the_applied_route_model_is_executable_for_the_bound_grade():
    """A model the administrator applied to this grade reaches B14."""
    messages = [{"role": "user", "content": "안녕하세요"}]
    with request_tier_context("plus", model_id=ROUTED_MODEL):
        assert current_request_route_model() == ROUTED_MODEL
        assert current_request_tier_id() == "plus"
        assert resolve_request_model_policy(messages).model_id == ROUTED_MODEL
        assert model_policy_is_request_executable(ROUTED_MODEL) is True
    assert current_request_route_model() is None


def test_the_applied_route_model_is_not_executable_without_a_bound_grade():
    """The route model never becomes a global executable model."""
    assert model_policy_is_executable(ROUTED_MODEL) is False
    assert model_policy_is_request_executable(ROUTED_MODEL) is False


def test_the_route_model_does_not_leak_into_another_grade():
    """A route bound to one grade never authorizes another grade's request."""
    messages = [{"role": "user", "content": "안녕하세요"}]
    with request_tier_context("plus", model_id=ROUTED_MODEL):
        with request_tier_context("pro"):
            assert current_request_route_model() is None
            assert model_policy_is_request_executable(ROUTED_MODEL) is False


def test_dispatch_quota_accepts_the_applied_route_model():
    """The live pre-dispatch gate must not refund a routed dispatch."""
    client = _live_quota_client()
    messages = [{"role": "user", "content": "안녕하세요"}]
    with request_tier_context("plus", model_id=ROUTED_MODEL):
        assert _run(client._reject_non_executable_policy(messages)) is None
        assert resolve_request_model_policy(messages).model_id == ROUTED_MODEL


def test_dispatch_quota_still_rejects_a_model_that_is_neither_declared_nor_routed(
    monkeypatch,
):
    """The gate stays fail-closed for every unrelated model."""
    from app import dispatch_quota
    from app.b14_client import ChatRuntimeError

    client = _live_quota_client()
    monkeypatch.setattr(
        dispatch_quota,
        "_resolve_b62_policy",
        lambda *args, **kwargs: type(
            "P", (), {"model_id": NOT_A_ROUTE}
        )(),
    )
    with request_tier_context("plus", model_id=ROUTED_MODEL):
        try:
            _run(client._reject_non_executable_policy([{"role": "user", "content": "x"}]))
        except ChatRuntimeError as exc:
            assert exc.code == "model_profile_unassigned"
        else:
            raise AssertionError("a model outside every route must stay rejected")


def test_tier_identity_client_accepts_the_applied_route_model():
    """The identity client gate honours the same request-scoped route."""
    from app import tier_identity_client as tier_identity_module

    client = tier_identity_module.PadiemTierB14Client.__new__(
        tier_identity_module.PadiemTierB14Client
    )
    client.settings = Settings(
        runtime_mode="b14", b14_base_url="https://b14.internal", live_enabled=True
    )
    messages = [{"role": "user", "content": "안녕하세요"}]
    with request_tier_context("plus", model_id=ROUTED_MODEL):
        policy = resolve_request_model_policy(messages)
        assert policy.model_id == ROUTED_MODEL
        assert tier_identity_module._verified_admin_exact_dispatch(policy.model_id) is False
        assert model_policy_is_request_executable(policy.model_id) is True
        assert client is not None


def test_the_declared_tier_route_stays_executable_without_any_route():
    """The existing product-tier contract is unchanged."""
    assert model_policy_is_executable(DECLARED_MODEL) is True
    assert model_policy_is_request_executable(DECLARED_MODEL) is True
