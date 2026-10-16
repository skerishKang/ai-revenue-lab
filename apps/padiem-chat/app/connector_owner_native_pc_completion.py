"""#4139 B54-only ONE canonical completion from verified owner to live PC WSS.

Operator review source: NOT HTTP mounted, NOT production activated.
Reuses original canonical Identity+Broker and canonical Host.redeem for the
sole credential issuance, Windows DPAPI sender/ACK, post-ACK owner grant
revalidation and compensating Broker revoke. Browser receives no proof, code,
credential or new dispatch permission.

The per-request original signed B54 owner must pass CanonicalOwnerPcIdentity-
Preflight (fresh grant and one-use same-DO PC proof) before this orchestrator
can even construct the trusted same-native-WSS gateway.
"""
from __future__ import annotations

from typing import Any

from padiem_control_plane.auth_sessions import AuthSessionSnapshot

from .canonical_connector_enrollment_async_host import CanonicalConnectorEnrollmentAsyncHost
from .canonical_connector_gateway_handoff import CanonicalGatewayProtectedHandoff
from .connector_native_pc_gateway_port import CanonicalNativePcTrustedGateway
from .connector_owner_identity_pc_completion import CanonicalOwnerPcIdentityPreflight
from .control_plane_identity import IdentityBridgeError

NATIVE_OWNER_PC_COMPLETION_PUBLIC_MOUNTED = False
NATIVE_OWNER_PC_COMPLETION_PRODUCTION_ENABLED = False


class CanonicalOwnerNativePcCompletion:
    def __init__(
        self, *, identity: Any, broker: Any,
        private_broker: Any, preflight: CanonicalOwnerPcIdentityPreflight,
    ) -> None:
        if type(preflight) is not CanonicalOwnerPcIdentityPreflight:
            raise ValueError("canonical signed owner PC preflight required")
        # Check interfaces at operator composition time, before redemption.
        # Every step below uses existing typed Canonical Broker/Identity ports.
        CanonicalConnectorEnrollmentAsyncHost(
            identity=identity, broker=broker, credential_handoff=None,
        )
        self._identity = identity
        self._broker = broker
        self._private = private_broker
        self._preflight = preflight

    async def complete(
        self, *, signed_owner: AuthSessionSnapshot, request_ref: str,
    ) -> dict[str, Any]:
        verified = await self._preflight.prepare(
            signed_owner=signed_owner, request_ref=request_ref, wait_for_fetch=True,
        )
        # If any private native RPC is missing, refuse BEFORE consuming the
        # original canonical Broker challenge/issuing a credential.
        try:
            gateway = CanonicalNativePcTrustedGateway(
                verified=verified, private_broker=self._private,
            )
        except Exception:
            raise IdentityBridgeError(
                503, "native_pc_protected_gateway_unavailable",
                "Current PC protected connection is unavailable.",
            ) from None
        handoff = CanonicalGatewayProtectedHandoff(gateway=gateway)
        host = CanonicalConnectorEnrollmentAsyncHost(
            identity=self._identity, broker=self._broker,
            credential_handoff=handoff,
        )
        # This ORIGINAL host is solely responsible for:
        # 1) re-authorizing the canonical Identity (again, from live session)
        # 2) original Broker verify+redeem and one-use credential mutation
        # 3) sending ONLY over the authenticated same-PC gateway
        # 4) comparing Windows DPAPI readback keyed install transcript with
        #    raw Broker secret PLUS independently signed Broker WSS ACK
        # 5) rechecking Identity after ACK and revoking on any failure.
        result = await host.redeem(
            challenge_id=verified.challenge_id,
            device_id=verified.device_id,
            proof_ref=verified.proof_ref,
        )
        if (
            type(result) is not dict
            or result.get("device_id") != verified.device_id
            or result.get("credential_installed_by_canonical_handoff") is not True
            or result.get("lifecycle") != "paired_offline"
            or result.get("raw_device_credential") is not False
            or result.get("dispatch_authorized") is not False
        ):
            raise IdentityBridgeError(
                503, "native_pc_canonical_result_invalid",
                "Canonical PC result was not confirmed.",
            )
        try:
            await gateway.confirm_completed_installation()
        except Exception:
            # A lost completion frame must not leave an uncertain binding
            # active or trigger another credential delivery attempt.
            try:
                await host._revoke_confirmed(binding_ref=result["binding_ref"])
            except Exception:
                raise IdentityBridgeError(
                    503, "native_pc_terminal_revoke_unconfirmed",
                    "PC completion and revocation could not be confirmed.",
                ) from None
            raise IdentityBridgeError(
                503, "native_pc_terminal_unconfirmed",
                "PC completion could not be confirmed.",
            ) from None
        return result
