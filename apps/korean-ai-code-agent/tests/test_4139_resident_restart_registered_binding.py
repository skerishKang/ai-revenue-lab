"""#4139 STEP 3 — a registered PC restarts itself from durable state.

The gap this pins: the credential was durable but the ``DeviceBinding`` lived
only in the enrollment process's memory, so a restart had nothing to resume
from and the Resident refused with ``handoff_refused`` even though the PC was
already registered. The one-shot handoff is for *first* registration only.

These tests use a synthetic redeem port and a stand-in protected-data port, so
no real Broker, DPAPI blob, registry key or user file is touched. The
protected-data stand-in mirrors the real port's contract (protect/unprotect
under an entropy), which is what makes the disk-only resume meaningful.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

AGENT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(AGENT_SRC))

from kagent import local_agent_resident_process as resident
from kagent.contracts import ContractError
from kagent.local_agent_device_binding_store import (
    DEVICE_BINDING_FILENAME,
    ProtectedDeviceBindingStore,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
from kagent.local_agent_resident_process import (
    HANDOFF_CONTRACT_VERSION,
    BrokerEntry,
    resume_registered_binding,
    redeem_handoff,
)
from kagent.local_agent_secure_transport import (
    ProtectedFileDeviceCredentialStore,
    WindowsDpapiProtectedDataPort,
)

DEVICE_ID = "device.4139.restart"
AUTHORITY_REF = "control-plane.local-agent-broker.4139.restart.v1"
CREDENTIAL_REF = "credential-ref.4139.restart.1"
CREDENTIAL = b"4139-restart-credential-bytes"
BASE = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class _ProtectedDataPort:
    """Mirrors the real DPAPI port contract: protect/unprotect under entropy."""

    def _stream(self, entropy: bytes, length: int) -> bytes:
        import hashlib

        out = b""
        block = 0
        while len(out) < length:
            out += hashlib.sha256(entropy + block.to_bytes(4, "big")).digest()
            block += 1
        return out[:length]

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        stream = self._stream(entropy, len(plaintext))
        return bytes(a ^ b for a, b in zip(plaintext, stream))

    def unprotect(self, protected: bytes, *, entropy: bytes) -> bytes:
        stream = self._stream(entropy, len(protected))
        return bytes(a ^ b for a, b in zip(protected, stream))


class _FakeRedeemPort:
    """Returns one canonical enrollment response; no network is contacted."""

    def __init__(self, *, device_id: str = DEVICE_ID) -> None:
        self._device_id = device_id
        self.payloads: list[dict] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del config, timeout_seconds
        self.payloads.append(payload)
        now = datetime.fromisoformat(str(payload["now"]).replace("Z", "+00:00"))
        return {
            "ok": True,
            "enrollment": {
                "binding_ref": "binding.4139.restart.1",
                "device_id": self._device_id,
                "account_ref": "account.4139",
                "workspace_ref": "workspace.4139",
                "credential_ref": CREDENTIAL_REF,
                "credential_generation": 1,
                "issued_at": now.isoformat().replace("+00:00", "Z"),
                "credential_expires_at": (now + timedelta(hours=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "challenge_id": payload["challenge_id"],
                "server_owned_binding_refs": True,
                "raw_device_credential": False,
                "production_ready": False,
            },
            "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
            "credential_returned_once": True,
        }


def _handoff(challenge_id: str = "challenge.4139.restart.1") -> dict:
    return {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "pairing_code": "0" * 32,
        "correlation_ref": "pairref.4139.restart",
        "challenge_id": challenge_id,
    }


def _entry(credential_dir: Path) -> BrokerEntry:
    return BrokerEntry(
        device_id=DEVICE_ID,
        authority_ref=AUTHORITY_REF,
        request_port=_FakeRedeemPort(),
        credential_dir=str(credential_dir),
    )


def _enroll(tmp_path: Path, *, protection=None, now: datetime = BASE) -> tuple[dict, Path]:
    credential_dir = tmp_path / "credential-store"
    credential_dir.mkdir()
    redeemed = redeem_handoff(
        _handoff(),
        entry=_entry(credential_dir),
        base_dir=str(credential_dir),
        now=now,
        protected_data=protection if protection is not None else _ProtectedDataPort(),
    )
    return redeemed, credential_dir


# -- what is written to disk ------------------------------------------------


def test_enrollment_persists_the_binding_beside_its_credential(tmp_path):
    redeemed, credential_dir = _enroll(tmp_path)
    record_path = credential_dir / DEVICE_BINDING_FILENAME

    assert record_path.is_file()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["binding_ref"] == redeemed["binding"].binding_ref
    assert record["device_id"] == DEVICE_ID
    assert record["state"] == DeviceLifecycle.PAIRED_OFFLINE.value


def test_the_binding_record_holds_no_plaintext_reference_or_credential(tmp_path):
    _, credential_dir = _enroll(tmp_path)
    raw = (credential_dir / DEVICE_BINDING_FILENAME).read_text(encoding="utf-8")

    # The security design is preserved: neither the reference in the clear nor
    # any credential material is on disk.
    assert CREDENTIAL_REF not in raw
    assert base64.b64encode(CREDENTIAL).decode("ascii") not in raw
    assert CREDENTIAL.decode("ascii") not in raw
    assert "pairing_code" not in raw
    assert "challenge_id" not in raw


# -- the restart path -------------------------------------------------------


def test_a_restart_resumes_the_registered_device_with_no_handoff(tmp_path):
    redeemed, credential_dir = _enroll(tmp_path)
    later = BASE + timedelta(minutes=5)

    # Disk only: a fresh entry, fresh stores, no in-memory binding carried over.
    resumed = resume_registered_binding(
        entry=_entry(credential_dir), now=later, protected_data=_ProtectedDataPort()
    )

    assert resumed["resumed"] is True
    assert resumed["redeem_count"] == 0
    assert resumed["binding"] == redeemed["binding"]
    # The rebuilt binding is the one the credential was protected under, so the
    # canonical store returns the credential without any new secret.
    assert resumed["store"].load(binding=resumed["binding"], now=later) == CREDENTIAL


def test_resume_refuses_a_binding_that_belongs_to_another_device(tmp_path):
    _, credential_dir = _enroll(tmp_path)
    store = ProtectedDeviceBindingStore(
        base_dir=credential_dir, protected_data=_ProtectedDataPort()
    )

    with pytest.raises(ContractError):
        store.load(device_id="device.4139.someone.else", now=BASE)


def test_resume_refuses_when_nothing_is_registered(tmp_path):
    credential_dir = tmp_path / "empty-store"
    credential_dir.mkdir()

    with pytest.raises(ContractError):
        resume_registered_binding(
            entry=_entry(credential_dir), now=BASE, protected_data=_ProtectedDataPort()
        )


@pytest.mark.parametrize(
    "state",
    [DeviceLifecycle.REVOKED, DeviceLifecycle.UNPAIRED, DeviceLifecycle.CREDENTIAL_EXPIRED],
)
def test_resume_refuses_a_binding_the_server_would_reject(tmp_path, state):
    credential_dir = tmp_path / "credential-store"
    credential_dir.mkdir()
    store = ProtectedDeviceBindingStore(
        base_dir=credential_dir, protected_data=_ProtectedDataPort()
    )
    store.save(
        binding=DeviceBinding(
            device_id=DEVICE_ID,
            binding_ref="binding.4139.restart.1",
            account_ref="account.4139",
            workspace_ref="workspace.4139",
            credential_ref=CREDENTIAL_REF,
            credential_generation=1,
            issued_at=BASE,
            credential_expires_at=BASE + timedelta(hours=1),
            state=state,
        ),
        now=BASE,
    )

    with pytest.raises(ContractError):
        store.load(device_id=DEVICE_ID, now=BASE + timedelta(minutes=1))


def test_resume_refuses_an_expired_binding(tmp_path):
    credential_dir = tmp_path / "credential-store"
    credential_dir.mkdir()
    store = ProtectedDeviceBindingStore(
        base_dir=credential_dir, protected_data=_ProtectedDataPort()
    )
    store.save(
        binding=DeviceBinding(
            device_id=DEVICE_ID,
            binding_ref="binding.4139.restart.1",
            account_ref="account.4139",
            workspace_ref="workspace.4139",
            credential_ref=CREDENTIAL_REF,
            credential_generation=1,
            issued_at=BASE,
            credential_expires_at=BASE + timedelta(hours=1),
        ),
        now=BASE,
    )

    with pytest.raises(ContractError):
        store.load(device_id=DEVICE_ID, now=BASE + timedelta(hours=2))


def test_a_tampered_record_is_refused(tmp_path):
    _, credential_dir = _enroll(tmp_path)
    record_path = credential_dir / DEVICE_BINDING_FILENAME
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["credential_ref_protected_b64"] = base64.b64encode(b"forged").decode("ascii")
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ContractError):
        resume_registered_binding(
            entry=_entry(credential_dir), now=BASE, protected_data=_ProtectedDataPort()
        )


# -- the Resident's own startup decision ------------------------------------


def _configure(monkeypatch, credential_dir: Path) -> None:
    monkeypatch.setenv("PADIEM_AGENT_DEVICE_ID", DEVICE_ID)
    monkeypatch.setenv("PADIEM_AGENT_AUTHORITY_REF", AUTHORITY_REF)
    monkeypatch.setenv("PADIEM_AGENT_CREDENTIAL_DIR", str(credential_dir))
    # The request-port factory refuses to be constructed without a pinned
    # broker origin. Nothing in these two tests opens a socket: the resume path
    # is disk-only and the host composition is stubbed.
    monkeypatch.setenv("PADIEM_AGENT_BROKER_URL", "https://local-agent.padiem.net")
    monkeypatch.setenv(
        "PADIEM_AGENT_REQUEST_PORT",
        "kagent.local_agent_broker_pairing_handoff_entry:make_request_port",
    )


def _emitted(capsys) -> list[dict]:
    return [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip().startswith("{")
    ]


def test_main_resumes_instead_of_refusing_when_already_registered(
    tmp_path, monkeypatch, capsys
):
    # The real current-user DPAPI port, because ``main`` has no injectable port:
    # the resume must work through exactly the protection the Resident uses in
    # production, not a stand-in. ``main`` also reads the wall clock, so the
    # enrollment is made against real time.
    _, credential_dir = _enroll(
        tmp_path,
        protection=WindowsDpapiProtectedDataPort(),
        now=datetime.now(timezone.utc).replace(microsecond=0),
    )
    _configure(monkeypatch, credential_dir)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    # The host composition is a separate concern here (and needs a real Windows
    # execution root), so stop at the decision under test.
    def _refuse_host(*_args, **_kwargs):
        raise ContractError("host composition not part of this test")

    monkeypatch.setattr(resident, "build_resident_host", _refuse_host)

    assert resident.main([]) == 0
    events = _emitted(capsys)
    assert [event["event"] for event in events if "event" in event] == [
        "registered_device_resumed",
        "host_build_start",
    ]
    assert not [event for event in events if event.get("reason") == "handoff_refused"]


def test_main_still_refuses_a_device_that_was_never_registered(
    tmp_path, monkeypatch, capsys
):
    credential_dir = tmp_path / "never-registered"
    credential_dir.mkdir()
    _configure(monkeypatch, credential_dir)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    assert resident.main([]) == 2
    events = _emitted(capsys)
    assert events[-1]["reason"] == "handoff_refused"
    assert "no durable device binding is stored" in events[-1]["resume_refused"]
