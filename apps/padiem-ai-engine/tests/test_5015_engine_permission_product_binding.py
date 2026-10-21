"""#5015 (F-032): the execution app id and the permission product id are one
connected chain, not one overloaded field.

The Engine carries two product vocabularies:

* the **execution app id** — the Engine's own app identity. The caller
  registry authorizes it (``allowed_app_ids``) and the Engine admission binds
  it. The Chat product executes as ``padiem-chat`` and keeps that identity.
* the **permission product id** — the Control Plane entitlement/usage product.
  The Control Plane resolves the session, the grant, the usage reservation and
  the usage receipt for it. The Chat product's existing permission semantics
  are the ``b62`` product.

Before this change the Engine derived both from one field, so the Chat
product asked the Control Plane about a product (``padiem-chat``) that the
Control Plane's Engine entitlement policy does not know, and the admission
failed closed with 503 before the PC lane could run.

These tests pin the whole chain: the snapshot request, the admission, the
usage reservation and the usage receipt must all name the same permission
product for the same user, the Claw path must be untouched, and the Control
Plane's own refusals (other user, other product, expired, revoked, no
permission) must still refuse.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.execution_admission import (
    ExecutionAdmissionError,
    ExecutionAdmissionRequest,
    TrustedExecutionAdmission,
    TrustedUsageReservation,
    permission_product_id_for_execution_app,
    require_trusted_admission,
)
from app.execution_admission_resume import OriginalAdmissionBinding
from app.execution_admission_gate import resolve_and_require_trusted_admission
from app.tenant_auth import (
    ControlPlaneTenantAdmissionAdapter,
    UsageReceipt,
    identify_tenant,
)
from app.usage_lifecycle import build_terminal_usage_receipt

NOW = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)

CHAT_APP_ID = "padiem-chat"
CHAT_PERMISSION_PRODUCT_ID = "b62"
CLAW_APP_ID = "b54-padiem-claw"
CLAW_PERMISSION_PRODUCT_ID = "b54-padiem-claw"
CANONICAL_SUBJECT = "sub_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OTHER_SUBJECT = "sub_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def iso(value: datetime) -> str:
    return value.isoformat()


def snapshot_dict(**overrides):
    values = {
        "snapshot_id": "snap-f032-chat",
        "product_id": CHAT_PERMISSION_PRODUCT_ID,
        "subject": {"subject_type": "user", "subject_id": CANONICAL_SUBJECT},
        "revision": "policy-rev-f032",
        "issued_at": iso(NOW - timedelta(minutes=1)),
        "expires_at": iso(NOW + timedelta(minutes=30)),
        "grants": [{"key": "orchestration.run", "allowed": True, "limit": None}],
    }
    values.update(overrides)
    return values


def reservation_dict(**overrides):
    values = {
        "reservation_ref": "res-f032-1",
        "admitted": True,
        "expires_at": iso(NOW + timedelta(minutes=5)),
        "reserved_at": iso(NOW),
    }
    values.update(overrides)
    return values


class FakeControlPlaneClient:
    """Recording Control Plane authority double with CP-shaped payloads."""

    def __init__(self, *, snapshot=None, reservation=None):
        self.snapshot = snapshot if snapshot is not None else snapshot_dict()
        self.reservation = reservation if reservation is not None else reservation_dict()
        self.calls: list[tuple[str, dict]] = []
        self.receipts: list[dict] = []

    def fetch_entitlement_snapshot(self, *, product_id, subject):
        self.calls.append(
            ("fetch_entitlement_snapshot", {"product_id": product_id, "subject": dict(subject)})
        )
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
        self.receipts.append(dict(usage_event))
        return {"accepted": True, "event_id": usage_event["event_id"]}


def request(**overrides):
    values = {
        "app_id": CHAT_APP_ID,
        "subject_id": CANONICAL_SUBJECT,
        "capability": "orchestration.run",
        "trace_id": "tr-f032",
        "request_fingerprint": "a" * 64,
        "usage_reservation_identity": "usage-f032-1",
    }
    values.update(overrides)
    return ExecutionAdmissionRequest(**values)


def adapter(client, **kwargs):
    kwargs.setdefault("clock", lambda: NOW)
    return ControlPlaneTenantAdmissionAdapter(client=client, **kwargs)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# The mapping itself: server-owned, closed, and the Chat identity unchanged.
# ---------------------------------------------------------------------------


def test_the_chat_execution_app_id_maps_to_the_existing_b62_permission_product():
    assert permission_product_id_for_execution_app(CHAT_APP_ID) == CHAT_PERMISSION_PRODUCT_ID
    assert permission_product_id_for_execution_app(CLAW_APP_ID) == CLAW_PERMISSION_PRODUCT_ID


def test_an_unmapped_app_id_keeps_its_own_permission_product():
    """Every other path is still decided by the Control Plane's own check."""
    assert permission_product_id_for_execution_app("b62") == "b62"
    assert permission_product_id_for_execution_app("padiem-web-xlsx-p01") == "padiem-web-xlsx-p01"
    assert permission_product_id_for_execution_app("b54-padiem-claw-drive") == "b54-padiem-claw-drive"


def test_the_execution_app_id_is_not_a_client_supplied_permission_product():
    """The request carries no permission product field at all."""
    fields = set(ExecutionAdmissionRequest.__dataclass_fields__)
    assert "permission_product_id" not in fields
    assert "product_id" not in fields


def test_identify_tenant_separates_the_execution_app_id_from_the_permission_product():
    tenant = identify_tenant(request())

    assert tenant.execution_app_id == CHAT_APP_ID
    assert tenant.product_id == CHAT_PERMISSION_PRODUCT_ID
    assert tenant.subject_ref() == {"subject_type": "user", "subject_id": CANONICAL_SUBJECT}


def test_identify_tenant_keeps_the_claw_execution_and_permission_identity():
    tenant = identify_tenant(request(app_id=CLAW_APP_ID, subject_id=CANONICAL_SUBJECT))

    assert tenant.execution_app_id == CLAW_APP_ID
    assert tenant.product_id == CLAW_PERMISSION_PRODUCT_ID
    assert tenant.subject_ref() == {"subject_type": "user", "subject_id": CANONICAL_SUBJECT}


# ---------------------------------------------------------------------------
# Chat normal path: snapshot -> admission -> reservation -> receipt.
# ---------------------------------------------------------------------------


def test_the_chat_run_asks_the_control_plane_about_the_b62_permission_product():
    client = FakeControlPlaneClient()

    resolved = run(adapter(client).resolve_admission(request()))

    assert isinstance(resolved, TrustedExecutionAdmission)
    assert resolved.allowed is True
    # The execution identity of the Chat product is unchanged.
    assert resolved.app_id == CHAT_APP_ID
    # The permission product is the existing b62 product.
    assert resolved.permission_product_id == CHAT_PERMISSION_PRODUCT_ID
    snapshot_call = client.calls[0]
    assert snapshot_call[0] == "fetch_entitlement_snapshot"
    assert snapshot_call[1]["product_id"] == CHAT_PERMISSION_PRODUCT_ID
    assert snapshot_call[1]["subject"] == {
        "subject_type": "user",
        "subject_id": CANONICAL_SUBJECT,
    }


def test_the_chat_reservation_and_receipt_name_the_same_product_and_user():
    client = FakeControlPlaneClient()
    resolved = run(adapter(client).resolve_admission(request()))

    reservation_call = client.calls[1]
    assert reservation_call[0] == "reserve_usage"
    reservation = reservation_call[1]
    assert reservation["product_id"] == CHAT_PERMISSION_PRODUCT_ID
    assert reservation["subject"] == {
        "subject_type": "user",
        "subject_id": CANONICAL_SUBJECT,
    }
    assert reservation["billing_semantic_id"] == "orchestration.run"

    # The receipt is built only from the admitted reservation evidence.
    original = OriginalAdmissionBinding.from_run_admission(resolved)
    receipt = build_terminal_usage_receipt(original, outcome="succeeded")
    assert isinstance(receipt, UsageReceipt)
    assert receipt.product_id == CHAT_PERMISSION_PRODUCT_ID
    assert dict(receipt.subject) == {
        "subject_type": "user",
        "subject_id": CANONICAL_SUBJECT,
    }
    assert receipt.billing_disposition == "non_billable"


def test_the_claw_path_reserves_and_reports_its_own_permission_product():
    client = FakeControlPlaneClient(
        snapshot=snapshot_dict(
            snapshot_id="snap-f032-claw",
            product_id=CLAW_PERMISSION_PRODUCT_ID,
        )
    )

    resolved = run(
        adapter(client).resolve_admission(request(app_id=CLAW_APP_ID))
    )

    assert resolved.app_id == CLAW_APP_ID
    assert resolved.permission_product_id == CLAW_PERMISSION_PRODUCT_ID
    assert client.calls[0][1]["product_id"] == CLAW_PERMISSION_PRODUCT_ID
    assert client.calls[1][1]["product_id"] == CLAW_PERMISSION_PRODUCT_ID
    original = OriginalAdmissionBinding.from_run_admission(resolved)
    receipt = build_terminal_usage_receipt(original, outcome="succeeded")
    assert receipt.product_id == CLAW_PERMISSION_PRODUCT_ID


# ---------------------------------------------------------------------------
# Refusals: another user, another product, expiry/revocation, no permission.
# ---------------------------------------------------------------------------


def test_a_snapshot_for_another_user_is_refused():
    client = FakeControlPlaneClient(
        snapshot=snapshot_dict(
            subject={"subject_type": "user", "subject_id": OTHER_SUBJECT}
        )
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(adapter(client).resolve_admission(request()))

    assert excinfo.value.code == "entitlement_subject_mismatch"
    assert client.calls[1:] == []


def test_a_snapshot_for_another_product_is_refused():
    client = FakeControlPlaneClient(
        snapshot=snapshot_dict(product_id=CLAW_PERMISSION_PRODUCT_ID)
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(adapter(client).resolve_admission(request()))

    assert excinfo.value.code == "entitlement_app_mismatch"
    assert client.calls[1:] == []


def test_an_expired_snapshot_is_refused():
    client = FakeControlPlaneClient(
        snapshot=snapshot_dict(expires_at=iso(NOW - timedelta(seconds=1)))
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(adapter(client).resolve_admission(request()))

    assert excinfo.value.code == "entitlement_expired"
    assert client.calls[1:] == []


def test_a_revoked_grant_is_refused():
    client = FakeControlPlaneClient(
        snapshot=snapshot_dict(grants=[{"key": "orchestration.run", "allowed": False, "limit": None}])
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(
            resolve_and_require_trusted_admission(
                adapter=adapter(client), request=request(), now=NOW
            )
        )

    assert excinfo.value.code == "entitlement_denied"
    assert client.calls[1:] == []


def test_a_missing_grant_is_refused():
    client = FakeControlPlaneClient(snapshot=snapshot_dict(grants=[]))

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        run(
            resolve_and_require_trusted_admission(
                adapter=adapter(client), request=request(), now=NOW
            )
        )

    assert excinfo.value.code == "entitlement_denied"
    assert client.calls[1:] == []


# ---------------------------------------------------------------------------
# The admission contract refuses an inconsistent product binding.
# ---------------------------------------------------------------------------


def _admission(**overrides):
    values = {
        "decision_id": "adm-f032-1",
        "app_id": CHAT_APP_ID,
        "subject_id": CANONICAL_SUBJECT,
        "capability": "orchestration.run",
        "allowed": True,
        "authority_ref": "control-plane:entitlement:snap-f032-chat",
        "policy_revision": "policy-rev-f032",
        "issued_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=5),
        "request_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return TrustedExecutionAdmission(**values)


def test_the_admission_rejects_a_permission_product_that_is_not_the_mapped_one():
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        _admission(permission_product_id=CLAW_PERMISSION_PRODUCT_ID)

    assert excinfo.value.code == "invalid_admission"


def test_the_admission_rejects_a_reservation_for_another_permission_product():
    reservation = TrustedUsageReservation(
        reservation_ref="res-f032-2",
        idempotency_key="res-f032-2",
        billing_semantic_id="orchestration.run",
        product_id=CLAW_PERMISSION_PRODUCT_ID,
        subject_type="user",
        subject_id=CANONICAL_SUBJECT,
        request_fingerprint="a" * 64,
        reserved_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        _admission(usage_reservation=reservation)

    assert excinfo.value.code == "invalid_admission"


def test_the_admission_rejects_a_reservation_for_another_user():
    reservation = TrustedUsageReservation(
        reservation_ref="res-f032-3",
        idempotency_key="res-f032-3",
        billing_semantic_id="orchestration.run",
        product_id=CHAT_PERMISSION_PRODUCT_ID,
        subject_type="user",
        subject_id=OTHER_SUBJECT,
        request_fingerprint="a" * 64,
        reserved_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        _admission(usage_reservation=reservation)

    assert excinfo.value.code == "invalid_admission"


def test_require_trusted_admission_refuses_an_admission_for_another_execution_app():
    admission = _admission(app_id=CLAW_APP_ID)

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_trusted_admission(request=request(), admission=admission, now=NOW)

    assert excinfo.value.code == "entitlement_app_mismatch"


def test_require_trusted_admission_accepts_the_mapped_permission_product():
    admission = _admission()

    accepted = require_trusted_admission(request=request(), admission=admission, now=NOW)

    assert accepted.permission_product_id == CHAT_PERMISSION_PRODUCT_ID


# ---------------------------------------------------------------------------
# The persisted evidence of a paused run keeps the same product/user binding.
# ---------------------------------------------------------------------------


def _reservation(*, product_id: str, subject_id: str) -> TrustedUsageReservation:
    return TrustedUsageReservation(
        reservation_ref="res-f032-persist",
        idempotency_key="res-f032-persist",
        billing_semantic_id="orchestration.run",
        product_id=product_id,
        subject_type="user",
        subject_id=subject_id,
        request_fingerprint="a" * 64,
        reserved_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def test_the_persisted_evidence_refuses_a_reservation_for_another_permission_product():
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        OriginalAdmissionBinding(
            decision_id="adm-f032-persist",
            app_id=CHAT_APP_ID,
            subject_id=CANONICAL_SUBJECT,
            authority_ref="control-plane:entitlement:snap-f032-chat",
            policy_revision="policy-rev-f032",
            request_fingerprint="a" * 64,
            usage_reservation=_reservation(
                product_id=CLAW_PERMISSION_PRODUCT_ID, subject_id=CANONICAL_SUBJECT
            ),
        )

    assert excinfo.value.code == "invalid_admission"


def test_the_persisted_evidence_refuses_a_reservation_for_another_user():
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        OriginalAdmissionBinding(
            decision_id="adm-f032-persist",
            app_id=CHAT_APP_ID,
            subject_id=CANONICAL_SUBJECT,
            authority_ref="control-plane:entitlement:snap-f032-chat",
            policy_revision="policy-rev-f032",
            request_fingerprint="a" * 64,
            usage_reservation=_reservation(
                product_id=CHAT_PERMISSION_PRODUCT_ID, subject_id=OTHER_SUBJECT
            ),
        )

    assert excinfo.value.code == "invalid_admission"


def test_the_persisted_evidence_keeps_the_mapped_permission_product():
    binding = OriginalAdmissionBinding(
        decision_id="adm-f032-persist",
        app_id=CHAT_APP_ID,
        subject_id=CANONICAL_SUBJECT,
        authority_ref="control-plane:entitlement:snap-f032-chat",
        policy_revision="policy-rev-f032",
        request_fingerprint="a" * 64,
        usage_reservation=_reservation(
            product_id=CHAT_PERMISSION_PRODUCT_ID, subject_id=CANONICAL_SUBJECT
        ),
    )

    assert binding.app_id == CHAT_APP_ID
    assert binding.usage_reservation is not None
    assert binding.usage_reservation.product_id == CHAT_PERMISSION_PRODUCT_ID
