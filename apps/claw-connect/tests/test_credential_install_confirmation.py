"""#4139 LOCAL2 protected credential install confirmation tests (isolated).

Proves the local install gate reuses the canonical store contract, fails closed
on store failure, correlates the store's own projection with the exact binding it
was handed, reads the credential back through the protected store, keeps a
redeemed challenge single-use, and never carries raw credential material. The
central delivery channel stays undefined, so the wired receiver stays disabled.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import re
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.credential_install import (  # noqa: E402
    CREDENTIAL_HANDOFF_WIRED,
    INSTALL_ACK_TRANSCRIPT_VERSION,
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
    install_ack_proof,
    installation_ack_transcript,
    plan_install_failure_recovery,
)
from claw_connect import credential_install  # noqa: E402

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
CREDENTIAL = b"raw-device-credential-bytes"
READBACK_PROOF = "protected_store_save_readback"
PROOF_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class _FakeBinding:
    binding_ref: str
    device_id: str
    credential_generation: int
    account_ref: str = "acct-1"
    workspace_ref: str = "ws-1"


@dataclass(frozen=True)
class _FakeProjection:
    binding_ref: str
    device_id: str
    credential_generation: int
    account_ref: str = "acct-1"
    workspace_ref: str = "ws-1"


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
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
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
    # The ack proof exists only for this exact binding, over the pinned
    # transcript, and is re-derived here from literal bytes rather than the
    # implementation, so a transcript edit cannot pass silently.
    assert confirmation.challenge_id == "c1"
    assert confirmation.transcript_version == INSTALL_ACK_TRANSCRIPT_VERSION
    assert confirmation.proof_hex == hmac.new(
        CREDENTIAL,
        b"padiem.connector-device-install-ack.v1"
        b"\nc1\npc_abc123\nbinding-1\n2",
        hashlib.sha256,
    ).hexdigest()
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


# --- cross-authority pins (read as literals, never imported) ----------------
#: #4139 Decision A: 4096 is the *pairing protocol* ceiling and 16 is the current
#: install-ACK security floor. The generic DPAPI store capacity (16384) is not permission
#: to exceed the pairing bound. The connector mirrors these constants because it is a
#: stdlib-only Windows app; these pins keep the mirror honest against the canonical
#: authorities in the same tree.
#:
#: The values are read from the authority source files, not imported. The connector CI
#: gate installs only pytest, while ``padiem_control_plane`` reaches
#: ``packages/padiem-ai-core`` — present on a developer PC through unrelated editable
#: installs and absent on the runner, so an import-based pin passes locally and fails in
#: CI without proving anything about the contract. Reading literals also keeps this file
#: from mutating ``sys.path``/``sys.modules``, which would silently flip the in-process S1
#: drift guard in ``test_enrollment_contract.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAIRING_AUTHORITY = (
    _REPO_ROOT
    / "packages"
    / "padiem-control-plane"
    / "padiem_control_plane"
    / "local_agent_broker_pairing.py"
)
_BROKER_CLIENT_AUTHORITY = (
    _REPO_ROOT
    / "apps"
    / "korean-ai-code-agent"
    / "src"
    / "kagent"
    / "local_agent_broker_pairing_client.py"
)


def _module_literal(path: Path, name: str):
    """Return the single module-level literal bound to ``name`` in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    ]
    assert len(values) == 1, (
        f"{name} in {path.name}: expected exactly one module-level literal, found {len(values)}"
    )
    return values[0]


def _factory_token_length(path: Path, function_name: str) -> int:
    """Read the byte length the canonical credential factory actually requests."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and call.args:
                    return ast.literal_eval(call.args[0])
    raise AssertionError(f"{function_name} requesting a literal byte length not found")


def test_local_ack_key_window_equals_the_canonical_pairing_bound():
    ceiling = _module_literal(_PAIRING_AUTHORITY, "MAX_PAIRING_CREDENTIAL_BYTES")
    client_ceiling = _module_literal(
        _BROKER_CLIENT_AUTHORITY, "MAX_ENROLLMENT_CREDENTIAL_BYTES"
    )
    assert ceiling == client_ceiling
    assert ceiling == credential_install._MAX_ACK_KEY_BYTES
    assert credential_install._MIN_ACK_KEY_BYTES == 16
    assert credential_install._MAX_ACK_KEY_BYTES < 16_384  # generic DPAPI capacity


def test_default_pairing_credential_fits_the_local_window():
    issued = _factory_token_length(_PAIRING_AUTHORITY, "_default_credential_factory")
    assert issued >= credential_install._MIN_ACK_KEY_BYTES
    assert issued <= credential_install._MAX_ACK_KEY_BYTES


def test_connector_pairing_transcript_mirror_equals_the_s1_authority():
    from claw_connect.enrollment import (
        ENROLLMENT_PROOF_REF_PREFIX,
        ENROLLMENT_PROOF_TRANSCRIPT,
    )

    assert (
        _module_literal(_PAIRING_AUTHORITY, "PAIRING_PROOF_TRANSCRIPT")
        == ENROLLMENT_PROOF_TRANSCRIPT
    )
    assert (
        _module_literal(_PAIRING_AUTHORITY, "PAIRING_PROOF_REF_PREFIX")
        == ENROLLMENT_PROOF_REF_PREFIX
    )


# --- versioned install-ack proof (LOCAL2 half of CENTRAL's transcript) -------
ACK_KEY = b"synthetic-broker-credential-key-32by"


@pytest.mark.parametrize(
    "credential,fields,expected",
    [
        (
            ACK_KEY,
            {
                "challenge_id": "challenge-1",
                "device_id": "pc_abc123",
                "binding_ref": "binding-1",
                "credential_generation": 1,
            },
            "d8eb1bd8dc1e35456d78f7313ec5d10590929a081ba15eee63f324d082b329f8",
        ),
        (
            ACK_KEY + ACK_KEY,
            {
                "challenge_id": "chal.9:AZ",
                "device_id": "pc_2",
                "binding_ref": "bind_@x",
                "credential_generation": 1000000,
            },
            "e33494c4601776776a6ea02b997da649d831d8332ae0e176fff7e1198051cd61",
        ),
    ],
)
def test_install_ack_proof_matches_the_pinned_central_vectors(credential, fields, expected):
    # Both vectors were computed from CENTRAL's own ``installation_proof`` in
    # ``canonical_connector_credential_handoff.py``; they pin device↔server
    # transcript interop, which a shared implementation detail cannot drift past.
    assert install_ack_proof(credential=credential, **fields) == expected


def test_install_ack_transcript_is_versioned_without_trailing_newline():
    assert INSTALL_ACK_TRANSCRIPT_VERSION == "padiem.connector-device-install-ack.v1"
    transcript = installation_ack_transcript(
        challenge_id="challenge-1",
        device_id="pc_abc123",
        binding_ref="binding-1",
        credential_generation=7,
    )
    assert transcript == (
        b"padiem.connector-device-install-ack.v1"
        b"\nchallenge-1\npc_abc123\nbinding-1\n7"
    )
    assert not transcript.endswith(b"\n")


@pytest.mark.parametrize("size", [1, 15, 4097, 16384])
def test_credential_outside_the_acknowledged_window_is_refused_before_any_write(size):
    # CENTRAL keys the ack HMAC with this credential, so a credential it cannot
    # verify must never reach the protected store as an installed binding.
    store = _FakeCanonicalStore()
    with pytest.raises(CredentialInstallError) as exc:
        _install(_receiver(store), credential=b"k" * size)
    assert str(exc.value) == "credential is outside the acknowledged key window"
    assert store.saved == []


@pytest.mark.parametrize("size", [16, 4096])
def test_credentials_at_both_central_window_bounds_are_accepted(size):
    confirmation = _install(_receiver(), credential=b"k" * size)
    assert confirmation.installed is True
    assert PROOF_HEX_RE.fullmatch(confirmation.proof_hex)


@pytest.mark.parametrize(
    "fields",
    [
        {"challenge_id": "", "device_id": "pc_abc123", "binding_ref": "b-1",
         "credential_generation": 1},
        {"challenge_id": "c 1", "device_id": "pc_abc123", "binding_ref": "b-1",
         "credential_generation": 1},
        {"challenge_id": "c1", "device_id": "pc/1", "binding_ref": "b-1",
         "credential_generation": 1},
        {"challenge_id": "c1", "device_id": "pc_1", "binding_ref": "b 1",
         "credential_generation": 1},
        {"challenge_id": "c1", "device_id": "pc_1", "binding_ref": "b-1",
         "credential_generation": 0},
        {"challenge_id": "c1", "device_id": "pc_1", "binding_ref": "b-1",
         "credential_generation": 1000001},
        {"challenge_id": "c1", "device_id": "pc_1", "binding_ref": "b-1",
         "credential_generation": True},
    ],
)
def test_install_ack_proof_rejects_material_central_could_not_verify(fields):
    with pytest.raises(CredentialInstallError):
        install_ack_proof(credential=ACK_KEY, **fields)


def test_installed_confirmation_without_a_valid_proof_is_unconstructible():
    base = {
        "installed": True,
        "binding_ref": "binding-1",
        "device_id": "pc_abc123",
        "credential_generation": 2,
        "proof_kind": READBACK_PROOF,
        "challenge_id": "c1",
        "transcript_version": INSTALL_ACK_TRANSCRIPT_VERSION,
        "proof_hex": "a" * 64,
        "confirmed_by_local_store": True,
    }
    ProtectedCredentialInstallConfirmation(**base)
    for broken in (
        {"proof_hex": "Z" * 64},
        {"proof_hex": "a" * 63},
        {"proof_hex": None},
        {"transcript_version": "padiem.connector-device-install-ack.v2"},
        {"transcript_version": None},
        {"challenge_id": ""},
        {"credential_generation": 0},
    ):
        with pytest.raises(CredentialInstallError):
            ProtectedCredentialInstallConfirmation(**{**base, **broken})
