"""COM2 gateway edge proofs over an actual loopback WebSocket connection."""
import asyncio
import hashlib
import hmac
import json
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import uvicorn
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages/padiem-control-plane"))
from com2_edge_proof import EdgeProofVerifier
from app.com2_connector_websocket import create_com2_gateway
from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH as PATH

SECRET = "synthetic-" + "s" * 32
CHALLENGE = "pairing." + "a" * 32
DEVICE = "device.test"
LEASE = "gateway.test"


class Identity:
    async def resolve_connector_enrollment_consent_for_device(self, payload):
        raise AssertionError("not yet authorized")
    async def bind_connector_enrollment_challenge(self, payload):
        raise AssertionError("not yet authorized")
    async def authorize_connector_enrollment_redeem(self, payload):
        raise AssertionError("not yet authorized")


class Broker:
    def __init__(self):
        self.calls = []
    async def gateway_bootstrap_rpc(self, payload):
        self.calls.append(payload["operation"])
        common = {"challenge_id": CHALLENGE, "device_id": DEVICE, "lease_ref": LEASE}
        if payload["operation"] == "begin":
            common.update(nonce_hex="c" * 64, expires_at=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(), credential=False, challenge_consumed=False)
        elif payload["operation"] == "finish":
            common.update(verified=True, credential=False, challenge_consumed=False)
        elif payload["operation"] == "authorize":
            common.update(action=payload["args"]["action"], counter=payload["args"]["counter"], authenticated=True)
        else:
            return {"ok": False, "error": {"code": "disabled", "message": "disabled"}}
        return {"ok": True, "gateway": common}
    async def get_enrollment_binding(self, payload):
        return {"ok": False, "error": {"code": "test_refused", "message": "refused"}}
    async def verify_enrollment_bootstrap(self, payload): raise AssertionError()
    async def redeem_enrollment(self, payload): raise AssertionError()
    async def revoke_binding(self, payload): raise AssertionError()


def signed(request_id):
    at = str(int(time.time()))
    tls = "TLSv1.3"
    raw = "\n".join(("v1", "GET", PATH, at, request_id, tls)).encode()
    return {
        "x-padiem-edge-at": at, "x-padiem-edge-id": request_id,
        "x-padiem-edge-tls": tls,
        "x-padiem-edge-proof": "v1=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest(),
    }


@pytest.mark.asyncio
async def test_actual_socket_proof_handshake_and_disconnect(tmp_path):
    broker = Broker()
    gateway = create_com2_gateway(
        verifier=EdgeProofVerifier(SECRET, str(tmp_path / "replay.sqlite3")),
        identity_binding=Identity(), broker_binding=broker,
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(gateway, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(300):
            if server.started: break
            await asyncio.sleep(0.01)
        assert server.started
        url = f"ws://127.0.0.1:{port}{PATH}"
        headers = signed("a" * 32)
        async with websockets.connect(url, extra_headers=headers) as ws:
            await ws.send(json.dumps({"type": "begin", "challenge_id": CHALLENGE, "device_id": DEVICE, "proof_ref": "pairing-proof:" + "b" * 64}))
            nonce = json.loads(await ws.recv())
            assert nonce["type"] == "nonce"
            await ws.send(json.dumps({"type": "finish", "lease_ref": LEASE, "proof_hex": "d" * 64}))
            assert json.loads(await ws.recv())["type"] == "bootstrap_verified"
            # Device disappears before credential fetch.
        assert broker.calls == ["begin", "finish"]
        async with websockets.connect(url, extra_headers=signed("c" * 32)) as ws:
            await ws.send(json.dumps({"type": "begin", "challenge_id": CHALLENGE, "device_id": DEVICE, "proof_ref": "pairing-proof:" + "b" * 64}))
            assert json.loads(await ws.recv())["type"] == "nonce"
            await ws.send(json.dumps({"type": "finish", "lease_ref": LEASE, "proof_hex": "d" * 64}))
            assert json.loads(await ws.recv())["type"] == "bootstrap_verified"
            await ws.send(json.dumps({"type": "credential_fetch", "counter": 1, "proof_hex": "e" * 64}))
            assert json.loads(await ws.recv()) == {"type": "terminal", "status": "security_hold", "can_retry_challenge": False}
            with pytest.raises(websockets.exceptions.ConnectionClosedOK) as closed:
                await ws.recv()
            assert closed.value.code == 1000
        for bad in ({}, headers, dict(signed("b" * 32), **{"x-padiem-edge-proof": "v1=" + "0" * 64})):
            with pytest.raises(websockets.exceptions.InvalidStatusCode):
                async with websockets.connect(url, extra_headers=bad):
                    pass
        assert broker.calls == ["begin", "finish", "begin", "finish", "authorize"]
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)
        sock.close()


@pytest.mark.asyncio
async def test_loopback_identity_rpc_is_scoped_and_signed():
    import httpx
    from app.com2_connector_websocket import LoopbackRpcBinding, _IDENTITY_METHODS
    from app.local_service_bridge import service_proof_headers

    def handler(request):
        assert str(request.url) == "http://127.0.0.1:8802/internal/rpc/authorize_connector_enrollment_redeem"
        expected = service_proof_headers(SECRET, method="POST", path=request.url.path,
                                         body=request.content,
                                         at=int(request.headers["x-padiem-service-at"]))
        assert request.headers["x-padiem-service-proof"] == expected["x-padiem-service-proof"]
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        binding = LoopbackRpcBinding(port=8802, secret=SECRET, methods=_IDENTITY_METHODS, client=client)
        assert await binding.authorize_connector_enrollment_redeem({"challenge_id": CHALLENGE}) == {"ok": True}
        with pytest.raises(AttributeError):
            binding.revoke_all_auth_sessions
    with pytest.raises(ValueError):
        LoopbackRpcBinding(port=443, secret=SECRET, methods=_IDENTITY_METHODS)
