from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.engine_admission_authority import (
    CloudflareEngineAdmissionAuthorityStore,
)
from padiem_control_plane.entitlements import (
    EntitlementGrant,
    EntitlementSnapshot,
)


NOW = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
SUBJECT = CanonicalSubjectRef(
    SubjectType.USER,
    "subject-owner",
)


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def toArray(self) -> list[dict]:
        return list(self._rows)


class FakeSql:
    def __init__(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        self._connection = connection

    def exec(self, statement: str, *args):
        cursor = self._connection.execute(
            statement,
            args,
        )
        if cursor.description is None:
            return FakeCursor([])
        columns = [
            item[0]
            for item in cursor.description
        ]
        return FakeCursor(
            [
                dict(
                    zip(
                        columns,
                        row,
                        strict=True,
                    )
                )
                for row in cursor.fetchall()
            ]
        )


class FakeStorage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(
            ":memory:",
            isolation_level=None,
        )
        self.sql = FakeSql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result

    def count(self, table: str) -> int:
        return int(
            self.connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
        )


def store_fixture():
    storage = FakeStorage()
    store = CloudflareEngineAdmissionAuthorityStore(
        storage,
        allowed_product_ids=frozenset(
            {"b62"}
        ),
    )
    return store, storage


def snapshot(
    *,
    snapshot_id: str = "ent-snap-1",
    revision: str = "rev-1",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    grants: tuple[EntitlementGrant, ...] | None = None,
) -> EntitlementSnapshot:
    issued = issued_at or NOW - timedelta(
        minutes=1
    )
    return EntitlementSnapshot(
        snapshot_id=snapshot_id,
        product_id="b62",
        subject=SUBJECT,
        revision=revision,
        issued_at=issued,
        expires_at=expires_at
        or issued + timedelta(minutes=15),
        grants=(
            grants
            if grants is not None
            else (
                EntitlementGrant(
                    key="orchestration.run",
                    allowed=True,
                    limit=2,
                ),
            )
        ),
    )


def reservation(**overrides):
    value = {
        "idempotency_key": "res-" + "a" * 64,
        "billing_semantic_id": "orchestration.run",
        "product_id": "b62",
        "subject": SUBJECT.to_public_dict(),
        "request_fingerprint": "b" * 64,
        "trace_id": "trace-1",
        "estimated_units": 1,
        "occurred_at": NOW.isoformat(),
    }
    value.update(overrides)
    return value


def usage_event(**overrides):
    value = {
        "event_id": "evt-e7-1",
        "idempotency_key": "usage-idem-1",
        "billing_semantic_id": "orchestration.run",
        "product_id": "b62",
        "subject": SUBJECT.to_public_dict(),
        "execution_id": "run-e7-1",
        "outcome": "succeeded",
        "billing_disposition": "non_billable",
        "occurred_at": NOW.isoformat(),
        "tokens": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
        "route": {"status": "unknown"},
        "cost": None,
    }
    value.update(overrides)
    return value


def test_entitlement_snapshot_is_canonical_durable_source_and_fetch_is_scope_exact():
    store, storage = store_fixture()
    source = snapshot()
    store.install_entitlement_snapshot(
        source,
        now=NOW,
    )

    fetched = store.fetch_entitlement_snapshot(
        product_id="b62",
        subject=SUBJECT.to_public_dict(),
        now=NOW,
    )

    assert (
        fetched.to_policy_dict()
        == source.to_policy_dict()
    )
    assert storage.count(
        "engine_entitlement_snapshot"
    ) == 1
    projection = repr(
        fetched.to_policy_dict()
    ).lower()
    for forbidden in (
        "plan_name",
        "subscription",
        "payment",
        "credit_balance",
        "credential",
    ):
        assert forbidden not in projection


def test_entitlement_install_is_idempotent_but_revision_identity_cannot_change_bytes():
    store, storage = store_fixture()
    source = snapshot()
    store.install_entitlement_snapshot(
        source,
        now=NOW,
    )
    store.install_entitlement_snapshot(
        source,
        now=NOW,
    )
    assert storage.count(
        "engine_entitlement_snapshot"
    ) == 1

    with pytest.raises(
        ControlPlaneContractError
    ) as exc:
        store.install_entitlement_snapshot(
            snapshot(
                snapshot_id="ent-snap-other"
            ),
            now=NOW,
        )
    assert (
        exc.value.code
        == "entitlement_snapshot_conflict"
    )
    assert storage.count(
        "engine_entitlement_snapshot"
    ) == 1


def test_entitlement_revisions_move_forward_and_expired_truth_is_not_returned():
    store, _ = store_fixture()
    first = snapshot()
    store.install_entitlement_snapshot(
        first,
        now=NOW,
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as exc:
        store.install_entitlement_snapshot(
            snapshot(
                snapshot_id="ent-snap-stale",
                revision="rev-2",
                issued_at=first.issued_at,
            ),
            now=NOW,
        )
    assert (
        exc.value.code
        == "stale_entitlement_snapshot"
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as exc:
        store.fetch_entitlement_snapshot(
            product_id="b62",
            subject=SUBJECT.to_public_dict(),
            now=first.expires_at
            + timedelta(seconds=1),
        )
    assert (
        exc.value.code
        == "entitlement_snapshot_unavailable"
    )


def test_usage_reservation_is_entitlement_bound_and_idempotent():
    store, storage = store_fixture()
    store.install_entitlement_snapshot(
        snapshot(),
        now=NOW,
    )

    first = store.reserve_usage(
        reservation(),
        now=NOW,
    )
    second = store.reserve_usage(
        reservation(
            trace_id="trace-2",
            occurred_at=(NOW + timedelta(seconds=1)).isoformat(),
        ),
        now=NOW + timedelta(seconds=1),
    )

    assert first == second
    assert first["admitted"] is True
    assert first["reserved_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert second["reserved_at"] == first["reserved_at"]
    assert first["reservation_ref"].startswith(
        "cp_res_"
    )
    assert storage.count(
        "engine_usage_reservation"
    ) == 1


def test_usage_reservation_denies_missing_denied_or_over_limit_grant_without_credit_authority():
    cases = (
        ((), 1),
        (
            (
                EntitlementGrant(
                    key="orchestration.run",
                    allowed=False,
                ),
            ),
            1,
        ),
        (
            (
                EntitlementGrant(
                    key="orchestration.run",
                    allowed=True,
                    limit=1,
                ),
            ),
            2,
        ),
    )
    for grants, estimated_units in cases:
        store, _ = store_fixture()
        store.install_entitlement_snapshot(
            snapshot(grants=grants),
            now=NOW,
        )
        result = store.reserve_usage(
            reservation(
                estimated_units=estimated_units
            ),
            now=NOW,
        )
        assert result["admitted"] is False


def test_usage_reservation_replay_cannot_change_scope_or_units():
    store, storage = store_fixture()
    store.install_entitlement_snapshot(
        snapshot(),
        now=NOW,
    )
    store.reserve_usage(
        reservation(),
        now=NOW,
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as exc:
        store.reserve_usage(
            reservation(
                estimated_units=2
            ),
            now=NOW,
        )
    assert (
        exc.value.code
        == "usage_reservation_replay_mismatch"
    )
    assert storage.count(
        "engine_usage_reservation"
    ) == 1


def test_usage_event_is_recorded_once_from_narrow_engine_receipt():
    store, storage = store_fixture()
    first = store.record_usage(
        usage_event(),
        now=NOW,
    )
    second = store.record_usage(
        usage_event(),
        now=NOW,
    )

    assert first == second == {
        "accepted": True,
        "event_id": "evt-e7-1",
    }
    assert storage.count(
        "engine_usage_event"
    ) == 1
    persisted = storage.connection.execute(
        "SELECT payload_json "
        "FROM engine_usage_event "
        "WHERE event_id='evt-e7-1'"
    ).fetchone()[0]
    assert "prompt" not in persisted
    assert "response" not in persisted
    assert '"cost":null' in persisted
    assert (
        '"route":{"status":"unknown"}'
        in persisted
    )


def test_usage_event_identities_are_immutable():
    store, storage = store_fixture()
    store.record_usage(
        usage_event(),
        now=NOW,
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as exc:
        store.record_usage(
            usage_event(
                outcome="failed"
            ),
            now=NOW,
        )
    assert (
        exc.value.code
        == "usage_event_conflict"
    )
    assert storage.count(
        "engine_usage_event"
    ) == 1


def test_engine_receipt_cannot_activate_billable_accounting():
    store, storage = store_fixture()

    with pytest.raises(
        ControlPlaneContractError
    ) as exc:
        store.record_usage(
            usage_event(
                billing_disposition="billable"
            ),
            now=NOW,
        )
    assert (
        exc.value.code
        == "invalid_engine_usage_event"
    )
    assert storage.count(
        "engine_usage_event"
    ) == 0


def test_engine_receipt_cannot_assert_provider_route_or_cost_authority():
    store, storage = store_fixture()

    with pytest.raises(
        ControlPlaneContractError
    ) as route_exc:
        store.record_usage(
            usage_event(
                route={
                    "status": "observed",
                    "selected_provider": "forged",
                }
            ),
            now=NOW,
        )
    assert (
        route_exc.value.code
        == "invalid_engine_admission_authority"
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as cost_exc:
        store.record_usage(
            usage_event(
                cost={"amount": "1.00"}
            ),
            now=NOW,
        )
    assert (
        cost_exc.value.code
        == "invalid_engine_usage_event"
    )
    assert storage.count(
        "engine_usage_event"
    ) == 0


def test_unreviewed_product_fails_closed_before_authority_write():
    store, storage = store_fixture()

    with pytest.raises(
        ControlPlaneContractError
    ) as exc:
        store.reserve_usage(
            reservation(
                product_id="other"
            ),
            now=NOW,
        )
    assert (
        exc.value.code
        == "engine_admission_product_mismatch"
    )
    assert storage.count(
        "engine_usage_reservation"
    ) == 0

def test_engine_private_gateway_cannot_install_entitlement_truth():
    from pathlib import Path
    import ast

    root = Path(__file__).resolve().parents[1]
    worker_path = root / "engine_admission_authority_worker.py"
    tree = ast.parse(
        worker_path.read_text(encoding="utf-8")
    )
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }

    default_methods = {
        node.name
        for node in classes["Default"].body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }
    durable_methods = {
        node.name
        for node in classes[
            "CanonicalEngineAdmissionDurableObject"
        ].body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }

    assert {
        "fetch_entitlement_snapshot",
        "reserve_usage",
        "record_usage",
    } <= default_methods
    assert (
        "install_entitlement_snapshot"
        not in default_methods
    )
    assert (
        "install_entitlement_snapshot"
        in durable_methods
    )

    config_path = next(
        root.glob(
            "*.engine-admission-authority.jsonc"
        )
    )
    config = config_path.read_text(
        encoding="utf-8"
    )
    assert '"workers_dev": false' in config
    assert '"preview_urls": false' in config
    assert '"routes"' not in config

