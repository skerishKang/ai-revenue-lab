"""Tests for Engine trusted execution admission gate helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.execution_admission import (
    ExecutionAdmissionError,
    ExecutionAdmissionRequest,
    TrustedExecutionAdmission,
)
from app.execution_admission_gate import resolve_and_require_trusted_admission


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def request(**overrides):
    values = {
        "app_id": "b62",
        "subject_id": "subject:owner",
        "capability": "orchestration.run",
        "trace_id": "tr_gate",
        "request_fingerprint": "fp_gate",
    }
    values.update(overrides)
    return ExecutionAdmissionRequest(**values)


def admission(**overrides):
    values = {
        "decision_id": "adm_gate_1",
        "app_id": "b62",
        "subject_id": "subject:owner",
        "capability": "orchestration.run",
        "allowed": True,
        "authority_ref": "control-plane:entitlement:rev1",
        "policy_revision": "policy:rev1",
        "issued_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=5),
        "request_fingerprint": "fp_gate",
    }
    values.update(overrides)
    return TrustedExecutionAdmission(**values)


class Adapter:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def resolve_admission(self, req):
        self.calls.append(req)
        return self.value


class AsyncAdapter(Adapter):
    async def resolve_admission(self, req):
        self.calls.append(req)
        return self.value


class ExplodingAdapter:
    def resolve_admission(self, req):
        raise RuntimeError("backend unavailable")


def run(coro):
    return asyncio.run(coro)


def test_gate_allows_valid_trusted_sync_admission() -> None:
    req = request()
    adapter = Adapter(admission())

    resolved = run(resolve_and_require_trusted_admission(adapter=adapter, request=req, now=NOW))

    assert resolved.decision_id == "adm_gate_1"
    assert adapter.calls == [req]


def test_gate_allows_valid_trusted_async_admission() -> None:
    req = request()
    adapter = AsyncAdapter(admission())

    resolved = run(resolve_and_require_trusted_admission(adapter=adapter, request=req, now=NOW))

    assert resolved.decision_id == "adm_gate_1"
    assert adapter.calls == [req]


@pytest.mark.parametrize("adapter", [None, object(), ExplodingAdapter()])
def test_gate_fails_closed_when_trusted_authority_unavailable(adapter) -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(resolve_and_require_trusted_admission(adapter=adapter, request=request(), now=NOW))

    assert excinfo.value.code == "entitlement_unavailable"
    assert excinfo.value.status_code == 503


def test_gate_rejects_client_shaped_allow_object() -> None:
    class ClientAssertionAdapter:
        def resolve_admission(self, req):
            return {
                "allow": True,
                "plan": "pro",
                "credit_balance": 999999,
                "entitlement": {"self_asserted": True},
            }

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(resolve_and_require_trusted_admission(adapter=ClientAssertionAdapter(), request=request(), now=NOW))

    assert excinfo.value.code == "missing_entitlement"
    assert excinfo.value.status_code == 403


@pytest.mark.parametrize(
    ("trusted", "code"),
    [
        (admission(allowed=False), "entitlement_denied"),
        (admission(expires_at=NOW), "entitlement_expired"),
        (admission(issued_at=NOW + timedelta(seconds=1), expires_at=NOW + timedelta(minutes=5)), "invalid_admission"),
        (admission(app_id="b14"), "entitlement_app_mismatch"),
        (admission(subject_id="subject:other"), "entitlement_subject_mismatch"),
        (admission(capability="orchestration.resume"), "entitlement_capability_mismatch"),
        (admission(request_fingerprint="fp_other"), "entitlement_request_mismatch"),
    ],
)
def test_gate_preserves_contract_fail_closed_mismatches(trusted, code) -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(resolve_and_require_trusted_admission(adapter=Adapter(trusted), request=request(), now=NOW))

    assert excinfo.value.code == code


def test_gate_does_not_fallback_to_service_identity_or_credit_assertion() -> None:
    class ServiceIdentityOnlyAdapter:
        def resolve_admission(self, req):
            return {
                "service_identity": "service:b62-worker",
                "app_authenticated": True,
                "credit_balance": 1,
            }

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(resolve_and_require_trusted_admission(adapter=ServiceIdentityOnlyAdapter(), request=request(), now=NOW))

    assert excinfo.value.code == "missing_entitlement"
