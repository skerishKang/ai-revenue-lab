"""The combined admission RPC on the Engine admission authority (#7305 follow-up).

One round trip carries the entitlement policy and the adjudication of the
reservation behind the same request: the snapshot stage runs the same policy
lookup as ``fetch_entitlement_snapshot``, the reservation stage runs the same
store path as ``reserve_usage``, and both stages keep the existing closed-shape
and error envelopes. No existing RPC changes; a refusal never becomes an
admitted reservation.
"""

from __future__ import annotations

import asyncio
import types
from datetime import UTC, datetime, timedelta

# Same tests directory, same load-the-worker pattern as the ingress contract.
from test_engine_admission_rpc_ingress_261031 import _load_worker  # noqa: E402

from test_engine_admission_authority import (  # noqa: E402
    snapshot as policy_snapshot,
    reservation as base_reservation,
    store_fixture,
)

from padiem_control_plane.entitlements import EntitlementGrant  # noqa: E402

from padiem_control_plane.contracts import ControlPlaneContractError

OCCURRED_AT = datetime(2026, 11, 9, 14, 30, tzinfo=UTC).isoformat()
PRODUCT = "b62"
SUBJECT = {"subject_type": "user", "subject_id": "subject:padiem:user:com2"}


def reservation_payload(**overrides):
    payload = {
        "idempotency_key": "res-" + "c" * 64,
        "billing_semantic_id": "orchestration.run",
        "product_id": PRODUCT,
        "subject": dict(SUBJECT),
        "request_fingerprint": "d" * 64,
        "trace_id": None,
        "estimated_units": 1,
        "occurred_at": OCCURRED_AT,
    }
    payload.update(overrides)
    return payload


class _Snapshot:
    def to_policy_dict(self) -> dict:
        return {
            "snapshot_id": "snap-com2-0001",
            "product_id": PRODUCT,
            "subject": dict(SUBJECT),
            "revision": "rev-41",
            "issued_at": OCCURRED_AT,
            "expires_at": OCCURRED_AT,
            "grants": [{"key": "orchestration.run", "allowed": True, "limit": None}],
        }


class _Store:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, datetime]] = []

    def reserve_usage(self, reservation, *, now):
        self.calls.append((dict(reservation), now))
        return {
            "reservation_ref": "cp_res_com2_0001",
            "admitted": True,
            "expires_at": OCCURRED_AT,
            "reserved_at": OCCURRED_AT,
        }


def _authority(*, ensure=None, store=None):
    module = _load_worker()
    authority = object.__new__(module.CanonicalEngineAdmissionDurableObject)
    authority._voice_policy = None
    authority._store = store if store is not None else _Store()
    if ensure is not None:
        authority._ensure_current_entitlement = ensure
    return module, authority


def _calls_authority(*, admission=None, store=None):
    async def ensure(*, product_id, subject, now):
        ensure.calls.append({"product_id": product_id, "subject": dict(subject), "now": now})
        if admission is not None:
            raise admission
        return _Snapshot()

    ensure.calls = []
    _module, authority = _authority(ensure=ensure, store=store)
    return authority, ensure, authority._store


def test_admit_returns_snapshot_and_reservation_in_one_response():
    authority, ensure, store = _calls_authority()
    result = asyncio.run(
        authority.admit_usage(
            {
                "product_id": PRODUCT,
                "subject": dict(SUBJECT),
                "reservation": reservation_payload(),
            }
        )
    )
    assert set(result) == {"ok", "snapshot", "reservation"}
    assert result["ok"] is True
    assert result["snapshot"] == _Snapshot().to_policy_dict()
    assert result["reservation"]["reservation_ref"] == "cp_res_com2_0001"
    assert [call["product_id"] for call in ensure.calls] == [PRODUCT]
    assert len(store.calls) == 1


def test_reservation_is_forwarded_verbatim_and_adjudicated_once():
    authority, _ensure, store = _calls_authority()
    payload = reservation_payload(trace_id="tr-1")
    asyncio.run(
        authority.admit_usage(
            {"product_id": PRODUCT, "subject": dict(SUBJECT), "reservation": payload}
        )
    )
    assert len(store.calls) == 1
    forwarded, when = store.calls[0]
    assert forwarded == payload
    assert isinstance(when, datetime)


def test_snapshot_refusal_is_an_error_and_never_touches_the_store():
    refusal = ControlPlaneContractError(
        "entitlement_snapshot_unavailable", "refused by the test double"
    )
    authority, _ensure, store = _calls_authority(admission=refusal)
    result = asyncio.run(
        authority.admit_usage(
            {
                "product_id": PRODUCT,
                "subject": dict(SUBJECT),
                "reservation": reservation_payload(),
            }
        )
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "entitlement_snapshot_unavailable"
    assert store.calls == []


def test_malformed_payload_is_refused_without_a_store_call():
    authority, _ensure, store = _calls_authority()
    result = asyncio.run(
        authority.admit_usage({"product_id": PRODUCT, "subject": dict(SUBJECT)})
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_engine_admission_authority_rpc"
    assert store.calls == []


class _DeniedStore:
    """Store-boundary denial: the policy ran, the request was not admitted."""

    def __init__(self) -> None:
        self.calls = 0

    def reserve_usage(self, reservation, *, now):
        self.calls += 1
        return {
            "reservation_ref": "cp_res_denied_0001",
            "admitted": False,
            "expires_at": OCCURRED_AT,
            "reserved_at": OCCURRED_AT,
        }


def test_admit_usage_snapshot_grant_denied_never_creates_admitted_reservation():
    store = _DeniedStore()
    authority, _ensure, _store = _calls_authority(store=store)
    result = asyncio.run(
        authority.admit_usage(
            {
                "product_id": PRODUCT,
                "subject": dict(SUBJECT),
                "reservation": reservation_payload(),
            }
        )
    )
    assert result["ok"] is True
    assert result["snapshot"] == _Snapshot().to_policy_dict()
    assert result["reservation"]["admitted"] is False
    assert result["reservation"]["reservation_ref"] == "cp_res_denied_0001"
    assert store.calls == 1


def test_admit_usage_response_loss_retry_replays_same_reservation_without_duplicate_insert():
    # The retry after a lost response carries byte-identical input, so the real
    # store must replay the committed reservation rather than insert again.
    store, storage = store_fixture()
    now = datetime.now(UTC)
    policy = policy_snapshot(
        grants=(
            EntitlementGrant(key="orchestration.run", allowed=True, limit=None),
        ),
                    issued_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(minutes=15),
    )
    store.install_entitlement_snapshot(policy, now=datetime.now(UTC))
    authority, _ensure, _store = _calls_authority(store=store)
    payload = {
        "product_id": PRODUCT,
        "subject": {"subject_type": "user", "subject_id": "subject-owner"},
        "reservation": base_reservation(
            occurred_at=now.isoformat(),
        ),
    }
    first = asyncio.run(authority.admit_usage(dict(payload)))
    # The response is lost in transit; the Engine retries the identical request.
    second = asyncio.run(authority.admit_usage(dict(payload)))

    assert first["ok"] is True and second["ok"] is True
    assert first["reservation"] == second["reservation"]
    assert first["reservation"]["admitted"] is True
    assert second["reservation"]["admitted"] is True
    assert storage.count("engine_usage_reservation") == 1


