"""#4139 B54 signed-owner HTTP -> ONE existing canonical Broker private RPC port.

SOURCE ONLY. Exports neither public route nor Worker method. This deliberately
does not create a second credential/broker, an HTTP bearer token, or an
isolated process-global socket map.

Real production precondition: the existing Broker Durable Object must expose
these TWO gated methods on the same authority-ref DO which holds the one
authenticated PC WSS. Calling a different DO must fail closed; no fallback to
a B62 in-memory map is permitted. The broker response is *not* an install ACK.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from padiem_control_plane.auth_sessions import AuthSessionSnapshot

OWNER_PENDING_BROKER_PRIVATE_RPC_EXPORTED = False
OWNER_PENDING_BROKER_PRODUCTION_ENABLED = False
OWNER_PENDING_BROKER_HTTP_MOUNTED = False

_REF = re.compile(r"^link\.[0-9a-f]{32}$")
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_CODE = re.compile(r"^[0-9a-f]{32}$")


class OwnerPcPrivateRpcDenied(RuntimeError):
    """Safe bounded error, never echoes pairing code or session ID."""


def _valid_owner(owner_session: Any) -> bool:
    now = datetime.now(timezone.utc)
    try:
        return (
            type(owner_session) is AuthSessionSnapshot
            and owner_session.product_id == "b54-padiem-claw"
            and bool(owner_session.tenant_id)
            and owner_session.is_active(now=now)
        )
    except Exception:
        return False


def _reply(value: Any) -> dict[str, Any] | None:
    # JS Cloudflare Service Binding replies may be JsProxy-like; use the
    # canonical existing broker client's strict conversion.
    from .control_plane_broker_pairing_client import _dict
    return _dict(value)


class CanonicalBrokerOwnerPendingPcPort:
    """Scoped per-verified-request private Broker DO stub.

    Methods go through the existing authority-ref service binding; no
    direct Worker-to-PC connections, no browser-provided DO IDs, and no
    session/tenant data is transported as alleged authentication.
    """

    def __init__(
        self, *, signed_owner: AuthSessionSnapshot, canonical_broker_binding: Any, identity: Any = None,
    ) -> None:
        if not _valid_owner(signed_owner):
            raise OwnerPcPrivateRpcDenied("pending_pc_owner_unverified")
        if any(
            not callable(getattr(canonical_broker_binding, method, None))
            for method in ("reserve_pending_pc_owner_intent", "deliver_pending_pc_link")
        ):
            raise OwnerPcPrivateRpcDenied("pending_pc_broker_binding_missing")
        self._broker = canonical_broker_binding
        self._identity = identity
        self._owner = signed_owner

    async def reserve_once(self, *, request_ref: str) -> dict[str, Any]:
        if type(request_ref) is not str or _REF.fullmatch(request_ref) is None:
            raise OwnerPcPrivateRpcDenied("pending_pc_ref_invalid")
        try:
            if not callable(getattr(self._identity, "resolve_connector_owner_scope", None)):
                raise OwnerPcPrivateRpcDenied("pending_pc_identity_scope_unavailable")
            scope = await self._identity.resolve_connector_owner_scope(
                session_id=self._owner.session_id,
            )
            if (
                type(scope) is not dict or set(scope) != {"account_ref", "workspace_ref"}
                or any(type(v) is not str or _DEVICE.fullmatch(v) is None for v in scope.values())
            ):
                raise OwnerPcPrivateRpcDenied("pending_pc_identity_scope_invalid")
            raw_response = await self._broker.reserve_pending_pc_owner_intent({
                "request_ref": request_ref,
                "owner_subject_ref": self._owner.subject.subject_id,
                "account_ref": scope["account_ref"],
                "workspace_ref": scope["workspace_ref"],
            })
        except Exception:
            raise OwnerPcPrivateRpcDenied("pending_pc_reserve_unavailable") from None
        response = _reply(raw_response)
        if (
            type(response) is not dict
            or set(response) != {
                "request_ref", "device_id", "device_possession_verified",
                "connected_to_outbound_channel", "reserved_once", "expires_at",
            }
            or response["request_ref"] != request_ref
            or type(response["device_id"]) is not str
            or _DEVICE.fullmatch(response["device_id"]) is None
            or response["device_possession_verified"] is not True
            or response["connected_to_outbound_channel"] is not True
            or response["reserved_once"] is not True
            or type(response["expires_at"]) is not str
        ):
            raise OwnerPcPrivateRpcDenied("pending_pc_reserve_invalid")
        return response

    async def deliver_once(
        self, *, request_ref: str, device_id: str,
        challenge_id: str, pairing_code: str,
    ) -> None:
        if (
            type(request_ref) is not str or _REF.fullmatch(request_ref) is None
            or type(device_id) is not str or _DEVICE.fullmatch(device_id) is None
            or type(challenge_id) is not str or _DEVICE.fullmatch(challenge_id) is None
            or type(pairing_code) is not str or _CODE.fullmatch(pairing_code) is None
        ):
            raise OwnerPcPrivateRpcDenied("pending_pc_delivery_invalid")
        try:
            raw_response = await self._broker.deliver_pending_pc_link({
                "request_ref": request_ref,
                "device_id": device_id,
                "challenge_id": challenge_id,
                "pairing_code": pairing_code,
            })
        except Exception:
            # One-time Broker slot may have been consumed; do not retry.
            raise OwnerPcPrivateRpcDenied("pending_pc_delivery_unconfirmed") from None
        response = _reply(raw_response)
        if (
            type(response) is not dict
            or set(response) != {"ok", "sent_once", "registered", "connected"}
            or response["ok"] is not True
            or response["sent_once"] is not True
            or response["registered"] is not False
            or response["connected"] is not False
        ):
            raise OwnerPcPrivateRpcDenied("pending_pc_delivery_unconfirmed")
