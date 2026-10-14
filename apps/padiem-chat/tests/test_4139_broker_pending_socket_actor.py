"""Same-Broker-DO socket actor, real Ed25519 PoP on synthetic WSS frames.

No mounted endpoint, Cloudflare isolate, real owner OAuth or Windows DPAPI.
The tests enforce precisely the conditions that need a future private DO RPC.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import json

import pytest

from app.connector_broker_pending_socket_actor import (
    CanonicalBrokerPendingSocketActor, PendingSocketActorRefused,
    SOCKET_ACTOR_ENABLED_IN_WORKER, SOCKET_ACTOR_WSS_ROUTE_MOUNTED,
    SOCKET_ACTOR_OWNER_RPC_EXPORTED,
)
from app.connector_one_click_approval import OneClickOwnerApproval, OneClickDenied
from app.connector_worker_webcrypto_verify import CloudflareWorkerEd25519Verifier
from canonical_broker_pending_pc_link import install_pending_pc_link_schema, MIGRATION_ID
from test_4139_pending_pc_delivery_adapter import Storage
from test_4139_pending_pc_offer_gateway import (
    FakeSocket, TrustedIngress, _PUBLIC, _node_crypto, ownership_transcript,
)
from test_4139_connector_one_click_approval import Fixture, session

REF = "link." + "a"*32
DEVICE = "windows.device.1"
NONCE = "c"*64
CODE = "b"*32


class BytesFactory:
    @staticmethod
    def new(size):
        return [0]*size


class NativeFixture:
    """Trusted mock of Workers js.crypto.subtle, backed by actual Node crypto."""
    async def importKey(self, fmt, key, algorithm, extractable, usages):
        assert (fmt,algorithm,extractable,usages)==("raw","Ed25519",False,["verify"])
        return bytes(key)

    async def verify(self, algorithm, key, signature, transcript):
        assert algorithm=="Ed25519"
        return _node_crypto(
            operation="verify", public=key, signature=bytes(signature),
            transcript=bytes(transcript),
        )


def actor(*, signed=True, schema=True):
    socket=FakeSocket()
    storage=Storage()
    if schema:
        install_pending_pc_link_schema(
            storage=storage, migration_id=MIGRATION_ID, operator_gate=True,
        )
    subtle=NativeFixture()
    verifier=CloudflareWorkerEd25519Verifier(
        runtime_loader=lambda: (subtle, BytesFactory, lambda v: v),
    )
    if signed is False:
        class DeniedSubtle(NativeFixture):
            async def verify(self, *a):
                return False
        verifier=CloudflareWorkerEd25519Verifier(
            runtime_loader=lambda: (DeniedSubtle(),BytesFactory,lambda v: v),
        )
    item=CanonicalBrokerPendingSocketActor(
        canonical_broker_storage=storage, socket=socket,
        trusted_ingress=TrustedIngress(), key_verifier=verifier,
        ref_factory=lambda:REF, nonce_factory=lambda:NONCE,
    )
    return item,socket,storage


async def begin(item, socket):
    task=asyncio.create_task(item.begin_and_wait())
    await socket.input.put(json.dumps({
        "type":"pc_offer_begin", "device_id":DEVICE,
        "public_key_b64":base64.b64encode(_PUBLIC).decode(),
    }))
    first=json.loads(await asyncio.wait_for(socket.output.get(),3))
    assert first=={
        "type":"pc_offer_challenge", "device_id":DEVICE, "nonce_hex":NONCE,
    }
    signature=_node_crypto(
        operation="sign", transcript=ownership_transcript(
            device_id=DEVICE, nonce_hex=NONCE, public_key=_PUBLIC,
        ),
    )
    await socket.input.put(json.dumps({
        "type":"pc_offer_prove", "signature_b64":base64.b64encode(signature).decode(),
    }))
    return task


async def offer(item,socket):
    task=await begin(item,socket)
    ready=json.loads(await asyncio.wait_for(socket.output.get(),3))
    assert ready["type"]=="pc_offer_ready" and ready["request_ref"]==REF
    # Actor wait-loop is attached to this socket, not a process-global map.
    await asyncio.sleep(0)
    return task


def stored(storage):
    return storage.exec("SELECT * FROM canonical_broker_pending_pc_link").toArray()


def test_one_do_socket_actor_delivers_once_and_retains_socket_for_real_dpapi_ack():
    async def run():
        item,sock,storage=actor()
        pending=await offer(item,sock)
        issuer=Fixture()
        owner=OneClickOwnerApproval(
            identity=issuer,host=issuer,pc_rendezvous=item,
        )
        outcome=await owner.approve(
            owner_session=session(),request_ref=REF,confirmed=True,
        )
        assert outcome["state"]=="awaiting_device_confirmation"
        assert outcome["registered"] is False
        message=json.loads(await asyncio.wait_for(sock.output.get(),2))
        assert message=={
            "type":"pc_offer_approved","device_id":DEVICE,
            "request_ref":REF,"challenge_id":"challenge.1","pairing_code":CODE,
        }
        result=await asyncio.wait_for(pending,2)
        assert result=={
            "state":"awaiting_canonical_dpapi_ack","request_ref":REF,
            "registered":False,"connected":False,
        }
        assert sock.closed is False  # Existing WSS handler MUST now continue.
        assert stored(storage)[0]["state"]=="delivery_claimed"
        assert CODE not in repr(stored(storage))
        with pytest.raises(OneClickDenied,match="pending_pc_unavailable"):
            await owner.approve(
                owner_session=session(),request_ref=REF,confirmed=True,
            )
        assert len(sock.output._queue)==0
    asyncio.run(run())


def test_disconnected_socket_cannot_use_owner_approval_or_mint_code():
    async def run():
        item,sock,storage=actor()
        pending=await offer(item,sock)
        item.mark_disconnected()
        with pytest.raises(PendingSocketActorRefused,match="unconfirmed"):
            await asyncio.wait_for(pending,2)
        with pytest.raises(PendingSocketActorRefused,match="unavailable"):
            await item.reserve_once(request_ref=REF)
        assert sock.closed is True
        assert stored(storage)[0]["state"]=="pending"
    asyncio.run(run())


def test_other_actor_instance_cannot_reach_live_offer_or_use_socket():
    async def run():
        item,sock,storage=actor()
        pending=await offer(item,sock)
        other,_,other_storage=actor()
        with pytest.raises(PendingSocketActorRefused,match="unavailable"):
            await other.reserve_once(request_ref=REF)
        assert stored(other_storage)==[]
        assert stored(storage)[0]["state"]=="pending"
        item.mark_disconnected()
        with pytest.raises(PendingSocketActorRefused):
            await pending
    asyncio.run(run())


def test_wrong_device_on_reserved_offer_does_not_send():
    async def run():
        item,sock,storage=actor()
        pending=await offer(item,sock)
        receipt=await item.reserve_once(request_ref=REF)
        assert receipt["device_id"]==DEVICE
        with pytest.raises(PendingSocketActorRefused,match="delivery_denied"):
            await item.deliver_once(
                request_ref=REF,device_id="other.device.1",
                challenge_id="challenge.1",pairing_code=CODE,
            )
        assert stored(storage)[0]["state"]=="reserved"
        assert sock.output.empty()
        item.mark_disconnected()
        with pytest.raises(PendingSocketActorRefused):
            await pending
    asyncio.run(run())


def test_source_only_schema_missing_refuses_offer_before_registration():
    async def run():
        item,sock,storage=actor(schema=False)
        pending=await begin(item,sock)
        with pytest.raises(PendingSocketActorRefused,match="unconfirmed"):
            await asyncio.wait_for(pending,3)
        assert sock.closed is True
        assert storage.exec(
            "SELECT name FROM sqlite_master WHERE name='canonical_broker_pending_pc_link'"
        ).toArray()==[]
    asyncio.run(run())


def test_signature_failure_refuses_without_storage_mutation():
    async def run():
        item,sock,storage=actor(signed=False)
        pending=await begin(item,sock)
        with pytest.raises(PendingSocketActorRefused,match="unconfirmed"):
            await asyncio.wait_for(pending,3)
        assert sock.closed is True
        assert stored(storage)==[]
    asyncio.run(run())


def test_wrong_verifier_and_untrusted_socket_closed_value_denied_at_constructor():
    sock=FakeSocket()
    storage=Storage()
    with pytest.raises(ValueError,match="Worker-native"):
        CanonicalBrokerPendingSocketActor(
            canonical_broker_storage=storage,socket=sock,
            trusted_ingress=TrustedIngress(),key_verifier=object(),
        )
    sock.closed=True
    with pytest.raises(ValueError,match="closed property"):
        CanonicalBrokerPendingSocketActor(
            canonical_broker_storage=storage,socket=sock,
            trusted_ingress=TrustedIngress(),
            key_verifier=CloudflareWorkerEd25519Verifier(),
        )


def test_no_default_worker_actor_route_or_owner_private_rpc():
    assert SOCKET_ACTOR_ENABLED_IN_WORKER is False
    assert SOCKET_ACTOR_WSS_ROUTE_MOUNTED is False
    assert SOCKET_ACTOR_OWNER_RPC_EXPORTED is False


def test_same_preaccepted_wss_continues_into_canonical_gateway_once(monkeypatch):
    from types import SimpleNamespace
    import app.connector_gateway_websocket_session as canonical_module
    from app.connector_broker_pending_socket_actor import (
        run_approved_pc_offer_then_canonical_session,
        _PreacceptedCanonicalSocket,
    )

    async def run():
        item,sock,storage=actor()
        entered=[]
        async def mock_gateway(socket, *, trusted_tls, broker, host_factory):
            assert type(socket) is _PreacceptedCanonicalSocket
            assert socket._raw_socket is sock
            assert callable(broker.gateway_bootstrap_rpc)
            assert callable(host_factory)
            assert sock.accept_calls == 1
            await socket.accept()  # canonical original accepts once
            assert sock.accept_calls == 1  # NO SECOND physical ASGI accept
            with pytest.raises(PendingSocketActorRefused,match="double_accept"):
                await socket.accept()
            await socket.send_text('{"type":"canonical_frame"}')
            entered.append(1)
            await socket.close(code=1000)

        monkeypatch.setattr(
            canonical_module,"run_device_initiated_enrollment",mock_gateway,
        )
        host=SimpleNamespace(gateway_bootstrap_rpc=lambda x: None)
        pending=asyncio.create_task(
            run_approved_pc_offer_then_canonical_session(
                actor=item,socket=sock,trusted_tls=TrustedIngress(),
                canonical_broker=host,host_factory=lambda **kw: object(),
            )
        )
        await sock.input.put(json.dumps({
            "type":"pc_offer_begin", "device_id":DEVICE,
            "public_key_b64":base64.b64encode(_PUBLIC).decode(),
        }))
        first=json.loads(await asyncio.wait_for(sock.output.get(),3))
        assert first["type"]=="pc_offer_challenge"
        signature=_node_crypto(operation="sign",transcript=ownership_transcript(
            device_id=DEVICE,nonce_hex=NONCE,public_key=_PUBLIC,
        ))
        await sock.input.put(json.dumps({
            "type":"pc_offer_prove",
            "signature_b64":base64.b64encode(signature).decode(),
        }))
        ready=json.loads(await asyncio.wait_for(sock.output.get(),3))
        assert ready["type"]=="pc_offer_ready"
        canonical=Fixture()
        owner=OneClickOwnerApproval(
            identity=canonical,host=canonical,pc_rendezvous=item,
        )
        done=await owner.approve(
            owner_session=session(),request_ref=REF,confirmed=True,
        )
        assert done["connected"] is False
        delivered=json.loads(await sock.output.get())
        assert delivered["type"]=="pc_offer_approved"
        assert delivered["pairing_code"]==CODE
        await asyncio.wait_for(pending,3)
        continuation=json.loads(await sock.output.get())
        assert continuation["type"]=="canonical_frame"
        assert entered==[1]
        assert sock.accept_calls == 1
        assert sock.closed is True
        with pytest.raises(PendingSocketActorRefused):
            await item.reserve_once(request_ref=REF)
    asyncio.run(run())


def test_canonical_upgrade_with_wrong_socket_does_not_emit_frames():
    from types import SimpleNamespace
    from app.connector_broker_pending_socket_actor import (
        run_approved_pc_offer_then_canonical_session,
    )
    async def run():
        item,sock,storage=actor()
        foreign=FakeSocket()
        with pytest.raises(PendingSocketActorRefused,match="canonical_boundary"):
            await run_approved_pc_offer_then_canonical_session(
                actor=item,socket=foreign,
                trusted_tls=TrustedIngress(),
                canonical_broker=SimpleNamespace(gateway_bootstrap_rpc=lambda x:None),
                host_factory=lambda **kw:None,
            )
        assert sock.accept_calls==0
        assert foreign.accept_calls==0
        assert stored(storage)==[]
    asyncio.run(run())


def test_revoked_tls_before_owner_approval_does_not_reserve_or_mint_challenge():
    async def run():
        item, sock, storage = actor()
        pending = await offer(item, sock)
        item._trusted_ingress.ok = False
        with pytest.raises(PendingSocketActorRefused, match="ingress_denied"):
            await item.reserve_once(request_ref=REF)
        assert stored(storage)[0]["state"] == "pending"
        assert sock.output.empty()
        item.mark_disconnected()
        with pytest.raises(PendingSocketActorRefused):
            await pending
    asyncio.run(run())


def test_revoked_tls_after_owner_reservation_cannot_claim_delivery_slot():
    async def run():
        item, sock, storage = actor()
        pending = await offer(item, sock)
        await item.reserve_once(request_ref=REF)
        item._trusted_ingress.ok = False
        with pytest.raises(PendingSocketActorRefused, match="ingress_denied"):
            await item.deliver_once(
                request_ref=REF, device_id=DEVICE,
                challenge_id="challenge.1", pairing_code=CODE,
            )
        assert stored(storage)[0]["state"] == "reserved"
        assert sock.output.empty()
        item.mark_disconnected()
        with pytest.raises(PendingSocketActorRefused):
            await pending
    asyncio.run(run())


def test_tls_verification_must_precede_actual_wss_upgrade_and_any_frames():
    async def run():
        item,sock,storage=actor()
        item._trusted_ingress.ok=False
        with pytest.raises(PendingSocketActorRefused,match="unconfirmed"):
            await item.begin_and_wait()
        assert sock.accept_calls==0
        assert sock.output.empty()
        assert sock.closed is True
        assert stored(storage)==[]
    asyncio.run(run())
