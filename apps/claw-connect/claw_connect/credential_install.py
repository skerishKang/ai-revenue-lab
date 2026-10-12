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
* A server "installed" flag alone is never trusted. The confirmation is only
  produced by a store ``save`` that returned a projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

#: The authenticated central->PC credential delivery contract is not defined
#: yet, so the receiver stays disabled. Never set True without the central CTO's
#: reviewed handoff contract.
CREDENTIAL_HANDOFF_WIRED = False

#: Evidence kinds a confirmation may cite. Anything else is not a local proof.
_LOCAL_PROOF_KINDS = frozenset({"protected_store_save_projection"})


class CredentialInstallNotWiredError(RuntimeError):
    """Raised when no reviewed credential delivery channel is wired."""


class CredentialInstallError(RuntimeError):
    """Raised when local installation could not be confirmed. Never a success."""


@dataclass(frozen=True, slots=True)
class ProtectedCredentialInstallConfirmation:
    """Non-secret proof that the canonical store persisted a credential.

    Carries no raw credential material and no store path. ``installed`` is True
    only when the store returned a projection for this exact binding.
    """

    installed: bool
    binding_ref: str
    device_id: str
    credential_generation: int
    proof_kind: str
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

    def safe_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "credential_generation": self.credential_generation,
            "proof_kind": self.proof_kind,
            "raw_credential_persisted": False,
            "confirmed_by_local_store": self.confirmed_by_local_store,
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


class LocalStoreCredentialReceiver:
    """Install through the canonical protected store, then confirm locally.

    ``store`` is any object matching the canonical ``DeviceCredentialStore``
    contract (``save(*, binding, credential, now) -> projection``). This keeps
    ``kagent`` out of ``claw_connect`` while reusing its implementation.

    The credential is forwarded to the store exactly once and is never retained.
    A store exception or a missing projection fails closed: no confirmation, so
    the caller must not report the PC as enrolled.
    """

    def __init__(self, *, store: Any, now_factory: Any | None = None) -> None:
        self._store = store
        self._now_factory = now_factory

    def ready(self, *, challenge_id: str, device_id: str) -> bool:
        del challenge_id, device_id
        return callable(getattr(self._store, "save", None))

    def install_once(
        self, *, challenge_id: str, device_id: str, credential: bytes, binding: Any
    ) -> ProtectedCredentialInstallConfirmation:
        del challenge_id
        if not isinstance(credential, (bytes, bytearray)) or not credential:
            raise CredentialInstallError("credential must be non-empty bytes")
        save = getattr(self._store, "save", None)
        if not callable(save):
            raise CredentialInstallError("protected store is not available")
        now = self._now_factory() if callable(self._now_factory) else datetime.now(
            tz=timezone.utc
        )
        try:
            projection = save(binding=binding, credential=bytes(credential), now=now)
        except Exception as exc:  # store failure is never a success
            raise CredentialInstallError("protected store save failed") from exc
        if projection is None:
            raise CredentialInstallError("protected store returned no projection")
        binding_ref = getattr(projection, "binding_ref", None)
        device_id_value = getattr(projection, "device_id", None)
        generation = getattr(projection, "credential_generation", None)
        if not isinstance(binding_ref, str) or not binding_ref:
            raise CredentialInstallError("store projection missing binding_ref")
        if device_id_value != device_id:
            raise CredentialInstallError("store projection device mismatch")
        if type(generation) is not int or generation < 1:
            raise CredentialInstallError("store projection generation invalid")
        return ProtectedCredentialInstallConfirmation(
            installed=True,
            binding_ref=binding_ref,
            device_id=device_id_value,
            credential_generation=generation,
            proof_kind="protected_store_save_projection",
            confirmed_by_local_store=True,
        )
