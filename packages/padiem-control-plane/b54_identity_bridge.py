"""Trusted B54 (padiem-claw) → Shared Control Plane identity/session bridge.

B54 keeps its existing server-trusted tenant-based automation identity.
Canonical subject identity and canonical auth-session state are accepted only
from an injected server-trusted Control Plane authority (CONTROL_PLANE_IDENTITY
service binding).

This module deliberately does **not**:

* mint canonical subject IDs;
* accept browser user/plan assertions;
* persist OAuth or bearer credentials;
* share session state with B62 — every session is product-scoped at the
  authority level and the Engine firewall (``auth_session.product_id == app_id``)
  rejects cross-product sessions unconditionally.

Fail-closed chain; no step is optional::

    TrustedB54ServerAuthEvidence (server-produced only)
        → resolve_or_create_product_link  (product_id="b54-padiem-claw")
        → IdentityLinkState.ACTIVE check
        → CanonicalSubjectRef
        → establish_auth_session          (product_id="b54-padiem-claw")
        → session.product_id == "b54-padiem-claw" guard
        → session.subject == subject guard
        → B54BridgedIdentitySession       (bounded, mints no external authority)
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from padiem_control_plane import (
    AuthSessionSnapshot,
    CanonicalSubjectRef,
    IdentityLinkState,
    ProductIdentityLink,
    SubjectType,
)

B54_PRODUCT_ID = "b54-padiem-claw"

__all__ = [
    "B54_PRODUCT_ID",
    "B54BridgedIdentitySession",
    "B54IdentityBridgeError",
    "TrustedB54ControlPlaneIdentityAuthority",
    "TrustedB54ServerAuthEvidence",
    "bridge_trusted_b54_server_auth",
    "require_active_b54_canonical_session",
]


@dataclass(frozen=True, slots=True)
class B54IdentityBridgeError(RuntimeError):
    status_code: int
    code: str
    safe_message: str

    def __str__(self) -> str:
        return self.safe_message


@dataclass(frozen=True, slots=True)
class TrustedB54ServerAuthEvidence:
    """Bounded server-side evidence produced after B54 server authentication succeeds.

    Only server-trusted code may construct this dataclass.  The ``product_user_id``
    must be a bounded server-assigned identifier — never a browser-supplied value.
    The ``provider`` must be ``"password"`` (the only reviewed B54 auth provider;
    OAuth is B62-only).
    """

    product_user_id: str
    provider: str
    provider_subject: str
    authenticated_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_user_id, str)
            or not self.product_user_id.startswith("usr_")
            or len(self.product_user_id) > 80
        ):
            raise ValueError("product_user_id must be a bounded B54 server-assigned identifier")
        if self.provider not in {"password"}:
            raise ValueError(
                "provider must be 'password' — the only reviewed B54 server auth provider"
            )
        if (
            not isinstance(self.provider_subject, str)
            or not self.provider_subject.strip()
            or len(self.provider_subject) > 255
        ):
            raise ValueError("provider_subject must be a bounded trusted provider subject")
        for name, value in (
            ("authenticated_at", self.authenticated_at),
            ("expires_at", self.expires_at),
        ):
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.expires_at <= self.authenticated_at:
            raise ValueError("expires_at must be later than authenticated_at")


class TrustedB54ControlPlaneIdentityAuthority(Protocol):
    """Server-only adapter boundary implemented by Shared Control Plane integration.

    Identical protocol surface to the B62 ``TrustedControlPlaneIdentityAuthority``
    but consumed with ``product_id=B54_PRODUCT_ID`` only.
    """

    def resolve_or_create_product_link(
        self,
        *,
        product_id: str,
        product_user_id: str,
        auth_provider: str,
        provider_subject: str,
    ) -> ProductIdentityLink: ...

    def establish_auth_session(
        self,
        *,
        product_id: str,
        subject: CanonicalSubjectRef,
        authenticated_at: datetime,
        not_after: datetime,
    ) -> AuthSessionSnapshot: ...

    def create_tenant(self) -> str: ...

    def assign_tenant_membership(
        self, *, tenant_id: str, canonical_subject_id: str
    ) -> None: ...

    def resolve_active_memberships(
        self, *, canonical_subject_id: str
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class B54BridgedIdentitySession:
    """Validated canonical projection of one existing B54 authenticated session."""

    product_user_id: str
    identity_link: ProductIdentityLink
    auth_session: AuthSessionSnapshot

    @property
    def canonical_subject(self) -> CanonicalSubjectRef:
        return self.auth_session.subject


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _bridge_error(code: str, message: str, status_code: int = 503) -> B54IdentityBridgeError:
    return B54IdentityBridgeError(
        status_code=status_code, code=code, safe_message=message
    )


async def bridge_trusted_b54_server_auth(
    authority: TrustedB54ControlPlaneIdentityAuthority | None,
    evidence: TrustedB54ServerAuthEvidence,
    *,
    now: datetime | None = None,
    ensure_personal_tenant: bool = False,
) -> B54BridgedIdentitySession:
    """Resolve canonical identity/session from trusted B54 server authentication evidence.

    The injected authority owns canonical identity/account-linking rules and
    canonical session IDs/revisions.  B54 validates that the returned authority
    is bound to the already-authenticated product user and cannot outlive the
    server authentication evidence that established it.

    Cross-product isolation is enforced by two independent layers:

    1. This bridge hardcodes ``product_id=B54_PRODUCT_ID`` — it can never mint
       a B62 session.
    2. The Engine ``AuthSessionScopeAuthority`` enforces
       ``auth_session.product_id == app_id`` — a B62 session is rejected when
       the requesting app is B54, and vice versa.
    """

    if authority is None:
        raise _bridge_error(
            "b54_control_plane_identity_unavailable",
            "B54 canonical identity resolution is unavailable.",
        )
    if not isinstance(evidence, TrustedB54ServerAuthEvidence):
        raise _bridge_error(
            "b54_invalid_server_auth_evidence",
            "Trusted B54 server authentication evidence is invalid.",
            500,
        )

    try:
        link = await _maybe_await(
            authority.resolve_or_create_product_link(
                product_id=B54_PRODUCT_ID,
                product_user_id=evidence.product_user_id,
                auth_provider=evidence.provider,
                provider_subject=evidence.provider_subject,
            )
        )
    except Exception as exc:
        raise _bridge_error(
            "b54_control_plane_identity_unavailable",
            "B54 canonical identity resolution is unavailable.",
        ) from exc

    if not isinstance(link, ProductIdentityLink):
        raise _bridge_error(
            "b54_control_plane_identity_invalid",
            "Canonical identity authority returned an invalid B54 product link.",
        )
    if (
        link.product_id != B54_PRODUCT_ID
        or link.product_user_id != evidence.product_user_id
        or link.state is not IdentityLinkState.ACTIVE
    ):
        raise _bridge_error(
            "b54_control_plane_identity_mismatch",
            "Canonical identity does not match the authenticated B54 server user.",
            403,
        )

    subject = CanonicalSubjectRef(
        subject_type=SubjectType.USER,
        subject_id=link.canonical_subject_id,
    )

    if ensure_personal_tenant:
        try:
            memberships = await _maybe_await(
                authority.resolve_active_memberships(
                    canonical_subject_id=subject.subject_id,
                )
            )
            if not isinstance(memberships, tuple) or not all(
                isinstance(item, str) and item for item in memberships
            ):
                raise ValueError("invalid tenant membership projection")
            if len(memberships) == 0:
                tenant_id = await _maybe_await(authority.create_tenant())
                if not isinstance(tenant_id, str) or not tenant_id:
                    raise ValueError("invalid canonical tenant")
                await _maybe_await(
                    authority.assign_tenant_membership(
                        tenant_id=tenant_id,
                        canonical_subject_id=subject.subject_id,
                    )
                )
            elif len(memberships) > 1:
                raise ValueError("ambiguous canonical tenant membership")
        except Exception as exc:
            raise _bridge_error(
                "b54_control_plane_tenant_unavailable",
                "B54 canonical tenant provisioning is unavailable.",
            ) from exc

    try:
        session = await _maybe_await(
            authority.establish_auth_session(
                product_id=B54_PRODUCT_ID,
                subject=subject,
                authenticated_at=evidence.authenticated_at,
                not_after=evidence.expires_at,
            )
        )
    except Exception as exc:
        raise _bridge_error(
            "b54_control_plane_session_unavailable",
            "B54 canonical auth session is unavailable.",
        ) from exc

    if not isinstance(session, AuthSessionSnapshot):
        raise _bridge_error(
            "b54_control_plane_session_invalid",
            "Canonical auth authority returned an invalid B54 session.",
        )
    if session.product_id != B54_PRODUCT_ID or session.subject != subject:
        raise _bridge_error(
            "b54_control_plane_session_mismatch",
            "B54 canonical auth session does not match the authenticated identity.",
            403,
        )
    if (
        session.issued_at < evidence.authenticated_at
        or session.expires_at > evidence.expires_at
    ):
        raise _bridge_error(
            "b54_control_plane_session_scope_mismatch",
            "B54 canonical auth session exceeds the trusted server authentication scope.",
            403,
        )

    effective_now = now if now is not None else datetime.now(timezone.utc)
    if effective_now.tzinfo is None or effective_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not session.is_active(now=effective_now):
        raise _bridge_error(
            "b54_control_plane_session_inactive",
            "B54 canonical auth session is expired or revoked.",
            401,
        )

    return B54BridgedIdentitySession(
        product_user_id=evidence.product_user_id,
        identity_link=link,
        auth_session=session,
    )


def require_active_b54_canonical_session(
    bridged: B54BridgedIdentitySession,
    *,
    now: datetime | None = None,
) -> CanonicalSubjectRef:
    """Fail closed when a previously resolved B54 canonical session is no longer active."""

    if not isinstance(bridged, B54BridgedIdentitySession):
        raise _bridge_error(
            "b54_control_plane_session_invalid",
            "B54 canonical auth session is invalid.",
            401,
        )
    effective_now = now if now is not None else datetime.now(timezone.utc)
    if effective_now.tzinfo is None or effective_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not bridged.auth_session.is_active(now=effective_now):
        raise _bridge_error(
            "b54_control_plane_session_inactive",
            "B54 canonical auth session is expired or revoked.",
            401,
        )
    return bridged.canonical_subject
