"""#3782 browser P01 ticket issuance: REAL Control Plane session resolution.

Uses the existing Engine AuthSessionScopeAuthority and private Control Plane
resolve_auth_session client. The B54 product-user/session shadow is only a
POINTER, never a substitute for current CP session truth. The caller cannot
supply subject/tenant/scope. No extra identity/approval authority or route.
SOURCE ONLY: NO Worker binding, Production activation or user approval issued.
"""
from __future__ import annotations

import inspect
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from app.auth_session_scope_authority import (
    AuthSessionScopeAuthority,
    ControlPlaneAuthSessionClient,
)
from app.browser_control_owner_p01_ticket_issuer import (
    CurrentCanonicalHumanSession,
)

PADIEM_CHAT_PRODUCT_ID = "b62"
BROWSER_P01_CURRENT_CP_SESSION_WIRED = False


class CurrentProductIdentityShadowStore(Protocol):
    def load_projection(self, product_user_id: str) -> Any: ...


class _SingleResolvedSession:
    """One CP-authoritative payload, validated by existing Engine scope code."""

    def __init__(self, *, session_id: str, payload: Mapping[str, Any]):
        self.session_id = session_id
        self.payload = payload

    def resolve_auth_session(self, *, session_id: str) -> Mapping[str, Any] | None:
        return self.payload if session_id == self.session_id else None


class FirstPartyControlPlaneBrowserP01SessionAuthority:
    """CP-authenticated exact B54 USER/session/tenant correlation.

    The Engine must be given the current trusted B54 user identity pointer by
    the existing canonical identity owner, NOT a snapshot built from model
    arguments. Real CP session RPC is made for EVERY issue attempt.
    """

    def __init__(
        self,
        *,
        identity_shadow: CurrentProductIdentityShadowStore,
        session_client: ControlPlaneAuthSessionClient,
    ) -> None:
        if (
            not callable(getattr(identity_shadow, "load_projection", None))
            or not callable(getattr(session_client, "resolve_auth_session", None))
        ):
            raise TypeError("canonical identity shadow and CP session client required")
        self._shadow = identity_shadow
        self._client = session_client

    async def resolve_active(
        self, *, product_user_id: str, auth_session_ref: str,
    ) -> CurrentCanonicalHumanSession | None:
        if (
            type(product_user_id) is not str
            or not product_user_id.startswith("usr_")
            or type(auth_session_ref) is not str
            or not auth_session_ref
            or len(auth_session_ref) > 256
        ):
            return None
        try:
            shadow = self._shadow.load_projection(product_user_id)
            if inspect.isawaitable(shadow):
                shadow = await shadow
            # Exact linked product-user pointer. Do not trust an auth session
            # identifier merely because it was supplied with a valid cookie.
            if (
                shadow is None
                or getattr(shadow, "product_user_id", None) != product_user_id
                or getattr(shadow, "auth_session_id", None) != auth_session_ref
                or getattr(shadow, "session_state", None) != "active"
                or type(getattr(shadow, "session_revision", None)) is not int
                or shadow.session_revision < 1
            ):
                return None
            now = datetime.now(timezone.utc)
            shadow_expires = getattr(shadow, "session_expires_at", None)
            if (
                type(shadow_expires) is not datetime
                or shadow_expires.tzinfo is None
                or shadow_expires.utcoffset() is None
                or shadow_expires <= now
            ):
                return None
            # One authoritative read. The established AuthSessionScopeAuthority
            # validates exact app, active session, bounded ID, tenant/subject.
            current = self._client.resolve_auth_session(session_id=auth_session_ref)
            if inspect.isawaitable(current):
                current = await current
            if not isinstance(current, Mapping):
                return None
            if (
                current.get("session_id") != auth_session_ref
                or current.get("product_id") != PADIEM_CHAT_PRODUCT_ID
                or current.get("state") != "active"
                or type(current.get("revision")) is not int
                or current["revision"] < shadow.session_revision
            ):
                return None
            subject = current.get("subject")
            if (
                not isinstance(subject, Mapping)
                or subject.get("subject_type") != "user"
                or subject.get("subject_id") != getattr(shadow, "canonical_subject_id", None)
            ):
                return None
            scope = await AuthSessionScopeAuthority(
                session_client=_SingleResolvedSession(
                    session_id=auth_session_ref, payload=current,
                ),
                clock=lambda: now,
            ).scope_for_request(
                app_id=PADIEM_CHAT_PRODUCT_ID,
                auth_session_id=auth_session_ref,
            )
            if scope.subject_id != shadow.canonical_subject_id:
                return None
            return CurrentCanonicalHumanSession(
                product_user_id=product_user_id,
                canonical_subject_id=scope.subject_id,
                workspace_ref=scope.tenant_id,
                auth_session_ref=auth_session_ref,
            )
        except Exception:  # noqa: BLE001 - CP/identity failure cannot issue browser P01
            return None
