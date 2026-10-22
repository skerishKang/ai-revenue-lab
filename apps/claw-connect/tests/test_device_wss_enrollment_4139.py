"""WSS device-side proof/DPAPI-ACK parity with CENTRAL #4476 frames.

Synthetic connection and protected store: NEVER a claim of live TLS or DPAPI.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import sys
import time
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


class FakeBindingStore:
    """The composition's canonical protected binding store, faked for speed.

    The real store is exercised in test_4139_registration_binding_persistence;
    here only the save-then-readback-before-publish ordering matters.
    """

    def __init__(self, *, corrupt=False, fail=False):
        self.saved = []
        self.corrupt = corrupt
        self.fail = fail

    def save(self, *, binding, now):
        if self.fail:
            raise OSError("binding disk")
        self.saved.append(binding)

    def load(self, *, device_id, now):
        restored = SimpleNamespace(**vars(self.saved[-1]))
        if self.corrupt:
            restored.binding_ref = "pairing-binding.other"
        return SimpleNamespace(binding=restored)


class Socket:
    def __init__(self, *, terminal="paired_offline", corrupted=None,
                 lease_expires_at="2030-01-01T00:00:00+00:00"):
        self.sent = []
        self.closed = False
        self.terminal = terminal
        self.corrupted = corrupted
        self.lease_expires_at = lease_expires_at
        self.index = 0
    async def send_text(self, message):
        self.sent.append(json.loads(message))
    async def receive_text(self):
        stage = self.index
        self.index += 1
        if stage == 0:
            data = {"type": "nonce", "challenge_id": CID,
                    "device_id": DEVICE, "lease_ref": LEASE,
                    "nonce_hex": NONCE, "expires_at": self.lease_expires_at}
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
    def __init__(self, ok=True, delay=0.0):
        self.ok = ok
        self.delay = delay
    async def verify(self, socket):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.ok


def _fake_binding(fields, *, now, expires_at):
    return SimpleNamespace(**fields)


def run(sock, store=None, trusted=None, *, on_stage=None, now=None):
    return asyncio.run(run_review_only_device_session(
        socket=sock, trusted_tls=trusted or Trusted(),
        receiver=LocalStoreCredentialReceiver(store=store or Store(), now_factory=lambda: NOW),
        challenge_id=CID, device_id=DEVICE, pairing_code=CODE, now=now or NOW,
        binding_factory=_fake_binding, on_stage=on_stage,
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
        binding_store=FakeBindingStore(),
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
            binding_store=FakeBindingStore(),
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
            binding_store=FakeBindingStore(),
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
            binding_store=FakeBindingStore(),
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



@pytest.mark.skipif(sys.platform != "win32", reason="real DPAPI is Windows only")
def test_exact_wss_delivery_drives_real_canonical_windows_dpapi_store(tmp_path):
    """No real network: genuine kagent DeviceBinding + Windows user DPAPI.

    The broker frame is scripted, but the actual Windows credential store
    writes encrypted bytes, reads the same scope and yields the ACK proof.
    """
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / "apps" / "korean-ai-code-agent" / "src"))
    from kagent.local_agent_secure_transport import (
        ProtectedFileDeviceCredentialStore, WindowsDpapiProtectedDataPort,
    )
    store = ProtectedFileDeviceCredentialStore(
        base_dir=tmp_path / "protected",
        protected_data=WindowsDpapiProtectedDataPort(),
    )
    receiver = LocalStoreCredentialReceiver(store=store, now_factory=lambda: NOW)
    sock = Socket()
    receipt = asyncio.run(run_review_only_device_session(
        socket=sock, trusted_tls=Trusted(), receiver=receiver,
        challenge_id=CID, device_id=DEVICE, pairing_code=CODE, now=NOW,
        # NO synthetic binding_factory here: use actual canonical kagent type.
    ))
    assert receipt.binding_ref == BINDING["binding_ref"]
    assert receipt.online is False and receipt.local_record_committed is False
    assert sock.sent[-1]["type"] == "install_ack"
    assert len(list((tmp_path / "protected").glob("*.credential.json"))) == 1
    persisted = b"".join(
        file.read_bytes() for file in (tmp_path / "protected").glob("*.credential.json")
    )
    assert CREDENTIAL not in persisted
    assert base64.b64encode(CREDENTIAL) not in persisted


def test_device_wss_source_stage_codes_observe_canonical_success_without_secrets():
    stages = []
    sock = Socket()
    result = run(sock, on_stage=stages.append)
    assert result.lifecycle == "paired_offline"
    assert stages == [
        "device_session_tls_verified",
        "device_session_begin_sent",
        "device_session_nonce_verified",
        "device_session_finish_sent",
        "device_session_bootstrap_verified",
        "device_session_credential_fetch_sent",
        "credential_once_received",
        "dpapi_store_confirmed",
        "install_ack_sent",
        "install_ack_accepted",
    ]
    emitted = " ".join(stages)
    for private in (CODE, CID, DEVICE, LEASE, NONCE, CREDENTIAL.decode()):
        assert private not in emitted


def test_device_wss_source_stages_preserve_nonce_and_tls_fail_closed():
    denied_tls_stages = []
    tls_socket = Socket()
    with pytest.raises(DeviceSessionRefused, match="trusted_tls_required"):
        run(tls_socket, trusted=Trusted(ok=False), on_stage=denied_tls_stages.append)
    assert denied_tls_stages == []
    assert tls_socket.sent == []
    assert tls_socket.closed is True

    nonce_stages = []
    nonce_socket = Socket(corrupted="nonce_swap")
    with pytest.raises(DeviceSessionRefused, match="device_nonce_correlation_invalid"):
        run(nonce_socket, on_stage=nonce_stages.append)
    assert nonce_stages == [
        "device_session_tls_verified", "device_session_begin_sent",
    ]
    assert nonce_socket.closed is True


def test_device_wss_source_transport_error_remains_bounded_and_closes():
    stages = []

    class BrokenTransport(Socket):
        async def receive_text(self):
            raise OSError("private transport detail must not leak")

    sock = BrokenTransport()
    with pytest.raises(DeviceSessionRefused, match=r"^device_session_security_hold$"):
        run(sock, on_stage=stages.append)
    assert stages == [
        "device_session_tls_verified", "device_session_begin_sent",
    ]
    assert sock.closed is True


def test_credential_fetch_timeout_is_bounded_and_does_not_store_or_ack():
    stages = []
    store = Store()

    class CredentialTimeout(Socket):
        async def receive_text(self):
            if self.index == 2:
                raise asyncio.TimeoutError("private upstream timeout message")
            return await super().receive_text()

    sock = CredentialTimeout()
    with pytest.raises(DeviceSessionRefused, match=r"^device_credential_response_timeout$"):
        run(sock, store=store, on_stage=stages.append)
    assert sock.closed is True
    assert store.saved == []
    assert [entry["type"] for entry in sock.sent] == [
        "begin", "finish", "credential_fetch",
    ]
    assert stages[-1] == "device_session_credential_fetch_sent"
    assert "private upstream timeout message" not in " ".join(stages)


def test_installed_connector_persists_new_safe_device_session_stage(tmp_path):
    from claw_connect.runtime import ConnectApp

    holder = SimpleNamespace(_state_dir=str(tmp_path), _offer_stage="owner_link_confirmed")
    ConnectApp._record_offer_stage(holder, "device_session_begin_sent")
    state = json.loads((tmp_path / "customer-offer-stage.json").read_text())
    assert state == {
        "stage": "device_session_begin_sent",
        "result": "in_progress",
        "reason": None,
    }
    ConnectApp._record_offer_stage(
        holder, "device_session_credential_fetch_sent",
        failure="device_session_security_hold",
    )
    state = json.loads((tmp_path / "customer-offer-stage.json").read_text())
    assert state == {
        "stage": "device_session_credential_fetch_sent",
        "result": "failed",
        "reason": "device_session_security_hold",
    }
    # Unrecognized wire/private values cannot be persisted as stage text.
    ConnectApp._record_offer_stage(holder, "credential_" + CREDENTIAL.decode())
    assert json.loads((tmp_path / "customer-offer-stage.json").read_text()) == state


def test_credential_delivery_waits_for_the_canonical_owner_driven_delivery(monkeypatch):
    """#3099: the canonical credential is delivered by the server's owner
    approval flow, not by the preceding ``credential_fetch`` frame.

    The PC used to apply the generic per-frame bound to that delivery and
    aborted a registration the server was still completing, which is what the
    live 2026-10-22 attempt recorded as
    ``device_session_credential_fetch_sent / device_credential_response_timeout``.
    """
    import claw_connect.device_wss_enrollment as module

    monkeypatch.setattr(module, "FRAME_TIMEOUT_SECONDS", 0.05)
    # The canonical delivery window must never be shorter than the generic
    # per-frame bound it replaces.
    assert module.CREDENTIAL_DELIVERY_TIMEOUT_SECONDS > module.FRAME_TIMEOUT_SECONDS

    class DelayedCredentialSocket(Socket):
        async def receive_text(self):
            if self.index == 2:
                # Longer than the generic per-frame bound, inside the
                # canonical delivery window.
                await asyncio.sleep(0.2)
            return await super().receive_text()

    sock, store = DelayedCredentialSocket(), Store()
    receipt = run(sock, store)
    assert receipt.lifecycle == "paired_offline"
    assert receipt.device_id == DEVICE
    assert store.saved and store.saved[0][1] == CREDENTIAL
    assert [entry["type"] for entry in sock.sent] == [
        "begin", "finish", "credential_fetch", "install_ack",
    ]
    assert sock.closed is True


def test_credential_delivery_stall_still_fails_closed_without_store_or_ack(monkeypatch):
    """A genuinely missing credential is still refused: no store write, no ACK."""
    import claw_connect.device_wss_enrollment as module

    monkeypatch.setattr(module, "CREDENTIAL_DELIVERY_TIMEOUT_SECONDS", 0.05)

    class StalledCredentialSocket(Socket):
        async def receive_text(self):
            if self.index == 2:
                await asyncio.sleep(5)
            return await super().receive_text()

    sock, store = StalledCredentialSocket(), Store()
    with pytest.raises(DeviceSessionRefused, match=r"^device_credential_response_timeout$"):
        run(sock, store)
    assert sock.closed is True
    assert store.saved == []
    assert [entry["type"] for entry in sock.sent] == [
        "begin", "finish", "credential_fetch",
    ]


def test_credential_window_subtracts_begin_and_bootstrap_delays(monkeypatch):
    """#3099: the whole handshake time is charged to the receive window.

    The budget is computed after ``credential_fetch`` is sent, so the ``begin``
    -> ``nonce`` leg AND the ``finish`` -> ``bootstrap_verified`` leg must both
    already have been subtracted. Only the local monotonic elapsed time is
    used, so no clock difference can change the result.
    """
    import claw_connect.device_wss_enrollment as module

    # 1.0s lease with a 0.5s ACK reserve leaves a 0.5s budget.
    monkeypatch.setattr(module, "GATEWAY_LEASE_TTL_SECONDS", 1.0)
    monkeypatch.setattr(module, "INSTALL_ACK_RESERVE_SECONDS", 0.5)

    class SlowLegsSocket(Socket):
        async def receive_text(self):
            if self.index in (0, 1):
                # The begin leg and the bootstrap leg.
                await asyncio.sleep(0.3)
            return await super().receive_text()

    sock, store = SlowLegsSocket(), Store()
    started = time.monotonic()
    with pytest.raises(
        DeviceSessionRefused, match=r"^device_credential_delivery_window_expired$",
    ):
        run(sock, store)
    # The discriminator is the refusal code above: with only one leg charged
    # the budget would still be positive and this would be a credential timeout
    # instead. The wall time below is only a sanity bound, never the assertion.
    assert time.monotonic() - started >= 0.5
    assert sock.closed is True
    assert store.saved == []
    assert [entry["type"] for entry in sock.sent] == ["begin", "finish", "credential_fetch"]


def test_credential_window_starts_before_the_tls_verification(monkeypatch):
    """#3099: the budget starts before ``begin``, not after the TLS check."""
    import claw_connect.device_wss_enrollment as module

    monkeypatch.setattr(module, "GATEWAY_LEASE_TTL_SECONDS", 1.0)
    monkeypatch.setattr(module, "INSTALL_ACK_RESERVE_SECONDS", 0.5)

    sock, store = Socket(), Store()
    started = time.monotonic()
    with pytest.raises(
        DeviceSessionRefused, match=r"^device_credential_delivery_window_expired$",
    ):
        run(sock, store, trusted=Trusted(delay=0.6))
    # The discriminator is the refusal code above: starting the budget after
    # the TLS verification would leave a positive window and the fake socket
    # would deliver immediately. The wall time below is only a sanity bound.
    assert time.monotonic() - started >= 0.5
    assert sock.closed is True
    assert store.saved == []
    assert [entry["type"] for entry in sock.sent] == ["begin", "finish", "credential_fetch"]


def test_credential_window_is_capped_by_the_remaining_broker_lease(monkeypatch):
    """#3099: the wait may never outlive the Broker gateway lease.

    The Broker authorizes the ``install_ack`` against the SAME lease, so a
    credential window longer than the remaining lease would let the Broker
    refuse the ACK of a credential it already delivered. The budget is the
    canonical lease TTL minus the locally measured handshake time minus the
    ACK reserve - never a fixed number.
    """
    import claw_connect.device_wss_enrollment as module

    # Even the maximum client window leaves the ACK reserve inside the lease.
    assert (
        module.CREDENTIAL_DELIVERY_TIMEOUT_SECONDS
        + module.INSTALL_ACK_RESERVE_SECONDS
        <= module.GATEWAY_LEASE_TTL_SECONDS
    )

    class SlowHandshakeSocket(Socket):
        async def receive_text(self):
            if self.index == 0:
                # The handshake itself consumes lease time.
                await asyncio.sleep(0.2)
            return await super().receive_text()

    # A live lease leaves a usable window: the credential is still accepted.
    monkeypatch.setattr(module, "GATEWAY_LEASE_TTL_SECONDS", 30.0)
    monkeypatch.setattr(module, "INSTALL_ACK_RESERVE_SECONDS", 25.0)
    sock, store = SlowHandshakeSocket(), Store()
    receipt = run(sock, store)
    assert receipt.lifecycle == "paired_offline"
    assert store.saved and store.saved[0][1] == CREDENTIAL

    # A handshake that already consumed the lease cannot carry the ACK.
    monkeypatch.setattr(module, "GATEWAY_LEASE_TTL_SECONDS", 12.0)
    monkeypatch.setattr(module, "INSTALL_ACK_RESERVE_SECONDS", 10.0)

    class LeaseConsumingSocket(Socket):
        async def receive_text(self):
            if self.index == 0:
                await asyncio.sleep(3)
            return await super().receive_text()

    sock, store = LeaseConsumingSocket(), Store()
    started = time.monotonic()
    with pytest.raises(
        DeviceSessionRefused, match=r"^device_credential_delivery_window_expired$",
    ):
        run(sock, store)
    assert time.monotonic() - started >= 3.0
    assert sock.closed is True
    assert store.saved == []
    assert [entry["type"] for entry in sock.sent] == [
        "begin", "finish", "credential_fetch",
    ]


def test_credential_window_refuses_immediately_when_the_lease_cannot_carry_the_ack(monkeypatch):
    """A lease that cannot still authorize the install ACK is refused at once."""
    import claw_connect.device_wss_enrollment as module

    monkeypatch.setattr(module, "GATEWAY_LEASE_TTL_SECONDS", 0.05)
    sock = Socket()
    store = Store()
    started = time.monotonic()
    with pytest.raises(
        DeviceSessionRefused, match=r"^device_credential_delivery_window_expired$",
    ):
        run(sock, store)
    assert time.monotonic() - started < 1.0
    assert sock.closed is True
    assert store.saved == []
    assert [entry["type"] for entry in sock.sent] == ["begin", "finish", "credential_fetch"]


def test_credential_window_does_not_depend_on_any_wall_clock(monkeypatch):
    """#3099: a clock difference between this PC and the Broker must not size
    the window.

    The Broker's absolute lease expiry is a server wall-clock value and this
    PC's own clock can differ from it, so neither may decide how long the PC
    waits. The window is derived from the local monotonic handshake time and
    the canonical lease TTL only.
    """
    import claw_connect.device_wss_enrollment as module

    monkeypatch.setattr(module, "GATEWAY_LEASE_TTL_SECONDS", 12.0)
    monkeypatch.setattr(module, "INSTALL_ACK_RESERVE_SECONDS", 10.0)

    class DelayedCredentialSocket(Socket):
        async def receive_text(self):
            if self.index == 2:
                await asyncio.sleep(3)
            return await super().receive_text()

    outcomes = []
    for lease_expires_at, session_now in (
        # A lease that looks nearly expired on the Broker's clock.
        ((datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(), NOW),
        # A lease that looks far away on the Broker's clock, with this PC's
        # own clock a year ahead of the session it was started with.
        ("2030-01-01T00:00:00+00:00",
         datetime.now(timezone.utc) + timedelta(days=365)),
    ):
        sock, store = DelayedCredentialSocket(lease_expires_at=lease_expires_at), Store()
        try:
            run(sock, store, now=session_now)
            outcomes.append(("accepted", store.saved != []))
        except DeviceSessionRefused as exc:
            outcomes.append((str(exc), store.saved == []))
    # Identical behaviour for both clock views: the wall clock decides nothing.
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] != "accepted"
    assert module.GATEWAY_LEASE_TTL_SECONDS > 0.0

