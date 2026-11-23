"""End-to-end SOURCE composition: owner consent -> Broker offer CAS -> PC socket.

No live Windows, Worker route, external HTTP, or secret persistence is involved.
"""
from __future__ import annotations

import asyncio

import pytest

from app.connector_one_click_approval import OneClickOwnerApproval, OneClickDenied
from app.connector_pending_pc_delivery import (
    CanonicalPendingPcDelivery, PcDeliveryRefused,
    PENDING_PC_DELIVERY_PRODUCTION_ENABLED, PENDING_PC_DELIVERY_HTTP_MOUNTED,
)
from _support.connector_one_click import Fixture, session, CODE, CHALLENGE
from _support.pending_pc_delivery import (
    DEVICE, REQUEST, BrokerPort, Socket,
)

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
