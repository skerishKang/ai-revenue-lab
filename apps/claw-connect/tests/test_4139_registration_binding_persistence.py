"""#4139 LOCAL2: the real WSS registration must make the binding durable.

The scripted part is the *server* (no real TLS / real Broker claim) and the
protected-data port (a reversible stand-in: NOT a DPAPI claim). Everything the
Windows side owns is real: the canonical ``ProtectedDeviceBindingStore``, the
canonical ``ProtectedFileDeviceCredentialStore``, the canonical DeviceBinding
and the canonical ``resume_registered_binding()`` restart path.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))
sys.path.insert(0, str(_HERE.parents[3] / "apps" / "korean-ai-code-agent" / "src"))

from claw_connect.credential_install import LocalStoreCredentialReceiver
from claw_connect.device_wss_enrollment import (
    DeviceSessionRefused, run_and_stage_review_only_device_enrollment,
)
from claw_connect.enrollment import ConnectorEnrollment, EnrollmentPersistenceError
from test_device_wss_enrollment_4139 import (  # noqa: E402 - sibling test fixtures
    BINDING, CID, CODE, CREDENTIAL, DEVICE, NOW, Socket, Trusted,
)

from kagent.local_agent_device_binding_store import (  # noqa: E402
    ProtectedDeviceBindingStore, ResumedDeviceBinding,
)
from kagent.local_agent_resident_process import (  # noqa: E402
    BrokerEntry, resume_registered_binding,
)
from kagent.local_agent_secure_transport import (  # noqa: E402
    ProtectedFileDeviceCredentialStore,
)


class ReversibleProtection:
    """Reversible stand-in for the current-user DPAPI port. Not a DPAPI claim."""

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        return b"stand-in-protected:" + plaintext[::-1]

    def unprotect(self, protected: bytes, *, entropy: bytes) -> bytes:
        assert protected.startswith(b"stand-in-protected:")
        return protected[len(b"stand-in-protected:"):][::-1]


class FailingBindingStore:
    def __init__(self, path):
        self.path = path

    def save(self, *, binding, now):
        raise OSError("binding disk")

    def load(self, *, device_id, now):
        raise AssertionError("a failed save must not be read back as a success")


class MismatchingBindingStore:
    """A store that answers with a different binding than it was handed."""

    def __init__(self, store):
        self._store = store
        self.path = store.path

    def save(self, *, binding, now):
        return self._store.save(binding=binding, now=now)

    def load(self, *, device_id, now):
        resumed = self._store.load(device_id=device_id, now=now)
        return ResumedDeviceBinding(
            binding=replace(resumed.binding, binding_ref="pairing-binding.other"),
        )


class UnusedPort:
    """The resume path must not need a broker call to rebuild the boundary."""

    def post(self, **kwargs):  # pragma: no cover - a call here is the failure
        raise AssertionError("resume must not open a broker call")


def _register(tmp_path, *, binding_store=None, credential_store=None, protection=None):
    protection = protection or ReversibleProtection()
    credential_dir = tmp_path / "protected"
    credential_store = credential_store or ProtectedFileDeviceCredentialStore(
        base_dir=credential_dir, protected_data=protection,
    )
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    enrollment.record().device_id = DEVICE
    enrollment.flush()
    published: list[bool] = []
    original_write = enrollment._write

    def spy(record):
        published.append(
            binding_store.path.is_file() if binding_store is not None else False
        )
        return original_write(record)

    enrollment._write = spy
    result = asyncio.run(
        run_and_stage_review_only_device_enrollment(
            enrollment=enrollment, socket=Socket(), trusted_tls=Trusted(),
            receiver=LocalStoreCredentialReceiver(
                store=credential_store, now_factory=lambda: NOW,
            ),
            challenge_id=CID, pairing_code=CODE, now=NOW,
            binding_store=binding_store,
        )
    )
    return result, enrollment, credential_dir, credential_store, published


def _real_stores(tmp_path):
    protection = ReversibleProtection()
    credential_dir = tmp_path / "protected"
    return (
        protection,
        ProtectedFileDeviceCredentialStore(
            base_dir=credential_dir, protected_data=protection,
        ),
        ProtectedDeviceBindingStore(
            base_dir=credential_dir, protected_data=protection,
        ),
    )


def test_wss_registration_persists_the_binding_before_it_publishes(tmp_path):
    protection, credential_store, binding_store = _real_stores(tmp_path)
    result, enrollment, credential_dir, _, published = _register(
        tmp_path, binding_store=binding_store, credential_store=credential_store,
        protection=protection,
    )
    # The one ordering claim: the canonical binding record existed on disk at
    # the moment the enrollment record was published — never after.
    assert published == [True]
    assert result.binding_ref == BINDING["binding_ref"]
    assert enrollment.record().is_enrolled() is True
    assert enrollment.reconciliation_hold() is None
    # Restore check through the same store the Resident will read from.
    resumed = binding_store.load(device_id=DEVICE, now=NOW)
    assert resumed.binding.binding_ref == BINDING["binding_ref"]
    assert resumed.binding.account_ref == BINDING["account_ref"]
    assert resumed.binding.workspace_ref == BINDING["workspace_ref"]
    assert resumed.binding.credential_generation == BINDING["credential_generation"]
    # Two records in ONE canonical directory: the credential and its binding.
    files = sorted(path.name for path in credential_dir.iterdir())
    assert "device-binding.json" in files
    assert len([name for name in files if name.endswith(".credential.json")]) == 1


def test_a_registered_pc_resumes_without_redeeming_a_new_pairing_code(tmp_path):
    protection, credential_store, binding_store = _real_stores(tmp_path)
    _, _, credential_dir, _, _ = _register(
        tmp_path, binding_store=binding_store, credential_store=credential_store,
        protection=protection,
    )
    # A restarted process holds no handoff and no challenge — exactly the state
    # that used to refuse with handoff_refused.
    entry = BrokerEntry(
        device_id=DEVICE, authority_ref="authority.4139.local2",
        request_port=UnusedPort(), credential_dir=str(credential_dir),
    )
    later = NOW + timedelta(minutes=1)
    resumed = resume_registered_binding(entry=entry, now=later, protected_data=protection)
    assert resumed["resumed"] is True
    assert resumed["redeem_count"] == 0  # no pairing code, no new redemption
    assert resumed["binding"].binding_ref == BINDING["binding_ref"]
    # The canonical store returns the credential only when the rebuilt binding
    # context is the protected one, which is the proof the resume is real.
    assert resumed["store"].load(binding=resumed["binding"], now=later) == CREDENTIAL


def test_a_binding_store_that_cannot_persist_publishes_no_enrollment(tmp_path):
    protection, credential_store, _ = _real_stores(tmp_path)
    failing = FailingBindingStore(tmp_path / "protected" / "device-binding.json")
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    enrollment.record().device_id = DEVICE
    enrollment.flush()
    with pytest.raises(EnrollmentPersistenceError) as exc:
        asyncio.run(
            run_and_stage_review_only_device_enrollment(
                enrollment=enrollment, socket=Socket(), trusted_tls=Trusted(),
                receiver=LocalStoreCredentialReceiver(
                    store=credential_store, now_factory=lambda: NOW,
                ),
                challenge_id=CID, pairing_code=CODE, now=NOW,
                binding_store=failing,
            )
        )
    assert exc.value.recovery.action == "security_hold_reconciliation_required"
    assert exc.value.recovery.report_enrolled is False
    assert enrollment.record().binding_ref is None
    assert enrollment.record().is_enrolled() is False
    committed = ConnectorEnrollment(state_dir=tmp_path / "state").committed_record()
    assert committed is not None and committed.binding_ref is None
    assert committed.is_enrolled() is False
    assert enrollment.reconciliation_hold() is not None
    assert isinstance(exc.value.__cause__, DeviceSessionRefused)


def test_a_binding_that_does_not_restore_publishes_no_enrollment(tmp_path):
    protection, credential_store, binding_store = _real_stores(tmp_path)
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    enrollment.record().device_id = DEVICE
    enrollment.flush()
    with pytest.raises(EnrollmentPersistenceError) as exc:
        asyncio.run(
            run_and_stage_review_only_device_enrollment(
                enrollment=enrollment, socket=Socket(), trusted_tls=Trusted(),
                receiver=LocalStoreCredentialReceiver(
                    store=credential_store, now_factory=lambda: NOW,
                ),
                challenge_id=CID, pairing_code=CODE, now=NOW,
                binding_store=MismatchingBindingStore(binding_store),
            )
        )
    assert str(exc.value.__cause__) == "device_binding_restore_mismatch"
    assert enrollment.record().is_enrolled() is False
    committed = ConnectorEnrollment(state_dir=tmp_path / "state").committed_record()
    assert committed is not None and committed.binding_ref is None
    assert committed.is_enrolled() is False


def test_the_default_store_requires_the_canonical_credential_dir(tmp_path, monkeypatch):
    protection, credential_store, _ = _real_stores(tmp_path)
    monkeypatch.delenv("PADIEM_AGENT_CREDENTIAL_DIR", raising=False)
    enrollment = ConnectorEnrollment(state_dir=tmp_path / "state")
    enrollment.record().device_id = DEVICE
    enrollment.flush()
    with pytest.raises(EnrollmentPersistenceError) as exc:
        asyncio.run(
            run_and_stage_review_only_device_enrollment(
                enrollment=enrollment, socket=Socket(), trusted_tls=Trusted(),
                receiver=LocalStoreCredentialReceiver(
                    store=credential_store, now_factory=lambda: NOW,
                ),
                challenge_id=CID, pairing_code=CODE, now=NOW,
            )
        )
    assert isinstance(exc.value.__cause__, DeviceSessionRefused)
    assert "canonical_credential_dir" in str(exc.value.__cause__)
    assert enrollment.record().is_enrolled() is False


def test_the_operator_wss_path_supplies_the_canonical_binding_store():
    source = (
        Path(__file__).resolve().parents[1] / "claw_connect" / "operator_wss_enrollment.py"
    ).read_text(encoding="utf-8")
    assert "canonical_binding_store(" in source
    assert "binding_store=binding_store" in source
