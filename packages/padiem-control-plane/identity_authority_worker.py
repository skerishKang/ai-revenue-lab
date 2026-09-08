from __future__ import annotations

from datetime import datetime
from typing import Any

from workers import DurableObject, Response, WorkerEntrypoint

from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)

from identity_authority_durable import (
    CloudflareCanonicalIdentityAuthorityStore,
    decode_identity_lookup_key,
)
from identity_connector_ticket import (
    CanonicalConnectorContextStore,
    GoogleConnectTicketIssuer,
    decode_connect_ticket_key,
)


_AUTHORITY_REF = "control-plane.identity.production.v1"
_ALLOWED_PRODUCT = "b62"
_LINK_KEYS = frozenset({"product_id", "product_user_id", "auth_provider", "provider_subject"})
_SESSION_KEYS = frozenset({"product_id", "subject", "authenticated_at", "not_after"})
_RESOLVE_KEYS = frozenset({"session_id"})
_CONNECT_KEYS = frozenset({"session_id", "connector_id"})
_SUBJECT_KEYS = frozenset({"subject_type", "subject_id"})


def _required_env(env: Any, name: str) -> str:
    value = getattr(env, name, None)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"required identity authority binding {name} is missing")
    return value.strip()


def _closed(payload: Any, keys: frozenset[str], field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ControlPlaneContractError(
            "invalid_identity_authority_rpc",
            f"{field_name} must contain exactly the reviewed fields",
        )
    return payload


def _parse_time(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ControlPlaneContractError(
            "invalid_identity_authority_rpc",
            f"{field_name} must be ISO-8601 text",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlPlaneContractError(
            "invalid_identity_authority_rpc",
            f"{field_name} must be valid ISO-8601 text",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_identity_authority_rpc",
            f"{field_name} must be timezone-aware",
        )
    return parsed


def _safe_error(exc: ControlPlaneContractError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": exc.code,
            "message": "Canonical identity request was rejected",
        },
    }


class CanonicalIdentityDurableObject(DurableObject):
    """Private canonical identity/session and connector-ticket authority."""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        allowed = getattr(env, "CONTROL_PLANE_ALLOWED_PRODUCT", _ALLOWED_PRODUCT)
        if allowed != _ALLOWED_PRODUCT:
            raise RuntimeError("identity authority product boundary does not match the reviewed product")
        self._store = CloudflareCanonicalIdentityAuthorityStore(
            ctx.storage,
            lookup_key=decode_identity_lookup_key(
                _required_env(env, "CONTROL_PLANE_IDENTITY_LOOKUP_KEY")
            ),
            allowed_product_id=_ALLOWED_PRODUCT,
        )
        self._connector_context_store = CanonicalConnectorContextStore(ctx.storage)
        self._connect_ticket_issuer = GoogleConnectTicketIssuer(
            context_store=self._connector_context_store,
            signing_key=decode_connect_ticket_key(
                _required_env(env, "GOOGLE_CONNECT_TICKET_KEY")
            ),
        )

    async def resolve_or_create_product_link(self, payload: dict) -> dict:
        try:
            wire = _closed(payload, _LINK_KEYS, "identity-link RPC")
            link = self._store.resolve_or_create_product_link(
                product_id=wire["product_id"],
                product_user_id=wire["product_user_id"],
                auth_provider=wire["auth_provider"],
                provider_subject=wire["provider_subject"],
                now=datetime.now().astimezone(),
            )
            return {"ok": True, "link": link.to_public_dict()}
        except ControlPlaneContractError as exc:
            return _safe_error(exc)

    async def establish_auth_session(self, payload: dict) -> dict:
        try:
            wire = _closed(payload, _SESSION_KEYS, "auth-session RPC")
            subject_wire = _closed(wire["subject"], _SUBJECT_KEYS, "canonical subject")
            subject = CanonicalSubjectRef(
                subject_type=SubjectType(subject_wire["subject_type"]),
                subject_id=subject_wire["subject_id"],
            )
            session = self._store.establish_auth_session(
                product_id=wire["product_id"],
                subject=subject,
                authenticated_at=_parse_time(wire["authenticated_at"], "authenticated_at"),
                not_after=_parse_time(wire["not_after"], "not_after"),
                now=datetime.now().astimezone(),
            )
            return {"ok": True, "session": session.to_public_dict()}
        except (ControlPlaneContractError, ValueError) as exc:
            if isinstance(exc, ControlPlaneContractError):
                return _safe_error(exc)
            return _safe_error(
                ControlPlaneContractError(
                    "invalid_identity_authority_rpc",
                    "canonical identity request is invalid",
                )
            )

    async def resolve_auth_session(self, payload: dict) -> dict:
        try:
            wire = _closed(payload, _RESOLVE_KEYS, "auth-session resolve RPC")
            session = self._store.resolve_auth_session(session_id=wire["session_id"])
            return {"ok": True, "session": session.to_public_dict()}
        except ControlPlaneContractError as exc:
            return _safe_error(exc)

    async def issue_google_connect_ticket(self, payload: dict) -> dict:
        """Mint one short-lived ticket after authoritative session re-read.

        The caller supplies only the canonical session id and reviewed connector.
        actor/account/workspace references are resolved exclusively inside this
        private Control Plane Durable Object and cannot be client asserted.
        """

        try:
            wire = _closed(payload, _CONNECT_KEYS, "Google connect-ticket RPC")
            session = self._store.resolve_auth_session(session_id=wire["session_id"])
            receipt = self._connect_ticket_issuer.issue(
                auth_session=session,
                connector_id=wire["connector_id"],
            )
            return {"ok": True, "ticket": receipt.to_private_rpc_dict()}
        except ControlPlaneContractError as exc:
            return _safe_error(exc)

    async def fetch(self, request):
        del request
        return Response("Not Found", status=404, headers={"cache-control": "no-store"})


class Default(WorkerEntrypoint):
    """Private Service Binding gateway. No public route is configured."""

    def _stub(self):
        namespace = self.env.CONTROL_PLANE_IDENTITY
        object_id = namespace.idFromName(_AUTHORITY_REF)
        return namespace.get(object_id)

    async def resolve_or_create_product_link(self, payload: dict) -> dict:
        return await self._stub().resolve_or_create_product_link(payload)

    async def establish_auth_session(self, payload: dict) -> dict:
        return await self._stub().establish_auth_session(payload)

    async def resolve_auth_session(self, payload: dict) -> dict:
        return await self._stub().resolve_auth_session(payload)

    async def issue_google_connect_ticket(self, payload: dict) -> dict:
        return await self._stub().issue_google_connect_ticket(payload)

    async def fetch(self, request):
        del request
        return Response("Not Found", status=404, headers={"cache-control": "no-store"})


CANONICAL_IDENTITY_AUTHORITY_WORKER_SOURCE = True
SQLITE_BACKED_DURABLE_OBJECT = True
PRIVATE_SERVICE_BINDING_RPC = True
PROVIDER_SUBJECT_PERSISTED = False
PRODUCT_D1_SHADOW_AUTHORITATIVE = False
CONNECT_TICKET_ISSUED_BY_CONTROL_PLANE = True
CLIENT_ACTOR_ACCOUNT_WORKSPACE_AUTHORITY = False
RAW_CONNECT_TICKET_PUBLIC = False
GOOGLE_WRITE_SCOPE = False
PUBLIC_FETCH = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_MUTATION = False
