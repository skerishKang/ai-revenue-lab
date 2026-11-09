"""Combined admission RPC on the Engine side: opt-in switch, one round trip.

The switch defaults off so the two-call flow keeps its existing shape; when on,
the adapter issues a single ``admit_usage`` request and validates the returned
policy and reservation with the same parsers as before. The admission stage log
keeps its name (admission_ms) and carries ``combined=true`` only on this path.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.engine_timing import EngineTiming
from app.execution_admission import ExecutionAdmissionError, ExecutionAdmissionRequest
from app.tenant_auth import (
    ControlPlaneTenantAdmissionAdapter,
    admission_combined_rpc_enabled,
)

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
CAPABILITY = "orchestration.run"


def iso(value):
    return value.isoformat()


def snapshot_dict(**overrides):
    values = {
        "snapshot_id": "snap-e7-1",
        "product_id": "b62",
        "subject": {"subject_type": "user", "subject_id": "subject:owner"},
        "revision": "policy-rev-7",
        "issued_at": iso(NOW - timedelta(minutes=1)),
        "expires_at": iso(NOW + timedelta(minutes=30)),
        "grants": [{"key": CAPABILITY, "allowed": True, "limit": None}],
    }
    values.update(overrides)
    return values


def reservation_dict(**overrides):
    values = {
        "reservation_ref": "res-e7-1",
        "admitted": True,
        "expires_at": iso(NOW + timedelta(minutes=5)),
        "reserved_at": iso(NOW),
    }
    values.update(overrides)
    return values


class FakeControlPlaneClient:
    """Recording Control Plane authority double with CP-shaped payloads."""

    def __init__(self, *, snapshot=None, reservation=None, admit=None):
        self.snapshot = snapshot if snapshot is not None else snapshot_dict()
        self.reservation = (
            reservation if reservation is not None else reservation_dict()
        )
        self.admit = admit
        self.calls: list[tuple] = []

    def fetch_entitlement_snapshot(self, *, product_id, subject):
        self.calls.append(("fetch_entitlement_snapshot", product_id, dict(subject)))
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot

    def reserve_usage(self, *, reservation):
        self.calls.append(("reserve_usage", reservation))
        if isinstance(self.reservation, Exception):
            raise self.reservation
        return self.reservation

    def admit_usage(self, *, product_id, subject, reservation):
        self.calls.append(("admit_usage", product_id, dict(subject), reservation))
        if callable(self.admit):
            return self.admit(
                product_id=product_id, subject=subject, reservation=reservation
            )
        if isinstance(self.admit, Exception):
            raise self.admit
        return {"snapshot": self.snapshot, "reservation": self.reservation}


class LegacyOnlyClient(FakeControlPlaneClient):
    # No combined capability: enabling the switch must fail closed.
    admit_usage = None  # type: ignore[assignment]


def adapter(client, **kwargs):
    kwargs.setdefault("clock", lambda: NOW)
    return ControlPlaneTenantAdmissionAdapter(client=client, **kwargs)


def request(**overrides):
    values = {
        "app_id": "b62",
        "subject_id": "subject:owner",
        "capability": CAPABILITY,
        "trace_id": "tr-e7",
        "request_fingerprint": "a" * 64,
        "usage_reservation_identity": "usage-e7-1",
    }
    values.update(overrides)
    return ExecutionAdmissionRequest(**values)


def run(coro):
    return asyncio.run(coro)


def facts(admission):
    reservation = admission.usage_reservation
    return (
        admission.allowed,
        admission.authority_ref,
        admission.permission_product_id,
        admission.policy_revision,
        admission.issued_at,
        admission.expires_at,
        None
        if reservation is None
        else (
            reservation.reservation_ref,
            reservation.idempotency_key,
            reservation.billing_semantic_id,
            reservation.product_id,
            reservation.subject_type,
            reservation.subject_id,
            reservation.request_fingerprint,
            reservation.reserved_at,
            reservation.expires_at,
        ),
    )


def test_allowed_case_matches_between_the_two_paths():
    legacy_client = FakeControlPlaneClient()
    combined_client = FakeControlPlaneClient()
    legacy = run(adapter(legacy_client).resolve_admission(request()))
    combined = run(adapter(combined_client, combined_rpc=True).resolve_admission(request()))

    assert facts(legacy) == facts(combined)
    assert combined.allowed is True
    assert [call[0] for call in legacy_client.calls] == [
        "fetch_entitlement_snapshot",
        "reserve_usage",
    ]
    assert [call[0] for call in combined_client.calls] == ["admit_usage"]


NEGATIVE_CASES = [
    (
        "local-shortfall",
        snapshot_dict(grants=[{"key": CAPABILITY, "allowed": True, "limit": 1}]),
        reservation_dict(admitted=False),
        2,
    ),
    (
        "denied-flag",
        snapshot_dict(
            grants=[{"key": CAPABILITY, "allowed": False, "limit": None}]
        ),
        reservation_dict(),
        1,
    ),
    ("missing-grant", snapshot_dict(grants=[]), reservation_dict(), 1),
]


@pytest.mark.parametrize("label,snapshot,reservation,units", NEGATIVE_CASES)
def test_not_allowed_cases_match_and_hold_no_reservation(
    label, snapshot, reservation, units
):
    legacy_client = FakeControlPlaneClient(snapshot=snapshot, reservation=reservation)
    combined_client = FakeControlPlaneClient(snapshot=snapshot, reservation=reservation)
    legacy = run(
        adapter(legacy_client, estimated_units=units).resolve_admission(request())
    )
    combined = run(
        adapter(combined_client, estimated_units=units, combined_rpc=True).resolve_admission(
            request()
        )
    )

    assert facts(legacy) == facts(combined)
    assert combined.allowed is False
    assert combined.usage_reservation is None
    assert [call[0] for call in legacy_client.calls] == [
        "fetch_entitlement_snapshot"
    ]
    assert [call[0] for call in combined_client.calls] == ["admit_usage"]

def test_switch_off_keeps_two_calls_even_when_available():
    client = FakeControlPlaneClient()
    result = run(adapter(client, combined_rpc=False).resolve_admission(request()))
    assert result.allowed is True
    assert [call[0] for call in client.calls] == [
        "fetch_entitlement_snapshot",
        "reserve_usage",
    ]


def test_new_engine_combined_on_against_old_worker_without_admit_usage_fails_closed():
    # An older Control Plane has no admit_usage surface: the combined path must
    # refuse the admission rather than silently falling back to the two calls
    # (which would split the round trip again and blur the contract).
    client = LegacyOnlyClient()
    with pytest.raises(ExecutionAdmissionError) as caught:
        run(adapter(client, combined_rpc=True).resolve_admission(request()))
    assert caught.value.code == "entitlement_unavailable"
    assert caught.value.status_code == 503
    assert client.calls == []

def test_switch_on_requires_the_client_capability():
    with pytest.raises(ExecutionAdmissionError):
        adapter(LegacyOnlyClient(), combined_rpc=True)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        (" yes ", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        (None, False),
        (5, False),
    ],
)
def test_switch_reader_accepts_only_explicit_truthy_values(raw, expected):
    source = {"PADIEM_ENGINE_ADMISSION_COMBINED_RPC": raw}
    assert admission_combined_rpc_enabled(source) is expected


def test_switch_reader_handles_attribute_sources_and_garbage():
    assert (
        admission_combined_rpc_enabled(
            SimpleNamespace(PADIEM_ENGINE_ADMISSION_COMBINED_RPC="1")
        )
        is True
    )
    assert admission_combined_rpc_enabled(object()) is False


def test_engine_timing_keeps_admission_ms_and_marks_combined():
    plain = EngineTiming().line(run_hash="r", trace_id="t", b14_ms=840, outcome="ok")
    assert " combined=true" not in plain
    assert plain.startswith(
        "engine_timing run_hash=r trace_id=t admission_ms=-1.0 core_ms=-1.0 b14_ms=840"
    )
    assert plain.endswith(" outcome=ok")

    combined = EngineTiming().line(
        run_hash="r", trace_id="t", b14_ms=840, outcome="ok", combined=True
    )
    assert combined.endswith(" outcome=ok combined=true")
