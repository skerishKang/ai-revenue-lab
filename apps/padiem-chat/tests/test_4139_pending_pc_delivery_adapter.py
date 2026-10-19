"""End-to-end SOURCE composition: owner consent -> Broker offer CAS -> PC socket.

No live Windows, Worker route, external HTTP, or secret persistence is involved.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import sqlite3

import pytest

from padiem_control_plane.pending_pc_link import (
    DurablePendingPcLink, VerifiedPendingPc, MIGRATION_ID,
    install_pending_pc_link_schema,
)
from app.connector_one_click_approval import OneClickOwnerApproval, OneClickDenied
from app.connector_pending_pc_delivery import (
    CanonicalPendingPcDelivery, PcDeliveryRefused,
    PENDING_PC_DELIVERY_PRODUCTION_ENABLED, PENDING_PC_DELIVERY_HTTP_MOUNTED,
)
from test_4139_connector_one_click_approval import Fixture, session, CODE, CHALLENGE

REQUEST = "link." + "a"*32
DEVICE = "windows.device.1"
KEY_FINGERPRINT = "f"*64


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
    def toArray(self):
        if self.cursor.description is None:
            return []
        return [
            dict(zip((column[0] for column in self.cursor.description), record))
            for record in self.cursor.fetchall()
        ]


class Storage:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = self
    def exec(self, query, *values):
        return Cursor(self.connection.execute(query, values))
    def transactionSync(self, fn):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = fn()
            self.connection.execute("COMMIT")
            return result
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise


class BrokerPort:
    def __init__(self):
        self.store = Storage()
        install_pending_pc_link_schema(
            storage=self.store, migration_id=MIGRATION_ID, operator_gate=True,
        )
        self.online = True
        self.ledger = DurablePendingPcLink(
            storage=self.store, canonical_broker_storage=self.store,
            ref_factory=lambda: REQUEST,
            channel_verified=lambda ref, device, key: (
                self.online and ref == REQUEST and device == DEVICE
                and key == KEY_FINGERPRINT
            ),
        )
        self.ledger.offer(
            attested=VerifiedPendingPc(
                device_id=DEVICE, possession_key_sha256=KEY_FINGERPRINT,
            ),
            now=datetime.now(timezone.utc),
        )
    async def reserve_once(self, *, request_ref):
        return self.ledger.reserve_once(
            request_ref=request_ref, now=datetime.now(timezone.utc),
        )
    async def claim_delivery_once(self, *, request_ref, device_id):
        self.ledger.claim_delivery_once(
            request_ref=request_ref, device_id=device_id,
            now=datetime.now(timezone.utc),
        )
    def state(self):
        return self.store.exec(
            "SELECT state FROM canonical_broker_pending_pc_link"
        ).toArray()[0]["state"]


class Socket:
    def __init__(self):
        self.calls = []
        self.fail = False
    async def send_once(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("credential prefix must not leak")


def fixture():
    broker = BrokerPort()
    channel = Socket()
    approval = Fixture()
    pc = CanonicalPendingPcDelivery(broker=broker, socket=channel)
    service = OneClickOwnerApproval(
        identity=approval, host=approval, pc_rendezvous=pc,
    )
    return broker, channel, approval, service


def test_one_click_owner_to_real_sqlite_reservation_and_one_socket_delivery():
    broker, socket, mock, service = fixture()
    result = asyncio.run(service.approve(
        owner_session=session(), request_ref=REQUEST, confirmed=True,
    ))
    assert result["state"] == "awaiting_device_confirmation"
    assert result["connected"] is False and result["registered"] is False
    assert result["dispatch_authorized"] is False
    assert CODE not in repr(result)
    assert broker.state() == "delivery_claimed"
    assert socket.calls == [{
        "request_ref": REQUEST, "device_id": DEVICE,
        "challenge_id": CHALLENGE, "pairing_code": CODE,
    }]
    stored = broker.store.exec(
        "SELECT * FROM canonical_broker_pending_pc_link"
    ).toArray()[0]
    assert CODE not in repr(stored)
    assert CHALLENGE not in repr(stored)
    assert "account_ref" not in stored and "workspace_ref" not in stored
    with pytest.raises(OneClickDenied) as exc:
        asyncio.run(service.approve(
            owner_session=session(), request_ref=REQUEST, confirmed=True,
        ))
    assert str(exc.value) == "pending_pc_unavailable"
    assert len(socket.calls) == 1
    assert sum(name == "issue" for name, _ in mock.calls) == 1


def test_broker_offline_before_reserve_never_mints_a_challenge():
    broker, socket, mock, service = fixture()
    broker.online = False
    with pytest.raises(OneClickDenied) as exc:
        asyncio.run(service.approve(
            owner_session=session(), request_ref=REQUEST, confirmed=True,
        ))
    assert str(exc.value) == "pending_pc_unavailable"
    assert broker.state() == "pending"
    assert socket.calls == []
    assert mock.calls == []


def test_broker_offline_after_reserve_refuses_any_code_send():
    broker, socket, mock, service = fixture()
    original = mock.grant_connector_enrollment_consent
    async def disconnect(**kwargs):
        answer = await original(**kwargs)
        broker.online = False
        return answer
    mock.grant_connector_enrollment_consent = disconnect
    with pytest.raises(OneClickDenied) as exc:
        asyncio.run(service.approve(
            owner_session=session(), request_ref=REQUEST, confirmed=True,
        ))
    assert str(exc.value) == "pc_delivery_unconfirmed"
    assert socket.calls == []
    assert broker.state() == "reserved"


def test_sending_error_consumes_slot_and_never_replays_pairing_code():
    broker, socket, mock, service = fixture()
    socket.fail = True
    with pytest.raises(OneClickDenied) as exc:
        asyncio.run(service.approve(
            owner_session=session(), request_ref=REQUEST, confirmed=True,
        ))
    assert str(exc.value) == "pc_delivery_unconfirmed"
    assert broker.state() == "delivery_claimed"
    assert len(socket.calls) == 1
    with pytest.raises(OneClickDenied):
        asyncio.run(service.approve(
            owner_session=session(), request_ref=REQUEST, confirmed=True,
        ))
    assert len(socket.calls) == 1


@pytest.mark.parametrize("change", [
    {"request_ref": "link."+"A"*32},
    {"device_id": "evil device"},
    {"challenge_id": "bad challenge"},
    {"pairing_code": "not-a-code"},
])
def test_bad_delivery_arguments_fail_before_broker_or_socket(change):
    broker, socket, mock, service = fixture()
    port = CanonicalPendingPcDelivery(broker=broker, socket=socket)
    kwargs = {
        "request_ref": REQUEST, "device_id": DEVICE,
        "challenge_id": CHALLENGE, "pairing_code": CODE,
    }
    kwargs.update(change)
    with pytest.raises(PcDeliveryRefused) as err:
        asyncio.run(port.deliver_once(**kwargs))
    assert str(err.value) == "pending_pc_delivery_invalid"
    assert broker.state() == "pending"
    assert socket.calls == []


def test_default_ports_are_unmounted_and_production_off():
    assert PENDING_PC_DELIVERY_PRODUCTION_ENABLED is False
    assert PENDING_PC_DELIVERY_HTTP_MOUNTED is False
