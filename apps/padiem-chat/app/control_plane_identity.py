"""Trusted B62 -> Shared Control Plane identity/session bridge.

B62 keeps its existing Google OAuth, signed compatibility cookie, product user row,
and history/project ownership. Canonical subject identity and canonical auth-session
state are accepted only from an injected server-trusted Control Plane authority.

This module deliberately does not mint canonical subject IDs, accept browser
user/plan assertions, or persist OAuth/bearer credentials.
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
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

PADIEM_CHAT_PRODUCT_ID = "b62"


@dataclass(frozen=True, slots=True)
class IdentityBridgeError(RuntimeError):
    status_code: int
    code: str
    safe_message: str

    def __str__(self) -> str:
        return self.safe_message


@dataclass(frozen=True, slots=True)
class TrustedProductAuthEvidence:
    """Bounded server-side evidence produced after B62 authentication succeeds."""

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
            raise ValueError("product_user_id must be a bounded B62 user identifier")
        if self.provider not in {"google", "password"}:
            raise ValueError("provider must be a reviewed trusted B62 auth provider")
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


class TrustedControlPlaneIdentityAuthority(Protocol):
    """Server-only adapter boundary implemented by Shared Control Plane integration."""

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
        self,
        *,
        tenant_id: str,
        canonical_subject_id: str,
        role: str | None = None,
    ) -> TenantMembership: ...

    def resolve_connector_workspace(self, *, session_id: str) -> Any: ...

    def resolve_connector_context(self, *, session_id: str) -> Any: ...

    def resolve_active_memberships(
        self, *, canonical_subject_id: str
    ) -> tuple[str, ...]: ...

    def resolve_active_tenant_membership(
        self, *, tenant_id: str, canonical_subject_id: str, now: datetime
    ) -> TenantMembership: ...


@dataclass(frozen=True, slots=True)
class BridgedIdentitySession:
    """Validated canonical projection of one existing B62 authenticated session."""

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


def _bridge_error(code: str, message: str, status_code: int = 503) -> IdentityBridgeError:
    return IdentityBridgeError(status_code=status_code, code=code, safe_message=message)


async def ensure_personal_tenant_membership(
    authority: "TrustedControlPlaneIdentityAuthority",
    *,
    subject: CanonicalSubjectRef,
    now: datetime,
) -> str | None:
    """Ensure the canonical subject has its one personal tenant membership.

    Shared by every login bridge. The authority is the only source of
    membership truth; a subject with exactly one membership keeps it, a
    subject with none receives a personal tenant with the OWNER role, and an
    ambiguous projection fails closed. Returns the tenant id when known.
    """

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
            membership = await _maybe_await(
                authority.assign_tenant_membership(
                    tenant_id=tenant_id,
                    canonical_subject_id=subject.subject_id,
                    role=TenantMembershipRole.OWNER.value,
                )
            )
            if (
                not isinstance(membership, TenantMembership)
                or membership.tenant_id != tenant_id
                or membership.canonical_subject_id != subject.subject_id
                or membership.state is not TenantMembershipState.ACTIVE
                or membership.role is not TenantMembershipRole.OWNER
            ):
                raise ValueError("invalid personal tenant owner membership")
            return tenant_id
        if len(memberships) == 1:
            tenant_id = memberships[0]
            try:
                membership = await _maybe_await(
                    authority.resolve_active_tenant_membership(
                        tenant_id=tenant_id,
                        canonical_subject_id=subject.subject_id,
                        now=now,
                    )
                )
            except Exception as exc:
                if getattr(exc, "code", None) != "canonical_tenant_membership_role_missing":
                    raise
                membership = None
            if membership is not None and (
                not isinstance(membership, TenantMembership)
                or membership.tenant_id != tenant_id
                or membership.canonical_subject_id != subject.subject_id
                or membership.state is not TenantMembershipState.ACTIVE
            ):
                raise ValueError("invalid existing personal tenant membership")
            if membership is None or membership.role is None:
                membership = await _maybe_await(
                    authority.assign_tenant_membership(
                        tenant_id=tenant_id,
                        canonical_subject_id=subject.subject_id,
                        role=TenantMembershipRole.OWNER.value,
                    )
                )
                if (
                    not isinstance(membership, TenantMembership)
                    or membership.tenant_id != tenant_id
                    or membership.canonical_subject_id != subject.subject_id
                    or membership.state is not TenantMembershipState.ACTIVE
                    or membership.role is not TenantMembershipRole.OWNER
                ):
                    raise ValueError("invalid personal tenant owner membership")
            return tenant_id
        raise ValueError("ambiguous canonical tenant membership")
    except Exception as exc:
        raise _bridge_error(
            "control_plane_tenant_unavailable",
            "Canonical tenant provisioning is unavailable.",
        ) from exc


async def bridge_verified_canonical_subject(
    authority: "TrustedControlPlaneIdentityAuthority | None",
    *,
    product_user_id: str,
    canonical_subject_id: str,
    authenticated_at: datetime,
    expires_at: datetime,
    ensure_tenant: bool = True,
) -> BridgedIdentitySession:
    """Bind an already-verified canonical subject to one B62 session (#7364).

    The shared login has already proved, through the common auth authority's
    signed access token, that this canonical subject is the caller and that it
    maps to this product user (the reverse lookup that resolved the login).
    This is the same canonical session establishment the Google bridge
    performs, driven by that verified subject instead of provider evidence:
    the authority itself refuses a subject without an active B62 link, derives
    the tenant from server-owned membership, and owns the session id/revision.
    """

    if authority is None:
        raise _bridge_error(
            "control_plane_identity_unavailable",
            "Canonical identity resolution is unavailable.",
        )
    if (
        not isinstance(product_user_id, str)
        or not product_user_id.startswith("usr_")
        or len(product_user_id) > 80
    ):
        raise _bridge_error(
            "invalid_product_auth_evidence",
            "Trusted product authentication evidence is invalid.",
            500,
        )
    if (
        not isinstance(canonical_subject_id, str)
        or not canonical_subject_id.startswith("sub_")
        or len(canonical_subject_id) > 136
    ):
        raise _bridge_error(
            "invalid_product_auth_evidence",
            "Trusted product authentication evidence is invalid.",
            500,
        )
    if (
        not isinstance(authenticated_at, datetime)
        or authenticated_at.tzinfo is None
        or authenticated_at.utcoffset() is None
        or not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
        or expires_at.utcoffset() is None
        or expires_at <= authenticated_at
    ):
        raise _bridge_error(
            "invalid_product_auth_evidence",
            "Trusted product authentication evidence is invalid.",
            500,
        )

    subject = CanonicalSubjectRef(
        subject_type=SubjectType.USER,
        subject_id=canonical_subject_id,
    )
    if ensure_tenant:
        await ensure_personal_tenant_membership(
            authority, subject=subject, now=authenticated_at,
        )
    try:
        session = await _maybe_await(
            authority.establish_auth_session(
                product_id=PADIEM_CHAT_PRODUCT_ID,
                subject=subject,
                authenticated_at=authenticated_at,
                not_after=expires_at,
            )
        )
    except Exception as exc:
        raise _bridge_error(
            "control_plane_session_unavailable",
            "Canonical auth session is unavailable.",
        ) from exc
    if not isinstance(session, AuthSessionSnapshot):
        raise _bridge_error(
            "control_plane_session_invalid",
            "Canonical auth authority returned an invalid session.",
        )
    if session.product_id != PADIEM_CHAT_PRODUCT_ID or session.subject != subject:
        raise _bridge_error(
            "control_plane_session_mismatch",
            "Canonical auth session does not match the authenticated identity.",
            403,
        )
    if session.issued_at < authenticated_at or session.expires_at > expires_at:
        raise _bridge_error(
            "control_plane_session_scope_mismatch",
            "Canonical auth session exceeds the trusted product authentication scope.",
            403,
        )
    if not session.is_active(now=authenticated_at):
        raise _bridge_error(
            "control_plane_session_inactive",
            "Canonical auth session is expired or revoked.",
        )
    return BridgedIdentitySession(
        product_user_id=product_user_id,
        identity_link=ProductIdentityLink(
            product_id=PADIEM_CHAT_PRODUCT_ID,
            product_user_id=product_user_id,
            canonical_subject_id=canonical_subject_id,
            state=IdentityLinkState.ACTIVE,
        ),
        auth_session=session,
    )


async def bridge_trusted_product_auth(
    authority: TrustedControlPlaneIdentityAuthority | None,
    evidence: TrustedProductAuthEvidence,
    *,
    now: datetime | None = None,
    ensure_personal_tenant: bool = False,
) -> BridgedIdentitySession:
    """Resolve canonical identity/session from trusted server authentication evidence.

    The injected authority owns canonical identity/account-linking rules and
    canonical session IDs/revisions. B62 only validates that returned authority is
    bound to the already-authenticated product user and cannot outlive the product
    authentication evidence that established it.
    """

    if authority is None:
        raise _bridge_error(
            "control_plane_identity_unavailable",
            "Canonical identity resolution is unavailable.",
        )
    if not isinstance(evidence, TrustedProductAuthEvidence):
        raise _bridge_error(
            "invalid_product_auth_evidence",
            "Trusted product authentication evidence is invalid.",
            500,
        )

    try:
        link = await _maybe_await(
            authority.resolve_or_create_product_link(
                product_id=PADIEM_CHAT_PRODUCT_ID,
                product_user_id=evidence.product_user_id,
                auth_provider=evidence.provider,
                provider_subject=evidence.provider_subject,
            )
        )
    except Exception as exc:
        raise _bridge_error(
            "control_plane_identity_unavailable",
            "Canonical identity resolution is unavailable.",
        ) from exc

    if not isinstance(link, ProductIdentityLink):
        raise _bridge_error(
            "control_plane_identity_invalid",
            "Canonical identity authority returned an invalid product link.",
        )
    if (
        link.product_id != PADIEM_CHAT_PRODUCT_ID
        or link.product_user_id != evidence.product_user_id
        or link.state is not IdentityLinkState.ACTIVE
    ):
        raise _bridge_error(
            "control_plane_identity_mismatch",
            "Canonical identity does not match the authenticated product user.",
            403,
        )

    subject = CanonicalSubjectRef(
        subject_type=SubjectType.USER,
        subject_id=link.canonical_subject_id,
    )

    if ensure_personal_tenant:
        await ensure_personal_tenant_membership(
            authority, subject=subject, now=evidence.authenticated_at,
        )

    try:
        session = await _maybe_await(
            authority.establish_auth_session(
                product_id=PADIEM_CHAT_PRODUCT_ID,
                subject=subject,
                authenticated_at=evidence.authenticated_at,
                not_after=evidence.expires_at,
            )
        )
    except Exception as exc:
        raise _bridge_error(
            "control_plane_session_unavailable",
            "Canonical auth session is unavailable.",
        ) from exc

    if not isinstance(session, AuthSessionSnapshot):
        raise _bridge_error(
            "control_plane_session_invalid",
            "Canonical auth authority returned an invalid session.",
        )
    if session.product_id != PADIEM_CHAT_PRODUCT_ID or session.subject != subject:
        raise _bridge_error(
            "control_plane_session_mismatch",
            "Canonical auth session does not match the authenticated identity.",
            403,
        )
    if session.issued_at < evidence.authenticated_at or session.expires_at > evidence.expires_at:
        raise _bridge_error(
            "control_plane_session_scope_mismatch",
            "Canonical auth session exceeds the trusted product authentication scope.",
            403,
        )

    effective_now = now if now is not None else datetime.now(timezone.utc)
    if effective_now.tzinfo is None or effective_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not session.is_active(now=effective_now):
        raise _bridge_error(
            "control_plane_session_inactive",
            "Canonical auth session is expired or revoked.",
            401,
        )

    return BridgedIdentitySession(
        product_user_id=evidence.product_user_id,
        identity_link=link,
        auth_session=session,
    )


def require_active_canonical_session(
    bridged: BridgedIdentitySession,
    *,
    now: datetime | None = None,
) -> CanonicalSubjectRef:
    """Fail closed when a previously resolved canonical session is no longer active."""

    if not isinstance(bridged, BridgedIdentitySession):
        raise _bridge_error(
            "control_plane_session_invalid",
            "Canonical auth session is invalid.",
            401,
        )
    effective_now = now if now is not None else datetime.now(timezone.utc)
    if effective_now.tzinfo is None or effective_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not bridged.auth_session.is_active(now=effective_now):
        raise _bridge_error(
            "control_plane_session_inactive",
            "Canonical auth session is expired or revoked.",
            401,
        )
    return bridged.canonical_subject
