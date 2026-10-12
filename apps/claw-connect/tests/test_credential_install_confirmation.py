"""#4139 LOCAL2 protected credential install confirmation tests (isolated).

Proves the local install gate reuses the canonical store contract, fails closed
on store failure, never carries raw credential material, and stays disabled
until the central delivery channel is defined.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.credential_install import (  # noqa: E402
    CREDENTIAL_HANDOFF_WIRED,
    CredentialInstallError,
    CredentialInstallNotWiredError,
    LocalStoreCredentialReceiver,
    ProtectedCredentialInstallConfirmation,
    UnconfiguredProtectedCredentialReceiver,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
CREDENTIAL = b"raw-device-credential-bytes"


@dataclass(frozen=True)
class _FakeBinding:
    binding_ref: str
    device_id: str


@dataclass(frozen=True)
class _FakeProjection:
    binding_ref: str
    device_id: str
    credential_generation: int


class _FakeCanonicalStore:
    """Mirrors kagent ``DeviceCredentialStore.save`` shape (no kagent import)."""

    def __init__(self, *, fail: bool = False, return_none: bool = False, wrong_device=False):
        self._fail = fail
        self._return_none = return_none
        self._wrong_device = wrong_device
        self.saved: list[bytes] = []

    def save(self, *, binding, credential, now):
        if self._fail:
            raise OSError("DPAPI protect failed with system error 5")
        self.saved.append(credential)
        if self._return_none:
            return None
        device = "pc_other" if self._wrong_device else binding.device_id
        return _FakeProjection(
            binding_ref=binding.binding_ref,
            device_id=device,
            credential_generation=2,
        )


def test_delivery_channel_is_disabled_by_default():
    assert CREDENTIAL_HANDOFF_WIRED is False
    receiver = UnconfiguredProtectedCredentialReceiver()
    assert receiver.ready(challenge_id="c1", device_id="pc_abc123") is False
    with pytest.raises(CredentialInstallNotWiredError):
        receiver.install_once(
            challenge_id="c1",
            device_id="pc_abc123",
            credential=CREDENTIAL,
            binding=_FakeBinding("binding-1", "pc_abc123"),
        )


def test_install_is_confirmed_only_by_local_store_projection():
    store = _FakeCanonicalStore()
    receiver = LocalStoreCredentialReceiver(store=store, now_factory=lambda: NOW)
    confirmation = receiver.install_once(
        challenge_id="c1",
        device_id="pc_abc123",
        credential=CREDENTIAL,
        binding=_FakeBinding("binding-1", "pc_abc123"),
    )
    assert isinstance(confirmation, ProtectedCredentialInstallConfirmation)
    assert confirmation.installed is True
    assert confirmation.confirmed_by_local_store is True
    assert confirmation.raw_credential_persisted is False
    assert store.saved == [CREDENTIAL]
    # The confirmation never carries the credential.
    payload = confirmation.safe_dict()
    assert "credential" not in {k for k in payload}
    assert CREDENTIAL not in repr(payload).encode("utf-8", "ignore")


@pytest.mark.parametrize(
    "store,expected",
    [
        (_FakeCanonicalStore(fail=True), "protected store save failed"),
        (_FakeCanonicalStore(return_none=True), "protected store returned no projection"),
        (_FakeCanonicalStore(wrong_device=True), "store projection device mismatch"),
    ],
)
def test_store_failure_never_produces_a_confirmation(store, expected):
    receiver = LocalStoreCredentialReceiver(store=store, now_factory=lambda: NOW)
    with pytest.raises(CredentialInstallError) as exc:
        receiver.install_once(
            challenge_id="c1",
            device_id="pc_abc123",
            credential=CREDENTIAL,
            binding=_FakeBinding("binding-1", "pc_abc123"),
        )
    assert str(exc.value) == expected


def test_empty_credential_is_refused():
    receiver = LocalStoreCredentialReceiver(store=_FakeCanonicalStore())
    with pytest.raises(CredentialInstallError):
        receiver.install_once(
            challenge_id="c1",
            device_id="pc_abc123",
            credential=b"",
            binding=_FakeBinding("binding-1", "pc_abc123"),
        )


def test_confirmation_rejects_raw_credential_flag():
    with pytest.raises(CredentialInstallError):
        ProtectedCredentialInstallConfirmation(
            installed=True,
            binding_ref="binding-1",
            device_id="pc_abc123",
            credential_generation=2,
            proof_kind="protected_store_save_projection",
            raw_credential_persisted=True,
            confirmed_by_local_store=True,
        )


def test_confirmation_requires_local_store_proof_when_installed():
    with pytest.raises(CredentialInstallError):
        ProtectedCredentialInstallConfirmation(
            installed=True,
            binding_ref="binding-1",
            device_id="pc_abc123",
            credential_generation=2,
            proof_kind="protected_store_save_projection",
            confirmed_by_local_store=False,
        )
