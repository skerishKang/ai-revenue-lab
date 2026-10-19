"""Authenticated quote admission, using real quota and Core/dispatch adapters."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.b66_registered_model_boundary import (
    B14QuoteExactModelExecutor, B66ModelRouteError, B66RegisteredModelCompletion,
)
from app.dispatch_quota import DispatchAwareB14Client, DispatchAwareUsageCounterStore
from app.usage_gate import UsageGate
from test_b66_quote_execution_guards import Binding, MODEL
from test_b66_quote_runtime import SAVED_ID, USER_A, _Store, _settings
from test_b66_registered_model_boundary import FakeTrustedResolver, approved_route
from test_dispatch_quota_refund import RefundableMemoryStore


def client_for(*, binding=None, resolver=None, interpreter=None, **overrides):
    settings = _settings(
        runtime_mode="b14", live_enabled=True, b14_base_url="https://b14.internal",
        quota_salt="synthetic-b66-admission-salt-not-real-0001", user_burst_limit=1,
        user_daily_limit=10, global_daily_limit=10, **overrides,
    )
    store = RefundableMemoryStore()
    binding = binding if binding is not None else Binding()
    resolver = resolver if resolver is not None else FakeTrustedResolver(approved_route(model_id=MODEL))
    exact = DispatchAwareB14Client(settings, service_transport=binding, require_service_binding=True)
    if interpreter is None:
        interpreter = B66QuoteConversationInterpreter(B66RegisteredModelCompletion(
            resolver=resolver, executor=B14QuoteExactModelExecutor(exact),
        ))
    app = create_app(
        settings=settings, history_store=MagicMock(), b66_saved_quote_skill_store=_Store(),
        b66_quote_interpreter=interpreter,
    )
    app.state.usage_gate_enforced = True
    app.state.usage_gate = UsageGate(settings, DispatchAwareUsageCounterStore(store),
        clock=lambda: datetime(2026, 10, 8, tzinfo=timezone.utc))
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(SESSION_COOKIE, create_session_token(settings, USER_A),
        domain="chat.example.test", path="/")
    return client, store, resolver, binding


def post(client, **overrides):
    return client.post("/api/b66/quote/interpret", json={
        "saved_skill_id": SAVED_ID, "model_id": MODEL, "message": "SYNTHETIC PRIVATE QUOTE", **overrides,
    })


def assert_private(response):
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert "SYNTHETIC PRIVATE QUOTE" not in response.text
    assert "PRIVATE" not in str(response.headers)


def test_second_quote_denied_before_registry_or_provider_and_does_not_refund_first():
    client, store, resolver, binding = client_for()
    first = post(client)
    assert first.status_code == 200
    second = post(client)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert int(second.headers["Retry-After"]) > 0
    assert len(resolver.calls) == len(binding.calls) == 1
    assert sorted(store.counts.values()) == [1, 1, 1]
    assert store.bucket_refund_calls == 0
    assert_private(second)


@pytest.mark.parametrize("missing", ["gate", "store", "salt"])
def test_unavailable_admission_fails_closed_before_model_io(missing):
    client, store, resolver, binding = client_for()
    if missing == "gate":
        client.app.state.usage_gate = None
    elif missing == "store":
        client.app.state.usage_gate.store = None
    else:
        client.app.state.usage_gate.settings = replace(client.app.state.usage_gate.settings, quota_salt=None)
    response = post(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "live_abuse_gate_unavailable"
    assert resolver.calls == binding.calls == []
    assert store.counts == {}
    assert_private(response)


@pytest.mark.parametrize("invalid", ["message", "foreign_skill", "owner_field"])
def test_request_and_skill_validation_precede_quota_reservation(invalid):
    client, store, resolver, binding = client_for()
    payload = {"message": ""} if invalid == "message" else (
        {"saved_skill_id": "b66skill_" + "f" * 32} if invalid == "foreign_skill" else {"user_id": USER_A}
    )
    response = post(client, **payload)
    assert response.status_code in (400, 404)
    assert resolver.calls == binding.calls == []
    assert store.counts == {}


@pytest.mark.parametrize("code", ["runtime_unavailable", "selection_unavailable", "selection_ambiguous"])
def test_pre_dispatch_failure_refunds_only_its_own_reservation_once(code):
    class Rejected:
        async def interpret(self, **kwargs):
            raise B66ModelRouteError(code)
    client, store, resolver, binding = client_for(interpreter=Rejected())
    for _ in range(2):
        response = post(client)
        assert response.status_code == 503
        assert sorted(store.counts.values()) == [0, 0, 0]
        assert_private(response)
    assert store.bucket_refund_calls == 6
    assert resolver.calls == binding.calls == []
    if code == "runtime_unavailable":
        assert response.json()["error"]["code"] == "quote_runtime_unavailable"
        assert "X-B66-Model-Selection-Status" not in response.headers
    else:
        assert response.headers["X-B66-Model-Selection-Status"] == (
            "ambiguous" if code == "selection_ambiguous" else "unavailable"
        )


@pytest.mark.parametrize(("status", "upstream"), [(504, "upstream_timeout"), (503, "provider_server_error")])
def test_provider_failure_keeps_class_and_consumed_buckets_after_core_child_dispatch(status, upstream):
    client, store, resolver, binding = client_for(binding=Binding(status=status))
    response = post(client)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "quote_interpretation_failed"
    assert response.headers["X-B66-Upstream-Class"] == upstream
    assert "X-B66-Model-Selection-Status" not in response.headers
    assert len(resolver.calls) == len(binding.calls) == 1
    assert sorted(store.counts.values()) == [1, 1, 1]
    assert store.bucket_refund_calls == 0
    assert_private(response)


@pytest.mark.parametrize(("code", "upstream", "stage"), [
    ("provider_execution_failed", "upstream_error", "provider_execution"),
    ("provider_response_invalid", "malformed_upstream", "provider_response"),
    ("provider_route_mismatch", "malformed_upstream", "provider_response"),
])
def test_provider_boundary_errors_do_not_claim_selection_failure(code, upstream, stage):
    class Failed:
        async def interpret(self, **kwargs):
            raise B66ModelRouteError(code)
    client, _, _, _ = client_for(interpreter=Failed())
    response = post(client)
    assert response.status_code == 502
    assert response.headers["X-B66-Upstream-Class"] == upstream
    assert response.headers["X-B66-Interpret-Failure-Stage"] == stage
    assert "X-B66-Model-Selection-Status" not in response.headers
    assert_private(response)
