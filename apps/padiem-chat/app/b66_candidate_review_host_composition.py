"""#5094 — host composition for B66 Saved Quote Skill candidate review.

The review contract in ``b66_saved_skill_candidate_authority`` requires two
server-trusted inputs:

* a short-lived grant projected from a verified operator identity;
* a canonical target account resolved for the submitted candidate.

Neither may come from the browser. This module composes both from authorities
that already exist in the PADIEM Worker:

* ``D1B66MemberAdminStore`` — the same verified Google administrator used by
  the B66 admin routes; a grant is a bounded projection of that identity, not a
  second admin authority;
* ``D1SavedQuoteSkillCandidateStore`` — the server-recorded owner scope of the
  candidate, never a request field;
* ``resolve_refreshed_session`` — the shared Control Plane canonical session
  contract, used to obtain the target tenant and canonical subject.

No table, migration, admin class or browser route is added. Missing bindings
keep the decision route fail-closed (503); nothing here fabricates a grant,
tenant or canonical subject.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

from .b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from .b66_saved_skill_candidate_store import (
    CANDIDATE_STATUS_PENDING,
    validate_candidate_row_id,
)
from .control_plane_identity_shadow import resolve_refreshed_session

_MAX_GRANT_MINUTES = 15
_DEFAULT_GRANT_MINUTES = 5
_AUTHORITY_REF = "authority:b66:verified-google-admin"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class B66VerifiedAdminReviewGrantIssuer:
    """Project a verified B66 Google administrator into a bounded review grant.

    The caller (``D1B66SavedQuoteSkillCandidateOperatorAuthority``) only invokes
    this after its own admin check. The issuer re-checks the same server-side
    membership store so a grant is never minted from a request payload, an
    e-mail string or a cached role claim.
    """

    def __init__(
        self,
        *,
        member_admin_store: Any,
        grant_minutes: int = _DEFAULT_GRANT_MINUTES,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if member_admin_store is None:
            raise ValueError("verified B66 member admin store is required")
        if (
            isinstance(grant_minutes, bool)
            or not isinstance(grant_minutes, int)
            or not (1 <= grant_minutes <= _MAX_GRANT_MINUTES)
        ):
            raise ValueError("grant duration must be 1-15 minutes")
        self._member_admin_store = member_admin_store
        self._grant_minutes = grant_minutes
        self._now = now or _utc_now

    async def __call__(
        self,
        *,
        request: Any,
        operator_user_id: str,
        action: B66ProvisioningAction,
    ) -> TrustedB66ProvisioningGrant | None:
        if action is not B66ProvisioningAction.REVIEW_CANDIDATE:
            return None
        if not isinstance(operator_user_id, str) or not operator_user_id:
            return None
        verifier = getattr(self._member_admin_store, "is_google_admin", None)
        if not callable(verifier):
            return None
        try:
            allowed = verifier(operator_user_id)
            if inspect.isawaitable(allowed):
                allowed = await allowed
        except Exception:
            return None
        if allowed is not True:
            return None
        try:
            subject = CanonicalSubjectRef(SubjectType.USER, operator_user_id)
        except Exception:
            return None
        now = self._now()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            return None
        try:
            return TrustedB66ProvisioningGrant(
                grant_ref="b66rgrant_" + uuid.uuid4().hex,
                operator_subject=subject,
                authority_ref=_AUTHORITY_REF,
                allowed_actions=(B66ProvisioningAction.REVIEW_CANDIDATE,),
                issued_at=now,
                expires_at=now + timedelta(minutes=self._grant_minutes),
            )
        except Exception:
            return None


class B66CanonicalCandidateTargetResolver:
    """Resolve the candidate's server-recorded owner through canonical identity.

    The candidate row supplies the owner user/workspace that the submission
    route resolved from the customer session. The current tenant and canonical
    subject come from the shared Control Plane refresh contract. The stored
    workspace must equal the canonical tenant, so a legacy or stale scope is
    refused rather than approved under a guessed tenant.
    """

    def __init__(
        self,
        *,
        candidate_store: Any,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if candidate_store is None:
            raise ValueError("candidate store is required")
        self._candidate_store = candidate_store
        self._now = now or _utc_now

    async def __call__(
        self,
        *,
        request: Any,
        candidate_id: str,
    ) -> ResolvedB66ProvisioningTarget | None:
        try:
            row_id = validate_candidate_row_id(candidate_id)
        except Exception:
            return None

        reader = getattr(self._candidate_store, "read_candidate_scope", None)
        if not callable(reader):
            return None
        try:
            scope = reader(candidate_id=row_id)
            if inspect.isawaitable(scope):
                scope = await scope
        except Exception:
            return None
        if not isinstance(scope, dict):
            return None
        if scope.get("candidate_id") != row_id:
            return None
        if scope.get("status") != CANDIDATE_STATUS_PENDING:
            return None
        user_id = scope.get("user_id")
        workspace_id = scope.get("workspace_id")
        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(workspace_id, str) or not workspace_id:
            return None

        state = getattr(getattr(request, "app", None), "state", None)
        shadow_store = getattr(state, "identity_shadow_store", None)
        authority = getattr(state, "control_plane_identity_authority", None)
        if shadow_store is None or authority is None:
            return None
        try:
            session = await resolve_refreshed_session(
                authority=authority,
                store=shadow_store,
                product_user_id=user_id,
                now=self._now(),
            )
        except Exception:
            return None
        tenant_id = getattr(session, "tenant_id", None)
        subject = getattr(session, "subject", None)
        subject_id = getattr(subject, "subject_id", None)
        if not isinstance(tenant_id, str) or not tenant_id:
            return None
        if not isinstance(subject_id, str) or not subject_id:
            return None
        if workspace_id != tenant_id:
            return None
        try:
            return ResolvedB66ProvisioningTarget(
                user_id=user_id,
                workspace_id=workspace_id,
                tenant_id=tenant_id,
                canonical_subject_id=subject_id,
            )
        except Exception:
            return None


def build_b66_candidate_review_host(
    *,
    member_admin_store: Any,
    candidate_store: Any,
    grant_minutes: int = _DEFAULT_GRANT_MINUTES,
) -> tuple[B66VerifiedAdminReviewGrantIssuer, B66CanonicalCandidateTargetResolver] | None:
    """Compose both review authorities, or nothing when a real input is absent."""
    if member_admin_store is None or candidate_store is None:
        return None
    try:
        return (
            B66VerifiedAdminReviewGrantIssuer(
                member_admin_store=member_admin_store,
                grant_minutes=grant_minutes,
            ),
            B66CanonicalCandidateTargetResolver(candidate_store=candidate_store),
        )
    except ValueError:
        return None
