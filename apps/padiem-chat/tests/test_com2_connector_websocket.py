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
from websockets.legacy.client import connect as websocket_connect

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
        async with websocket_connect(url, extra_headers=headers) as ws:
            await ws.send(json.dumps({"type": "begin", "challenge_id": CHALLENGE, "device_id": DEVICE, "proof_ref": "pairing-proof:" + "b" * 64}))
            nonce = json.loads(await ws.recv())
            assert nonce["type"] == "nonce"
            await ws.send(json.dumps({"type": "finish", "lease_ref": LEASE, "proof_hex": "d" * 64}))
            assert json.loads(await ws.recv())["type"] == "bootstrap_verified"
            # Device disappears before credential fetch.
        assert broker.calls == ["begin", "finish"]
        async with websocket_connect(url, extra_headers=signed("c" * 32)) as ws:
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
                async with websocket_connect(url, extra_headers=bad):
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

    def handler(request):
        assert str(request.url) == "http://127.0.0.1:8802/internal/rpc/authorize_connector_enrollment_redeem"
        # Recomputed here, not by the sender's own helper: the id is part of
        # the signed canonical string, so an unsigned id would not verify.
        signed = b"\n".join((
            b"v2", b"POST", request.url.path.encode("utf-8"),
            request.headers["x-padiem-service-at"].encode("ascii"),
            request.headers["x-padiem-service-id"].encode("utf-8"),
            request.content,
        ))
        expected = "v2=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
        assert request.headers["x-padiem-service-proof"] == expected
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        binding = LoopbackRpcBinding(port=8802, secret=SECRET, methods=_IDENTITY_METHODS, client=client)
        assert await binding.authorize_connector_enrollment_redeem({"challenge_id": CHALLENGE}) == {"ok": True}
        with pytest.raises(AttributeError):
            binding.revoke_all_auth_sessions
    with pytest.raises(ValueError):
        LoopbackRpcBinding(port=443, secret=SECRET, methods=_IDENTITY_METHODS)


async def test_the_broker_loopback_keeps_v1_until_its_ingress_has_a_replay_guard():
    import httpx
    from app.com2_connector_websocket import LoopbackRpcBinding, _BROKER_METHODS

    def handler(request):
        # The broker ingress has no replay memory, so a v2 request would be a
        # 503 rpc_replay_guard_unavailable instead of a served call.
        assert "x-padiem-service-id" not in request.headers
        signed = b"\n".join((
            b"v1", b"POST", request.url.path.encode("utf-8"),
            request.headers["x-padiem-service-at"].encode("ascii"),
            request.content,
        ))
        expected = "v1=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
        assert request.headers["x-padiem-service-proof"] == expected
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        binding = LoopbackRpcBinding(
            port=8799, secret=SECRET, methods=_BROKER_METHODS, client=client,
            sign_request_id=False,
        )
        assert await binding.get_enrollment_binding({"challenge_id": CHALLENGE}) == {"ok": True}


class SuccessfulIdentity(Identity):
    async def authorize_connector_enrollment_redeem(self, payload):
        return {"ok": True, "authorization": {
            "challenge_id": CHALLENGE, "consent_id": "consent.test",
            "device_id": DEVICE, "owner_subject_id": "subject.test",
            "account_ref": "account.test", "workspace_ref": "workspace.test",
            "authorized_at": datetime.now(timezone.utc).isoformat(),
            "dispatch_authorized": False, "grants_read": False, "grants_write": False,
        }}


class SuccessfulBroker(Broker):
    async def get_enrollment_binding(self, payload):
        return {"ok": True, "binding": {
            "challenge_id": CHALLENGE, "consent_ref": "consent.test", "owner_ref": "subject.test",
            "account_ref": "account.test", "workspace_ref": "workspace.test", "device_id": DEVICE,
            "bound_at": datetime.now(timezone.utc).isoformat(), "server_owned_binding": True,
            "client_supplied_receipt_trusted": False, "raw_pairing_secret": False,
        }}

    async def verify_enrollment_bootstrap(self, payload):
        return {"ok": True, "bootstrap": {
            "challenge_id": CHALLENGE, "device_id": DEVICE,
            "proof_valid": True, "challenge_consumed": False,
        }}

    async def redeem_enrollment(self, payload):
        import base64
        now = datetime.now(timezone.utc)
        return {"ok": True, "enrollment": {
            "binding_ref": "pairing-binding.test", "device_id": DEVICE,
            "account_ref": "account.test", "workspace_ref": "workspace.test",
            "credential_ref": "credential.test", "credential_generation": 1,
            "issued_at": now.isoformat(), "credential_expires_at": (now + timedelta(days=30)).isoformat(),
            "challenge_id": CHALLENGE, "server_owned_binding_refs": True,
            "raw_device_credential": False, "production_ready": False,
        }, "credential_b64": base64.b64encode(b"synthetic-test-credential-123456").decode(),
            "credential_returned_once": True, "public_http_route": False}


@pytest.mark.asyncio
async def test_actual_socket_successful_pairing_with_service_doubles(tmp_path):
    import base64
    from app.canonical_connector_credential_handoff import installation_proof, INSTALL_ACK_TRANSCRIPT_VERSION

    broker = SuccessfulBroker()
    gateway = create_com2_gateway(verifier=EdgeProofVerifier(SECRET, str(tmp_path / "seen.db")),
                                  identity_binding=SuccessfulIdentity(), broker_binding=broker)
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
        async with websocket_connect(url, extra_headers=signed("e" * 32)) as ws:
            await ws.send(json.dumps({"type": "begin", "challenge_id": CHALLENGE, "device_id": DEVICE, "proof_ref": "pairing-proof:" + "b" * 64}))
            assert json.loads(await ws.recv())["type"] == "nonce"
            await ws.send(json.dumps({"type": "finish", "lease_ref": LEASE, "proof_hex": "d" * 64}))
            assert json.loads(await ws.recv())["type"] == "bootstrap_verified"
            await ws.send(json.dumps({"type": "credential_fetch", "counter": 1, "proof_hex": "e" * 64}))
            delivered = json.loads(await ws.recv())
            assert delivered["type"] == "credential_once"
            credential = base64.b64decode(delivered["credential_b64"])
            ack = {
                "challenge_id": CHALLENGE, "device_id": DEVICE,
                "binding_ref": "pairing-binding.test", "credential_generation": 1,
                "proof_kind": "protected_store_save_readback",
                "transcript_version": INSTALL_ACK_TRANSCRIPT_VERSION,
                "local_store_confirmed": True,
                "proof_hex": installation_proof(credential=credential, challenge_id=CHALLENGE,
                    device_id=DEVICE, binding_ref="pairing-binding.test", credential_generation=1),
            }
            body = json.dumps(ack, separators=(",", ":"), sort_keys=True).encode()
            await ws.send(json.dumps({"type": "install_ack", "counter": 2, "proof_hex": "f" * 64,
                                      "body_b64": base64.b64encode(body).decode()}))
            assert json.loads(await ws.recv()) == {"type": "terminal", "status": "paired_offline", "can_retry_challenge": False}
            with pytest.raises(websockets.exceptions.ConnectionClosedOK) as closed:
                await ws.recv()
            assert closed.value.code == 1000
        assert broker.calls == ["begin", "finish", "authorize", "authorize"]
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)
        sock.close()
