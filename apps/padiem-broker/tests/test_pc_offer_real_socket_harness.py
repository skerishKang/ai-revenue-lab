"""Real local socket over existing PC-offer actor. Test harness, not a mounted route."""
import asyncio
import base64
import json
import socket
import threading
from types import SimpleNamespace

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocketDisconnect
from websockets.legacy.client import connect

from storage import SqLiteDurableStorage
from padiem_control_plane.broker_pending_pc_private_rpc import CanonicalBrokerPendingPcLiveRPC
from padiem_control_plane.broker_pending_pc_wss import LivePcWssOffer
from padiem_control_plane.pending_pc_link import install_pending_pc_link_schema, MIGRATION_ID

DEVICE = "device.test"
PATH = "/internal/connector/pc-offer-4139"


class Owner(CanonicalBrokerPendingPcLiveRPC):
    def __init__(self, storage):
        self._storage = storage
        self.env = SimpleNamespace(
            LOCAL_AGENT_BROKER_PENDING_PC_OWNER_RPC_ENABLED="enabled",
            LOCAL_AGENT_BROKER_PENDING_PC_SCHEMA_INSTALLED="installed",
            LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE="isolated-operator-acceptance-4139",
        )
        self._pending_pc_live_by_ref = {}


class SocketAdapter:
    def __init__(self, websocket):
        self.websocket = websocket
        self.closed = False
    async def send_text(self, value):
        await self.websocket.send_text(value)
    async def close(self, *, code=1008):
        self.closed = True
        await self.websocket.close(code=code)


async def verify(*, public_key, signature, transcript):
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, transcript)
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_existing_actor_real_socket_and_sqlite(tmp_path):
    storage = SqLiteDurableStorage.open(str(tmp_path / "broker.sqlite"))
    install_pending_pc_link_schema(storage=storage, migration_id=MIGRATION_ID, operator_gate=True)
    owner = Owner(storage)
    disconnected = threading.Event()

    async def endpoint(ws):
        await ws.accept()
        adapter = SocketAdapter(ws)
        actor = LivePcWssOffer(storage=storage, socket=adapter, verifier=verify)
        try:
            while True:
                await actor.message(await ws.receive_text(), owner_do=owner)
        except WebSocketDisconnect:
            pass
        finally:
            actor.mark_disconnected()
            adapter.closed = True
            if actor._request_ref:
                owner._pending_pc_live_by_ref.pop(actor._request_ref, None)
            disconnected.set()

    app = Starlette(routes=[WebSocketRoute(PATH, endpoint)])
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
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        async with connect(f"ws://127.0.0.1:{port}{PATH}") as ws:
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
            assert ready["request_ref"] in owner._pending_pc_live_by_ref
        assert await asyncio.to_thread(disconnected.wait, 3)
        assert owner._pending_pc_live_by_ref == {}
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)
        sock.close()
        storage.close()
