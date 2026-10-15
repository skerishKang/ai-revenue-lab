"""Broker-DO SQLite pending PC link — deterministic no-secret source tests.

No user registry, Cloudflare migration, live socket or production route used.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

import padiem_control_plane.pending_pc_link as link
from padiem_control_plane.contracts import ControlPlaneContractError

NOW = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
REF = "link." + "a" * 32
DEVICE = "device.windows.1"
FINGERPRINT = "d" * 64


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
    def toArray(self):
        if self.cursor.description is None:
            return []
        return [
            dict(zip((col[0] for col in self.cursor.description), row))
            for row in self.cursor.fetchall()
        ]


class Sql:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
    def exec(self, statement, *args):
        return Cursor(self.db.execute(statement, args))


class Storage:
    def __init__(self):
        self.sql = Sql()
        self.commits = 0
    def transactionSync(self, work):
        self.sql.db.execute("BEGIN IMMEDIATE")
        try:
            result = work()
            self.sql.db.execute("COMMIT")
            self.commits += 1
            return result
        except BaseException:
            self.sql.db.execute("ROLLBACK")
            raise


class Fixture:
    def __init__(self, *, installed=True, online=True):
        self.storage = Storage()
        self.online = online
        self.checked = []
        if installed:
            link.install_pending_pc_link_schema(
                storage=self.storage, migration_id=link.MIGRATION_ID,
                operator_gate=True,
            )

    def check_channel(self, request_ref, device_id, fingerprint):
        self.checked.append((request_ref, device_id, fingerprint))
        return self.online and device_id == DEVICE and fingerprint == FINGERPRINT

    def authority(self):
        return link.DurablePendingPcLink(
            storage=self.storage, canonical_broker_storage=self.storage,
            channel_verified=self.check_channel,
            ref_factory=lambda: REF,
        )

    def attestation(self):
        return link.VerifiedPendingPc(
            device_id=DEVICE, possession_key_sha256=FINGERPRINT,
        )

    def offer(self, *, ttl=60):
        return self.authority().offer(
            attested=self.attestation(), now=NOW, ttl_seconds=ttl,
        )


def error(code, action):
    with pytest.raises(ControlPlaneContractError) as exc:
        action()
    assert exc.value.code == code


def rows(storage):
    return storage.sql.exec(
        "SELECT * FROM canonical_broker_pending_pc_link"
    ).toArray()


def test_schema_is_explicit_additive_same_broker_sqlite_no_second_store():
    storage = Storage()
    error("pending_pc_schema_disabled", lambda:
          link.install_pending_pc_link_schema(
              storage=storage, migration_id=link.MIGRATION_ID, operator_gate=False,
          ))
    error("pending_pc_schema_disabled", lambda:
          link.install_pending_pc_link_schema(
              storage=storage, migration_id="other", operator_gate=True,
          ))
    assert storage.sql.exec(
        "SELECT name FROM sqlite_master WHERE name='canonical_broker_pending_pc_link'"
    ).toArray() == []
    with pytest.raises(ValueError):
        link.DurablePendingPcLink(
            storage=storage, canonical_broker_storage=Storage(),
            channel_verified=lambda *_: True,
        )
    link.install_pending_pc_link_schema(
        storage=storage, migration_id=link.MIGRATION_ID, operator_gate=True,
    )
    assert storage.sql.exec(
        "SELECT name FROM sqlite_master WHERE name='canonical_broker_pending_pc_link'"
    ).toArray() == [{"name": "canonical_broker_pending_pc_link"}]


def test_owner_intent_is_durable_on_exact_live_pc_offer_and_one_use():
    fx = Fixture()
    fx.offer()
    record = fx.authority().reserve_owner_intent_once(
        request_ref=REF, owner_subject_ref="owner.1",
        account_ref="account.1", workspace_ref="workspace.1",
        now=NOW+timedelta(seconds=1),
    )
    assert record["device_possession_verified"] is True
    row = rows(fx.storage)[0]
    assert row["state"] == "reserved"
    assert (row["owner_subject_ref"], row["owner_account_ref"],
            row["owner_workspace_ref"]) == ("owner.1", "account.1", "workspace.1")
    error("pending_pc_request_already_used", lambda:
          fx.authority().reserve_owner_intent_once(
              request_ref=REF, owner_subject_ref="owner.2",
              account_ref="account.2", workspace_ref="workspace.2", now=NOW,
          ))
    assert rows(fx.storage)[0]["owner_account_ref"] == "account.1"


def test_offer_cold_restart_reserve_delivery_exactly_once():
    fx = Fixture()
    offer = fx.offer()
    assert offer == {
        "request_ref": REF,
        "expires_at": (NOW+timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
    }
    assert len(rows(fx.storage)) == 1
    assert rows(fx.storage)[0]["possession_key_sha256"] == FINGERPRINT
    # New object, same exact DO storage: survives isolate turnover/restart.
    cold = fx.authority()
    reserved = cold.reserve_once(request_ref=REF, now=NOW+timedelta(seconds=1))
    assert reserved == {
        "request_ref": REF, "device_id": DEVICE,
        "device_possession_verified": True,
        "connected_to_outbound_channel": True,
        "reserved_once": True, "expires_at": offer["expires_at"],
    }
    error("pending_pc_request_already_used", lambda:
          fx.authority().reserve_once(request_ref=REF, now=NOW+timedelta(seconds=2)))
    cold.claim_delivery_once(
        request_ref=REF, device_id=DEVICE, now=NOW+timedelta(seconds=3),
    )
    error("pending_pc_delivery_unavailable", lambda:
          cold.claim_delivery_once(
              request_ref=REF, device_id=DEVICE, now=NOW+timedelta(seconds=4),
          ))
    assert rows(fx.storage)[0]["state"] == "delivery_claimed"
    assert "pairing_code" not in rows(fx.storage)[0]
    assert "credential" not in rows(fx.storage)[0]
    assert "account_ref" not in rows(fx.storage)[0]
    assert "workspace_ref" not in rows(fx.storage)[0]


def test_unverified_or_offline_channel_can_never_reserve_or_deliver():
    fx = Fixture()
    fx.offer()
    fx.online = False
    error("pending_pc_outbound_channel_unverified", lambda:
          fx.authority().reserve_once(request_ref=REF, now=NOW))
    assert rows(fx.storage)[0]["state"] == "pending"
    fx.online = True
    fx.authority().reserve_once(request_ref=REF, now=NOW)
    fx.online = False
    error("pending_pc_outbound_channel_unverified", lambda:
          fx.authority().claim_delivery_once(
              request_ref=REF, device_id=DEVICE, now=NOW,
          ))
    assert rows(fx.storage)[0]["state"] == "reserved"


def test_never_create_offer_with_unverified_channel():
    fx = Fixture(online=False)
    error("pending_pc_outbound_channel_unverified", fx.offer)
    assert rows(fx.storage) == []


def test_expired_request_and_replay_fail_closed():
    fx = Fixture()
    fx.offer(ttl=5)
    error("pending_pc_request_unavailable", lambda:
          fx.authority().reserve_once(request_ref=REF, now=NOW+timedelta(seconds=5)))
    assert rows(fx.storage)[0]["state"] == "pending"
    error("pending_pc_request_invalid", lambda:
          fx.authority().reserve_once(request_ref=REF+"?token=bad", now=NOW))


@pytest.mark.parametrize("ttl", [-1, 0, 91, 99999, True, "60"])
def test_offer_ttl_rejects_unsafe_types_and_unbounded_expiry(ttl):
    fx = Fixture()
    error("pending_pc_ttl_invalid", lambda: fx.offer(ttl=ttl))
    assert rows(fx.storage) == []


@pytest.mark.parametrize("device,key", [
    ("", FINGERPRINT), ("../../Windows", FINGERPRINT),
    ("device.windows.1", "g"*64),
    ("device.windows.1", "f"*63),
    (None, FINGERPRINT),
])
def test_attestation_shape_is_strict(device, key):
    error("pending_pc_attestation_invalid", lambda:
          link.VerifiedPendingPc(device_id=device, possession_key_sha256=key))


def test_forged_browser_dict_cannot_be_offered():
    fx = Fixture()
    error("pending_pc_attestation_required", lambda:
          fx.authority().offer(
              attested={"device_id": DEVICE, "verified": True}, now=NOW,
          ))


def test_pending_request_does_not_allow_other_device_delivery():
    fx = Fixture()
    fx.offer()
    fx.authority().reserve_once(request_ref=REF, now=NOW)
    error("pending_pc_delivery_unavailable", lambda:
          fx.authority().claim_delivery_once(
              request_ref=REF, device_id="other.device.1", now=NOW,
          ))
    assert rows(fx.storage)[0]["state"] == "reserved"


def test_missing_schema_is_not_auto_created_by_ledger():
    fx = Fixture(installed=False)
    error("pending_pc_store_unavailable", fx.offer)
    assert fx.storage.sql.exec(
        "SELECT name FROM sqlite_master WHERE name='canonical_broker_pending_pc_link'"
    ).toArray() == []


def test_capacity_is_bounded_and_fails_closed(monkeypatch):
    fx = Fixture()
    monkeypatch.setattr(link, "MAX_UNEXPIRED_OFFERS", 1)
    fx.offer()
    error("pending_pc_capacity_reached", lambda:
          fx.authority().offer(
              attested=fx.attestation(), now=NOW+timedelta(seconds=1),
          ))
    assert len(rows(fx.storage)) == 1


def test_new_offer_cannot_override_existing_active_reference():
    fx = Fixture()
    fx.offer()
    error("pending_pc_store_unavailable", fx.offer)
    assert rows(fx.storage)[0]["state"] == "pending"


def test_expired_offer_purged_before_capacity_test(monkeypatch):
    fx = Fixture()
    monkeypatch.setattr(link, "MAX_UNEXPIRED_OFFERS", 1)
    fx.offer(ttl=2)
    nxt = fx.authority().offer(
        attested=fx.attestation(), now=NOW+timedelta(seconds=3),
    )
    assert nxt["request_ref"] == REF
    assert len(rows(fx.storage)) == 1


def test_never_mounted_or_implicitly_activated():
    assert link.PENDING_PC_LINK_SCHEMA_INSTALLED_BY_DEFAULT is False
    assert link.PENDING_PC_LINK_HTTP_ROUTE_MOUNTED is False
    assert link.PENDING_PC_LINK_PRODUCTION_ENABLED is False


def test_jsproxy_count_cursor_offers_without_changing_authority():
    """Cloudflare SQL JsProxy container/rows retain the exact one-use ledger."""
    from types import SimpleNamespace

    class JsRow:
        def __init__(self, value):
            self._value = value

        def to_py(self):
            return dict(self._value)

    class JsRows:
        def __init__(self, records):
            self.records = records

        def __iter__(self):
            return iter(JsRow(row) for row in self.records)

    fx = Fixture()
    original_exec = fx.storage.sql.exec

    def sql_exec(statement, *values):
        cursor = original_exec(statement, *values)
        if statement == "SELECT COUNT(*) AS n FROM canonical_broker_pending_pc_link":
            return SimpleNamespace(toArray=lambda: JsRows(cursor.toArray()))
        return cursor

    fx.storage.sql.exec = sql_exec
    assert fx.offer()["request_ref"] == REF
    assert rows(fx.storage)[0]["state"] == "pending"
    fx.authority().reserve_once(request_ref=REF, now=NOW + timedelta(seconds=1))
    assert rows(fx.storage)[0]["state"] == "reserved"


def test_jsproxy_row_conversion_still_rejects_malformed_results():
    from types import SimpleNamespace

    class InvalidRow:
        def to_py(self):
            return ["not", "an", "object"]

    for raw in (object(), [InvalidRow()], ["invalid"]):
        cursor = SimpleNamespace(toArray=lambda value=raw: value)
        with pytest.raises(ControlPlaneContractError) as exc:
            link._rows(cursor)
        assert exc.value.code == "pending_pc_store_invalid"
