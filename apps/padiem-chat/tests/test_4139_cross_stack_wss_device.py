"""#4139 CENTRAL: one in-memory socket connecting REAL server and REAL PC code.

Unlike two independent fabricated frame tests, this transports literal frames
between the separate PADIEM Chat WSS handler and PADIEM Connector state machine.
The Broker, Identity host, TLS attestations and protected store remain test
ports: this is NOT production TLS, DPAPI or cloud enrollment evidence.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "claw-connect"))

from claw_connect.credential_install import LocalStoreCredentialReceiver
from claw_connect.device_wss_enrollment import (
    DeviceSessionRefused, run_and_stage_review_only_device_enrollment,
    WSS_DEVICE_ENROLLMENT_PRODUCTION_ENABLED,
)
from claw_connect.enrollment import ConnectorEnrollment, build_enrollment_proof_ref
from claw_connect.wss_target import REVIEW_WSS_PATH, REVIEW_WSS_HOST, WSS_PRODUCTION_DIALER_ENABLED
from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from app.connector_gateway_first_pairing_tls_review import (
    CloudflareFirstPairingTlsTransportReview,
)
from app.connector_gateway_websocket_session import (
    PRODUCTION_WEBSOCKET_ROUTE_MOUNTED, run_device_initiated_enrollment,
)
from app.canonical_connector_credential_handoff import verify_install_ack
from app.control_plane_identity import IdentityBridgeError

CHALLENGE = "pairing." + "a" * 32
CODE = "d" * 32
LEASE = "gateway." + "b" * 32
NONCE = "c" * 64
CREDENTIAL = b"synthetic-canonical-credential-v1"


def _mac(*parts, key=CODE.encode("ascii")):
    return hmac.new(key, "\n".join(parts).encode(), hashlib.sha256).hexdigest()


def _action(action: str, counter: int, body: bytes, device: str):
    version = "padiem.connector-gateway-session.v1"
    key = hmac.new(
        CODE.encode("ascii"),
        "\n".join((version, CHALLENGE, device, NONCE, LEASE)).encode(),
        hashlib.sha256,
    ).digest()
    return _mac(version, action, str(counter), hashlib.sha256(body).hexdigest(), key=key)


class Duplex:
    """Async source-only frame delivery; no OS sockets or browser access."""

    def __init__(self):
        self.pc_to_server = asyncio.Queue()
        self.server_to_pc = asyncio.Queue()
        self.server_sent = []
        self.pc_sent = []
        self.server_closed = None
        self.pc_closed = False
        self.server_accepted = False
        outer = self

        class Server:
            url = SimpleNamespace(scheme="wss")
            headers = {}
            async def accept(self):
                outer.server_accepted = True
            async def send_text(self, raw):
                outer.server_sent.append(json.loads(raw))
                await outer.server_to_pc.put(raw)
            async def receive_text(self):
                msg = await outer.pc_to_server.get()
                if msg is None:
                    raise ConnectionError("test device closed")
                return msg
            async def close(self, *, code):
                outer.server_closed = code
                await outer.server_to_pc.put(None)

        class Pc:
            async def send_text(self, raw):
                outer.pc_sent.append(json.loads(raw))
                await outer.pc_to_server.put(raw)
            async def receive_text(self):
                msg = await outer.server_to_pc.get()
                if msg is None:
                    raise ConnectionError("test server closed")
                return msg
            async def close(self):
                outer.pc_closed = True
                await outer.pc_to_server.put(None)

        self.server = Server()
        self.pc = Pc()


class SyntheticIngress:
    def __init__(self, allow=True):
        self.allow = allow
        self.calls = 0
    async def verify(self, socket):
        self.calls += 1
        return self.allow


class SyntheticBroker:
    def __init__(self, device):
        self.device = device
        self.operations = []
        self.expected_proof = build_enrollment_proof_ref(
            challenge_id=CHALLENGE, device_id=device, pairing_code=CODE,
        )
    async def gateway_bootstrap_rpc(self, payload):
        op, args = payload["operation"], payload["args"]
        self.operations.append(op)
        if op == "begin":
            assert args == {
                "challenge_id": CHALLENGE, "device_id": self.device,
                "proof_ref": self.expected_proof,
            }
            data = {
                "challenge_id": CHALLENGE, "device_id": self.device,
                "lease_ref": LEASE, "nonce_hex": NONCE,
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=50)).isoformat(),
                "credential": False, "challenge_consumed": False,
            }
        elif op == "finish":
            assert args["lease_ref"] == LEASE
            assert args["proof_hex"] == _mac(
                "padiem.connector-gateway-bootstrap.v1",
                CHALLENGE, self.device, NONCE, LEASE,
            )
            data = {
                "challenge_id": CHALLENGE, "device_id": self.device,
                "lease_ref": LEASE, "verified": True,
                "credential": False, "challenge_consumed": False,
            }
        elif op == "authorize":
            body = base64.b64decode(args["body_b64"], validate=True)
            assert args["proof_hex"] == _action(
                args["action"], args["counter"], body, self.device,
            )
            assert (args["action"], args["counter"]) in (
                ("credential_fetch", 1), ("install_ack", 2),
            )
            data = {
                "challenge_id": CHALLENGE, "device_id": self.device,
                "lease_ref": LEASE, "action": args["action"],
                "counter": args["counter"], "authenticated": True,
            }
        else:
            raise AssertionError("unknown private Broker operation")
        return {"ok": True, "gateway": data}


class FakeProtectedStore:
    def __init__(self):
        self.record = None
    def save(self, *, binding, credential, now):
        self.record = (binding, bytes(credential))
        return binding
    def load(self, *, binding, now):
        if self.record is None or self.record[0] is not binding:
            raise ValueError("wrong stored binding")
        return self.record[1]


class SyntheticCanonicalHost:
    def __init__(self, *, handoff, device, events):
        self.handoff = handoff
        self.device = device
        self.events = events
        self.binding = {
            "binding_ref": "pairing-binding.1",
            "device_id": device,
            "account_ref": "account.1",
            "workspace_ref": "workspace.1",
            "credential_ref": "credential.1",
            "credential_generation": 1,
            "credential_expires_at": (
                datetime.now(timezone.utc) + timedelta(days=30)
            ).isoformat(),
        }

    async def redeem(self, *, challenge_id, device_id, proof_ref):
        self.events.append("host_redeem")
        assert challenge_id == CHALLENGE and device_id == self.device
        assert proof_ref == build_enrollment_proof_ref(
            challenge_id=CHALLENGE, device_id=device_id, pairing_code=CODE,
        )
        assert await self.handoff.ready(challenge_id=CHALLENGE, device_id=device_id)
        ack = await self.handoff.deliver_once(
            challenge_id=CHALLENGE, device_id=device_id, credential=CREDENTIAL,
            enrollment=self.binding, now=datetime.now(timezone.utc),
        )
        assert verify_install_ack(
            ack=ack, credential=CREDENTIAL, challenge_id=CHALLENGE,
            device_id=device_id, enrollment=self.binding,
        )
        assert await self.handoff.verify_authenticated_ack(
            challenge_id=CHALLENGE, device_id=device_id, ack=ack,
        )
        self.events.append("host_ack_verified")
        return {
            "lifecycle": "paired_offline",
            "raw_device_credential": False,
            "dispatch_authorized": False,
        }


def _fake_binding(fields, *, now, expires_at):
    return SimpleNamespace(**fields)


def _run_once(enrollment, *, trusted=True, first_pairing_tls_version=None):
    async def start():
        wire = Duplex()
        device = enrollment.record().device_id
        broker = SyntheticBroker(device)
        inbound = SyntheticIngress(trusted)
        if first_pairing_tls_version is not None:
            wire.server.scope = {
                "type": "websocket", "scheme": "wss",
                "path": CONNECTOR_GATEWAY_WSS_PATH,
                "raw_path": CONNECTOR_GATEWAY_WSS_PATH.encode("ascii"),
                "query_string": b"",
            }
            inbound = CloudflareFirstPairingTlsTransportReview(
                incoming_worker_request=SimpleNamespace(
                    url="https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH,
                    method="GET",
                    headers={"upgrade": "websocket"},
                    cf={"tlsVersion": first_pairing_tls_version, "tlsClientAuth": None},
                ),
                source_review_authorized=True,
            )
        outbound = SyntheticIngress(trusted)
        state = FakeProtectedStore()
        events = []
        async def server():
            await run_device_initiated_enrollment(
                wire.server, trusted_tls=inbound, broker=broker,
                host_factory=lambda *, handoff: SyntheticCanonicalHost(
                    handoff=handoff, device=device, events=events,
                ),
            )
        async def pc():
            return await run_and_stage_review_only_device_enrollment(
                enrollment=enrollment, socket=wire.pc, trusted_tls=outbound,
                receiver=LocalStoreCredentialReceiver(
                    store=state, now_factory=lambda: datetime.now(timezone.utc),
                ),
                challenge_id=CHALLENGE, pairing_code=CODE,
                binding_factory=_fake_binding,
            )
        return (*await asyncio.wait_for(
            asyncio.gather(server(), pc(), return_exceptions=True), timeout=8,
        ), wire, broker, state, events)
    return asyncio.run(start())


def test_real_server_and_real_device_frames_complete_one_synthetic_session(tmp_path):
    assert PRODUCTION_WEBSOCKET_ROUTE_MOUNTED is False
    assert WSS_PRODUCTION_DIALER_ENABLED is False
    assert REVIEW_WSS_PATH == CONNECTOR_GATEWAY_WSS_PATH
    assert REVIEW_WSS_HOST == "chat.padiem.net"
    assert WSS_DEVICE_ENROLLMENT_PRODUCTION_ENABLED is False
    record = ConnectorEnrollment(state_dir=tmp_path / "state")
    old = record.record()
    server, pc, wire, broker, store, events = _run_once(record)
    assert server is None
    assert not isinstance(pc, BaseException), repr(pc)
    assert pc.lifecycle == "paired_offline"
    assert broker.operations == ["begin", "finish", "authorize", "authorize"]
    assert events == ["host_redeem", "host_ack_verified"]
    assert [x["type"] for x in wire.pc_sent] == [
        "begin", "finish", "credential_fetch", "install_ack",
    ]
    assert [x["type"] for x in wire.server_sent] == [
        "nonce", "bootstrap_verified", "credential_once", "terminal",
    ]
    assert wire.server_closed == 1000 and wire.pc_closed
    assert store.record[1] == CREDENTIAL
    assert old.binding_ref is None
    assert record.record().binding_ref == pc.binding_ref
    assert record.record().device_lifecycle == "paired_offline"
    persisted = ConnectorEnrollment(state_dir=tmp_path / "state").committed_record()
    assert persisted and persisted.binding_ref == pc.binding_ref
    assert persisted.account_ref == "account.1"
    assert not any("credential_b64" in message for message in wire.pc_sent)


def test_tls_refusal_on_both_ends_never_contacts_private_broker(tmp_path):
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    server, pc, wire, broker, store, events = _run_once(enrollment, trusted=False)
    assert isinstance(pc, DeviceSessionRefused)
    assert server is None
    assert wire.server_closed == 1008
    assert not wire.server_accepted
    assert wire.pc_sent == [] and wire.server_sent == []
    assert broker.operations == []
    assert events == []
    assert store.record is None
    assert enrollment.record().binding_ref is None


def test_same_device_may_not_redeem_again_after_terminal(tmp_path):
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    first = _run_once(enrollment)
    assert first[0] is None and not isinstance(first[1], BaseException)
    # The original durable device binding cannot be overwritten by another
    # synthetic WSS session; admission must fail before any socket frame.
    replay = Duplex()
    async def retry():
        return await run_and_stage_review_only_device_enrollment(
            enrollment=enrollment, socket=replay.pc, trusted_tls=SyntheticIngress(),
            receiver=LocalStoreCredentialReceiver(store=FakeProtectedStore()),
            challenge_id=CHALLENGE, pairing_code=CODE, binding_factory=_fake_binding,
        )
    with pytest.raises(DeviceSessionRefused, match="existing_binding"):
        asyncio.run(retry())
    assert replay.pc_sent == [] and replay.server_sent == []


def test_first_enrollment_tls_only_then_existing_broker_proof_and_ack(tmp_path):
    """Synthetic Cloudflare edge TLS admits socket; code POP authenticates PC."""
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    server, pc, wire, broker, store, events = _run_once(
        enrollment, first_pairing_tls_version="TLSv1.3",
    )
    assert server is None
    assert not isinstance(pc, BaseException), repr(pc)
    assert pc.lifecycle == "paired_offline"
    assert broker.operations == ["begin", "finish", "authorize", "authorize"]
    assert events == ["host_redeem", "host_ack_verified"]
    assert store.record is not None
    assert enrollment.committed_record() is not None
    assert wire.server_accepted and wire.server_closed == 1000
    # Transport admission alone granted neither work authorization nor
    # a confirmed ONLINE session; the canonical pairing proof did the work.


def test_first_enrollment_legacy_edge_tls_denied_before_broker_rpc(tmp_path):
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    server, pc, wire, broker, store, events = _run_once(
        enrollment, first_pairing_tls_version="TLSv1.0",
    )
    assert server is None
    assert isinstance(pc, DeviceSessionRefused)
    assert broker.operations == []
    assert wire.server_accepted is False
    assert wire.server_closed == 1008
    assert store.record is None
    # The stable unpaired PC ID was written *before* network admission.
    # Failed TLS must preserve that identity but never commit a Broker binding.
    remaining = enrollment.committed_record()
    assert remaining is not None
    assert remaining.device_lifecycle == "unpaired"
    assert remaining.binding_ref is None
    assert remaining.account_ref is None and remaining.workspace_ref is None
    assert events == []
