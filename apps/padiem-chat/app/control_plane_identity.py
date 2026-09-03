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
        if self.provider != "google":
            raise ValueError("provider must be the trusted B62 Google auth provider")
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


async def bridge_trusted_product_auth(
    authority: TrustedControlPlaneIdentityAuthority | None,
    evidence: TrustedProductAuthEvidence,
    *,
    now: datetime | None = None,
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
