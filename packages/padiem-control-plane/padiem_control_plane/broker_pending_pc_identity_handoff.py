"""#4139 PRIVATE Broker -> existing B54 Identity host handoff discovery.

NO credential transfer, credential mint, Windows ACK, or browser endpoint.
Only the existing canonical Broker Durable Object can confirm a signed
credential_fetch arrived over the SAME outbound Windows WSS.

Protocol: (1) B54 trusted server gets a *non-secret* status by request_ref;
(2) the existing B54 Identity authority independently verifies owner,
session and still-active original consent/binding; (3) B54 claims the
already-authenticated pairing proof ONCE via private same-DO Service Binding.
A claim is NOT permission to issue a credential, and on uncertainty a retry
must fail closed. The existing canonical Host.redeem remains the sole mint/
revoke/Windows install-ACK owner, and is NOT invoked by this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

IDENTITY_HANDOFF_PUBLIC_MOUNTED = False
IDENTITY_HANDOFF_PRODUCTION_ENABLED = False
_IDENTITY_FLAG = "LOCAL_AGENT_BROKER_PENDING_PC_IDENTITY_HANDOFF_ENABLED"
_LINK = re.compile(r"^link\.[0-9a-f]{32}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_PROOF = re.compile(r"^pairing-proof:[0-9a-f]{64}$")


class BrokerPcIdentityHandoffDenied(RuntimeError):
    """Sanitized; no pairing proof, code, owner ID or WSS bytes."""


def _actor(owner_do: Any, request_ref: Any) -> Any:
    from .broker_pending_pc_private_rpc import _enabled

    if (
        not _enabled(owner_do.env)
        or getattr(owner_do.env, _IDENTITY_FLAG, None) != "enabled"
        or type(request_ref) is not str or _LINK.fullmatch(request_ref) is None
    ):
        raise BrokerPcIdentityHandoffDenied("pending_pc_identity_disabled")
    try:
        owner_do._pending_pc_live()  # exact canonical DO & review gates
        sessions = getattr(owner_do, "_pending_pc_wss_by_id", {})
        if type(sessions) is not dict or len(sessions) > 32:
            raise ValueError("untrusted session map")
        candidates = [
            candidate for candidate in sessions.values()
            if getattr(candidate, "_request_ref", None) == request_ref
        ]
        if len(candidates) != 1:
            raise ValueError("socket missing/duplicated")
        actor = candidates[0]
        bootstrap = actor._canonical_bootstrap
        if (
            actor._broker._store is not owner_do._storage
            or actor._gateway._socket is not actor._socket
            or actor._stage != "canonical"
            or actor._disconnected is not False
            or actor._approved_challenge != bootstrap._challenge_id
            or actor._device != bootstrap._device_id
            or actor._socket.closed is not False
            or datetime.now(timezone.utc) >= actor._expiry
            or bootstrap._stage != "identity_required"
            or bootstrap._fetch_verified is not True
            or bootstrap._socket is not actor._socket
            or bootstrap.authenticated_fetch_receipt(
                challenge_id=actor._approved_challenge,
                device_id=actor._device,
            ) is not True
            or type(bootstrap._proof_ref) is not str
            or _PROOF.fullmatch(bootstrap._proof_ref) is None
        ):
            raise ValueError("failed server-owned WSS proof")
        return actor
    except Exception:
        raise BrokerPcIdentityHandoffDenied(
            "pending_pc_identity_live_proof_missing"
        ) from None


async def identity_pc_status(owner_do: Any, payload: Any) -> dict[str, Any]:
    """Read-only server-to-server receipt with NO proof or credentials."""
    if type(payload) is not dict or set(payload) != {"request_ref"}:
        raise BrokerPcIdentityHandoffDenied("pending_pc_identity_fields_invalid")
    actor = _actor(owner_do, payload["request_ref"])
    return {
        "request_ref": actor._request_ref,
        "challenge_id": actor._approved_challenge,
        "device_id": actor._device,
        "signed_fetch_verified": True,
        "identity_authorized": False,
        "credential_issued": False,
        "connected": False,
    }


async def claim_identity_pc_proof(owner_do: Any, payload: Any) -> dict[str, Any]:
    """One-shot private handoff ONLY after B54 owner+Identity revalidation.

    Exact challenge/device are server-known from the first private status
    response, not browser-controlled. There is still NO authorization to
    mint a credential; the canonical B54 host must recheck original Identity
    grants both before and after Broker redemption.
    """
    if (
        type(payload) is not dict
        or set(payload) != {"request_ref", "challenge_id", "device_id"}
        or type(payload.get("challenge_id")) is not str
        or _REF.fullmatch(payload["challenge_id"]) is None
        or type(payload.get("device_id")) is not str
        or _REF.fullmatch(payload["device_id"]) is None
    ):
        raise BrokerPcIdentityHandoffDenied("pending_pc_identity_fields_invalid")
    actor = _actor(owner_do, payload["request_ref"])
    bootstrap = actor._canonical_bootstrap
    if (
        payload["challenge_id"] != actor._approved_challenge
        or payload["device_id"] != actor._device
        or getattr(actor, "_identity_proof_claimed", False) is not False
    ):
        raise BrokerPcIdentityHandoffDenied("pending_pc_identity_claim_denied")
    # Single actor/DO event loop; claim is complete BEFORE returning proof.
    # A failed private Service Binding response cannot mint another claim.
    actor._identity_proof_claimed = True
    return {
        "request_ref": actor._request_ref,
        "challenge_id": actor._approved_challenge,
        "device_id": actor._device,
        "proof_ref": bootstrap._proof_ref,
        "identity_authorized": False,
        "credential_issued": False,
        "connected": False,
    }
