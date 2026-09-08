"""Tests for Engine Control Plane tenant/entitlement admission (#1751 E7)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.execution_admission import (
    ExecutionAdmissionError,
    ExecutionAdmissionRequest,
    TrustedExecutionAdmission,
)
from app.execution_admission_gate import resolve_and_require_trusted_admission
from app.tenant_auth import (
    ControlPlaneTenantAdmissionAdapter,
    UsageReceipt,
    build_control_plane_admission_adapter,
    identify_tenant,
)

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def iso(value: datetime) -> str:
    return value.isoformat()


def snapshot_dict(**overrides):
    values = {
        "snapshot_id": "snap-e7-1",
        "product_id": "b62",
        "subject": {"subject_type": "user", "subject_id": "subject:owner"},
        "revision": "policy-rev-7",
        "issued_at": iso(NOW - timedelta(minutes=1)),
        "expires_at": iso(NOW + timedelta(minutes=30)),
        "grants": [
            {"key": "orchestration.run", "allowed": True, "limit": None},
        ],
    }
    values.update(overrides)
    return values


def reservation_dict(**overrides):
    values = {
        "reservation_ref": "res-e7-1",
        "admitted": True,
        "expires_at": iso(NOW + timedelta(minutes=5)),
    }
    values.update(overrides)
    return values


class FakeControlPlaneClient:
    """Recording Control Plane authority double with CP-shaped payloads."""

    def __init__(self, *, snapshot=None, reservation=None, receipt_ack=None):
        self.snapshot = snapshot if snapshot is not None else snapshot_dict()
        self.reservation = reservation if reservation is not None else reservation_dict()
        self.receipt_ack = receipt_ack
        self.calls: list[tuple[str, dict]] = []

    def fetch_entitlement_snapshot(self, *, product_id, subject):
        self.calls.append(("fetch_entitlement_snapshot", {"product_id": product_id, "subject": dict(subject)}))
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot

    def reserve_usage(self, *, reservation):
        self.calls.append(("reserve_usage", dict(reservation)))
        if isinstance(self.reservation, Exception):
            raise self.reservation
        return self.reservation

    def record_usage(self, *, usage_event):
        self.calls.append(("record_usage", dict(usage_event)))
        return self.receipt_ack


class AsyncFakeControlPlaneClient(FakeControlPlaneClient):
    async def fetch_entitlement_snapshot(self, *, product_id, subject):
        return super().fetch_entitlement_snapshot(product_id=product_id, subject=subject)

    async def reserve_usage(self, *, reservation):
        return super().reserve_usage(reservation=reservation)


def run(coro):
    return asyncio.run(coro)


def adapter(client, **kwargs):
    kwargs.setdefault("clock", lambda: NOW)
    return ControlPlaneTenantAdmissionAdapter(client=client, **kwargs)


def request(**overrides):
    values = {
        "app_id": "b62",
        "subject_id": "subject:owner",
        "capability": "orchestration.run",
        "trace_id": "tr-e7",
        "request_fingerprint": "fp-e7-1",
    }
    values.update(overrides)
    return ExecutionAdmissionRequest(**values)


def receipt(**overrides):
    values = {
        "event_id": "evt-e7-1",
        "idempotency_key": "idem-evt-e7-1",
        "billing_semantic_id": "orchestration.run",
        "product_id": "b62",
        "subject": {"subject_type": "user", "subject_id": "subject:owner"},
        "execution_id": "exec-e7-1",
        "outcome": "succeeded",
        "billing_disposition": "billable",
        "occurred_at": NOW,
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    values.update(overrides)
    return UsageReceipt(**values)


def test_identify_tenant_maps_subject_to_user_subject() -> None:
    tenant = identify_tenant(request())

    assert tenant.product_id == "b62"
    assert tenant.subject_ref() == {"subject_type": "user", "subject_id": "subject:owner"}


def test_identify_tenant_maps_app_request_to_account_subject() -> None:
    tenant = identify_tenant(request(subject_id=None))

    assert tenant.subject_ref() == {"subject_type": "account", "subject_id": "b62"}


def test_adapter_issues_allowed_admission_with_reservation_binding() -> None:
    client = FakeControlPlaneClient()
    resolved = run(adapter(client).resolve_admission(request()))

    assert isinstance(resolved, TrustedExecutionAdmission)
    assert resolved.allowed is True
    assert resolved.app_id == "b62"
    assert resolved.subject_id == "subject:owner"
    assert resolved.capability == "orchestration.run"
    assert resolved.policy_revision == "policy-rev-7"
    assert "control-plane:entitlement:snap-e7-1@res-e7-1" == resolved.authority_ref
    assert resolved.request_fingerprint == "fp-e7-1"
    assert resolved.issued_at == NOW
    # Snapshot grants 30 minutes but adapter TTL caps the admission window.
    assert resolved.expires_at == NOW + timedelta(minutes=5)
    kinds = [kind for kind, _ in client.calls]
    assert kinds == ["fetch_entitlement_snapshot", "reserve_usage"]
    fetch_payload = client.calls[0][1]
    assert fetch_payload["product_id"] == "b62"
    assert fetch_payload["subject"] == {"subject_type": "user", "subject_id": "subject:owner"}


def test_adapter_supports_async_control_plane_client() -> None:
    client = AsyncFakeControlPlaneClient()
    resolved = run(adapter(client).resolve_admission(request()))

    assert resolved.allowed is True
    assert [kind for kind, _ in client.calls] == ["fetch_entitlement_snapshot", "reserve_usage"]


def test_adapter_denies_when_grant_is_absent() -> None:
    client = FakeControlPlaneClient(snapshot=snapshot_dict(grants=[]))
    resolved = run(adapter(client).resolve_admission(request()))

    assert resolved.allowed is False
    # No usage reservation is attempted for a denied capability.
    assert [kind for kind, _ in client.calls] == ["fetch_entitlement_snapshot"]


def test_adapter_denies_when_grant_is_denied() -> None:
    client = FakeControlPlaneClient(
        snapshot=snapshot_dict(grants=[{"key": "orchestration.run", "allowed": False, "limit": None}])
    )
    resolved = run(adapter(client).resolve_admission(request()))

    assert resolved.allowed is False


def test_adapter_denies_when_reservation_is_denied() -> None:
    client = FakeControlPlaneClient(reservation=reservation_dict(admitted=False))
    resolved = run(adapter(client).resolve_admission(request()))

    assert resolved.allowed is False
    assert [kind for kind, _ in client.calls] == ["fetch_entitlement_snapshot", "reserve_usage"]


def test_gate_rejects_denied_tenant_admission_as_entitlement_denied() -> None:
    client = FakeControlPlaneClient(snapshot=snapshot_dict(grants=[]))

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(
            resolve_and_require_trusted_admission(
                adapter=adapter(client), request=request(), now=NOW
            )
        )

    assert excinfo.value.code == "entitlement_denied"
    assert excinfo.value.status_code == 403


def test_gate_allows_valid_tenant_admission_end_to_end() -> None:
    client = FakeControlPlaneClient()

    resolved = run(
        resolve_and_require_trusted_admission(adapter=adapter(client), request=request(), now=NOW)
    )

    assert resolved.allowed is True
    # At least one Control Plane authority call per admission.
    assert len(client.calls) >= 1


def test_adapter_fails_closed_as_unavailable_when_client_raises() -> None:
    client = FakeControlPlaneClient(snapshot=RuntimeError("control plane down"))

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(
            resolve_and_require_trusted_admission(
                adapter=adapter(client), request=request(), now=NOW
            )
        )

    assert excinfo.value.code == "entitlement_unavailable"
    assert excinfo.value.status_code == 503


@pytest.mark.parametrize(
    "snapshot",
    [
        snapshot_dict(product_id="other-tenant"),
        snapshot_dict(subject={"subject_type": "user", "subject_id": "subject:intruder"}),
        snapshot_dict(expires_at=iso(NOW - timedelta(seconds=1))),
        snapshot_dict(grants=[{"key": "orchestration.run", "allowed": True}]),
        snapshot_dict(grants=[{"key": "orchestration.run", "allowed": "yes", "limit": None}]),
        {"unexpected": "shape"},
    ],
)
def test_adapter_fails_closed_for_untrusted_snapshot(snapshot) -> None:
    client = FakeControlPlaneClient(snapshot=snapshot)
    req = request()

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(adapter(client).resolve_admission(req))

    assert excinfo.value.code in {
        "entitlement_app_mismatch",
        "entitlement_subject_mismatch",
        "entitlement_expired",
        "entitlement_unavailable",
    }
    # The authority was still consulted; nothing was decided locally.
    assert client.calls and client.calls[0][0] == "fetch_entitlement_snapshot"


def test_cross_tenant_snapshot_reports_subject_mismatch() -> None:
    client = FakeControlPlaneClient(
        snapshot=snapshot_dict(subject={"subject_type": "user", "subject_id": "subject:intruder"})
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(adapter(client).resolve_admission(request()))

    assert excinfo.value.code == "entitlement_subject_mismatch"


def test_other_tenant_snapshot_reports_app_mismatch() -> None:
    client = FakeControlPlaneClient(snapshot=snapshot_dict(product_id="other-tenant"))

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(adapter(client).resolve_admission(request()))

    assert excinfo.value.code == "entitlement_app_mismatch"


def test_adapter_rejects_missing_client_before_any_call() -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        ControlPlaneTenantAdmissionAdapter(client=None)

    assert excinfo.value.code == "entitlement_unavailable"
    assert excinfo.value.status_code == 503


def test_build_adapter_returns_none_without_client() -> None:
    assert build_control_plane_admission_adapter(None) is None


def test_build_adapter_returns_opt_in_adapter_with_client() -> None:
    built = build_control_plane_admission_adapter(FakeControlPlaneClient(), clock=lambda: NOW)

    assert isinstance(built, ControlPlaneTenantAdmissionAdapter)
    resolved = run(built.resolve_admission(request()))
    assert resolved.allowed is True


def test_record_usage_receipt_submits_server_evidence() -> None:
    client = FakeControlPlaneClient(receipt_ack={"accepted": True, "event_id": "evt-e7-1"})

    ack = run(adapter(client).record_usage_receipt(receipt()))

    assert ack == {"accepted": True, "event_id": "evt-e7-1"}
    kinds = [kind for kind, _ in client.calls]
    assert kinds == ["record_usage"]
    event = client.calls[0][1]
    assert event["event_id"] == "evt-e7-1"
    assert event["subject"] == {"subject_type": "user", "subject_id": "subject:owner"}
    assert event["outcome"] == "succeeded"
    assert event["tokens"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    assert "prompt" not in event and "response" not in event


def test_record_usage_receipt_rejects_event_identity_mismatch() -> None:
    client = FakeControlPlaneClient(receipt_ack={"accepted": True, "event_id": "evt-other"})

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(adapter(client).record_usage_receipt(receipt()))

    assert excinfo.value.code == "entitlement_request_mismatch"


def test_record_usage_receipt_fails_closed_without_client_capability() -> None:
    class SnapshotOnlyClient:
        def __init__(self, inner):
            self.inner = inner

        def fetch_entitlement_snapshot(self, *, product_id, subject):
            return self.inner.fetch_entitlement_snapshot(product_id=product_id, subject=subject)

        def reserve_usage(self, *, reservation):
            return self.inner.reserve_usage(reservation=reservation)

    built = adapter(SnapshotOnlyClient(FakeControlPlaneClient()), require_usage_reservation=True)

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(built.record_usage_receipt(receipt()))

    assert excinfo.value.code == "entitlement_unavailable"
    assert excinfo.value.status_code == 503


def test_usage_receipt_rejects_client_shaped_token_values() -> None:
    with pytest.raises(ValueError):
        receipt(input_tokens=-1)
    with pytest.raises(ValueError):
        receipt(outcome="refunded")
