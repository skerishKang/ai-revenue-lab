"""#4139 LOCAL2 protected credential installation confirmation (fail-closed).

This module owns exactly one thing: the **local** proof that a device credential
was actually persisted by the canonical protected store before the Connector may
report the PC as enrolled. It deliberately owns no store of its own.

Authority boundaries:

* The protected store is the existing canonical one in ``kagent``
  (``WindowsDpapiProtectedDataPort`` + ``ProtectedFileDeviceCredentialStore``).
  It is consumed here through a structural protocol, so ``claw_connect`` never
  imports ``kagent`` and no second credential authority is created.
* The raw device credential is passed to the store once and is **never** stored
  on this object, logged, projected or returned. Only the store's projection
  (a non-secret summary) is surfaced.
* The central ``ProtectedDeviceCredentialHandoff.deliver_once()`` transport
  contract is owned by the central CTO. Until that authenticated delivery
  channel and the device-installation acknowledgement are defined, the receiver
  is **disabled**: :class:`UnconfiguredProtectedCredentialReceiver` raises and
  nothing is installed. ``CREDENTIAL_HANDOFF_WIRED = False``.
* A server "installed" flag alone is never trusted. A local confirmation is
  produced only when the canonical store returns a projection naming this exact
  binding reference, device and credential generation **and** the same bytes read
  back through that binding's protected context.
* A redeemed challenge is single-use locally too: one install attempt per
  challenge. :func:`plan_install_failure_recovery` maps a failed attempt onto
  either a new challenge (canonical revocation confirmed) or a security hold for
  authority-side reconciliation — never a replay of the challenge or the
  credential.
* The versioned install-ack possession proof (CENTRAL transcript
  ``padiem.connector-device-install-ack.v1``) is computed only after that
  readback, and nothing here transmits it: the authenticated device transport is
  still unselected, so ``CREDENTIAL_HANDOFF_WIRED`` stays False and no sender
  exists.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

#: The authenticated central->PC credential delivery contract is not defined
#: yet, so the receiver stays disabled. Never set True without the central CTO's
#: reviewed handoff contract.
CREDENTIAL_HANDOFF_WIRED = False

#: Evidence kinds a confirmation may cite. Anything else is not a local proof.
#: ``protected_store_save_readback`` is the exact kind CENTRAL's installation
#: acknowledgement requires (``_STORE_PROOF_KIND`` in
#: ``apps/padiem-chat/app/canonical_connector_credential_handoff.py``), so a
#: write that was never read back through the protected store can never be
#: acknowledged as installed.
_STORE_READBACK_PROOF = "protected_store_save_readback"
_LOCAL_PROOF_KINDS = frozenset({_STORE_READBACK_PROOF})

#: Versioned install-ack transcript pinned to CENTRAL's
#: ``INSTALL_ACK_TRANSCRIPT_VERSION``. Byte-identical by contract: the proof is
#: only comparable against the canonical Broker's own computation.
INSTALL_ACK_TRANSCRIPT_VERSION = "padiem.connector-device-install-ack.v1"

#: The credential window CENTRAL will accept as an HMAC key for the ack
#: (``installation_proof`` in the same central module). A credential outside this
#: window can be stored but never acknowledged, so it is refused locally before
#: anything is written.
_MIN_ACK_KEY_BYTES = 16
_MAX_ACK_KEY_BYTES = 4096
_PROOF_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")

#: The one message a repeated local install attempt may produce. A redeemed
#: challenge is already spent server-side, so this is a terminal refusal.
REDEEMED_CHALLENGE_SINGLE_USE = (
    "redeemed challenge is single-use; a new challenge and fresh OWNER consent "
    "are required"
)


class CredentialInstallNotWiredError(RuntimeError):
    """Raised when no reviewed credential delivery channel is wired."""


class CredentialInstallError(RuntimeError):
    """Raised when local installation could not be confirmed. Never a success."""


@dataclass(frozen=True, slots=True)
class ProtectedCredentialInstallConfirmation:
    """Non-secret proof that the canonical store persisted a credential.

    Carries no raw credential material and no store path. ``installed`` is True
    only when the store returned a projection for this exact binding *and* the
    same bytes read back through it. ``proof_hex`` is CENTRAL's versioned
    possession proof over this binding, computed only after that readback; it is
    not a local success claim and nothing sends it until a reviewed authenticated
    transport exists.
    """

    installed: bool
    binding_ref: str
    device_id: str
    credential_generation: int
    proof_kind: str
    challenge_id: str | None = None
    transcript_version: str | None = None
    proof_hex: str | None = None
    raw_credential_persisted: bool = False
    confirmed_by_local_store: bool = False

    def __post_init__(self) -> None:
        if self.raw_credential_persisted is not False:
            raise CredentialInstallError("a confirmation never carries raw credential")
        if self.installed:
            if self.proof_kind not in _LOCAL_PROOF_KINDS:
                raise CredentialInstallError("unrecognised local install proof kind")
            if self.confirmed_by_local_store is not True:
                raise CredentialInstallError(
                    "installed=True requires confirmation by the local store"
                )
            if self.transcript_version != INSTALL_ACK_TRANSCRIPT_VERSION:
                raise CredentialInstallError("install ack transcript is unreviewed")
            for name, value in (
                ("challenge_id", self.challenge_id),
                ("device_id", self.device_id),
                ("binding_ref", self.binding_ref),
            ):
                if not isinstance(value, str) or _REFERENCE_RE.fullmatch(value) is None:
                    raise CredentialInstallError(f"install ack {name} invalid")
            generation = self.credential_generation
            if (
                type(generation) is not int
                or not 1 <= generation <= 1_000_000
            ):
                raise CredentialInstallError("install ack generation invalid")
            if not isinstance(self.proof_hex, str) or _PROOF_HEX_RE.fullmatch(
                self.proof_hex
            ) is None:
                raise CredentialInstallError("install ack proof must be 64 hex chars")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "challenge_id": self.challenge_id,
            "device_id": self.device_id,
            "binding_ref": self.binding_ref,
            "credential_generation": self.credential_generation,
            "proof_kind": self.proof_kind,
            "transcript_version": self.transcript_version,
            "local_store_confirmed": self.confirmed_by_local_store,
            "proof_hex": self.proof_hex,
            "raw_credential_persisted": False,
        }


class ProtectedCredentialReceiverPort(Protocol):
    """Reviewed transport + device installer for the one-time credential."""

    def ready(self, *, challenge_id: str, device_id: str) -> bool: ...

    def install_once(
        self, *, challenge_id: str, device_id: str, credential: bytes, binding: Any
    ) -> ProtectedCredentialInstallConfirmation: ...


class UnconfiguredProtectedCredentialReceiver:
    """Fail-closed default: no reviewed delivery channel, no installation."""

    def ready(self, *, challenge_id: str, device_id: str) -> bool:
        del challenge_id, device_id
        return False

    def install_once(
        self, *, challenge_id: str, device_id: str, credential: bytes, binding: Any
    ) -> ProtectedCredentialInstallConfirmation:
        del challenge_id, device_id, credential, binding
        raise CredentialInstallNotWiredError(
            "protected credential delivery channel is not wired "
            "(BLOCKED_DEPENDENCY: central ProtectedDeviceCredentialHandoff "
            "contract + device installation acknowledgement)"
        )


def installation_ack_transcript(
    *, challenge_id: str, device_id: str, binding_ref: str, credential_generation: int
) -> bytes:
    """CENTRAL's exact transcript: versioned, newline-separated, no trailing newline."""
    return "\n".join(
        (
            INSTALL_ACK_TRANSCRIPT_VERSION,
            challenge_id,
            device_id,
            binding_ref,
            str(credential_generation),
        )
    ).encode("utf-8")


def install_ack_proof(
    *,
    credential: bytes,
    challenge_id: str,
    device_id: str,
    binding_ref: str,
    credential_generation: int,
) -> str:
    """HMAC-SHA256 over the versioned transcript, keyed by the new credential.

    This proves *possession* of the canonical Broker credential bound to this
    transcript. It does not prove DPAPI installation and does not authenticate the
    PC — CENTRAL's device gateway must do both before any success. Nothing here
    opens a channel: the value is only computed after a protected save and readback.
    """
    if (
        not isinstance(credential, bytes)
        or not _MIN_ACK_KEY_BYTES <= len(credential) <= _MAX_ACK_KEY_BYTES
    ):
        raise CredentialInstallError("credential is outside the acknowledged key window")
    for name, value in (
        ("challenge_id", challenge_id),
        ("device_id", device_id),
        ("binding_ref", binding_ref),
    ):
        if not isinstance(value, str) or _REFERENCE_RE.fullmatch(value) is None:
            raise CredentialInstallError(f"install ack {name} invalid")
    if type(credential_generation) is not int or not 1 <= credential_generation <= 1_000_000:
        raise CredentialInstallError("install ack generation invalid")
    return hmac.new(
        credential,
        installation_ack_transcript(
            challenge_id=challenge_id,
            device_id=device_id,
            binding_ref=binding_ref,
            credential_generation=credential_generation,
        ),
        hashlib.sha256,
    ).hexdigest()


def _binding_fact(binding: Any, name: str) -> str:
    value = getattr(binding, name, None)
    if not isinstance(value, str) or not value:
        raise CredentialInstallError(f"install binding {name} invalid")
    return value


class LocalStoreCredentialReceiver:
    """Install through the canonical protected store, then confirm by reading back.

    ``store`` is any object matching the canonical ``DeviceCredentialStore``
    contract (``save(*, binding, credential, now) -> projection`` **and**
    ``load(*, binding, now) -> bytes``). This keeps ``kagent`` out of
    ``claw_connect`` while reusing its implementation.

    The credential is forwarded to the store exactly once and is never retained.
    A confirmation requires all three of: the store's own projection, that
    projection naming *this exact* binding reference, device and credential
    generation, and a protected readback of the same bytes under the same binding
    context. A projection for an unrelated or stale binding therefore fails
    closed, and so does a store that cannot read back. There is no falsy
    confirmation a caller could misread as success.
    """

    def __init__(self, *, store: Any, now_factory: Any | None = None) -> None:
        self._store = store
        self._now_factory = now_factory
        # The challenge reaching this receiver was already redeemed server-side,
        # so its single use is spent here whether the local install succeeds or
        # not. Retrying requires a new challenge and a fresh OWNER consent.
        self._consumed_challenges: set[str] = set()

    def ready(self, *, challenge_id: str, device_id: str) -> bool:
        del challenge_id, device_id
        store = self._store
        return callable(getattr(store, "save", None)) and callable(
            getattr(store, "load", None)
        )

    def _consume_challenge(self, challenge_id: Any) -> None:
        if not isinstance(challenge_id, str) or not challenge_id:
            raise CredentialInstallError(REDEEMED_CHALLENGE_SINGLE_USE)
        if challenge_id in self._consumed_challenges:
            raise CredentialInstallError(REDEEMED_CHALLENGE_SINGLE_USE)
        self._consumed_challenges.add(challenge_id)

    def install_once(
        self, *, challenge_id: str, device_id: str, credential: bytes, binding: Any
    ) -> ProtectedCredentialInstallConfirmation:
        self._consume_challenge(challenge_id)
        if not isinstance(credential, (bytes, bytearray)) or not credential:
            raise CredentialInstallError("credential must be non-empty bytes")
        if not _MIN_ACK_KEY_BYTES <= len(bytes(credential)) <= _MAX_ACK_KEY_BYTES:
            # Refuse before any store write: a credential CENTRAL could not key an
            # acknowledgement with can never become an installed binding.
            raise CredentialInstallError("credential is outside the acknowledged key window")
        save = getattr(self._store, "save", None)
        if not callable(save):
            raise CredentialInstallError("protected store is not available")
        load = getattr(self._store, "load", None)
        if not callable(load):
            raise CredentialInstallError("protected store readback is unavailable")
        expected_ref = _binding_fact(binding, "binding_ref")
        expected_device = _binding_fact(binding, "device_id")
        expected_generation = getattr(binding, "credential_generation", None)
        if type(expected_generation) is not int or expected_generation < 1:
            raise CredentialInstallError("install binding generation invalid")
        if expected_device != device_id:
            raise CredentialInstallError("install binding device mismatch")
        now = (
            self._now_factory()
            if callable(self._now_factory)
            else datetime.now(tz=timezone.utc)
        )
        try:
            projection = save(binding=binding, credential=bytes(credential), now=now)
        except Exception as exc:  # store failure is never a success
            raise CredentialInstallError("protected store save failed") from exc
        if projection is None:
            raise CredentialInstallError("protected store returned no projection")
        # The store must describe the binding it was handed, not merely return
        # something non-empty: a stale or unrelated projection would otherwise
        # confirm a credential that belongs to another PC or generation.
        if getattr(projection, "binding_ref", None) != expected_ref:
            raise CredentialInstallError("store projection binding mismatch")
        if getattr(projection, "device_id", None) != expected_device:
            raise CredentialInstallError("store projection device mismatch")
        generation = getattr(projection, "credential_generation", None)
        if type(generation) is not int or generation != expected_generation:
            raise CredentialInstallError("store projection generation mismatch")
        try:
            stored = load(binding=binding, now=now)
        except Exception as exc:
            raise CredentialInstallError("protected store readback failed") from exc
        if not isinstance(stored, (bytes, bytearray)) or not hmac.compare_digest(
            bytes(stored), bytes(credential)
        ):
            raise CredentialInstallError("protected store readback mismatch")
        # Only after a confirmed save *and* matching readback may this device
        # compute the possession proof CENTRAL's install acknowledgement requires.
        proof_hex = install_ack_proof(
            credential=bytes(credential),
            challenge_id=challenge_id,
            device_id=expected_device,
            binding_ref=expected_ref,
            credential_generation=generation,
        )
        return ProtectedCredentialInstallConfirmation(
            installed=True,
            binding_ref=expected_ref,
            device_id=expected_device,
            credential_generation=generation,
            proof_kind=_STORE_READBACK_PROOF,
            challenge_id=challenge_id,
            transcript_version=INSTALL_ACK_TRANSCRIPT_VERSION,
            proof_hex=proof_hex,
            confirmed_by_local_store=True,
        )


# -- single-use redemption recovery (CENTRAL #4476 decision, contract only) ---

#: The canonical Broker binding was revoked: a new challenge + fresh OWNER
#: consent may be issued. This is the only non-hold outcome.
RECOVERY_NEW_CHALLENGE = "new_challenge_required"
#: Revocation is unconfirmed or refused. The PC stays on a security hold for
#: authority-side reconciliation; it is never reported CONNECTED and never retried.
RECOVERY_SECURITY_HOLD = "security_hold_reconciliation_required"
RECOVERY_ACTIONS = frozenset({RECOVERY_NEW_CHALLENGE, RECOVERY_SECURITY_HOLD})


@dataclass(frozen=True, slots=True)
class InstallFailureRecovery:
    """The only dispositions available after a redeemed credential failed to install.

    Every unsafe retry is unrepresentable by construction: ``report_enrolled``,
    ``retry_same_challenge`` and ``retransmit_credential`` are pinned false, and
    any retry path requires a fresh OWNER consent.
    """

    action: str
    report_enrolled: bool
    retry_same_challenge: bool
    retransmit_credential: bool
    requires_new_challenge: bool
    requires_fresh_owner_consent: bool
    reconciliation_required: bool

    def __post_init__(self) -> None:
        if self.action not in RECOVERY_ACTIONS:
            raise CredentialInstallError("unknown install failure recovery action")
        if self.report_enrolled is not False:
            raise CredentialInstallError(
                "a failed installation never reports the PC as enrolled"
            )
        if self.retry_same_challenge is not False:
            raise CredentialInstallError("a redeemed challenge is never replayed")
        if self.retransmit_credential is not False:
            raise CredentialInstallError("a redeemed credential is never retransmitted")
        if self.requires_fresh_owner_consent is not True:
            raise CredentialInstallError("recovery always needs a current OWNER consent")
        if self.requires_new_challenge is not (self.action == RECOVERY_NEW_CHALLENGE):
            raise CredentialInstallError(
                "only a confirmed-revoked binding may take a new challenge"
            )
        if self.reconciliation_required is not (self.action == RECOVERY_SECURITY_HOLD):
            raise CredentialInstallError(
                "unconfirmed revocation must remain on security hold"
            )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "report_enrolled": False,
            "retry_same_challenge": False,
            "retransmit_credential": False,
            "requires_new_challenge": self.requires_new_challenge,
            "requires_fresh_owner_consent": True,
            "reconciliation_required": self.reconciliation_required,
        }


def plan_install_failure_recovery(*, revocation_confirmed: Any) -> InstallFailureRecovery:
    """Map one post-redemption installation failure onto its recovery action.

    ``revocation_confirmed`` is the canonical Broker's own answer about the newly
    created binding, read through the reviewed server path — the Connector never
    revokes a binding and never infers revocation from a local success. Anything
    other than an explicit ``True`` (including ``None`` / no answer / a transport
    error) fails closed into the reconciliation hold, because a live binding with
    an undelivered credential is a security finding, not a retryable failure.
    """
    if revocation_confirmed is True:
        return InstallFailureRecovery(
            action=RECOVERY_NEW_CHALLENGE,
            report_enrolled=False,
            retry_same_challenge=False,
            retransmit_credential=False,
            requires_new_challenge=True,
            requires_fresh_owner_consent=True,
            reconciliation_required=False,
        )
    return InstallFailureRecovery(
        action=RECOVERY_SECURITY_HOLD,
        report_enrolled=False,
        retry_same_challenge=False,
        retransmit_credential=False,
        requires_new_challenge=False,
        requires_fresh_owner_consent=True,
        reconciliation_required=True,
    )
