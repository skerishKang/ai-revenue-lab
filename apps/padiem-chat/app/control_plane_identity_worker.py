from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import inspect
from typing import Any

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    IdentityLinkState,
    ProductIdentityLink,
    SubjectType,
)

from .control_plane_identity import IdentityBridgeError


_MAX_RPC_TICKET_CHARS = 24_576
_LINK_KEYS = frozenset({"product_id", "product_user_id", "canonical_subject_id", "state"})
_SESSION_KEYS = frozenset({"session_id", "product_id", "subject", "issued_at", "expires_at", "state", "revision"})
_SUBJECT_KEYS = frozenset({"subject_type", "subject_id"})
_TICKET_KEYS = frozenset({"connect_ticket", "connector_id", "expires_at"})
_REVIEWED_CONNECTORS = frozenset({"gmail", "google-drive"})


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        converted = dict(value)
    except (TypeError, ValueError):
        return None
    return converted


def _closed(value: Any, keys: frozenset[str], field_name: str) -> dict[str, Any]:
    wire = _dict(value)
    if wire is None or set(wire) != keys:
        raise IdentityBridgeError(
            503,
            "control_plane_rpc_invalid",
            f"{field_name} returned invalid canonical data.",
        )
    return wire


def _time(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise IdentityBridgeError(503, "control_plane_rpc_invalid", f"{field_name} is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IdentityBridgeError(503, "control_plane_rpc_invalid", f"{field_name} is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IdentityBridgeError(503, "control_plane_rpc_invalid", f"{field_name} is invalid.")
    return parsed


def _status_for_code(code: str) -> int:
    if code in {"inactive_auth_session", "canonical_auth_session_not_found"}:
        return 401
    if code in {
        "connector_context_session_mismatch",
        "identity_authority_product_mismatch",
        "unreviewed_connect_scope",
    }:
        return 403
    return 503


@dataclass(frozen=True, slots=True)
class PrivateGoogleConnectTicket:
    connect_ticket: str = field(repr=False)
    connector_id: str = ""
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.connect_ticket, str)
            or not self.connect_ticket
            or len(self.connect_ticket) > _MAX_RPC_TICKET_CHARS
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector ticket is invalid.")
        if self.connector_id not in _REVIEWED_CONNECTORS:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector ticket is invalid.")
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector ticket expiry is invalid.")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "expires_at": self.expires_at.isoformat(),
            "raw_connect_ticket": False,
        }


class CloudflareControlPlaneIdentityAuthority:
    """B62 adapter over the private Control Plane identity Worker Service Binding."""

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("Control Plane identity Service Binding is required")
        self._binding = binding

    async def _rpc(self, method_name: str, payload: dict[str, Any], success_field: str) -> dict[str, Any]:
        method = getattr(self._binding, method_name, None)
        if not callable(method):
            raise IdentityBridgeError(
                503,
                "control_plane_identity_unavailable",
                "Canonical identity service is unavailable.",
            )
        try:
            result = _dict(await _maybe_await(method(payload)))
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise IdentityBridgeError(
                503,
                "control_plane_identity_unavailable",
                "Canonical identity service is unavailable.",
            ) from exc
        if result is None or not isinstance(result.get("ok"), bool):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        if result["ok"] is False:
            if set(result) != {"ok", "error"}:
                raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
            error = _dict(result.get("error"))
            if error is None or set(error) != {"code", "message"} or not isinstance(error.get("code"), str):
                raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
            code = error["code"]
            raise IdentityBridgeError(
                _status_for_code(code),
                code,
                "Canonical identity request was rejected.",
            )
        if set(result) != {"ok", success_field}:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        payload_wire = _dict(result.get(success_field))
        if payload_wire is None:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        return payload_wire

    async def resolve_or_create_product_link(
        self,
        *,
        product_id: str,
        product_user_id: str,
        auth_provider: str,
        provider_subject: str,
    ) -> ProductIdentityLink:
        wire = _closed(
            await self._rpc(
                "resolve_or_create_product_link",
                {
                    "product_id": product_id,
                    "product_user_id": product_user_id,
                    "auth_provider": auth_provider,
                    "provider_subject": provider_subject,
                },
                "link",
            ),
            _LINK_KEYS,
            "identity link",
        )
        try:
            return ProductIdentityLink(
                product_id=wire["product_id"],
                product_user_id=wire["product_user_id"],
                canonical_subject_id=wire["canonical_subject_id"],
                state=IdentityLinkState(wire["state"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity link is invalid.") from exc

    async def establish_auth_session(
        self,
        *,
        product_id: str,
        subject: CanonicalSubjectRef,
        authenticated_at: datetime,
        not_after: datetime,
    ) -> AuthSessionSnapshot:
        wire = _closed(
            await self._rpc(
                "establish_auth_session",
                {
                    "product_id": product_id,
                    "subject": subject.to_public_dict(),
                    "authenticated_at": authenticated_at.isoformat(),
                    "not_after": not_after.isoformat(),
                },
                "session",
            ),
            _SESSION_KEYS,
            "auth session",
        )
        return self._session_from_wire(wire)

    async def resolve_auth_session(self, *, session_id: str) -> AuthSessionSnapshot:
        wire = _closed(
            await self._rpc("resolve_auth_session", {"session_id": session_id}, "session"),
            _SESSION_KEYS,
            "auth session",
        )
        return self._session_from_wire(wire)

    async def issue_google_connect_ticket(
        self,
        *,
        session_id: str,
        connector_id: str,
    ) -> PrivateGoogleConnectTicket:
        wire = _closed(
            await self._rpc(
                "issue_google_connect_ticket",
                {"session_id": session_id, "connector_id": connector_id},
                "ticket",
            ),
            _TICKET_KEYS,
            "Google connect ticket",
        )
        return PrivateGoogleConnectTicket(
            connect_ticket=wire["connect_ticket"],
            connector_id=wire["connector_id"],
            expires_at=_time(wire["expires_at"], "connect ticket expiry"),
        )

    @staticmethod
    def _session_from_wire(wire: dict[str, Any]) -> AuthSessionSnapshot:
        subject_wire = _closed(wire.get("subject"), _SUBJECT_KEYS, "canonical subject")
        try:
            return AuthSessionSnapshot(
                session_id=wire["session_id"],
                product_id=wire["product_id"],
                subject=CanonicalSubjectRef(
                    subject_type=SubjectType(subject_wire["subject_type"]),
                    subject_id=subject_wire["subject_id"],
                ),
                issued_at=_time(wire["issued_at"], "issued_at"),
                expires_at=_time(wire["expires_at"], "expires_at"),
                state=AuthSessionState(wire["state"]),
                revision=wire["revision"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical auth session is invalid.") from exc


CONTROL_PLANE_IDENTITY_SERVICE_BINDING_ADAPTER = True
BROWSER_CANONICAL_ID_AUTHORITY = False
CLIENT_ACCOUNT_WORKSPACE_AUTHORITY = False
RAW_CONNECT_TICKET_LOGGED = False
PRODUCTION_IDENTITY_BINDING = False
CLIENT_IDENTITY_AUTHORITY = False
