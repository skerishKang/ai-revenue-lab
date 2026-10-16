"""Native SAME canonical Broker DO WSS secret transfer + original signed ACK.

These are *real* SQLite Broker MAC/counter tests and a synthetic raw WebSocket
with generated device install transcript. They are NOT live Cloudflare or a
real Windows DPAPI readback; only B54's existing Host may verify the original
credential-keyed proof and final Identity consent.
"""
from __future__ import annotations
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import pytest

from canonical_broker_gateway_bootstrap import session_mac
from padiem_control_plane.broker_pending_pc_native_delivery import (
    NativePcDeliveryDenied,
    NATIVE_PC_DELIVERY_PUBLIC_ROUTE_MOUNTED,
    NATIVE_PC_DELIVERY_PRODUCTION_ENABLED,
)
from test_4139_broker_identity_pc_handoff import verified, REF, DEVICE

SECRET = b"fixture-real-canonical-credential-32byte"
BINDING = {
    "binding_ref":"pairing-binding.1","device_id":DEVICE,
    "account_ref":"account.owner.1","workspace_ref":"workspace.owner.1",
    "credential_ref":"credential.1","credential_generation":1,
    "credential_expires_at": (
        datetime.now(timezone.utc)+timedelta(days=7)
    ).isoformat(),
}


async def transport(monkeypatch, *, enabled=True, rpc_wrapped=False):
    do, broker, sock, challenge, code = await verified(monkeypatch)
    do.env.LOCAL_AGENT_BROKER_PENDING_PC_NATIVE_DELIVERY_ENABLED=(
        "enabled" if enabled else "off"
    )
    if rpc_wrapped:
        class RpcPayload:
            def __init__(self, value): self.value = value
            def to_py(self): return dict(self.value)

        for name in (
            "pending_pc_identity_status", "claim_pending_pc_identity_proof",
            "reserve_native_pc_gateway", "authenticate_native_pc_gateway",
            "transfer_native_pc_credential_once", "receive_native_pc_install_ack",
            "authenticate_native_pc_install_ack",
        ):
            original = getattr(do, name)
            async def wrapped(payload, _original=original):
                return await _original(RpcPayload(payload))
            setattr(do, name, wrapped)
        status = await do.pending_pc_identity_status({"request_ref": REF})
        assert status["signed_fetch_verified"] is True
    await do.claim_pending_pc_identity_proof({
        "request_ref":REF,"challenge_id":challenge,"device_id":DEVICE,
    })
    proof = next(x for x in sock.sent if x["type"]=="nonce")
    return do,broker,sock,challenge,code,proof


def reserve_args(challenge):
    return {"request_ref":REF,"challenge_id":challenge,"device_id":DEVICE}


def lease_args(challenge, lease):
    return {**reserve_args(challenge),"lease_ref":lease}


async def reserve(do, challenge):
    result=await do.reserve_native_pc_gateway(reserve_args(challenge))
    assert result["authenticated"] is True
    assert result["credential_issued"] is False
    assert result["request_ref"]==REF
    return result["lease_ref"]


async def send(do, challenge, lease, *, credential=SECRET, binding=None):
    return await do.transfer_native_pc_credential_once({
        **lease_args(challenge, lease),
        "binding":dict(BINDING if binding is None else binding),
        "credential_b64":base64.b64encode(credential).decode("ascii"),
    })


def ack_frame(*, challenge, code, nonce, lease, credential=SECRET, binding=None):
    b = BINDING if binding is None else binding
    transcript="\n".join((
        "padiem.connector-device-install-ack.v1",challenge,DEVICE,
        b["binding_ref"],str(b["credential_generation"]),
    )).encode()
    install_proof=hmac.new(credential,transcript,hashlib.sha256).hexdigest()
    ack={
        "challenge_id":challenge,"device_id":DEVICE,
        "binding_ref":b["binding_ref"],"credential_generation":b["credential_generation"],
        "proof_kind":"protected_store_save_readback",
        "transcript_version":"padiem.connector-device-install-ack.v1",
        "local_store_confirmed":True,"proof_hex":install_proof,
    }
    body=json.dumps(ack,sort_keys=True,separators=(",",":")).encode()
    encoded=base64.b64encode(body).decode("ascii")
    return {"type":"install_ack","counter":2,"body_b64":encoded,
            "proof_hex":session_mac(
                pairing_code=code,challenge_id=challenge,device_id=DEVICE,
                nonce_hex=nonce,lease_ref=lease,action="install_ack",counter=2,
                payload_sha256=hashlib.sha256(body).hexdigest(),
            )},ack


@pytest.mark.parametrize("rpc_wrapped", [False, True])
def test_same_native_pc_wss_delivers_exactly_one_secret_and_signed_ack(monkeypatch, rpc_wrapped):
    async def main():
        do,broker,sock,challenge,code,nonce=await transport(monkeypatch, rpc_wrapped=rpc_wrapped)
        lease=await reserve(do,challenge)
        auth=await do.authenticate_native_pc_gateway(lease_args(challenge,lease))
        assert auth["authenticated"] is True
        # This is a real canonical Broker one-use redemption, simulated as
        # the existing B54 Identity-approved Host call. The test cannot
        # substitute for the separate B54 Identity/owner authorization.
        from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref
        redeemed=await broker.redeem_enrollment({
            "challenge_id":challenge,"device_id":DEVICE,
            "proof_ref":pairing_proof_ref(
                challenge_id=challenge,device_id=DEVICE,pairing_code=code,
            ),
            "consent_ref":"consent.owner.1","owner_ref":"subject.owner.1",
            "account_ref":"account.owner.1","workspace_ref":"workspace.owner.1",
        })
        assert redeemed["ok"] is True
        actual=base64.b64decode(redeemed["credential_b64"],validate=True)
        binding={k:redeemed["enrollment"][k] for k in BINDING}
        result=await send(do,challenge,lease,credential=actual,binding=binding)
        assert result=={
            "sent_once":True,"credential_installed":False,"registered":False,
        }
        delivered=sock.sent[-1]
        assert delivered["type"]=="credential_once"
        assert base64.b64decode(delivered["credential_b64"])==actual
        assert delivered["binding"]==binding
        with pytest.raises(NativePcDeliveryDenied):
            await send(do,challenge,lease,credential=actual,binding=binding)
        frame,ack=ack_frame(
            challenge=challenge,code=code,credential=actual,binding=binding,
            nonce=nonce["nonce_hex"],lease=lease,
        )
        task=asyncio.create_task(do.receive_native_pc_install_ack(
            lease_args(challenge,lease)
        ))
        await asyncio.sleep(0)
        await do.webSocketMessage(sock,json.dumps(frame))
        receipt=await task
        assert receipt=={
            "ack":ack,"source_authenticated":True,"registered":False,
        }
        sender=await do.authenticate_native_pc_install_ack({
            **lease_args(challenge,lease),"ack":ack,
        })
        assert sender=={"source_authenticated":True,"registered":False}
        assert sock.closes==[]
        assert broker._storage.sql.exec(
            "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge"
        ).toArray()[0]["redeemed_at"] is not None
        # Broker challenge consumed, but neither socket send nor self-asserted
        # ACK is a final Windows DPAPI installation or online-state grant.
        assert not any(x.get("status")=="paired_offline" for x in sock.sent)
        assert len([x for x in sock.sent if x["type"]=="credential_once"])==1
    asyncio.run(main())


def test_default_off_delivery_cannot_mint_or_expose_secret(monkeypatch):
    async def main():
        do,broker,sock,challenge,code,nonce=await transport(
            monkeypatch,enabled=False,
        )
        with pytest.raises(NativePcDeliveryDenied,match="disabled"):
            await do.reserve_native_pc_gateway(reserve_args(challenge))
        assert not any(x.get("type")=="credential_once" for x in sock.sent)
    asyncio.run(main())
    assert NATIVE_PC_DELIVERY_PUBLIC_ROUTE_MOUNTED is False
    assert NATIVE_PC_DELIVERY_PRODUCTION_ENABLED is False


def test_send_requires_same_DO_claim_once_and_same_original_lease(monkeypatch):
    async def main():
        do,broker,sock,challenge,code,nonce=await transport(monkeypatch)
        with pytest.raises(NativePcDeliveryDenied):
            await send(do,challenge,"gateway."+"0"*32)
        lease=await reserve(do,challenge)
        with pytest.raises(NativePcDeliveryDenied):
            await reserve(do,challenge)
        with pytest.raises(NativePcDeliveryDenied):
            await do.authenticate_native_pc_gateway(
                lease_args("other.challenge",lease)
            )
        # A forged challenge/lease cannot even send an empty fake credential.
        assert len([x for x in sock.sent if x["type"]=="credential_once"])==0
    asyncio.run(main())


def test_invalid_device_ACK_MAC_closes_socket_without_positive_receipt(monkeypatch):
    async def main():
        do,broker,sock,challenge,code,nonce=await transport(monkeypatch)
        lease=await reserve(do,challenge)
        await send(do,challenge,lease)
        frame,ack=ack_frame(
            challenge=challenge,code=code,
            nonce=nonce["nonce_hex"],lease=lease,
        )
        frame["proof_hex"]="f"*64
        await do.webSocketMessage(sock,json.dumps(frame))
        assert sock.closes
        with pytest.raises(NativePcDeliveryDenied):
            await do.receive_native_pc_install_ack(lease_args(challenge,lease))
        assert broker._storage.sql.exec(
            "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge"
        ).toArray()[0]["redeemed_at"] is None
    asyncio.run(main())


def test_disconnected_native_socket_refuses_secret_before_send(monkeypatch):
    async def main():
        do,broker,sock,challenge,code,nonce=await transport(monkeypatch)
        lease=await reserve(do,challenge)
        sock.close(1008,"")
        with pytest.raises(NativePcDeliveryDenied):
            await send(do,challenge,lease)
        assert all(x.get("type")!="credential_once" for x in sock.sent)
    asyncio.run(main())
