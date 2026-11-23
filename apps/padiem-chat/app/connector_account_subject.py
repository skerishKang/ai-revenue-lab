"""Request-local proof from existing authentication, never request identity fields."""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import logging
import time
from typing import Any

from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

_SEAL = object()
_PRODUCTS = frozenset({"b62", "b54-padiem-claw"})
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class VerifiedConnectorSubject:
    """Only the existing verified-login producer can issue this capability."""

    product_id: str
    subject_id: str
    expires_at: float
    session_id: str | None
    tenant_id: str | None

    def __init__(self, *, _seal, product_id, subject_id, expires_at,
                 session_id=None, tenant_id=None):
        if (_seal is not _SEAL or product_id not in _PRODUCTS
                or not isinstance(subject_id, str) or not subject_id.startswith("sub_")
                or type(expires_at) not in {int, float}
                or not math.isfinite(expires_at) or expires_at <= time.time()):
            raise ValueError("verified_connector_subject_required")
        try:
            CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject_id)
        except Exception:
            raise ValueError("verified_connector_subject_required") from None
        for key, value in (("product_id", product_id), ("subject_id", subject_id),
                           ("expires_at", expires_at), ("session_id", session_id), ("tenant_id", tenant_id)):
            object.__setattr__(self, key, value)

    def __repr__(self):
        return "VerifiedConnectorSubject()"


@dataclass(slots=True, repr=False)
class _RequestProof:
    subject: VerifiedConnectorSubject | None = None
    sessions: dict[str, AuthSessionSnapshot] = field(default_factory=dict)
    key_mode: bool = False
    pc_scope_tenant_only: bool = False


_current: ContextVar[_RequestProof | None] = ContextVar("connector_account_proof", default=None)


class ConnectorAccountShadowContextMiddleware:
    """Installed only by the explicit default-off settings; reset on every exit.

    ``key_mode`` is the account-key switch: when it is on, PC call sites answer
    from the account key (see ``connector_account_shadow.pc_connector_read``)
    instead of the session key; the comparison context is installed either way.
    ``pc_scope_tenant_only`` is the separate PC-scope switch: when it is on the
    connector-scope verdict follows the single tenant check; the cross-check
    comparison is still recorded.
    """

    def __init__(self, app, *, key_mode: bool = False,
                 pc_scope_tenant_only: bool = False):
        self.app = app
        self.key_mode = key_mode is True
        self.pc_scope_tenant_only = pc_scope_tenant_only is True

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _current.set(_RequestProof(
            key_mode=self.key_mode,
            pc_scope_tenant_only=self.pc_scope_tenant_only,
        ))
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)


def shadow_context_enabled() -> bool:
    return _current.get() is not None


def account_key_mode_enabled() -> bool:
    proof = _current.get()
    return proof is not None and proof.key_mode is True


def pc_scope_tenant_only_enabled() -> bool:
    proof = _current.get()
    return proof is not None and proof.pc_scope_tenant_only is True


def detach_shadow_request() -> None:
    """Background comparison keeps only its immutable captured proof."""
    _current.set(None)


def _remember_verified_login(verified: Any, user_id: Any) -> None:
    """Called only AFTER signature verification and existing user/deny checks.

    This is an authentication producer hook, not a raw-account constructor for
    callers. Read APIs accept only its sealed output and never claim a tenant.
    """
    proof = _current.get()
    if proof is None:
        return
    proof.subject = None
    try:
        if not isinstance(verified, dict) or not isinstance(user_id, str) or not user_id:
            return
        if not isinstance(verified.get("sessionId"), str) or not verified["sessionId"]:
            return
        proof.subject = VerifiedConnectorSubject(_seal=_SEAL, product_id="b62",
            subject_id=verified.get("accountId"), expires_at=verified.get("expiresAt"))
    except Exception:
        # Observation must never change authentication's established verdict.
        proof.subject = None


def forget_verified_login() -> None:
    proof = _current.get()
    if proof is not None:
        proof.subject = None


def remember_connector_session(session):
    """Keep existing authority metadata, including cache hits, without a new read."""
    proof = _current.get()
    if proof is not None and isinstance(session, AuthSessionSnapshot):
        proof.sessions[session.session_id] = session
    return session


def subject_for_connector_read(session_id: str, method: str) -> VerifiedConnectorSubject | None:
    proof = _current.get()
    if proof is None or proof.subject is None:
        return None
    source = proof.subject
    if source.expires_at <= time.time():
        return None
    session = proof.sessions.get(session_id)
    if session is None:
        # Only these two RPCs pin the product to b62 in the authority contract.
        # The enrollment RPCs review two products and must never guess which.
        return source if method in {"workspace", "context"} else None
    if session.subject.subject_id != source.subject_id or session.product_id not in _PRODUCTS:
        return None
    try:
        return VerifiedConnectorSubject(_seal=_SEAL, product_id=session.product_id,
            subject_id=source.subject_id, expires_at=source.expires_at,
            session_id=session.session_id, tenant_id=session.tenant_id)
    except Exception:
        return None


async def subject_from_authenticated_owner_record(request, session: AuthSessionSnapshot):
    """Unwired extension for an already authenticated server-owned record.

    The subject is read from the account database and matched to the existing
    verified session. No account, tenant or product string is accepted from a
    background caller. This extension still requires an active authenticated
    request; unattended caller migration remains separate work.
    """
    from .session_revocation_guard import session_verdict
    from .history import _row_to_dict
    verdict = session_verdict(request)
    if (not shadow_context_enabled() or verdict is None or not verdict.authenticated
            or not isinstance(session, AuthSessionSnapshot)
            or verdict.canonical_session_id != session.session_id):
        raise ValueError("verified_connector_subject_required")
    db = request.app.state.account_data_db
    row = _row_to_dict(await db.prepare("SELECT provider_subject FROM users WHERE id = ?")
                      .bind(verdict.user_id).first())
    if (not row or row.get("provider_subject") != "shared:" + session.subject.subject_id
            or not session.is_active(now=datetime.now(timezone.utc))):
        raise ValueError("verified_connector_subject_required")
    return VerifiedConnectorSubject(_seal=_SEAL, product_id=session.product_id,
        subject_id=session.subject.subject_id, expires_at=session.expires_at.timestamp(),
        session_id=session.session_id, tenant_id=session.tenant_id)


@asynccontextmanager
async def maintenance_owner_context(app, user_id):
    """Only the Chat host's server-known paired owner; no browser proof minted.

    Resolve current B54 authority, reverse B62 link and active membership
    without the request cache. Bind a short-lived subject to this task only.
    """
    from padiem_control_plane.b54_identity_bridge import (
        B54IdentityBridgeError, resolve_current_b54_canonical_session,
    )
    from padiem_control_plane.tenants import TenantMembership, TenantMembershipState
    from .history import _row_to_dict, _user_id
    stage = "b54_session"
    try:
        authority = app.state.control_plane_identity_authority
        uncached = getattr(authority, "maintenance_uncached_authority", None)
        if callable(uncached):
            authority = uncached()
        now = datetime.now(timezone.utc)
        session = (await resolve_current_b54_canonical_session(authority, user_id, now=now)).auth_session
        subject = session.subject.subject_id
        stage = "b62_reverse_link"
        # The Cloudflare adapter itself has a process cache beneath the outer
        # request cache. Maintenance authority must bypass both caches.
        linked = await authority.resolve_product_user_for_subject_uncached(
            product_id="b62", canonical_subject_id=subject)
        if linked != user_id:
            raise ValueError("maintenance_owner_unresolved")
        stage = "membership"
        membership = await authority.resolve_active_tenant_membership(
            tenant_id=session.tenant_id, canonical_subject_id=subject, now=now)
        if (not isinstance(membership, TenantMembership)
                or membership.tenant_id != session.tenant_id
                or membership.canonical_subject_id != subject
                or membership.state is not TenantMembershipState.ACTIVE or membership.role is None):
            raise ValueError("maintenance_owner_unresolved")
        stage = "provider_subject"
        row = _row_to_dict(await app.state.account_data_db.prepare(
            "SELECT auth_provider, provider_subject FROM users WHERE id=?").bind(user_id).first())
        provider = row.get("provider_subject") if row else None
        b62_session = None
        if provider != "shared:" + subject:
            # Existing Google accounts keep their original deterministic
            # product user id (#7078). They are not shared: rows. Require
            # both the exact legacy binding and a fresh, same-tenant canonical
            # B62 session; never treat a local row alone as authentication.
            if (not row or row.get("auth_provider") != "google"
                    or not isinstance(provider, str) or not provider
                    or provider.startswith(("shared:", "password:"))
                    or _user_id(provider) != user_id):
                raise ValueError("maintenance_owner_unresolved")
            stage = "b62_session"
            b62_session = await authority.resolve_current_auth_session(
                product_id="b62", product_user_id=user_id)
            if (not isinstance(b62_session, AuthSessionSnapshot)
                    or b62_session.product_id != "b62"
                    or b62_session.subject.subject_type is not SubjectType.USER
                    or b62_session.subject.subject_id != subject
                    or b62_session.tenant_id != session.tenant_id):
                raise ValueError("maintenance_owner_unresolved")
        stage = "session_expiry"
        checked_at = datetime.now(timezone.utc)
        if (not session.is_active(now=checked_at)
                or (b62_session is not None and not b62_session.is_active(now=checked_at))):
            raise ValueError("maintenance_owner_unresolved")
        stage = "proof"
        proof = _RequestProof(
            subject=VerifiedConnectorSubject(_seal=_SEAL, product_id=session.product_id,
                subject_id=subject, expires_at=min(session.expires_at, b62_session.expires_at
                    if b62_session is not None else session.expires_at).timestamp(),
                session_id=session.session_id, tenant_id=session.tenant_id),
            sessions={session.session_id: session}, key_mode=True)
    except Exception as exc:
        if (stage == "b54_session" and isinstance(exc, B54IdentityBridgeError)
                and exc.code == "b54_control_plane_session_inactive"):
            stage = "session_expiry"
        # Labels are chosen only by this function, not by RPC error text.
        logger.warning("pc_maintenance_owner_context outcome=denied stage=%s", stage)
        raise ValueError("maintenance_owner_unresolved") from None
    token = _current.set(proof)
    try:
        yield session
    finally:
        _current.reset(token)
