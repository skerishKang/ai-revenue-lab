"""Real Cloudflare Python DO WebSocketPair API contract with native socket fakes.

RFC8032 fixed Ed25519 test key is signed by node:crypto, verification is
performed against the identical domain-separated transcript. No Worker
deploy/migration/real PC/DPAPI ACK is claimed.
"""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

import pytest

from padiem_control_plane.pending_pc_link import (
    install_pending_pc_link_schema, MIGRATION_ID,
)
from padiem_control_plane.broker_pending_pc_private_rpc import (
    CanonicalBrokerPendingPcLiveRPC, BrokerPendingPcPrivateRefused,
)
from padiem_control_plane.broker_pending_pc_wss import (
    fetch_broker_pending_pc_wss, broker_pending_pc_wss_message,
    broker_pending_pc_wss_close, native_ed25519_verify,
    WSS_REVIEW_PATH, WSS_PRODUCTION_ENABLED, WSS_PUBLIC_FETCH_MOUNTED,
    WSS_HIBERNATED_SESSION_RESTORE_ENABLED,
)
from test_4139_pending_pc_link_durable import Storage, rows

PUBLIC = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
DEVICE = "windows.device.1"
REF = "link."+"a"*32
NONCE = "b"*64
CODE = "d"*32
SIGN_SCRIPT = r"""
const c=require('node:crypto');
const pk=c.createPrivateKey({
 key:Buffer.concat([
   Buffer.from('302e020100300506032b657004220420','hex'),
   Buffer.from(process.argv[1],'hex')
 ]), format:'der',type:'pkcs8'
});
process.stdout.write(c.sign(null,Buffer.from(process.argv[2],'hex'),pk).toString('base64'));
"""
VERIFY_SCRIPT = r"""
const c=require('node:crypto');
const pub=c.createPublicKey({
 key:Buffer.concat([
   Buffer.from('302a300506032b6570032100','hex'),
   Buffer.from(process.argv[1],'hex')
 ]),format:'der',type:'spki'
});
process.stdout.write(c.verify(null,Buffer.from(process.argv[2],'hex'),
 pub,Buffer.from(process.argv[3],'base64'))?'1':'0');
"""


def sign(transcript):
    if not shutil.which("node"):
        pytest.skip("Node native Ed25519 unavailable")
    return subprocess.check_output(
        ["node","-e",SIGN_SCRIPT,SEED,transcript.hex()],timeout=8,
    ).decode()


async def verify_native(*, public_key, signature, transcript):
    if not shutil.which("node"):
        pytest.skip("Node native Ed25519 unavailable")
    code=subprocess.check_output(
        ["node","-e",VERIFY_SCRIPT,public_key.hex(),transcript.hex(),
         base64.b64encode(signature).decode()],timeout=8,
    )
    return code == b"1"


class Socket:
    def __init__(self):
        self.readyState=1
        self.sent=[]
        self.tag=None
        self.closes=[]
    def serializeAttachment(self, value):
        self.tag=value
    def deserializeAttachment(self):
        return self.tag
    def send(self, raw):
        assert self.readyState==1
        self.sent.append(json.loads(raw))
    def close(self, code, reason):
        self.closes.append((code,reason))
        self.readyState=3


class Context:
    def __init__(self):
        self.accepted=[]
    def acceptWebSocket(self,socket):
        self.accepted.append(socket)


class Response:
    def __init__(self, content=None, *, status, web_socket=None, headers=None):
        self.content=content
        self.status=status
        self.web_socket=web_socket
        self.headers=headers or {}


class DurableObject(CanonicalBrokerPendingPcLiveRPC):
    def __init__(self, storage=None, *, enabled=True):
        self._storage=storage or Storage()
        self._pending_pc_ctx=Context()
        self.env=SimpleNamespace(
            LOCAL_AGENT_BROKER_PENDING_PC_OWNER_RPC_ENABLED="enabled" if enabled else "off",
            LOCAL_AGENT_BROKER_PENDING_PC_SCHEMA_INSTALLED="installed" if enabled else "off",
            LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE="isolated-operator-acceptance-4139",
            LOCAL_AGENT_BROKER_PENDING_PC_WSS_ENABLED="enabled" if enabled else "off",
        )


def req(**headers):
    return SimpleNamespace(
        url="https://broker.test"+WSS_REVIEW_PATH,method="GET",
        headers={"upgrade":"websocket", **headers},
    )


async def start(monkeypatch, *, owner=None, request=None, verifier=verify_native,
                installed=True):
    mod=ModuleType("workers")
    mod.Response=Response
    monkeypatch.setitem(sys.modules,"workers",mod)
    do=owner or DurableObject()
    if installed:
        install_pending_pc_link_schema(
            storage=do._storage,migration_id=MIGRATION_ID,operator_gate=True,
        )
    client,server=Socket(),Socket()
    result=await fetch_broker_pending_pc_wss(
        do, request or req(), pair_factory=lambda:((client,server),Response),
        verifier=verifier, nonce_factory=lambda:NONCE, ref_factory=lambda:REF,
    )
    return do,client,server,result


async def handshake(monkeypatch, *, verifier=verify_native, installed=True):
    do,client,server,result=await start(
        monkeypatch,verifier=verifier,installed=installed,
    )
    assert result.status==101 and result.web_socket is client
    assert do._pending_pc_ctx.accepted==[server]
    await broker_pending_pc_wss_message(do,server,json.dumps({
        "type":"pc_offer_begin","device_id":DEVICE,
        "public_key_b64":base64.b64encode(PUBLIC).decode(),
    }))
    assert server.sent[0]=={
        "type":"pc_offer_challenge","device_id":DEVICE,"nonce_hex":NONCE,
    }
    transcript=(
        b"padiem.connector-pending-pc.v1\n"+DEVICE.encode()
        +b"\n"+bytes.fromhex(NONCE)+b"\n"+PUBLIC
    )
    await broker_pending_pc_wss_message(do,server,json.dumps({
        "type":"pc_offer_prove", "signature_b64":sign(transcript),
    }))
    return do,client,server,result


def test_real_native_ws_accept_and_same_broker_do_private_owner_delivery(monkeypatch):
    async def main():
        do,client,server,result=await handshake(monkeypatch)
        assert len(rows(do._storage))==1
        assert server.sent[1]["type"]=="pc_offer_ready"
        assert server.sent[1]["request_ref"]==REF
        assert server.sent[1]["device_id"]==DEVICE
        assert do._pending_pc_live_by_ref[REF]._socket.raw is server
        answer=await do.reserve_pending_pc_link({"request_ref":REF})
        assert answer["reserved_once"] is True
        assert answer["connected_to_outbound_channel"] is True
        reply=await do.deliver_pending_pc_link({
            "request_ref":REF,"device_id":DEVICE,
            "challenge_id":"challenge.1","pairing_code":CODE,
        })
        assert reply=={
            "ok":True,"sent_once":True,"registered":False,"connected":False,
        }
        assert server.sent[2]=={
            "type":"pc_offer_approved","request_ref":REF,
            "device_id":DEVICE,"challenge_id":"challenge.1",
            "pairing_code":CODE,
        }
        assert rows(do._storage)[0]["state"]=="delivery_claimed"
        assert CODE not in repr(rows(do._storage))
        assert do._pending_pc_live_by_ref=={}
        with pytest.raises(BrokerPendingPcPrivateRefused):
            await do.deliver_pending_pc_link({
                "request_ref":REF,"device_id":DEVICE,
                "challenge_id":"challenge.1","pairing_code":CODE,
            })
        assert len(server.sent)==3
    asyncio.run(main())


def test_public_fetch_and_owner_flags_default_off(monkeypatch):
    async def main():
        do,client,server,result=await start(
            monkeypatch,owner=DurableObject(enabled=False),installed=False,
        )
        assert result.status==404
        assert do._pending_pc_ctx.accepted==[]
        assert not server.sent
    asyncio.run(main())
    assert WSS_PRODUCTION_ENABLED is False
    assert WSS_PUBLIC_FETCH_MOUNTED is False
    assert WSS_HIBERNATED_SESSION_RESTORE_ENABLED is False


@pytest.mark.parametrize("broken",[
    {"origin":"https://attacker.example"},
    {"cookie":"session=forged"},
    {"sec-websocket-protocol":"random"},
    {"upgrade":"wrong"},
])
def test_bad_headers_deny_before_http_101(monkeypatch,broken):
    async def main():
        do,client,server,result=await start(
            monkeypatch,request=req(**broken),installed=False,
        )
        assert result.status==404
        assert do._pending_pc_ctx.accepted==[]
    asyncio.run(main())


def test_missing_schema_never_auto_migrates_and_fails_closed(monkeypatch):
    async def main():
        do,client,server,result=await handshake(monkeypatch,installed=False)
        assert result.status==101
        assert server.closes
        assert server.sent[0]["type"]=="pc_offer_challenge"
        assert all(frame["type"]!="pc_offer_ready" for frame in server.sent)
        assert do._pending_pc_live_by_ref=={}
        assert do._storage.sql.exec(
            "SELECT name FROM sqlite_master WHERE name='canonical_broker_pending_pc_link'"
        ).toArray()==[]
    asyncio.run(main())


def test_invalid_signature_does_not_create_offer(monkeypatch):
    async def invalid(**kw):
        return False
    async def main():
        do,client,server,result=await handshake(monkeypatch,verifier=invalid)
        assert server.closes
        assert rows(do._storage)==[]
        assert all(frame["type"]!="pc_offer_ready" for frame in server.sent)
    asyncio.run(main())


def test_hibernation_does_not_resurrect_lost_session_key_or_grant(monkeypatch):
    async def main():
        do,client,server,result=await handshake(monkeypatch)
        # Simulate Cloudflare DO hibernation/restart with preserved SQL and
        # existing WebSocket but no in-memory verified key or socket session.
        restarted=DurableObject(storage=do._storage)
        with pytest.raises(BrokerPendingPcPrivateRefused,match="socket_missing"):
            await restarted.reserve_pending_pc_link({"request_ref":REF})
        await broker_pending_pc_wss_message(restarted,server,'{"type":"retry"}')
        assert server.closes
        with pytest.raises(BrokerPendingPcPrivateRefused):
            await do.reserve_pending_pc_link({"request_ref":REF})
    asyncio.run(main())


def test_disconnect_callback_invalidates_pending_offer(monkeypatch):
    async def main():
        do,client,server,result=await handshake(monkeypatch)
        await broker_pending_pc_wss_close(do,server)
        assert server.closes
        assert do._pending_pc_live_by_ref=={}
        with pytest.raises(BrokerPendingPcPrivateRefused):
            await do.reserve_pending_pc_link({"request_ref":REF})
    asyncio.run(main())


def test_replayed_or_duplicate_proof_after_ready_closes_socket(monkeypatch):
    async def main():
        do,client,server,result=await handshake(monkeypatch)
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"pc_offer_prove","signature_b64":"A"*86+"==",
        }))
        assert server.closes
        assert do._pending_pc_live_by_ref=={}
        assert rows(do._storage)[0]["state"]=="pending"
    asyncio.run(main())


def test_real_webcrypto_verifier_refuses_when_runtime_missing():
    assert asyncio.run(native_ed25519_verify(
        public_key=PUBLIC,signature=b"x"*64,transcript=b"test",
    )) is False


@pytest.mark.parametrize("url,method", [
    ("http://broker.test"+WSS_REVIEW_PATH,"GET"),
    ("https://broker.test"+WSS_REVIEW_PATH+"?token=bad","GET"),
    ("https://broker.test"+WSS_REVIEW_PATH+"#x","GET"),
    ("https://broker.test/internal/connector/other","GET"),
    ("https://broker.test"+WSS_REVIEW_PATH,"POST"),
    ("https://user:pass@broker.test"+WSS_REVIEW_PATH,"GET"),
])
def test_foreign_url_or_method_denied_before_native_pair(monkeypatch,url,method):
    async def main():
        do,client,server,response=await start(
            monkeypatch,installed=False,
            request=SimpleNamespace(
                url=url,method=method,headers={"upgrade":"websocket"},
            ),
        )
        assert response.status==404
        assert do._pending_pc_ctx.accepted==[]
    asyncio.run(main())


def test_bad_or_duplicate_frame_never_mints_offer(monkeypatch):
    async def main():
        do,client,server,response=await start(monkeypatch)
        await broker_pending_pc_wss_message(
            do,server,
            '{"type":"pc_offer_begin","type":"pc_offer_begin","device_id":"'+DEVICE+
            '","public_key_b64":"'+base64.b64encode(PUBLIC).decode()+'"}',
        )
        assert server.closes and server.sent==[]
        assert rows(do._storage)==[]
    asyncio.run(main())


def test_concurrent_private_owner_reserve_and_delivery_are_each_once(monkeypatch):
    async def main():
        do,client,server,response=await handshake(monkeypatch)
        reserved=await asyncio.gather(*(
            do.reserve_pending_pc_link({"request_ref":REF})
            for _ in range(2)
        ),return_exceptions=True)
        assert len([x for x in reserved if type(x) is dict])==1
        assert len([x for x in reserved if isinstance(x,Exception)])==1
        delivery={
            "request_ref":REF,"device_id":DEVICE,
            "challenge_id":"challenge.1","pairing_code":CODE,
        }
        results=await asyncio.gather(*(
            do.deliver_pending_pc_link(delivery) for _ in range(2)
        ),return_exceptions=True)
        assert len([x for x in results if type(x) is dict])==1
        assert len([x for x in results if isinstance(x,Exception)])==1
        assert sum(frame["type"]=="pc_offer_approved" for frame in server.sent)==1
        assert rows(do._storage)[0]["state"]=="delivery_claimed"
    asyncio.run(main())


def test_delivered_socket_cannot_accept_forged_enrollment_ack(monkeypatch):
    async def main():
        do,client,server,response=await handshake(monkeypatch)
        await do.reserve_pending_pc_link({"request_ref":REF})
        await do.deliver_pending_pc_link({
            "request_ref":REF,"device_id":DEVICE,
            "challenge_id":"challenge.1","pairing_code":CODE,
        })
        # The canonical post-delivery WSS/DPAPI ACK gateway is NOT mounted.
        # A forged 'success' frame must not mark the device registered.
        await broker_pending_pc_wss_message(do,server,json.dumps({
            "type":"canonical_enrollment_completed","registered":True,
        }))
        assert server.closes
        assert rows(do._storage)[0]["state"]=="delivery_claimed"
        assert all(frame.get("registered") is not True for frame in server.sent)
    asyncio.run(main())


def test_review_entrypoint_routes_upgrade_to_same_authority_ref_do_only(monkeypatch):
    from padiem_control_plane.broker_pending_pc_wss import (
        route_private_pc_wss_upgrade, fetch_broker_pending_pc_wss,
    )
    async def main():
        mock_workers=ModuleType("workers")
        mock_workers.Response=Response
        monkeypatch.setitem(sys.modules,"workers",mock_workers)
        do=DurableObject()
        install_pending_pc_link_schema(
            storage=do._storage,migration_id=MIGRATION_ID,operator_gate=True,
        )
        client,server=Socket(),Socket()
        async def handle(request):
            return await fetch_broker_pending_pc_wss(
                do,request,pair_factory=lambda:((client,server),Response),
                verifier=verify_native,nonce_factory=lambda:NONCE,ref_factory=lambda:REF,
            )
        do.fetch=handle
        calls=[]
        worker=SimpleNamespace(env=do.env,_stub=lambda:do)
        async def existing_http(request,stub_factory):
            calls.append("legacy")
            return Response("legacy",status=404)
        result=await route_private_pc_wss_upgrade(
            worker,req(),existing_http,
        )
        assert result.status==101
        assert result.web_socket is client
        assert do._pending_pc_ctx.accepted == [server]
        assert calls == []
        # Ordinary existing device HTTP is unchanged when no exact Upgrade.
        incoming=SimpleNamespace(
            url="https://broker.test/normal-device-http",method="POST",
            headers={"cookie":"abc"},
        )
        result=await route_private_pc_wss_upgrade(
            worker,incoming,existing_http,
        )
        assert result.status==404 and calls==["legacy"]
        assert len(do._pending_pc_ctx.accepted)==1
    asyncio.run(main())


def test_review_do_caps_unverified_websockets_without_minting_credentials(monkeypatch):
    from padiem_control_plane.broker_pending_pc_wss import MAX_PENDING_PC_WSS_PER_DO
    async def main():
        mock_workers=ModuleType("workers")
        mock_workers.Response=Response
        monkeypatch.setitem(sys.modules,"workers",mock_workers)
        do=DurableObject()
        install_pending_pc_link_schema(
            storage=do._storage,migration_id=MIGRATION_ID,operator_gate=True,
        )
        for i in range(MAX_PENDING_PC_WSS_PER_DO):
            client,server=Socket(),Socket()
            res=await fetch_broker_pending_pc_wss(
                do,req(),pair_factory=lambda:((client,server),Response),
                verifier=verify_native,
            )
            assert res.status==101
        assert len(do._pending_pc_wss_by_id)==MAX_PENDING_PC_WSS_PER_DO
        further=await fetch_broker_pending_pc_wss(
            do,req(),pair_factory=lambda:(_ for _ in ()).throw(
                AssertionError("must not allocate any more sockets")
            ),
        )
        assert further.status==404
        assert rows(do._storage)==[]
    asyncio.run(main())
