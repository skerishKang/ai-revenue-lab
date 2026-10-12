"""#4139 source contract for a challenge-bound Windows credential installation ack.

NOT a network transport, a device identity authority, or proof that DPAPI was
used in production. The existing trusted device gateway must authenticate the
sender of the acknowledgement, and the existing Windows protected store must
confirm storage/readback before the device computes the keyed transcript proof.
Neither a bool nor an untrusted HTTP receipt can attest installation.

No product HTTP routes are mounted, no secret store is introduced and activation
remains OFF until a reviewed gateway, installer and operator wiring exist.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from typing import Any

INSTALL_ACK_TRANSCRIPT_VERSION = "padiem.connector-device-install-ack.v1"
PROTECTED_INSTALL_TRANSPORT_WIRED = False
PROTECTED_INSTALL_PRODUCTION_ENABLED = False
_STORE_PROOF_KIND = "protected_store_save_readback"
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_PROOF = re.compile(r"^[0-9a-f]{64}$")


def _reference(value: Any, name: str) -> str:
    if not isinstance(value, str) or _REF.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True, slots=True)
class DeviceCredentialInstallAck:
    """Secret-free claim from the device; not trusted without gateway validation.

    The proof is HMAC keyed by the *new* canonical Broker credential, computed
    only after the local store's save/readback confirmation. It establishes
    possession of that credential at the acknowledged transcript, NOT in
    isolation that the secret was persisted or that the device was authenticated.
    Both those properties require independent trusted-gateway verification.
    """

    challenge_id: str
    device_id: str
    binding_ref: str
    credential_generation: int
    proof_kind: str
    transcript_version: str
    local_store_confirmed: bool
    proof_hex: str

    def __post_init__(self) -> None:
        for name in ("challenge_id", "device_id", "binding_ref"):
            _reference(getattr(self, name), name)
        if type(self.credential_generation) is not int or not 1 <= self.credential_generation <= 1_000_000:
            raise ValueError("invalid credential generation")
        if self.proof_kind != _STORE_PROOF_KIND:
            raise ValueError("unknown protected-store proof")
        if self.transcript_version != INSTALL_ACK_TRANSCRIPT_VERSION:
            raise ValueError("unreviewed installation transcript")
        if self.local_store_confirmed is not True:
            raise ValueError("local-store persistence not confirmed")
        if not isinstance(self.proof_hex, str) or _PROOF.fullmatch(self.proof_hex) is None:
            raise ValueError("invalid keyed install proof")

    def safe_dict(self) -> dict[str, Any]:
        """Never includes the raw device credential or transport authentication."""
        return {
            "challenge_id": self.challenge_id,
            "device_id": self.device_id,
            "binding_ref": self.binding_ref,
            "credential_generation": self.credential_generation,
            "proof_kind": self.proof_kind,
            "transcript_version": self.transcript_version,
            "local_store_confirmed": True,
            "proof_hex": self.proof_hex,
        }


def installation_proof(
    *, credential: bytes, challenge_id: str, device_id: str,
    binding_ref: str, credential_generation: int,
) -> str:
    """Versioned HMAC transcript shared only with the reviewed LOCAL2 receiver."""
    if not isinstance(credential, bytes) or not 16 <= len(credential) <= 4096:
        raise ValueError("missing canonical Broker credential")
    for name, value in (
        ("challenge_id", challenge_id), ("device_id", device_id),
        ("binding_ref", binding_ref),
    ):
        _reference(value, name)
    if type(credential_generation) is not int or not 1 <= credential_generation <= 1_000_000:
        raise ValueError("invalid credential generation")
    transcript = "\n".join((
        INSTALL_ACK_TRANSCRIPT_VERSION, challenge_id, device_id, binding_ref,
        str(credential_generation),
    )).encode("utf-8")
    return hmac.new(credential, transcript, hashlib.sha256).hexdigest()


def verify_install_ack(
    *, ack: DeviceCredentialInstallAck, credential: bytes,
    challenge_id: str, device_id: str, enrollment: dict[str, Any],
) -> bool:
    """Check closed, key-confirmed facts, without trusting an arbitrary bool.

    The host must **also** verify the authenticated source using the canonical
    device gateway before treating this as successful Windows installation.
    """
    if type(ack) is not DeviceCredentialInstallAck or not isinstance(enrollment, dict):
        return False
    generation = enrollment.get("credential_generation")
    if (
        ack.challenge_id != challenge_id
        or ack.device_id != device_id
        or ack.binding_ref != enrollment.get("binding_ref")
        or ack.device_id != enrollment.get("device_id")
        or type(generation) is not int
        or ack.credential_generation != generation
    ):
        return False
    try:
        expected = installation_proof(
            credential=credential, challenge_id=challenge_id, device_id=device_id,
            binding_ref=ack.binding_ref, credential_generation=generation,
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(ack.proof_hex, expected)


class UnconfiguredProtectedDeviceHandoff:
    """Explicit default-off handoff, not a substitute for Windows installation."""

    async def ready(self, *, challenge_id: str, device_id: str) -> bool:
        del challenge_id, device_id
        return False

    async def deliver_once(self, **kwargs: Any) -> DeviceCredentialInstallAck:
        del kwargs
        raise RuntimeError("authenticated protected credential handoff is not wired")

    async def verify_authenticated_ack(self, **kwargs: Any) -> bool:
        del kwargs
        return False
