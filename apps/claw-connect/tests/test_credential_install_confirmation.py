"""#4139 LOCAL2 protected credential install confirmation tests (isolated).

Proves the local install gate reuses the canonical store contract, fails closed
on store failure, correlates the store's own projection with the exact binding it
was handed, reads the credential back through the protected store, keeps a
redeemed challenge single-use, and never carries raw credential material. The
central delivery channel stays undefined, so the wired receiver stays disabled.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.credential_install import (  # noqa: E402
    CREDENTIAL_HANDOFF_WIRED,
    RECOVERY_ACTIONS,
    RECOVERY_NEW_CHALLENGE,
    RECOVERY_SECURITY_HOLD,
    REDEEMED_CHALLENGE_SINGLE_USE,
    CredentialInstallError,
    CredentialInstallNotWiredError,
    InstallFailureRecovery,
    LocalStoreCredentialReceiver,
    ProtectedCredentialInstallConfirmation,
    UnconfiguredProtectedCredentialReceiver,
    plan_install_failure_recovery,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
CREDENTIAL = b"raw-device-credential-bytes"
READBACK_PROOF = "protected_store_save_readback"


@dataclass(frozen=True)
class _FakeBinding:
    binding_ref: str
    device_id: str
    credential_generation: int


@dataclass(frozen=True)
class _FakeProjection:
    binding_ref: str
    device_id: str
    credential_generation: int


def _binding(**overrides) -> _FakeBinding:
    base = _FakeBinding("binding-1", "pc_abc123", 2)
    return replace(base, **overrides) if overrides else base


class _FakeCanonicalStore:
    """Mirrors the kagent ``DeviceCredentialStore`` save/load shape (no import)."""

    def __init__(
        self,
        *,
        fail=False,
        return_none=False,
        wrong_device=False,
        wrong_binding=False,
        wrong_generation=False,
        readback_wrong=False,
        readback_raises=False,
        no_load=False,
    ):
        self._fail = fail
        self._return_none = return_none
        self._wrong_device = wrong_device
        self._wrong_binding = wrong_binding
        self._wrong_generation = wrong_generation
        self._readback_wrong = readback_wrong
        self._readback_raises = readback_raises
        self.saved: list[bytes] = []
        self.load_calls = 0
        if no_load:
            # Drop readback capability entirely (a store that cannot read back).
            self.load = None  # type: ignore[assignment]

    def save(self, *, binding, credential, now):
        if self._fail:
            raise OSError("DPAPI protect failed with system error 5")
        self.saved.append(credential)
        self._stored = credential
        self._stored_binding = binding
        if self._return_none:
            return None
        return _FakeProjection(
            binding_ref="binding-other" if self._wrong_binding else binding.binding_ref,
            device_id="pc_other" if self._wrong_device else binding.device_id,
            credential_generation=(
                binding.credential_generation + 1
                if self._wrong_generation
                else binding.credential_generation
            ),
        )

    def load(self, *, binding, now):
        self.load_calls += 1
        if self._readback_raises:
            raise RuntimeError("stored device credential does not match binding context")
        if binding != self._stored_binding or self._readback_wrong:
            return b"different-credential-bytes"
        return self._stored


def _receiver(store=None, **kwargs) -> LocalStoreCredentialReceiver:
    return LocalStoreCredentialReceiver(
        store=store if store is not None else _FakeCanonicalStore(),
        now_factory=lambda: NOW,
        **kwargs,
    )


def _install(receiver, *, challenge_id="c1", device_id="pc_abc123", binding=None,
             credential=CREDENTIAL):
    return receiver.install_once(
        challenge_id=challenge_id,
        device_id=device_id,
        credential=credential,
        binding=binding if binding is not None else _binding(),
    )


def test_delivery_channel_is_disabled_by_default():
    assert CREDENTIAL_HANDOFF_WIRED is False
    receiver = UnconfiguredProtectedCredentialReceiver()
    assert receiver.ready(challenge_id="c1", device_id="pc_abc123") is False
    with pytest.raises(CredentialInstallNotWiredError):
        _install(receiver)


def test_ready_requires_save_and_readback_capability():
    assert _receiver().ready(challenge_id="c1", device_id="pc_abc123") is True
    without_load = _receiver(_FakeCanonicalStore(no_load=True))
    assert without_load.ready(challenge_id="c1", device_id="pc_abc123") is False


def test_install_is_confirmed_by_save_plus_readback():
    store = _FakeCanonicalStore()
    confirmation = _install(_receiver(store))
    assert isinstance(confirmation, ProtectedCredentialInstallConfirmation)
    assert confirmation.installed is True
    assert confirmation.confirmed_by_local_store is True
    assert confirmation.raw_credential_persisted is False
    assert confirmation.binding_ref == "binding-1"
    assert confirmation.device_id == "pc_abc123"
    assert confirmation.credential_generation == 2
    assert confirmation.proof_kind == READBACK_PROOF
    # The credential reached the store exactly once and was read back once.
    assert store.saved == [CREDENTIAL]
    assert store.load_calls == 1
    payload = confirmation.safe_dict()
    assert "credential" not in set(payload)
    assert CREDENTIAL not in repr(payload).encode("utf-8", "ignore")


def test_proof_kind_matches_the_central_install_ack_requirement():
    # CENTRAL accepts only its own protected-store proof kind in a device ack
    # (canonical_connector_credential_handoff.py). A save without readback must
    # never be a locally confirmable proof.
    from claw_connect import credential_install

    assert credential_install._LOCAL_PROOF_KINDS == frozenset({READBACK_PROOF})


@pytest.mark.parametrize(
    "store,expected",
    [
        (_FakeCanonicalStore(fail=True), "protected store save failed"),
        (_FakeCanonicalStore(return_none=True), "protected store returned no projection"),
        (_FakeCanonicalStore(no_load=True), "protected store readback is unavailable"),
        (_FakeCanonicalStore(readback_wrong=True), "protected store readback mismatch"),
        (
            _FakeCanonicalStore(readback_raises=True),
            "protected store readback failed",
        ),
    ],
)
def test_store_failure_never_produces_a_confirmation(store, expected):
    with pytest.raises(CredentialInstallError) as exc:
        _install(_receiver(store))
    assert str(exc.value) == expected


@pytest.mark.parametrize(
    "store,expected",
    [
        (_FakeCanonicalStore(wrong_device=True), "store projection device mismatch"),
        (_FakeCanonicalStore(wrong_binding=True), "store projection binding mismatch"),
        (_FakeCanonicalStore(wrong_generation=True), "store projection generation mismatch"),
    ],
)
def test_projection_for_an_unrelated_or_stale_binding_is_never_installed(store, expected):
    receiver = _receiver(store)
    with pytest.raises(CredentialInstallError) as exc:
        _install(receiver)
    assert str(exc.value) == expected
    # A rejected projection must not leave a confirmation the caller can reuse.
    assert receiver._consumed_challenges == {"c1"}


@pytest.mark.parametrize(
    "binding,expected",
    [
        (_binding(device_id="pc_other"), "install binding device mismatch"),
        (_binding(credential_generation=0), "install binding generation invalid"),
        (_binding(credential_generation=True), "install binding generation invalid"),
        (_binding(binding_ref=""), "install binding binding_ref invalid"),
    ],
)
def test_binding_material_is_validated_before_any_store_write(binding, expected):
    store = _FakeCanonicalStore()
    with pytest.raises(CredentialInstallError) as exc:
        _install(_receiver(store), binding=binding)
    assert str(exc.value) == expected
    assert store.saved == []


def test_redeemed_challenge_is_single_use_even_after_a_failed_attempt():
    receiver = _receiver(_FakeCanonicalStore(fail=True))
    with pytest.raises(CredentialInstallError):
        _install(receiver)
    with pytest.raises(CredentialInstallError) as exc:
        _install(receiver)
    assert str(exc.value) == REDEEMED_CHALLENGE_SINGLE_USE

    ok = _receiver()
    _install(ok)
    with pytest.raises(CredentialInstallError) as exc:
        _install(ok)
    assert str(exc.value) == REDEEMED_CHALLENGE_SINGLE_USE
    # A different challenge is a different redemption, not a replay.
    _install(ok, challenge_id="c2", binding=_binding(binding_ref="binding-2"))


@pytest.mark.parametrize("challenge_id", ["", None, 7])
def test_absent_challenge_refuses_the_attempt(challenge_id):
    store = _FakeCanonicalStore()
    with pytest.raises(CredentialInstallError):
        _install(_receiver(store), challenge_id=challenge_id)
    assert store.saved == []


def test_empty_credential_is_refused():
    with pytest.raises(CredentialInstallError):
        _install(_receiver(), credential=b"")


def test_confirmation_rejects_raw_credential_flag():
    with pytest.raises(CredentialInstallError):
        ProtectedCredentialInstallConfirmation(
            installed=True,
            binding_ref="binding-1",
            device_id="pc_abc123",
            credential_generation=2,
            proof_kind=READBACK_PROOF,
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
            proof_kind=READBACK_PROOF,
            confirmed_by_local_store=False,
        )


def test_confirmation_rejects_a_projection_only_proof_kind():
    with pytest.raises(CredentialInstallError):
        ProtectedCredentialInstallConfirmation(
            installed=True,
            binding_ref="binding-1",
            device_id="pc_abc123",
            credential_generation=2,
            proof_kind="protected_store_save_projection",
            confirmed_by_local_store=True,
        )


# --- single-use redemption recovery (CENTRAL decision, contract only) --------
def test_revocation_confirmed_releases_a_new_challenge_only():
    disposition = plan_install_failure_recovery(revocation_confirmed=True)
    assert disposition.action == RECOVERY_NEW_CHALLENGE
    assert disposition.requires_new_challenge is True
    assert disposition.reconciliation_required is False
    assert disposition.report_enrolled is False
    assert disposition.retry_same_challenge is False
    assert disposition.retransmit_credential is False
    assert disposition.requires_fresh_owner_consent is True


@pytest.mark.parametrize("answer", [False, None, "true", 1, {}, "unconfirmed"])
def test_unconfirmed_revocation_stays_on_security_hold(answer):
    disposition = plan_install_failure_recovery(revocation_confirmed=answer)
    assert disposition.action == RECOVERY_SECURITY_HOLD
    assert disposition.reconciliation_required is True
    assert disposition.requires_new_challenge is False
    assert disposition.report_enrolled is False


def test_retryable_or_enrolled_recovery_is_unrepresentable():
    assert RECOVERY_ACTIONS == frozenset({RECOVERY_NEW_CHALLENGE, RECOVERY_SECURITY_HOLD})
    base = {
        "action": RECOVERY_NEW_CHALLENGE,
        "report_enrolled": False,
        "retry_same_challenge": False,
        "retransmit_credential": False,
        "requires_new_challenge": True,
        "requires_fresh_owner_consent": True,
        "reconciliation_required": False,
    }
    with pytest.raises(CredentialInstallError):
        InstallFailureRecovery(**{**base, "report_enrolled": True})
    with pytest.raises(CredentialInstallError):
        InstallFailureRecovery(**{**base, "retry_same_challenge": True})
    with pytest.raises(CredentialInstallError):
        InstallFailureRecovery(**{**base, "retransmit_credential": True})
    with pytest.raises(CredentialInstallError):
        InstallFailureRecovery(**{**base, "requires_fresh_owner_consent": False})
    with pytest.raises(CredentialInstallError):
        InstallFailureRecovery(**{**base, "action": "replay_old_credential"})
    # A new challenge is only legal with confirmed revocation, so the hold action
    # can never carry a retry path.
    with pytest.raises(CredentialInstallError):
        InstallFailureRecovery(
            **{**base, "action": RECOVERY_SECURITY_HOLD, "reconciliation_required": True}
        )


def test_recovery_disposition_projection_carries_no_retry_or_credential():
    payload = plan_install_failure_recovery(revocation_confirmed=None).safe_dict()
    assert payload["report_enrolled"] is False
    assert payload["retry_same_challenge"] is False
    assert payload["retransmit_credential"] is False
    assert CREDENTIAL not in repr(payload).encode("utf-8", "ignore")
