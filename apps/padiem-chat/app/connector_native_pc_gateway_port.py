"""#4139 signed B54 -> EXISTING Broker DO native same-PC WSS private gateway.

Injection only, UNMOUNTED. Implements the existing TrustedConnectorGateway
interface for CanonicalGatewayProtectedHandoff; never a second credential mint,
public HTTP route, browser-owned connection ID or Owner identity provider.

The canonical B54 host still handles Identity reauthorization (pre/post
redemption), sole Broker redeem, keyed Windows DPAPI ACK verification and
compensating revoke. This port checks EXACT private RPC shapes and does not
treat WSS delivery/send success as durable Windows installation evidence.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from .canonical_connector_gateway_handoff import GatewayBootstrapLease
from .canonical_connector_credential_handoff import DeviceCredentialInstallAck
from .connector_owner_identity_pc_completion import VerifiedCanonicalPcHandoff

REVIEW_ONLY_NATIVE_PC_GATEWAY_WIRED = False
REVIEW_ONLY_NATIVE_PC_GATEWAY_PRODUCTION_ENABLED = False
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_SAFE_BINDING = frozenset({
    "binding_ref", "device_id", "account_ref", "workspace_ref", "credential_ref",
    "credential_generation", "credential_expires_at",
})
_RPC = (
    "reserve_native_pc_gateway",
    "authenticate_native_pc_gateway",
    "transfer_native_pc_credential_once",
    "receive_native_pc_install_ack",
    "authenticate_native_pc_install_ack",
    "complete_native_pc_enrollment",
)


class NativePcGatewayDenied(RuntimeError):
    """Sensitive credential, original proof and PC session never echoed."""


def _receipt(raw: Any, keys: set[str]) -> dict[str, Any]:
    # JS Cloudflare Service Binding replies may be JsProxy-like; use the
    # canonical existing broker client's strict conversion.
    from .control_plane_broker_pairing_client import _dict
    value = _dict(raw)
    if type(value) is not dict or set(value) != keys:
        raise NativePcGatewayDenied("native_pc_rpc_invalid")
    return value


def _time(value: Any) -> datetime:
    if type(value) is not str:
        raise NativePcGatewayDenied("native_pc_lease_invalid")
    try:
        v = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("timezone required")
        now = datetime.now(timezone.utc)
        if not now < v <= now + timedelta(seconds=60):
            raise ValueError("expired or unbounded")
        return v
    except (ValueError, OverflowError):
        raise NativePcGatewayDenied("native_pc_lease_invalid") from None


class CanonicalNativePcTrustedGateway:
    """Per B54 preflight request, one PC, one previous Broker proof claim."""

    def __init__(self, *, verified: VerifiedCanonicalPcHandoff,
                 private_broker: Any) -> None:
        if type(verified) is not VerifiedCanonicalPcHandoff:
            raise NativePcGatewayDenied("native_pc_verified_owner_required")
        if any(not callable(getattr(private_broker, method, None)) for method in _RPC):
            raise NativePcGatewayDenied("native_pc_private_broker_missing")
        self._verified = verified
        self._broker = private_broker
        self._lease: GatewayBootstrapLease | None = None
        self._used = False
        self._receipt: dict[str, Any] | None = None

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        try:
            return await getattr(self._broker, method)(payload)
        except Exception:
            raise NativePcGatewayDenied("native_pc_private_rpc_unconfirmed") from None

    async def reserve_authenticated_bootstrap(
        self, *, challenge_id: str, device_id: str,
    ) -> GatewayBootstrapLease:
        if (
            self._lease is not None or self._used
            or challenge_id != self._verified.challenge_id
            or device_id != self._verified.device_id
        ):
            raise NativePcGatewayDenied("native_pc_reserve_denied")
        reply = _receipt(await self._call("reserve_native_pc_gateway", {
            "request_ref": self._verified.request_ref,
            "challenge_id": challenge_id, "device_id": device_id,
        }), {"request_ref", "challenge_id", "device_id",
             "lease_ref", "expires_at", "authenticated", "credential_issued"})
        if (
            reply["request_ref"] != self._verified.request_ref
            or reply["challenge_id"] != challenge_id or reply["device_id"] != device_id
            or type(reply["lease_ref"]) is not str
            or _REF.fullmatch(reply["lease_ref"]) is None
            or reply["authenticated"] is not True
            or reply["credential_issued"] is not False
        ):
            raise NativePcGatewayDenied("native_pc_reserve_receipt_invalid")
        self._lease = GatewayBootstrapLease(
            lease_ref=reply["lease_ref"], challenge_id=challenge_id,
            device_id=device_id, expires_at=_time(reply["expires_at"]),
        )
        return self._lease

    async def authenticate_bootstrap_lease(
        self, *, lease: GatewayBootstrapLease, challenge_id: str, device_id: str,
    ) -> bool:
        if (
            lease is not self._lease or self._used
            or challenge_id != self._verified.challenge_id
            or device_id != self._verified.device_id
        ):
            return False
        try:
            response = _receipt(await self._call("authenticate_native_pc_gateway", {
                "request_ref": self._verified.request_ref,
                "challenge_id": challenge_id, "device_id": device_id,
                "lease_ref": lease.lease_ref,
            }), {"request_ref", "challenge_id", "device_id", "lease_ref",
                 "authenticated", "credential_issued"})
            return (
                response["request_ref"] == self._verified.request_ref
                and response["challenge_id"] == challenge_id
                and response["device_id"] == device_id
                and response["lease_ref"] == lease.lease_ref
                and response["authenticated"] is True
                and response["credential_issued"] is False
            )
        except Exception:
            return False

    async def confirm_completed_installation(self) -> None:
        """Release the waiting PC only after the canonical host succeeds."""
        if self._lease is None or not self._used or self._receipt is None:
            raise NativePcGatewayDenied("native_pc_terminal_not_ready")
        result = _receipt(await self._call("complete_native_pc_enrollment", {
            "request_ref": self._verified.request_ref,
            "challenge_id": self._lease.challenge_id,
            "device_id": self._lease.device_id, "lease_ref": self._lease.lease_ref,
        }), {"sent_once", "connected"})
        if result["sent_once"] is not True or result["connected"] is not False:
            raise NativePcGatewayDenied("native_pc_terminal_unconfirmed")

    async def transfer_credential_once(
        self, *, lease: GatewayBootstrapLease, credential: bytes,
        binding: dict[str, Any],
    ) -> None:
        if (
            lease is not self._lease or self._used
            or type(credential) is not bytes or not 16 <= len(credential) <= 4096
            or type(binding) is not dict or set(binding) != _SAFE_BINDING
            or binding["device_id"] != lease.device_id
        ):
            raise NativePcGatewayDenied("native_pc_transfer_denied")
        # Do not retry on any ambiguity after the canonical Broker has
        # consumed its challenge, regardless of send or private RPC outcome.
        self._used = True
        result = _receipt(await self._call("transfer_native_pc_credential_once", {
            "request_ref": self._verified.request_ref,
            "challenge_id": lease.challenge_id, "device_id": lease.device_id,
            "lease_ref": lease.lease_ref, "binding": binding,
            "credential_b64": base64.b64encode(credential).decode("ascii"),
        }), {"sent_once", "credential_installed", "registered"})
        if (
            result["sent_once"] is not True
            or result["credential_installed"] is not False
            or result["registered"] is not False
        ):
            raise NativePcGatewayDenied("native_pc_transfer_unconfirmed")

    async def receive_authenticated_install_ack(self, *, lease: GatewayBootstrapLease) -> dict[str, Any]:
        if lease is not self._lease or not self._used or self._receipt is not None:
            raise NativePcGatewayDenied("native_pc_ack_not_expected")
        result = _receipt(await self._call("receive_native_pc_install_ack", {
            "request_ref": self._verified.request_ref,
            "challenge_id": lease.challenge_id, "device_id": lease.device_id,
            "lease_ref": lease.lease_ref,
        }), {"ack", "source_authenticated", "registered"})
        if result["source_authenticated"] is not True or result["registered"] is not False:
            raise NativePcGatewayDenied("native_pc_ack_unconfirmed")
        if type(result["ack"]) is not dict:
            raise NativePcGatewayDenied("native_pc_ack_invalid")
        self._receipt = result["ack"]
        return dict(result["ack"])

    async def authenticate_ack_sender(
        self, *, lease: GatewayBootstrapLease, ack: DeviceCredentialInstallAck,
    ) -> bool:
        if (
            lease is not self._lease or not self._used
            or self._receipt is None or type(ack) is not DeviceCredentialInstallAck
            or ack.safe_dict() != self._receipt
        ):
            return False
        try:
            response = _receipt(await self._call(
                "authenticate_native_pc_install_ack", {
                    "request_ref": self._verified.request_ref,
                    "challenge_id": lease.challenge_id, "device_id": lease.device_id,
                    "lease_ref": lease.lease_ref, "ack": ack.safe_dict(),
                }), {"source_authenticated", "registered"})
            return (
                response["source_authenticated"] is True
                and response["registered"] is False
            )
        except Exception:
            return False
