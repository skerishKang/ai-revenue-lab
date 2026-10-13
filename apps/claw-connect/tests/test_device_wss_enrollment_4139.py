"""WSS device-side proof/DPAPI-ACK parity with CENTRAL #4476 frames.

Synthetic connection and protected store: NEVER a claim of live TLS or DPAPI.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claw_connect.credential_install import LocalStoreCredentialReceiver
from claw_connect.enrollment import build_enrollment_proof_ref
from claw_connect.device_wss_enrollment import (
    DeviceSessionRefused, run_review_only_device_session, 
    run_and_stage_review_only_device_enrollment, _action_mac,
)
from claw_connect.enrollment import ConnectorEnrollment, EnrollmentPersistenceError

CODE = "d" * 32
CID = "pairing." + "a" * 32
DEVICE = "device.1"
LEASE = "gateway." + "b" * 32
NONCE = "c" * 64
CREDENTIAL = b"synthetic-canonical-credential-v1"
NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
BINDING = {
    "binding_ref": "pairing-binding.1",
    "device_id": DEVICE,
    "account_ref": "account.1",
    "workspace_ref": "workspace.1",
    "credential_ref": "credential.1",
    "credential_generation": 1,
    "credential_expires_at": "2030-01-01T00:00:00+00:00",
}


class Store:
    def __init__(self, *, corrupt_readback=False):
        self.saved = []
        self.corrupt_readback = corrupt_readback
    def save(self, *, binding, credential, now):
        self.saved.append((binding, credential))
        return binding
    def load(self, *, binding, now):
        return b"wrong" if self.corrupt_readback else self.saved[-1][1]


class Socket:
    def __init__(self, *, terminal="paired_offline", corrupted=None):
        self.sent = []
        self.closed = False
        self.terminal = terminal
        self.corrupted = corrupted
        self.index = 0
    async def send_text(self, message):
        self.sent.append(json.loads(message))
    async def receive_text(self):
        stage = self.index
        self.index += 1
        if stage == 0:
            data = {"type": "nonce", "challenge_id": CID,
                    "device_id": DEVICE, "lease_ref": LEASE,
                    "nonce_hex": NONCE, "expires_at": "2030-01-01T00:00:00+00:00"}
            if self.corrupted == "nonce_swap": data["device_id"] = "device.attacker"
            if self.corrupted == "duplicate": return '{"type":"nonce","type":"nonce"}'
        elif stage == 1:
            data = {"type": "bootstrap_verified", "lease_ref": LEASE, "credential": False}
        elif stage == 2:
            data = {"type": "credential_once", "challenge_id": CID,
                    "device_id": DEVICE, "lease_ref": LEASE,
                    "binding": dict(BINDING),
                    "credential_b64": base64.b64encode(CREDENTIAL).decode()}
            if self.corrupted == "binding_swap":
                data["binding"]["account_ref"] = "account.attacker"
                # Stored binding is still legitimate format, but same-request
                # owner authority can't be checked here: the remote Broker must.
            if self.corrupted == "device_swap": data["binding"]["device_id"] = "other.1"
            if self.corrupted == "bad_secret": data["credential_b64"] = "!!!!!"
            if self.corrupted == "extra": data["evil"] = True
        else:
            data = {"type": "terminal", "status": self.terminal, "can_retry_challenge": False}
        return json.dumps(data, sort_keys=True)
    async def close(self):
        self.closed = True


class Trusted:
    def __init__(self, ok=True): self.ok = ok
    async def verify(self, socket): return self.ok


def _fake_binding(fields, *, now, expires_at):
    return SimpleNamespace(**fields)


def run(sock, store=None, trusted=None):
    return asyncio.run(run_review_only_device_session(
        socket=sock, trusted_tls=trusted or Trusted(),
        receiver=LocalStoreCredentialReceiver(store=store or Store(), now_factory=lambda: NOW),
        challenge_id=CID, device_id=DEVICE, pairing_code=CODE, now=NOW,
        binding_factory=_fake_binding,
    ))


def exact_mac(*values, key=CODE.encode("ascii")):
    return hmac.new(key, "\n".join(values).encode(), hashlib.sha256).hexdigest()


def test_exact_wire_hmac_and_local_protected_readback_ack():
    sock, store = Socket(), Store()
    receipt = run(sock, store)
    assert receipt.lifecycle == "paired_offline"
    assert receipt.local_record_committed is False and receipt.online is False
    assert receipt.device_id == DEVICE and receipt.account_ref == BINDING["account_ref"]
    assert sock.closed is True and len(sock.sent) == 4
    assert sock.sent[0] == {
        "type": "begin", "challenge_id": CID, "device_id": DEVICE,
        "proof_ref": build_enrollment_proof_ref(
            challenge_id=CID, device_id=DEVICE, pairing_code=CODE,
        )}
    assert sock.sent[1] == {
        "type": "finish", "lease_ref": LEASE, "proof_hex": exact_mac(
            "padiem.connector-gateway-bootstrap.v1", CID, DEVICE, NONCE, LEASE,
        )}
    assert sock.sent[2]["type"] == "credential_fetch"
    assert sock.sent[2]["counter"] == 1
    assert sock.sent[2]["proof_hex"] == _action_mac(
        code=CODE, challenge_id=CID, device_id=DEVICE, nonce=NONCE,
        lease=LEASE, action="credential_fetch", counter=1, body=b"",
    )
    ack = sock.sent[3]
    assert ack["type"] == "install_ack" and ack["counter"] == 2
    body = base64.b64decode(ack["body_b64"], validate=True)
    content = json.loads(body)
    assert set(content) == {
        "challenge_id", "device_id", "binding_ref", "credential_generation",
        "proof_kind", "transcript_version", "local_store_confirmed", "proof_hex",
    }
    assert content["proof_kind"] == "protected_store_save_readback"
    assert content["local_store_confirmed"] is True
    assert ack["proof_hex"] == _action_mac(
        code=CODE, challenge_id=CID, device_id=DEVICE, nonce=NONCE,
        lease=LEASE, action="install_ack", counter=2, body=body,
    )
    assert len(store.saved) == 1 and store.saved[0][1] == CREDENTIAL
    assert b"synthetic-canonical-credential" not in body
    assert "credential_b64" not in str(content)


@pytest.mark.parametrize("bad", ["nonce_swap", "duplicate", "device_swap", "bad_secret", "extra"])
def test_malformed_or_swapped_server_frame_fails_before_ack(bad):
    sock, store = Socket(corrupted=bad), Store()
    with pytest.raises(DeviceSessionRefused):
        run(sock, store)
    assert sock.closed
    assert not any(x["type"] == "install_ack" for x in sock.sent)


def test_bad_store_readback_never_acks_and_cannot_retry_same_challenge():
    sock = Socket()
    store = Store(corrupt_readback=True)
    receiver = LocalStoreCredentialReceiver(store=store, now_factory=lambda: NOW)
    async def drive(s):
        return await run_review_only_device_session(
            socket=s, trusted_tls=Trusted(), receiver=receiver,
            challenge_id=CID, device_id=DEVICE, pairing_code=CODE, now=NOW,
            binding_factory=_fake_binding,
        )
    with pytest.raises(DeviceSessionRefused):
        asyncio.run(drive(sock))
    assert len(store.saved) == 1
    assert not any(x["type"] == "install_ack" for x in sock.sent)
    with pytest.raises(DeviceSessionRefused):
        asyncio.run(drive(Socket()))
    assert len(store.saved) == 1


@pytest.mark.parametrize("terminal", ["security_hold", "revoked", "online", "ok"])
def test_only_original_offline_terminal_is_success(terminal):
    sock = Socket(terminal=terminal)
    with pytest.raises(DeviceSessionRefused, match="device_terminal_security_hold"):
        run(sock)
    assert sock.closed


def test_trusted_tls_failure_never_sends_begin_or_mints_store_record():
    sock, store = Socket(), Store()
    with pytest.raises(DeviceSessionRefused, match="trusted_tls_required"):
        run(sock, store, Trusted(False))
    assert sock.sent == [] and store.saved == []


def test_no_production_transport_or_secret_logger_is_added():
    source = (Path(__file__).resolve().parents[1] /
              "claw_connect" / "device_wss_enrollment.py").read_text(encoding="utf-8")
    assert "WSS_DEVICE_TRANSPORT_PRODUCTION_WIRED = False" in source
    assert "WSS_DEVICE_ENROLLMENT_PRODUCTION_ENABLED = False" in source
    assert "websockets.connect" not in source
    assert "import logging" not in source
    assert "print(" not in source



def test_terminal_success_is_durably_staged_without_claiming_online(tmp_path):
    from claw_connect.enrollment import EnrollmentRecord
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    original = enrollment.record()
    # Server's synthetic WSS lease must correlate the client's own device id.
    # This test uses the same synthetic device id as the fake Broker fixture.
    original.device_id = DEVICE
    enrollment.flush()
    prior_shared = enrollment.record()
    sock = Socket()
    result = asyncio.run(run_and_stage_review_only_device_enrollment(
        enrollment=enrollment, socket=sock, trusted_tls=Trusted(),
        receiver=LocalStoreCredentialReceiver(store=Store(), now_factory=lambda: NOW),
        challenge_id=CID, pairing_code=CODE, now=NOW,
        binding_factory=_fake_binding,
    ))
    assert result.binding_ref == BINDING["binding_ref"]
    assert enrollment.record().binding_ref == result.binding_ref
    assert enrollment.record().device_lifecycle == "paired_offline"
    assert enrollment.record().is_enrolled() is True
    assert prior_shared.binding_ref is None  # original object not mutated
    reread = ConnectorEnrollment(state_dir=tmp_path / "state").committed_record()
    assert reread is not None and reread.binding_ref == result.binding_ref
    assert reread.account_ref == BINDING["account_ref"]
    assert reread.device_lifecycle == "paired_offline"
    assert sock.closed
    # A second pairing attempt is preflight refused: no new socket frame.
    repeat = Socket()
    with pytest.raises(DeviceSessionRefused, match="device_existing_binding"):
        asyncio.run(run_and_stage_review_only_device_enrollment(
            enrollment=enrollment, socket=repeat, trusted_tls=Trusted(),
            receiver=LocalStoreCredentialReceiver(store=Store()),
            challenge_id=CID, pairing_code=CODE, now=NOW,
            binding_factory=_fake_binding,
        ))
    assert repeat.sent == []


def test_failed_stage_yields_exact_existing_security_hold_and_no_enrollment(tmp_path, monkeypatch):
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    enrollment.record().device_id = DEVICE
    enrollment.flush()
    shared = enrollment.record()
    monkeypatch.setattr(enrollment, "_write", lambda record: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(EnrollmentPersistenceError) as exc:
        asyncio.run(run_and_stage_review_only_device_enrollment(
            enrollment=enrollment, socket=Socket(), trusted_tls=Trusted(),
            receiver=LocalStoreCredentialReceiver(store=Store(), now_factory=lambda: NOW),
            challenge_id=CID, pairing_code=CODE, now=NOW,
            binding_factory=_fake_binding,
        ))
    assert exc.value.recovery.action == "security_hold_reconciliation_required"
    assert exc.value.recovery.retry_same_challenge is False
    assert enrollment.record() is shared
    assert shared.binding_ref is None
    hold = enrollment.reconciliation_hold()
    assert hold is not None
    assert hold["binding_ref"] == BINDING["binding_ref"]
    assert ConnectorEnrollment(state_dir=tmp_path / "state").record().binding_ref is None
    # Even with a fresh pairing code, the unresolved local hold blocks new
    # redemption before any new Broker call.
    socket = Socket()
    with pytest.raises(DeviceSessionRefused, match="existing_security_hold"):
        asyncio.run(run_and_stage_review_only_device_enrollment(
            enrollment=enrollment, socket=socket, trusted_tls=Trusted(),
            receiver=LocalStoreCredentialReceiver(store=Store()),
            challenge_id=CID, pairing_code=CODE, now=NOW,
            binding_factory=_fake_binding,
        ))
    assert socket.sent == []



def test_actual_kagent_binding_factory_constructs_canonical_type_when_source_available():
    repo = Path(__file__).resolve().parents[3]
    kagent_src = repo / "apps" / "korean-ai-code-agent" / "src"
    assert kagent_src.is_dir(), "canonical kagent tree must be present in monorepo"
    sys.path.insert(0, str(kagent_src))
    from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
    from claw_connect.device_wss_enrollment import canonical_kagent_binding_factory
    instance = canonical_kagent_binding_factory(
        BINDING, now=NOW,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    assert type(instance) is DeviceBinding
    assert instance.state is DeviceLifecycle.PAIRED_OFFLINE
    assert instance.credential_ref == BINDING["credential_ref"]
    assert instance.issued_at == NOW
