"""Authenticated B54 owner -> existing Broker service RPC -> same PC socket.

This is a source-only private Service Binding contract test: no public route,
production DO export, actual Cloudflare isolate or real DPAPI registration.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.connector_pending_pc_owner_rpc import (
    CanonicalBrokerOwnerPendingPcPort, OwnerPcPrivateRpcDenied,
    OWNER_PENDING_BROKER_PRIVATE_RPC_EXPORTED,
    OWNER_PENDING_BROKER_HTTP_MOUNTED,
    OWNER_PENDING_BROKER_PRODUCTION_ENABLED,
)
from app.connector_one_click_approval import OneClickOwnerApproval, OneClickDenied
from test_4139_pending_pc_delivery_adapter import BrokerPort, Socket
from test_4139_connector_one_click_approval import Fixture, session, CODE, CHALLENGE

REF = "link." + "a"*32
DEVICE = "windows.device.1"


class BrokerServiceBinding:
    """Fake of the typed existing PRIVATE Broker DO stub, not public HTTP."""

    def __init__(self):
        self.broker = BrokerPort()
        self.socket = Socket()
        self.calls=[]
        self.corrupt_reservation=None
        self.corrupt_delivery=None
        self.fail_delivery=False

    async def reserve_pending_pc_owner_intent(self, payload):
        self.calls.append(("reserve", dict(payload)))
        if self.corrupt_reservation is not None:
            return self.corrupt_reservation
        assert payload == {
            "request_ref": REF, "owner_subject_ref": "owner.1",
            "account_ref": "account.1", "workspace_ref": "workspace.1",
        }
        return await self.broker.reserve_once(request_ref=payload["request_ref"])

    async def deliver_pending_pc_link(self, payload):
        self.calls.append(("deliver", dict(payload)))
        if self.fail_delivery:
            raise RuntimeError("mock private transport failure: code redacted")
        if self.corrupt_delivery is not None:
            return self.corrupt_delivery
        await self.broker.claim_delivery_once(
            request_ref=payload["request_ref"], device_id=payload["device_id"],
        )
        await self.socket.send_once(
            request_ref=payload["request_ref"],device_id=payload["device_id"],
            challenge_id=payload["challenge_id"],pairing_code=payload["pairing_code"],
        )
        return {"ok":True,"sent_once":True,"registered":False,"connected":False}


def make(*, owner_session=None):
    signed=owner_session or session()
    private=BrokerServiceBinding()
    fixture=Fixture()
    port=CanonicalBrokerOwnerPendingPcPort(
        signed_owner=signed, canonical_broker_binding=private, identity=fixture,
    )
    service=OneClickOwnerApproval(
        identity=fixture, host=fixture, pc_rendezvous=port,
    )
    return private, port, fixture, service, signed


def test_owner_one_click_goes_only_to_same_broker_do_and_real_ledger():
    private,port,fixture,service,signed=make()
    result=asyncio.run(service.approve(
        owner_session=signed,request_ref=REF,confirmed=True,
    ))
    assert result=={
        "ok":True,"state":"awaiting_device_confirmation",
        "device_id":DEVICE,"registered":False,"connected":False,
        "dispatch_authorized":False,
    }
    assert private.broker.state()=="delivery_claimed"
    assert private.socket.calls==[{
        "request_ref":REF,"device_id":DEVICE,
        "challenge_id":CHALLENGE,"pairing_code":CODE,
    }]
    assert [method for method,_ in private.calls]==["reserve","deliver"]
    assert private.calls[0][1]=={
        "request_ref": REF, "owner_subject_ref": "owner.1",
        "account_ref": "account.1", "workspace_ref": "workspace.1",
    }
    assert private.calls[1][1]=={
        "request_ref":REF,"device_id":DEVICE,
        "challenge_id":CHALLENGE,"pairing_code":CODE,
    }
    assert CODE not in repr(result)
    assert len([name for name,_ in fixture.calls if name=="issue"])==1
    with pytest.raises(OneClickDenied,match="pending_pc_unavailable"):
        asyncio.run(service.approve(
            owner_session=signed,request_ref=REF,confirmed=True,
        ))
    assert len(private.socket.calls)==1
    assert private.broker.state()=="delivery_claimed"


def test_explicit_owner_session_mandatory_before_any_broker_rpc():
    private=BrokerServiceBinding()
    for invalid in (None,object(),"signed-owner",{"verified":True}):
        with pytest.raises(OwnerPcPrivateRpcDenied,match="owner_unverified"):
            CanonicalBrokerOwnerPendingPcPort(
                signed_owner=invalid,canonical_broker_binding=private,
            )
    assert private.calls==[]


def test_missing_or_forged_private_broker_methods_fail_closed():
    with pytest.raises(OwnerPcPrivateRpcDenied,match="binding_missing"):
        CanonicalBrokerOwnerPendingPcPort(
            signed_owner=session(), canonical_broker_binding=object(),
        )
    assert OWNER_PENDING_BROKER_PRIVATE_RPC_EXPORTED is False
    assert OWNER_PENDING_BROKER_HTTP_MOUNTED is False
    assert OWNER_PENDING_BROKER_PRODUCTION_ENABLED is False


@pytest.mark.parametrize("bad", [
    {}, {"request_ref":REF}, {"request_ref":REF,"device_id":DEVICE},
    {"request_ref":REF, "device_id":DEVICE,
     "device_possession_verified":True,
     "connected_to_outbound_channel":True,
     "reserved_once":"true","expires_at":"2026-10-14T12:59:00Z"},
])
def test_forged_pending_reservation_cannot_mint_canonical_consent(bad):
    private,port,fixture,service,signed=make()
    private.corrupt_reservation=bad
    with pytest.raises(OneClickDenied,match="pending_pc_unavailable"):
        asyncio.run(service.approve(
            owner_session=signed,request_ref=REF,confirmed=True,
        ))
    assert [name for name,_ in private.calls]==["reserve"]
    assert fixture.calls==[]
    assert private.socket.calls==[]


def test_wrong_ref_and_no_replay_even_with_valid_signed_owner():
    private,port,fixture,service,signed=make()
    with pytest.raises(OwnerPcPrivateRpcDenied,match="ref_invalid"):
        asyncio.run(port.reserve_once(request_ref=REF+"?session=hidden"))
    assert private.calls==[]
    assert fixture.calls==[]


def test_one_use_delivery_transport_failure_never_reissues_code():
    private,port,fixture,service,signed=make()
    private.fail_delivery=True
    with pytest.raises(OneClickDenied,match="pc_delivery_unconfirmed"):
        asyncio.run(service.approve(
            owner_session=signed,request_ref=REF,confirmed=True,
        ))
    assert len(private.calls)==2
    assert len([name for name,_ in fixture.calls if name=="issue"])==1
    with pytest.raises(OneClickDenied,match="pending_pc_unavailable"):
        asyncio.run(service.approve(
            owner_session=signed,request_ref=REF,confirmed=True,
        ))
    assert len(private.socket.calls)==0


def test_unexpected_delivery_reply_cannot_mark_success():
    private,port,fixture,service,signed=make()
    private.corrupt_delivery={
        "ok":True,"sent_once":True,"registered":True,"connected":True,
    }
    with pytest.raises(OneClickDenied,match="pc_delivery_unconfirmed"):
        asyncio.run(service.approve(
            owner_session=signed,request_ref=REF,confirmed=True,
        ))
    assert private.broker.state()=="reserved"
