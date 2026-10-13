"""#4139 CENTRAL — source-only post-restart OWNER reconciliation.

This is deliberately NOT a public route, nor unauthenticated PC recovery.
An authenticated canonical OWNER session and STILL CURRENT original per-PC
consent must match the original challenge binding before the Broker's
existing owner-scoped device directory is queried. Only an exact canonical
REVOKED binding can confirm compensation after a lost WSS install ACK.
A missing/expired/active binding or a malformed record is always a hold,
never safe automatic retry or a locally asserted revocation.

No new authority, persistent table, credential, Broker revoke command,
Cloudflare ingress, browser cookie export or customer-facing disclosure.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .control_plane_identity import IdentityBridgeError

OWNER_RECOVERY_ROUTE_MOUNTED = False
OWNER_RECOVERY_PRODUCTION_ENABLED = False

_DIRECTORY_ENTRY_FIELDS = frozenset({
    "canonical_state", "binding", "session", "heartbeat_last_seen_at",
})
_BINDING_FIELDS = frozenset({
    "binding_ref", "device_id", "account_ref", "workspace_ref",
    "credential_generation", "issued_at", "credential_expires_at",
    "credential_digest_exposed", "raw_device_credential",
})
_STATES = frozenset({"revoked", "credential_expired", "paired_offline"})


def _safe_ref(value: Any, label: str) -> str:
    if (
        type(value) is not str or not 1 <= len(value) <= 256
        or not value[0].isalnum()
        or not all(c.isascii() and (c.isalnum() or c in "._:@+-") for c in value)
    ):
        raise IdentityBridgeError(400, "invalid_recovery_request", f"{label} invalid")
    return value


def _hold(*, challenge_id: str, device_id: str) -> dict[str, Any]:
    return {
        "challenge_id": challenge_id, "device_id": device_id,
        "disposition": "security_hold", "canonical_revocation_confirmed": False,
        "can_retry_challenge": False, "raw_device_credential": False,
        "dispatch_authorized": False,
    }


class CanonicalConnectorOwnerRecovery:
    """Owner-authorized, non-consuming read of ORIGINAL challenge and binding.

    The browser caller cannot select account/workspace/binding authority:
    consent + Broker challenge correlate them, then a deterministic binding
    name selects the exact device history row from the existing Broker
    directory. This is an after-crash OBSERVATION, not mutation.
    """

    def __init__(self, *, identity: Any, broker: Any):
        if not callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None)):
            raise ValueError("existing canonical Identity session/consent verifier required")
        if any(not callable(getattr(broker, x, None))
               for x in ("get_enrollment_binding", "owner_device_directory")):
            raise ValueError("existing canonical Broker binding and directory required")
        self._identity = identity
        self._broker = broker

    async def check(self, *, canonical_session_id: str, challenge_id: str,
                    device_id: str) -> dict[str, Any]:
        session = _safe_ref(canonical_session_id, "canonical_session_id")
        challenge = _safe_ref(challenge_id, "challenge_id")
        device = _safe_ref(device_id, "device_id")
        # Require a real signed-in canonical OWNER session AND still-live
        # consent before looking up a challenge. Never accept an account-ref
        # or owner-ref asserted by the client.
        consent = await self._identity.resolve_connector_enrollment_consent_for_device(
            session_id=session, device_id=device,
        )
        if (
            type(consent) is not dict
            or consent.get("device_id") != device
            or consent.get("withdrawn_at") is not None
            or not all(type(consent.get(k)) is str and consent[k] for k in
                       ("consent_id", "owner_subject_id", "account_ref", "workspace_ref"))
        ):
            raise IdentityBridgeError(403, "recovery_owner_unconfirmed",
                                      "Current owner consent not confirmed.")
        # The Broker challenge is durable after redemption and carries the
        # ORIGINAL owner/grant/device/account/workspace. A new consent cannot
        # grant a different owner visibility into this historical challenge.
        original = await self._broker.get_enrollment_binding(
            challenge_id=challenge,
        )
        expected = {
            "challenge_id": challenge,
            "device_id": device,
            "consent_ref": consent["consent_id"],
            "owner_ref": consent["owner_subject_id"],
            "account_ref": consent["account_ref"],
            "workspace_ref": consent["workspace_ref"],
        }
        if type(original) is not dict or any(original.get(k) != v for k, v in expected.items()):
            raise IdentityBridgeError(403, "recovery_scope_mismatch",
                                      "Current owner does not match original pairing authority.")
        # Do not trust a claimed device binding_ref: this is the exact
        # deterministic name the canonical Broker computes when redeeming
        # challenge/device (see InMemoryBrokerPairingAuthority._redeem_pending).
        digest = hashlib.sha256(f"{challenge}:{device}".encode("utf-8")).hexdigest()[:32]
        expected_ref = f"pairing-binding.{digest}"
        directory = await self._broker.owner_device_directory(
            account_ref=consent["account_ref"],
            workspace_ref=consent["workspace_ref"],
        )
        if type(directory) is not dict or set(directory) != {"available", "devices"}:
            raise IdentityBridgeError(503, "recovery_directory_invalid",
                                      "Canonical Broker directory not verified.")
        if directory["available"] is False and directory["devices"] == []:
            return _hold(challenge_id=challenge, device_id=device)
        if directory["available"] is not True or type(directory["devices"]) is not list:
            raise IdentityBridgeError(503, "recovery_directory_invalid",
                                      "Canonical Broker directory not verified.")
        matching = []
        for item in directory["devices"]:
            if type(item) is not dict or set(item) != _DIRECTORY_ENTRY_FIELDS:
                raise IdentityBridgeError(503, "recovery_directory_invalid",
                                          "Canonical Broker directory not verified.")
            binding = item["binding"]
            if type(binding) is not dict or set(binding) != _BINDING_FIELDS:
                raise IdentityBridgeError(503, "recovery_directory_invalid",
                                          "Canonical Broker directory not verified.")
            if (
                item.get("canonical_state") not in _STATES
                or binding.get("credential_digest_exposed") is not False
                or binding.get("raw_device_credential") is not False
            ):
                raise IdentityBridgeError(503, "recovery_directory_invalid",
                                          "Canonical Broker directory not verified.")
            if binding.get("binding_ref") == expected_ref:
                matching.append(item)
        if len(matching) != 1:
            return _hold(challenge_id=challenge, device_id=device)
        fact = matching[0]
        binding = fact["binding"]
        if (
            binding["device_id"] != device
            or binding["account_ref"] != consent["account_ref"]
            or binding["workspace_ref"] != consent["workspace_ref"]
            or type(binding["credential_generation"]) is not int
            or binding["credential_generation"] < 1
        ):
            raise IdentityBridgeError(503, "recovery_binding_mismatch",
                                      "Canonical Broker binding correlation invalid.")
        if fact["canonical_state"] != "revoked":
            return _hold(challenge_id=challenge, device_id=device)
        return {
            "challenge_id": challenge, "device_id": device,
            "disposition": "revoked", "canonical_revocation_confirmed": True,
            "can_retry_challenge": False, "raw_device_credential": False,
            "dispatch_authorized": False,
        }


__all__ = [
    "OWNER_RECOVERY_ROUTE_MOUNTED", "OWNER_RECOVERY_PRODUCTION_ENABLED",
    "CanonicalConnectorOwnerRecovery",
]
