"""Live native DO WSS PC-offer -> signed owner delivery -> REAL canonical
Broker one-use pairing MAC begin/finish. Credential fetch and DPAPI ACK MUST
remain denied until the existing B54 Identity-host authorization runs.

These tests use actual sqlite3 Broker pairing/gateway tables and actual
PC-side HMAC formulas, rather than a forged synthetic crypto-success port.
No Cloudflare upload, DPAPI install, Identity session, or credential transfer.
"""
from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from padiem_control_plane.pending_pc_link import (
    install_pending_pc_link_schema, MIGRATION_ID,
)
from padiem_control_plane.broker_pending_pc_bootstrap import (
    CANONICAL_IDENTITY_HOST_ON_NATIVE_WSS_MOUNTED,
    CANONICAL_DPAPI_ACK_PROVEN,
)
from padiem_control_plane.broker_pending_pc_wss import (
    broker_pending_pc_wss_message,
    fetch_broker_pending_pc_wss,
)
from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref
from canonical_broker_gateway_bootstrap import bootstrap_mac
from test_canonical_broker_pairing_rpc_4139 import Harness
from test_4139_broker_native_pc_wss import (
    DurableObject, Socket, Response, PUBLIC, DEVICE, REF, NONCE, sign, req,
    rows, CODE,
)


async def native_owner_approved(monkeypatch, *, canonical_enabled=True,
                                gateway_enabled=True):
    """One REAL Broker store for both WSS offer and canonical MAC leasing."""
    broker=Harness(limit=5)
    assert (await broker.install_pairing_schema({
        "migration_id":"canonical-broker-pairing-v1",
    }))["ok"] is True
    broker.env.LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED="true"
    issued=await broker.issue_enrollment_challenge({
        "account_ref":"account.owner.1","workspace_ref":"workspace.owner.1",
        "consent_ref":"consent.owner.1","owner_ref":"subject.owner.1",
        "device_id":DEVICE,
    })
    assert issued["ok"] is True
    challenge=issued["challenge"]["challenge_id"]
    code=issued["pairing_code"]
    broker.env.LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_SCHEMA_INSTALL_ENABLED="true"
    installed=await broker.gateway_bootstrap_rpc({
        "operation":"install",
        "args":{"migration_id":"canonical-broker-gateway-bootstrap-v1"},
    })
    assert installed["ok"] is True
    broker.env.LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_SCHEMA_INSTALLED = (
        "true" if gateway_enabled else "false"
    )
    broker.env.LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_ENABLED = (
        "true" if gateway_enabled else "false"
    )
    install_pending_pc_link_schema(
        storage=broker._storage, migration_id=MIGRATION_ID,operator_gate=True,
    )
    do=DurableObject(storage=broker._storage)
    do.env.LOCAL_AGENT_BROKER_PENDING_PC_CANONICAL_BOOTSTRAP_ENABLED=(
        "enabled" if canonical_enabled else "off"
    )
    # B54 canonical host has NOT been injected. Here the DO only holds
    # its OWN Broker pairing MAC operation, not any Identity permission.
    do.gateway_bootstrap_rpc = broker.gateway_bootstrap_rpc
    fake_workers=__import__("types").ModuleType("workers")
    fake_workers.Response=Response
    monkeypatch.setitem(__import__("sys").modules,"workers",fake_workers)
    client,server=Socket(),Socket()
    async def verify(*, public_key,signature,transcript):
        from test_4139_broker_native_pc_wss import verify_native
        return await verify_native(
            public_key=public_key, signature=signature, transcript=transcript,
        )
    response=await fetch_broker_pending_pc_wss(
        do,req(),pair_factory=lambda:((client,server),Response),
        verifier=verify,nonce_factory=lambda:NONCE,ref_factory=lambda:REF,
    )
    assert response.status==101
    await broker_pending_pc_wss_message(do,server,json.dumps({
        "type":"pc_offer_begin","device_id":DEVICE,
        "public_key_b64":base64.b64encode(PUBLIC).decode(),
    }))
    transcript=(
        b"padiem.connector-pending-pc.v1\n"
        +DEVICE.encode("ascii")+b"\n"+bytes.fromhex(NONCE)+b"\n"+PUBLIC
    )
    await broker_pending_pc_wss_message(do,server,json.dumps({
        "type":"pc_offer_prove","signature_b64":sign(transcript),
    }))
    assert server.sent[-1]["type"]=="pc_offer_ready"
    await do.reserve_pending_pc_link({"request_ref":REF})
    delivered=await do.deliver_pending_pc_link({
        "request_ref":REF,"device_id":DEVICE,
        "challenge_id":challenge,"pairing_code":code,
    })
    assert delivered == {
        "ok":True,"sent_once":True,"registered":False,"connected":False,
    }
    assert server.sent[-1]["type"]=="pc_offer_approved"
    assert server.sent[-1]["pairing_code"]==code
    return do,broker,server,challenge,code


def test_existing_real_broker_pairing_code_can_begin_and_finish_on_same_socket(monkeypatch):
    async def go():
        do,broker,server,cid,code=await native_owner_approved(monkeypatch)
        proof=pairing_proof_ref(
            challenge_id=cid,device_id=DEVICE,pairing_code=code,
        )
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"begin","challenge_id":cid,"device_id":DEVICE,
            "proof_ref":proof,
        }))
        receipt=server.sent[-1]
        assert receipt["type"]=="nonce"
        assert receipt["challenge_id"]==cid
        assert receipt["device_id"]==DEVICE
        assert receipt["nonce_hex"]
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"finish","lease_ref":receipt["lease_ref"],
            "proof_hex":bootstrap_mac(
                pairing_code=code,challenge_id=cid,device_id=DEVICE,
                nonce_hex=receipt["nonce_hex"],lease_ref=receipt["lease_ref"],
            ),
        }))
        assert server.sent[-1]=={
            "type":"bootstrap_verified","lease_ref":receipt["lease_ref"],
            "credential":False,
        }
        assert server.readyState==1
        assert rows(do._storage)[0]["state"]=="delivery_claimed"
        gw=broker._storage.sql.exec(
            "SELECT * FROM canonical_local_agent_gateway_bootstrap",
        ).toArray()
        assert len(gw)==1 and gw[0]["verified_at"] is not None
        original=broker._storage.sql.exec(
            "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge",
        ).toArray()
        assert len(original)==1 and original[0]["redeemed_at"] is None
        # It must NOT manufacture credential authority or DPAPI ACK.
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"credential_fetch","counter":1,"proof_hex":"f"*64,
        }))
        assert server.closes
        assert all(frame.get("type")!="credential_once" for frame in server.sent)
        assert all(frame.get("status")!="paired_offline" for frame in server.sent)
        assert broker._storage.sql.exec(
            "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge",
        ).toArray()[0]["redeemed_at"] is None
    asyncio.run(go())
    assert CANONICAL_IDENTITY_HOST_ON_NATIVE_WSS_MOUNTED is False
    assert CANONICAL_DPAPI_ACK_PROVEN is False


def test_default_post_approval_canonical_gate_is_off(monkeypatch):
    async def go():
        do,broker,server,cid,code=await native_owner_approved(
            monkeypatch,canonical_enabled=False,
        )
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"begin","challenge_id":cid,"device_id":DEVICE,
            "proof_ref":pairing_proof_ref(
                challenge_id=cid,device_id=DEVICE,pairing_code=code,
            ),
        }))
        assert server.closes
        assert all(f.get("type")!="nonce" for f in server.sent)
        assert broker._storage.sql.exec(
            "SELECT * FROM canonical_local_agent_gateway_bootstrap",
        ).toArray()==[]
    asyncio.run(go())


def test_forged_begin_cannot_mint_canonical_broker_lease(monkeypatch):
    async def go():
        do,broker,server,cid,code=await native_owner_approved(monkeypatch)
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"begin","challenge_id":cid,"device_id":DEVICE,
            "proof_ref":"pairing-proof:"+"f"*64,
        }))
        assert server.closes
        assert broker._storage.sql.exec(
            "SELECT * FROM canonical_local_agent_gateway_bootstrap",
        ).toArray()==[]
    asyncio.run(go())


def test_gateway_schema_gate_off_denies_real_signed_begin(monkeypatch):
    async def go():
        do,broker,server,cid,code=await native_owner_approved(
            monkeypatch,gateway_enabled=False,
        )
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"begin","challenge_id":cid,"device_id":DEVICE,
            "proof_ref":pairing_proof_ref(
                challenge_id=cid,device_id=DEVICE,pairing_code=code,
            ),
        }))
        assert server.closes
        assert all(f.get("type")!="nonce" for f in server.sent)
    asyncio.run(go())


def test_duplicate_begin_consumes_one_nonce_only(monkeypatch):
    async def go():
        do,broker,server,cid,code=await native_owner_approved(monkeypatch)
        frame={
            "type":"begin","challenge_id":cid,"device_id":DEVICE,
            "proof_ref":pairing_proof_ref(
                challenge_id=cid,device_id=DEVICE,pairing_code=code,
            ),
        }
        await broker_pending_pc_wss_message(do,server,json.dumps(frame))
        assert server.sent[-1]["type"]=="nonce"
        await broker_pending_pc_wss_message(do,server,json.dumps(frame))
        assert server.closes
        assert len(broker._storage.sql.exec(
            "SELECT * FROM canonical_local_agent_gateway_bootstrap",
        ).toArray())==1
    asyncio.run(go())


@pytest.mark.parametrize("frame",[
    {"type":"finish","lease_ref":"gateway."+"e"*32,"proof_hex":"f"*64},
    {"type":"begin","challenge_id":"other.challenge","device_id":DEVICE,
     "proof_ref":"pairing-proof:"+"e"*64},
    {"type":"install_ack","counter":2,"proof_hex":"f"*64,"body_b64":""},
])
def test_unexpected_approval_phase_frames_cannot_redeem(monkeypatch,frame):
    async def go():
        do,broker,server,cid,code=await native_owner_approved(monkeypatch)
        await broker_pending_pc_wss_message(do,server,json.dumps(frame))
        assert server.closes
        assert broker._storage.sql.exec(
            "SELECT * FROM canonical_local_agent_gateway_bootstrap",
        ).toArray()==[]
    asyncio.run(go())


def test_wrong_finish_mac_never_marks_broker_gateway_verified(monkeypatch):
    async def go():
        do,broker,server,cid,code=await native_owner_approved(monkeypatch)
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"begin","challenge_id":cid,"device_id":DEVICE,
            "proof_ref":pairing_proof_ref(
                challenge_id=cid,device_id=DEVICE,pairing_code=code,
            ),
        }))
        lease=server.sent[-1]["lease_ref"]
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"finish","lease_ref":lease,"proof_hex":"e"*64,
        }))
        assert server.closes
        assert all(f.get("type")!="bootstrap_verified" for f in server.sent)
        assert broker._storage.sql.exec(
            "SELECT verified_at FROM canonical_local_agent_gateway_bootstrap",
        ).toArray()[0]["verified_at"] is None
    asyncio.run(go())
