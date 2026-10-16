"""#4139 B54 signed owner -> canonical Identity -> SAME Broker PC WSS proof.

Review-only internal composition. NEVER a browser route, never a new identity
authority and never a credential sender. This performs the two-DO preflight
before the original CanonicalConnectorEnrollmentAsyncHost.redeem is allowed
to run with a future independently authenticated Windows DPAPI handoff.

The original canonical Broker DO is the ONLY producer of a signed PC fetch
status or one-time code-derived proof. B54 is the ONLY producer of a fresh
owner/session/consent authorization. Neither substitutes for the other.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from .control_plane_identity import IdentityBridgeError
from .control_plane_broker_pairing_client import _dict as _private_rpc_dict

B54_NATIVE_PC_IDENTITY_COMPLETION_ROUTE_MOUNTED = False
B54_NATIVE_PC_IDENTITY_COMPLETION_PRODUCTION_ENABLED = False
_REQUEST = re.compile(r"^link\.[0-9a-f]{32}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_PROOF = re.compile(r"^pairing-proof:[0-9a-f]{64}$")
_STATUS = frozenset({
    "request_ref", "challenge_id", "device_id", "signed_fetch_verified",
    "identity_authorized", "credential_issued", "connected",
})
_CLAIM = frozenset({
    "request_ref", "challenge_id", "device_id", "proof_ref",
    "identity_authorized", "credential_issued", "connected",
})


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedCanonicalPcHandoff:
    """Private-only ephemeral proof, never safe to print or JSON serialize."""
    challenge_id: str
    device_id: str
    proof_ref: str
    request_ref: str

    def __repr__(self) -> str:
        return "<VerifiedCanonicalPcHandoff private; no credential>"


def _ref(value: Any) -> bool:
    return type(value) is str and _REF.fullmatch(value) is not None


class CanonicalOwnerPcIdentityPreflight:
    """Constructed only from existing server-owned B54 Identity and Broker."""

    def __init__(self, *, identity: Any, broker: Any, private_broker: Any) -> None:
        if any(not callable(getattr(target, method, None)) for target, method in (
            (identity, "resolve_connector_enrollment_consent_for_device"),
            (identity, "authorize_connector_enrollment_redeem"),
            (broker, "get_enrollment_binding"),
            (private_broker, "pending_pc_identity_status"),
            (private_broker, "claim_pending_pc_identity_proof"),
        )):
            raise ValueError("canonical B54 Identity/Broker private bindings required")
        self._identity = identity
        self._broker = broker
        self._private = private_broker

    async def prepare(
        self, *, signed_owner: AuthSessionSnapshot, request_ref: str,
        wait_for_fetch: bool = False,
    ) -> VerifiedCanonicalPcHandoff:
        now = datetime.now(timezone.utc)
        if (
            type(signed_owner) is not AuthSessionSnapshot
            or signed_owner.product_id != "b54-padiem-claw"
            or not signed_owner.tenant_id
            or signed_owner.is_active(now=now) is not True
            or type(request_ref) is not str or _REQUEST.fullmatch(request_ref) is None
        ):
            raise IdentityBridgeError(
                403, "pending_pc_owner_required", "Current B54 owner approval is required.",
            )

        # Approval delivery and the PC's signed credential_fetch cross the
        # network independently. Only this read-only status may be retried;
        # proof claims and credential redemption below remain one-shot.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (5.0 if wait_for_fetch else 0.0)
        while True:
            try:
                status = _private_rpc_dict(await self._private.pending_pc_identity_status({
                    "request_ref": request_ref,
                }))
                break
            except Exception:
                if wait_for_fetch and loop.time() < deadline:
                    await asyncio.sleep(0.1)
                    continue
                raise IdentityBridgeError(
                    503, "pending_pc_live_fetch_unavailable", "Current PC proof is unavailable.",
                ) from None
        if (
            type(status) is not dict or set(status) != _STATUS
            or status["request_ref"] != request_ref
            or not _ref(status["challenge_id"]) or not _ref(status["device_id"])
            or status["signed_fetch_verified"] is not True
            or status["identity_authorized"] is not False
            or status["credential_issued"] is not False
            or status["connected"] is not False
        ):
            raise IdentityBridgeError(
                503, "pending_pc_fetch_invalid", "Current PC proof is invalid.",
            )
        challenge = status["challenge_id"]
        device = status["device_id"]
        try:
            binding = await self._broker.get_enrollment_binding(challenge_id=challenge)
            if (
                type(binding) is not dict
                or binding.get("challenge_id") != challenge
                or binding.get("device_id") != device
                or not all(_ref(binding.get(x)) for x in (
                    "consent_ref", "owner_ref", "account_ref", "workspace_ref",
                ))
            ):
                raise ValueError("wrong original challenge binding")
            consent = await self._identity.resolve_connector_enrollment_consent_for_device(
                session_id=signed_owner.session_id, device_id=device,
            )
            if (
                type(consent) is not dict
                or consent.get("device_id") != device
                or consent.get("withdrawn_at") is not None
                or consent.get("consent_id") != binding["consent_ref"]
                or consent.get("owner_subject_id") != binding["owner_ref"]
                or consent.get("owner_subject_id") != signed_owner.subject.subject_id
                or consent.get("account_ref") != binding["account_ref"]
                or consent.get("workspace_ref") != binding["workspace_ref"]
            ):
                raise ValueError("different owner/session/consent")
            authorized = await self._identity.authorize_connector_enrollment_redeem(
                challenge_id=challenge, consent_id=binding["consent_ref"],
                device_id=device, owner_ref=binding["owner_ref"],
                account_ref=binding["account_ref"],
                workspace_ref=binding["workspace_ref"],
            )
            if (
                type(authorized) is not dict
                or authorized.get("challenge_id") != challenge
                or authorized.get("device_id") != device
                or authorized.get("consent_id") != binding["consent_ref"]
                or authorized.get("owner_subject_id") != signed_owner.subject.subject_id
                or authorized.get("account_ref") != binding["account_ref"]
                or authorized.get("workspace_ref") != binding["workspace_ref"]
            ):
                raise ValueError("original Identity authorization refused")
        except Exception:
            raise IdentityBridgeError(
                403, "pending_pc_identity_unconfirmed",
                "Current owner consent could not be confirmed.",
            ) from None

        # No browser-authored challenge or proof is accepted. Claim-once
        # deliberately happens AFTER B54's fresh canonical Identity check.
        try:
            receipt = _private_rpc_dict(await self._private.claim_pending_pc_identity_proof({
                "request_ref": request_ref,
                "challenge_id": challenge, "device_id": device,
            }))
        except Exception:
            raise IdentityBridgeError(
                503, "pending_pc_claim_unconfirmed", "Current PC handoff is unavailable.",
            ) from None
        if (
            type(receipt) is not dict or set(receipt) != _CLAIM
            or receipt["request_ref"] != request_ref
            or receipt["challenge_id"] != challenge
            or receipt["device_id"] != device
            or type(receipt["proof_ref"]) is not str
            or _PROOF.fullmatch(receipt["proof_ref"]) is None
            or any(receipt[k] is not False for k in (
                "identity_authorized", "credential_issued", "connected",
            ))
        ):
            raise IdentityBridgeError(
                503, "pending_pc_claim_invalid", "Current PC handoff is invalid.",
            )
        # Re-read current grant after the separate Broker DO claim to limit
        # TOCTOU; if withdrawn in that window, the claim is NOT retryable.
        try:
            latest = await self._identity.resolve_connector_enrollment_consent_for_device(
                session_id=signed_owner.session_id, device_id=device,
            )
            if (
                type(latest) is not dict
                or latest.get("withdrawn_at") is not None
                or latest.get("consent_id") != binding["consent_ref"]
                or latest.get("owner_subject_id") != signed_owner.subject.subject_id
                or latest.get("account_ref") != binding["account_ref"]
                or latest.get("workspace_ref") != binding["workspace_ref"]
            ):
                raise ValueError("owner changed during claim")
        except Exception:
            raise IdentityBridgeError(
                403, "pending_pc_identity_changed",
                "Owner consent changed during PC handoff.",
            ) from None
        return VerifiedCanonicalPcHandoff(
            challenge_id=challenge, device_id=device,
            proof_ref=receipt["proof_ref"], request_ref=request_ref,
        )
