"""Real broker app + real loopback WebSocket + synthetic service proof and PC."""
import asyncio
import base64
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.exceptions import InvalidStatusCode, ConnectionClosed
from websockets.legacy.client import connect

from internal_rpc_ingress import proof_for
from pc_offer_asgi import PATH
from padiem_control_plane.pending_pc_link import install_pending_pc_link_schema, MIGRATION_ID
from service import build_app

SECRET = "synthetic-service-" + "x" * 32
DEVICE = "device.test"


def headers(rid):
    at = int(time.time())
    return {"x-padiem-request-id": rid, "x-padiem-service-at": str(at),
            "x-padiem-service-proof": proof_for(SECRET, method="GET", path=PATH, at=at, body=rid.encode())}


@pytest.mark.asyncio
async def test_real_route_challenge_approval_disconnect_and_replay(tmp_path):
    env = {
        "PADIEM_BROKER_RPC_INGRESS_SECRET": SECRET,
        "LOCAL_AGENT_BROKER_PEPPER": "synthetic-pepper-" + "y" * 32,
        "LOCAL_AGENT_BROKER_AUTHORITY_REF": "staging.test",
        "LOCAL_AGENT_BROKER_PENDING_PC_OWNER_RPC_ENABLED": "enabled",
        "LOCAL_AGENT_BROKER_PENDING_PC_SCHEMA_INSTALLED": "installed",
        "LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE": "isolated-operator-acceptance-4139",
        "LOCAL_AGENT_BROKER_PENDING_PC_WSS_ENABLED": "enabled",
    }
    app = build_app(environ=env, db_path=str(tmp_path / "broker.sqlite"))
    storage = app.state.broker_storage
    install_pending_pc_link_schema(storage=storage, migration_id=MIGRATION_ID, operator_gate=True)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(300):
            if server.started: break
            await asyncio.sleep(0.01)
        assert server.started
        ws_url = f"ws://127.0.0.1:{port}{PATH}"
        for bad in ({}, dict(headers("b" * 32), **{"x-padiem-service-proof": "v1=" + "0" * 64})):
            with pytest.raises(InvalidStatusCode):
                async with connect(ws_url, extra_headers=bad): pass
        signed = headers("a" * 32)
        # Deterministic non-production RFC test key, no operational key creation.
        key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        async with connect(ws_url, extra_headers=headers("c" * 32)) as ws:
            await ws.send(json.dumps({"type": "pc_offer_begin", "device_id": DEVICE,
                                      "public_key_b64": base64.b64encode(public).decode()}))
            assert json.loads(await ws.recv())["type"] == "pc_offer_challenge"
            await ws.send(json.dumps({"type": "pc_offer_prove",
                                      "signature_b64": base64.b64encode(bytes(64)).decode()}))
            with pytest.raises(ConnectionClosed):
                await ws.recv()
        async with connect(ws_url, extra_headers=signed) as ws:
            await ws.send(json.dumps({"type": "pc_offer_begin", "device_id": DEVICE,
                                      "public_key_b64": base64.b64encode(public).decode()}))
            challenge = json.loads(await ws.recv())
            assert challenge["type"] == "pc_offer_challenge"
            transcript = (b"padiem.connector-pending-pc.v1\n" + DEVICE.encode() + b"\n"
                          + bytes.fromhex(challenge["nonce_hex"]) + b"\n" + public)
            await ws.send(json.dumps({"type": "pc_offer_prove",
                                      "signature_b64": base64.b64encode(key.sign(transcript)).decode()}))
            ready = json.loads(await ws.recv())
            assert ready["type"] == "pc_offer_ready"
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                async def rpc(method, payload):
                    path = "/internal/rpc/" + method
                    body = json.dumps(payload, separators=(",", ":")).encode()
                    at = int(time.time())
                    return await client.post(path, content=body, headers={
                        "x-padiem-service-at": str(at),
                        "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)})
                reserved = await rpc("reserve_pending_pc_link", {"request_ref": ready["request_ref"]})
                assert reserved.status_code == 200 and reserved.json()["reserved_once"] is True
                result = await rpc("deliver_pending_pc_link", {
                    "request_ref": ready["request_ref"], "device_id": DEVICE,
                    "challenge_id": "pairing." + "f" * 32, "pairing_code": "d" * 32,
                })
                assert result.status_code == 200 and result.json()["sent_once"] is True
                assert json.loads(await ws.recv())["type"] == "pc_offer_approved"
        with pytest.raises(InvalidStatusCode):
            async with connect(ws_url, extra_headers=signed): pass
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)
        sock.close()
        storage.close()
