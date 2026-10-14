"""Signed B54 owner -> private Broker Worker -> SAME canonical DO/live PC WSS.

Real sqlite3 durable ledger + Ed25519 possession proof over fake WSS.
Not production Cloudflare, user OAuth, real WSS ingress or Windows DPAPI ACK.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import pytest

from padiem_control_plane.broker_pending_pc_private_rpc import (
    CanonicalBrokerPendingPcLiveRPC, BrokerPendingPcPrivateRefused,
    _PRIVATE_METHODS_PRODUCTION_ENABLED, _OWNER_RPC_MOUNTED,
    _PC_WSS_SAME_BROKER_DO_MOUNTED,
)
from app.connector_pending_pc_owner_rpc import (
    CanonicalBrokerOwnerPendingPcPort,
)
from app.connector_one_click_approval import OneClickOwnerApproval, OneClickDenied
from test_4139_broker_pending_socket_actor import actor, offer, stored, REF, DEVICE, CODE
from test_4139_connector_one_click_approval import Fixture, session


class SameDo(CanonicalBrokerPendingPcLiveRPC):
    def __init__(self, storage, *, gated=True):
        self._storage=storage
        if gated:
            self.env=SimpleNamespace(
                LOCAL_AGENT_BROKER_PENDING_PC_OWNER_RPC_ENABLED="enabled",
                LOCAL_AGENT_BROKER_PENDING_PC_SCHEMA_INSTALLED="installed",
                LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE="isolated-operator-acceptance-4139",
            )
        else:
            self.env=SimpleNamespace()


async def mounted_test_stack():
    item,socket,storage=actor()
    wait=await offer(item,socket)
    authority=SameDo(storage)
    authority._bind_verified_pc_wss(request_ref=REF,actor=item)
    port=CanonicalBrokerOwnerPendingPcPort(
        signed_owner=session(),canonical_broker_binding=authority,
    )
    identity=Fixture()
    service=OneClickOwnerApproval(identity=identity,host=identity,pc_rendezvous=port)
    return authority,item,socket,storage,wait,identity,service


def test_real_do_route_once_no_second_store_and_no_browser_secret():
    async def run():
        do,item,socket,storage,waiting,fixture,service=await mounted_test_stack()
        result=await service.approve(
            owner_session=session(),request_ref=REF,confirmed=True,
        )
        assert result["state"]=="awaiting_device_confirmation"
        assert result["registered"] is False and result["connected"] is False
        assert CODE not in repr(result)
        delivery=json.loads(await socket.output.get())
        assert delivery["type"]=="pc_offer_approved"
        assert delivery["device_id"]==DEVICE
        assert delivery["request_ref"]==REF
        assert delivery["pairing_code"]==CODE
        assert len(stored(storage))==1
        assert stored(storage)[0]["state"]=="delivery_claimed"
        assert CODE not in repr(stored(storage))
        state=await waiting
        assert state["state"]=="awaiting_canonical_dpapi_ack"
        assert state["registered"] is False and state["connected"] is False
        assert do._pending_pc_live_by_ref=={}
        with pytest.raises(OneClickDenied,match="pending_pc_unavailable"):
            await service.approve(
                owner_session=session(),request_ref=REF,confirmed=True,
            )
        assert socket.output.empty()
    asyncio.run(run())


def test_explicit_three_gates_off_deny_without_reserve_or_challenge():
    async def run():
        item,sock,storage=actor()
        waiting=await offer(item,sock)
        disabled=SameDo(storage,gated=False)
        with pytest.raises(BrokerPendingPcPrivateRefused,match="rpc_disabled"):
            disabled._bind_verified_pc_wss(request_ref=REF,actor=item)
        with pytest.raises(BrokerPendingPcPrivateRefused,match="rpc_disabled"):
            await disabled.reserve_pending_pc_link({"request_ref":REF})
        assert stored(storage)[0]["state"]=="pending"
        item.mark_disconnected()
        with pytest.raises(Exception):
            await waiting
    asyncio.run(run())


def test_other_do_instance_cannot_reach_same_durable_storage_socket():
    async def run():
        do,item,sock,storage,waiting,fixture,service=await mounted_test_stack()
        other=SameDo(storage)
        # Same SQLite object is necessary but NOT sufficient: the live WSS
        # is bound to its original Durable Object Python instance.
        with pytest.raises(BrokerPendingPcPrivateRefused,match="socket_missing"):
            await other.reserve_pending_pc_link({"request_ref":REF})
        assert stored(storage)[0]["state"]=="pending"
        item.mark_disconnected()
        with pytest.raises(Exception):
            await waiting
    asyncio.run(run())


def test_actor_binding_refuses_foreign_broker_store_or_socket():
    async def run():
        do,item,sock,storage,waiting,fixture,service=await mounted_test_stack()
        other,other_sock,other_store=actor()
        with pytest.raises(BrokerPendingPcPrivateRefused,match="actor_unverified"):
            do._bind_verified_pc_wss(request_ref="link."+"b"*32,actor=other)
        with pytest.raises(BrokerPendingPcPrivateRefused,match="actor_duplicate"):
            do._bind_verified_pc_wss(request_ref=REF,actor=item)
        item.mark_disconnected()
        with pytest.raises(Exception):
            await waiting
    asyncio.run(run())


def test_private_rpc_exact_fields_and_owner_token_not_accepted_as_ref():
    async def run():
        do,item,sock,storage,waiting,fixture,service=await mounted_test_stack()
        for payload in ({}, {"request_ref":REF,"owner_session":"forged"},
                        {"request_ref":REF+"?token=leak"}, {"request_ref":42}, None):
            with pytest.raises(BrokerPendingPcPrivateRefused):
                await do.reserve_pending_pc_link(payload)
        with pytest.raises(BrokerPendingPcPrivateRefused,match="private_fields"):
            await do.deliver_pending_pc_link({
                "request_ref":REF,"device_id":DEVICE,
                "challenge_id":"challenge.1","pairing_code":CODE,
                "tenant_id":"forged",
            })
        assert stored(storage)[0]["state"]=="pending"
        item.mark_disconnected()
        with pytest.raises(Exception):
            await waiting
    asyncio.run(run())


def test_owner_without_live_pc_cannot_issue_broker_reservation():
    async def run():
        do,item,sock,storage,waiting,fixture,service=await mounted_test_stack()
        item.mark_disconnected()
        with pytest.raises(OneClickDenied,match="pending_pc_unavailable"):
            await service.approve(
                owner_session=session(),request_ref=REF,confirmed=True,
            )
        assert fixture.calls==[]
        assert stored(storage)[0]["state"]=="pending"
        with pytest.raises(Exception):
            await waiting
    asyncio.run(run())


def test_rpc_not_exposed_to_public_fetch_or_production_automatically():
    assert _PRIVATE_METHODS_PRODUCTION_ENABLED is False
    assert _OWNER_RPC_MOUNTED is False
    assert _PC_WSS_SAME_BROKER_DO_MOUNTED is False
