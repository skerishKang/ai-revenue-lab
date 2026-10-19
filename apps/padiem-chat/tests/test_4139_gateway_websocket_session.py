"""#4139 focused tests of the same device-originated WSS session (mock ports).

A TestSocket is *not* evidence of TLS origin or real Windows DPAPI, and an
in-memory Broker double is not evidence of durable Cloudflare correctness.
"""
from __future__ import annotations

import asyncio
import base64

import app.connector_gateway_websocket_session as gateway_session
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from types import SimpleNamespace

from app.canonical_connector_credential_handoff import (
    installation_proof, verify_install_ack, INSTALL_ACK_TRANSCRIPT_VERSION,
)
from app.connector_gateway_websocket_session import (
    PRODUCTION_WEBSOCKET_ROUTE_MOUNTED,
    PRODUCTION_WEBSOCKET_CREDENTIAL_DELIVERY_ENABLED,
    run_device_initiated_enrollment,
)
from app.control_plane_identity import IdentityBridgeError

CID = "pairing." + "a" * 32
DEVICE = "device.1"
LEASE = "gateway." + "b" * 32
NONCE = "c" * 64
CODE = "d" * 32
PROOF = "pairing-proof:" + "e" * 64
CREDENTIAL = b"synthetic-canonical-credential-v1"
ENROLLMENT = {
    "binding_ref": "pairing-binding.1",
    "device_id": DEVICE,
    "account_ref": "account.1",
    "workspace_ref": "workspace.1",
    "credential_ref": "credential.1",
    "credential_generation": 1,
    "credential_expires_at": "2030-01-01T00:00:00+00:00",
}


def mac(*parts, key=CODE.encode("ascii")):
    return hmac.new(key, "\n".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def bootstrap_mac():
    return mac(
        "padiem.connector-gateway-bootstrap.v1", CID, DEVICE, NONCE, LEASE,
    )


def action_mac(action, counter, body: bytes):
    version = "padiem.connector-gateway-session.v1"
    session_key = hmac.new(
        CODE.encode("ascii"),
        "\n".join([version, CID, DEVICE, NONCE, LEASE]).encode(),
        hashlib.sha256,
    ).digest()
    return mac(
        version, action, str(counter), hashlib.sha256(body).hexdigest(),
        key=session_key,
    )


def wire_frame(payload):
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def ack_body():
    return wire_frame({
        "challenge_id": CID, "device_id": DEVICE,
        "binding_ref": ENROLLMENT["binding_ref"],
        "credential_generation": 1,
        "proof_kind": "protected_store_save_readback",
        "transcript_version": INSTALL_ACK_TRANSCRIPT_VERSION,
        "local_store_confirmed": True,
        "proof_hex": installation_proof(
            credential=CREDENTIAL, challenge_id=CID, device_id=DEVICE,
            binding_ref=ENROLLMENT["binding_ref"], credential_generation=1,
        ),
    }).encode("utf-8")


def device_frames(*, body=None, ack_mac=None, lease=LEASE, finish_proof=None):
    signed_body = ack_body() if body is None else body
    return [
        wire_frame({"type":"begin", "challenge_id":CID, "device_id":DEVICE,
                    "proof_ref":PROOF}),
        wire_frame({"type":"finish", "lease_ref":lease,
                    "proof_hex":finish_proof or bootstrap_mac()}),
        wire_frame({"type":"credential_fetch", "counter":1,
                    "proof_hex":action_mac("credential_fetch", 1, b"")}),
        wire_frame({"type":"install_ack", "counter":2,
                    "proof_hex":ack_mac or action_mac("install_ack", 2, signed_body),
                    "body_b64":base64.b64encode(signed_body).decode("ascii")}),
    ]


class FakeSocket:
    def __init__(self, frames=None, *, scheme="wss", origin=None,
                 stalled_receive=None, stalled_send=None):
        self.stalled_receive = stalled_receive
        self.stalled_send = stalled_send
        self.receive_count = 0
        self.send_count = 0
        self.url = SimpleNamespace(scheme=scheme)
        self.headers = {"origin": origin} if origin else {}
        self.pending = list(frames if frames is not None else device_frames())
        self.sent = []
        self.accepted = False
        self.closed = None

    async def accept(self):
        self.accepted = True

    async def close(self, *, code):
        self.closed = code

    async def receive_text(self):
        self.receive_count += 1
        if self.receive_count == self.stalled_receive:
            await asyncio.Event().wait()
        if not self.pending:
            raise RuntimeError("device disconnected")
        return self.pending.pop(0)

    async def send_text(self, text):
        self.send_count += 1
        if self.send_count == self.stalled_send:
            await asyncio.Event().wait()
        self.sent.append(json.loads(text))


class FakeIngress:
    def __init__(self, trusted=True):
        self.trusted = trusted
        self.calls = 0

    async def verify(self, socket):
        self.calls += 1
        return self.trusted


class FakeBroker:
    def __init__(self):
        self.calls = []
        self.reject = None

    async def gateway_bootstrap_rpc(self, payload):
        op, args = payload["operation"], payload["args"]
        self.calls.append(op)
        if self.reject == op:
            return {"ok": False, "error": {"code": "denied"}}
        if op == "begin":
            assert args == {"challenge_id": CID, "device_id": DEVICE,
                            "proof_ref": PROOF}
            result = {
                "challenge_id": CID, "device_id": DEVICE, "lease_ref": LEASE,
                "nonce_hex": NONCE,
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=50)).isoformat(),
                "credential": False, "challenge_consumed": False,
            }
        elif op == "finish":
            if args["proof_hex"] != bootstrap_mac():
                return {"ok": False, "error": {"code": "invalid"}}
            result = {
                "challenge_id": CID, "device_id": DEVICE, "lease_ref": LEASE,
                "verified": True, "credential": False, "challenge_consumed": False,
            }
        elif op == "authorize":
            body = base64.b64decode(args["body_b64"], validate=True)
            if (args["proof_hex"] != action_mac(args["action"], args["counter"], body)
                or (args["action"], args["counter"]) not in
                {("credential_fetch", 1), ("install_ack", 2)}):
                return {"ok": False, "error": {"code": "not_authenticated"}}
            result = {
                "challenge_id": CID, "device_id": DEVICE, "lease_ref": LEASE,
                "action": args["action"], "counter": args["counter"],
                "authenticated": True,
            }
        else:
            raise AssertionError("unexpected Broker action")
        return {"ok": True, "gateway": result}


class FakeCanonicalHost:
    def __init__(self, *, handoff, reject=False):
        self.handoff = handoff
        self.reject = reject
        self.redeemed = False
        self.revoked = False

    async def redeem(self, *, challenge_id, device_id, proof_ref):
        assert challenge_id == CID and device_id == DEVICE and proof_ref == PROOF
        assert await self.handoff.ready(challenge_id=CID, device_id=DEVICE)
        self.redeemed = True  # simulates canonical Broker single redemption
        if self.reject:
            raise IdentityBridgeError(503, "enrollment_handoff_revoke_unconfirmed",
                                      "revoke unknown")
        try:
            ack = await self.handoff.deliver_once(
                challenge_id=CID, device_id=DEVICE, credential=CREDENTIAL,
                enrollment=ENROLLMENT, now=datetime.now(timezone.utc),
            )
            assert verify_install_ack(ack=ack, credential=CREDENTIAL,
                                      challenge_id=CID, device_id=DEVICE,
                                      enrollment=ENROLLMENT)
            assert await self.handoff.verify_authenticated_ack(
                challenge_id=CID, device_id=DEVICE, ack=ack,
            )
        except Exception as exc:
            self.revoked = True
            raise IdentityBridgeError(503, "enrollment_credential_handoff_failed",
                                      "canonical revoke confirmed") from exc
        return {"lifecycle":"paired_offline", "raw_device_credential":False,
                "dispatch_authorized":False}


def run(frames=None, *, scheme="wss", trusted=True,
        broker=None, host_type=FakeCanonicalHost,
        stalled_receive=None, stalled_send=None):
    sock = FakeSocket(
        frames, scheme=scheme,
        stalled_receive=stalled_receive, stalled_send=stalled_send,
    )
    auth = FakeIngress(trusted)
    control = broker or FakeBroker()
    instantiated = []
    def factory(*, handoff):
        host = host_type(handoff=handoff)
        instantiated.append(host)
        return host
    asyncio.run(run_device_initiated_enrollment(
        sock, trusted_tls=auth, broker=control, host_factory=factory,
    ))
    return sock, auth, control, instantiated


def test_socket_is_source_only_and_never_mounted_or_enabled():
    assert PRODUCTION_WEBSOCKET_ROUTE_MOUNTED is False
    assert PRODUCTION_WEBSOCKET_CREDENTIAL_DELIVERY_ENABLED is False


def test_one_socket_carries_pop_once_credential_and_canonical_ack():
    sock, auth, broker, hosts = run()
    assert sock.accepted and sock.closed == 1000
    assert [m["type"] for m in sock.sent] == [
        "nonce", "bootstrap_verified", "credential_once", "terminal",
    ]
    assert sock.sent[2]["credential_b64"] == base64.b64encode(CREDENTIAL).decode("ascii")
    assert set(sock.sent[2]["binding"]) == set(ENROLLMENT)
    assert sock.sent[-1] == {"type":"terminal", "status":"paired_offline",
                             "can_retry_challenge":False}
    assert broker.calls == ["begin", "finish", "authorize", "authorize"]
    assert hosts[0].redeemed and not hosts[0].revoked


def test_missing_tls_or_broker_never_reserves_nonce_or_sends_credential():
    sock, auth, broker, hosts = run(scheme="ws")
    assert not sock.accepted and sock.closed == 1008
    assert sock.sent == [] and broker.calls == [] and hosts == []
    sock, auth, broker, hosts = run(trusted=False)
    assert not sock.accepted and sock.closed == 1008
    assert sock.sent == [] and broker.calls == [] and hosts == []


def test_wrong_device_session_proof_is_denied_before_host_redeem():
    frames = device_frames(finish_proof="f" * 64)
    sock, auth, broker, hosts = run(frames)
    assert sock.closed == 1011 and hosts == []
    assert broker.calls == ["begin", "finish"]
    assert not any("credential_b64" in x for x in sock.sent)


def test_wrong_signed_install_ack_is_compensated_and_never_reports_paired():
    frames = device_frames(ack_mac="f" * 64)
    sock, auth, broker, hosts = run(frames)
    assert hosts[0].redeemed and hosts[0].revoked
    assert broker.calls == ["begin", "finish", "authorize", "authorize"]
    assert not any(m.get("status") == "paired_offline" for m in sock.sent)
    assert sock.sent[-1] == {"type":"terminal", "status":"revoked",
                             "can_retry_challenge":False}


def test_broker_does_not_authorize_fetch_or_install_ack():
    for refusal in ("authorize",):
        broker = FakeBroker()
        broker.reject = refusal
        sock, auth, broker, hosts = run(broker=broker)
        assert sock.closed == 1011
        assert broker.calls == ["begin", "finish", "authorize"]
        assert hosts == []
        assert not any("credential_b64" in x for x in sock.sent)


def test_unconfirmed_revoke_can_never_claim_compensated():
    class HoldHost(FakeCanonicalHost):
        def __init__(self, *, handoff):
            super().__init__(handoff=handoff, reject=True)
    sock, auth, broker, hosts = run(host_type=HoldHost)
    assert hosts[0].redeemed
    assert sock.sent[-1] == {"type":"terminal", "status":"security_hold",
                             "can_retry_challenge":False}


def test_duplicate_frame_json_and_unknown_extra_keys_fail_closed():
    frames = device_frames()
    frames[0] = '{"type":"begin","type":"finish","challenge_id":"' + CID + '"}'
    sock, _, broker, hosts = run(frames)
    assert sock.closed == 1011 and broker.calls == [] and hosts == []
    frames = device_frames()
    frames[0] = wire_frame({"type":"begin", "challenge_id":CID,
                             "device_id":DEVICE, "proof_ref":PROOF,
                             "owner_ref":"attacker"})
    sock, _, broker, hosts = run(frames)
    assert sock.closed == 1011 and broker.calls == [] and hosts == []


def test_silent_pc_cannot_hold_pre_redeem_socket_forever(monkeypatch):
    monkeypatch.setattr(gateway_session, "MAX_BOOTSTRAP_FRAME_SECONDS", 0.01)
    sock, _, broker, hosts = run(stalled_receive=1)
    assert sock.closed == 1011
    assert broker.calls == [] and hosts == []
    assert not any("credential_b64" in msg for msg in sock.sent)


def test_windows_ack_timeout_triggers_existing_broker_compensation(monkeypatch):
    monkeypatch.setattr(gateway_session, "MAX_WINDOWS_ACK_SECONDS", 0.01)
    sock, _, broker, hosts = run(stalled_receive=4)
    assert len(hosts) == 1 and hosts[0].redeemed
    assert hosts[0].revoked is True
    assert broker.calls == ["begin", "finish", "authorize"]
    assert sock.closed == 1000
    assert sock.sent[-1] == {
        "type": "terminal", "status": "revoked",
        "can_retry_challenge": False,
    }
    assert not any(m.get("status") == "paired_offline" for m in sock.sent)


def test_credential_frame_send_timeout_never_reports_paired(monkeypatch):
    monkeypatch.setattr(gateway_session, "MAX_SOCKET_SEND_SECONDS", 0.01)
    sock, _, broker, hosts = run(stalled_send=3)
    assert len(hosts) == 1 and hosts[0].redeemed
    assert hosts[0].revoked is True
    assert sock.closed == 1000
    assert sock.sent[-1]["status"] == "revoked"
    assert not any(m.get("status") == "paired_offline" for m in sock.sent)


def test_trusted_tls_gate_timeout_prevents_private_broker_call(monkeypatch):
    monkeypatch.setattr(gateway_session, "MAX_TLS_VERIFY_SECONDS", 0.01)
    sock = FakeSocket()
    broker = FakeBroker()
    class StalledVerifier:
        async def verify(self, _):
            await asyncio.Event().wait()
    constructed = []
    asyncio.run(run_device_initiated_enrollment(
        sock, trusted_tls=StalledVerifier(), broker=broker,
        host_factory=lambda *, handoff: constructed.append(handoff),
    ))
    assert sock.closed == 1011 and not sock.accepted
    assert broker.calls == [] and constructed == []


def test_private_gateway_rpc_timeout_before_redeem_fails_closed(monkeypatch):
    monkeypatch.setattr(gateway_session, "MAX_GATEWAY_BROKER_RPC_SECONDS", 0.01)
    class StalledBroker(FakeBroker):
        async def gateway_bootstrap_rpc(self, payload):
            self.calls.append(payload["operation"])
            await asyncio.Event().wait()
    broker = StalledBroker()
    sock, _, _, hosts = run(broker=broker)
    assert sock.closed == 1011 and hosts == []
    assert broker.calls == ["begin"]
    assert not any("credential_b64" in m for m in sock.sent)
