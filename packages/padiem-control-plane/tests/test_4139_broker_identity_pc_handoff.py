"""Same DO WSS proof is not a B54 Identity owner: private claim remains off
without operator gate and never redeems a credential.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import pytest

from padiem_control_plane.broker_pending_pc_identity_handoff import (
    BrokerPcIdentityHandoffDenied, IDENTITY_HANDOFF_PUBLIC_MOUNTED,
    IDENTITY_HANDOFF_PRODUCTION_ENABLED,
)
from padiem_control_plane.broker_pending_pc_wss import broker_pending_pc_wss_message
from canonical_broker_gateway_bootstrap import bootstrap_mac, session_mac
from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref
from test_4139_broker_post_approval_bootstrap import (
    native_owner_approved, DEVICE, REF,
)


async def verified(monkeypatch, *, enabled=True):
    do,broker,socket,cid,code=await native_owner_approved(monkeypatch)
    do.env.LOCAL_AGENT_BROKER_PENDING_PC_IDENTITY_HANDOFF_ENABLED=(
        "enabled" if enabled else "off"
    )
    await broker_pending_pc_wss_message(do,socket,json.dumps({
        "type":"begin","challenge_id":cid,"device_id":DEVICE,
        "proof_ref":pairing_proof_ref(
            challenge_id=cid,device_id=DEVICE,pairing_code=code,
        ),
    }))
    nonce=socket.sent[-1]
    await broker_pending_pc_wss_message(do,socket,json.dumps({
        "type":"finish","lease_ref":nonce["lease_ref"],
        "proof_hex":bootstrap_mac(
            pairing_code=code,challenge_id=cid,device_id=DEVICE,
            nonce_hex=nonce["nonce_hex"],lease_ref=nonce["lease_ref"],
        ),
    }))
    await broker_pending_pc_wss_message(do,socket,json.dumps({
        "type":"credential_fetch","counter":1,
        "proof_hex":session_mac(
            pairing_code=code,challenge_id=cid,device_id=DEVICE,
            nonce_hex=nonce["nonce_hex"],lease_ref=nonce["lease_ref"],
            action="credential_fetch",counter=1,
            payload_sha256=hashlib.sha256(b"").hexdigest(),
        ),
    }))
    assert not socket.closes
    return do,broker,socket,cid,code


def test_canonical_do_status_and_claim_are_once_only_no_enrollment(monkeypatch):
    async def go():
        do,broker,sock,cid,code=await verified(monkeypatch)
        status=await do.pending_pc_identity_status({"request_ref":REF})
        assert status=={
            "request_ref":REF,"challenge_id":cid,"device_id":DEVICE,
            "signed_fetch_verified":True,"identity_authorized":False,
            "credential_issued":False,"connected":False,
        }
        assert code not in repr(status)
        receipt=await do.claim_pending_pc_identity_proof({
            "request_ref":REF,"challenge_id":cid,"device_id":DEVICE,
        })
        assert receipt["proof_ref"]==pairing_proof_ref(
            challenge_id=cid,device_id=DEVICE,pairing_code=code,
        )
        assert receipt["credential_issued"] is False
        assert receipt["identity_authorized"] is False
        assert not sock.closes
        assert broker._storage.sql.exec(
            "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge"
        ).toArray()[0]["redeemed_at"] is None
        with pytest.raises(BrokerPcIdentityHandoffDenied,match="claim_denied"):
            await do.claim_pending_pc_identity_proof({
                "request_ref":REF,"challenge_id":cid,"device_id":DEVICE,
            })
    asyncio.run(go())


def test_gate_off_no_status_and_no_proof_release(monkeypatch):
    async def go():
        do,broker,sock,cid,code=await verified(monkeypatch,enabled=False)
        for method,payload in (
            (do.pending_pc_identity_status,{"request_ref":REF}),
            (do.claim_pending_pc_identity_proof,{
                "request_ref":REF,"challenge_id":cid,"device_id":DEVICE,
            }),
        ):
            with pytest.raises(BrokerPcIdentityHandoffDenied,match="disabled"):
                await method(payload)
        assert broker._storage.sql.exec(
            "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge"
        ).toArray()[0]["redeemed_at"] is None
    asyncio.run(go())
    assert IDENTITY_HANDOFF_PUBLIC_MOUNTED is False
    assert IDENTITY_HANDOFF_PRODUCTION_ENABLED is False


def test_different_do_cannot_claim_wss_proof_even_with_same_sqlite(monkeypatch):
    from test_4139_broker_native_pc_wss import DurableObject
    async def go():
        do,broker,sock,cid,code=await verified(monkeypatch)
        other=DurableObject(storage=broker._storage)
        other.env.LOCAL_AGENT_BROKER_PENDING_PC_IDENTITY_HANDOFF_ENABLED="enabled"
        with pytest.raises(BrokerPcIdentityHandoffDenied,match="live_proof_missing"):
            await other.pending_pc_identity_status({"request_ref":REF})
        with pytest.raises(BrokerPcIdentityHandoffDenied,match="live_proof_missing"):
            await other.claim_pending_pc_identity_proof({
                "request_ref":REF,"challenge_id":cid,"device_id":DEVICE,
            })
    asyncio.run(go())


def test_disconnect_before_claim_fail_closed(monkeypatch):
    async def go():
        do,broker,sock,cid,code=await verified(monkeypatch)
        sock.close(1008,"")
        with pytest.raises(BrokerPcIdentityHandoffDenied,match="live_proof_missing"):
            await do.pending_pc_identity_status({"request_ref":REF})
    asyncio.run(go())


@pytest.mark.parametrize("bad",[
    {},{"request_ref":"link."+"a"*32,"owner_session":"forged"},
    {"request_ref":"link."+"0"*32},
    {"request_ref":"link."+"a"*32+"?code=secret"},
])
def test_private_status_rejects_foreign_keys_and_refs(monkeypatch,bad):
    async def go():
        do,broker,sock,cid,code=await verified(monkeypatch)
        with pytest.raises(BrokerPcIdentityHandoffDenied):
            await do.pending_pc_identity_status(bad)
    asyncio.run(go())


def test_private_claim_rejects_foreign_device_and_challenge(monkeypatch):
    async def go():
        do,broker,sock,cid,code=await verified(monkeypatch)
        with pytest.raises(BrokerPcIdentityHandoffDenied):
            await do.claim_pending_pc_identity_proof({
                "request_ref":REF,"challenge_id":"other.challenge",
                "device_id":DEVICE,
            })
        with pytest.raises(BrokerPcIdentityHandoffDenied):
            await do.claim_pending_pc_identity_proof({
                "request_ref":REF,"challenge_id":cid,
                "device_id":"other.device",
            })
        status=await do.pending_pc_identity_status({"request_ref":REF})
        assert status["signed_fetch_verified"] is True
    asyncio.run(go())
