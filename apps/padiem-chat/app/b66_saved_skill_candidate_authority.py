"""#3186 STEP 3-B — audited host-only B66 candidate decision authority.

A verified Google staff session proves identity, not an independent approval
capability or a canonical customer tenant. The host must inject BOTH a reviewed
grant issuer and canonical target resolver; the Worker currently injects
neither. No user-controlled parameters can mint a grant or resolve a target.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

from .auth_routes import auth_ready, current_user_id
from .b66_member_admin import D1B66MemberAdminStore
from .b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from .b66_saved_skill_candidate_store import (
    SavedQuoteSkillCandidateStore,
    validate_candidate_row_id,
)





class D1B66SavedQuoteSkillCandidateOperatorAuthority:
    """Adapts real server authorities, never creates its own grants."""

    def __init__(
        self,
        *,
        member_admin_store: D1B66MemberAdminStore,
        candidate_store: SavedQuoteSkillCandidateStore | None,
        trusted_review_grant_issuer: Callable[..., Any] | None = None,
        canonical_target_resolver: Callable[..., Any] | None = None,
        max_grant_minutes: int = 15,
    ) -> None:
        if not isinstance(member_admin_store, D1B66MemberAdminStore):
            raise ValueError("verified B66 member admin store is required")
        if not isinstance(max_grant_minutes, int) or not (1 <= max_grant_minutes <= 15):
            raise ValueError("grant duration must be 1-15 minutes")
        self._member_admin_store = member_admin_store
        self._candidate_store = candidate_store
        self._trusted_review_grant_issuer = trusted_review_grant_issuer
        self._canonical_target_resolver = canonical_target_resolver
        self._max_grant_minutes = max_grant_minutes

    async def _verified_admin_subject(self, request: Any) -> str | None:
        if not auth_ready(request):
            return None
        try:
            uid = current_user_id(request)
        except Exception:
            return None
        if not isinstance(uid, str) or not uid:
            return None
        try:
            authorized = self._member_admin_store.is_google_admin(uid)
            if inspect.isawaitable(authorized):
                authorized = await authorized
        except Exception:
            return None
        return uid if authorized is True else None

    async def issue_operator_grant(self, request: Any) -> TrustedB66ProvisioningGrant | None:
        uid = await self._verified_admin_subject(request)
        issuer = self._trusted_review_grant_issuer
        if uid is None or not callable(issuer):
            return None
        try:
            grant = issuer(
                request=request,
                operator_user_id=uid,
                action=B66ProvisioningAction.REVIEW_CANDIDATE,
            )
            if inspect.isawaitable(grant):
                grant = await grant
            now = datetime.now(timezone.utc)
            if not isinstance(grant, TrustedB66ProvisioningGrant):
                return None
            if grant.operator_subject != CanonicalSubjectRef(SubjectType.USER, uid):
                return None
            if not grant.is_active(now=now) or not grant.allows(B66ProvisioningAction.REVIEW_CANDIDATE):
                return None
            if grant.expires_at - grant.issued_at > timedelta(minutes=self._max_grant_minutes):
                return None
            return grant
        except Exception:
            return None

    async def resolve_operator_target(self, request: Any, candidate_id: str) -> ResolvedB66ProvisioningTarget | None:
        if await self._verified_admin_subject(request) is None:
            return None
        resolver = self._canonical_target_resolver
        store = self._candidate_store
        if not callable(resolver) or store is None:
            return None
        try:
            row_id = validate_candidate_row_id(candidate_id)
            target = resolver(request=request, candidate_id=row_id)
            if inspect.isawaitable(target):
                target = await target
            if not isinstance(target, ResolvedB66ProvisioningTarget):
                return None
            # This private D1 read is keyed by the *canonical* owner+workspace.
            # A public operator projection lacks workspace and is never used.
            envelope = store.read_candidate_envelope(
                user_id=target.user_id,
                workspace_id=target.workspace_id,
                candidate_id=row_id,
            )
            if inspect.isawaitable(envelope):
                envelope = await envelope
        except Exception:
            return None
        if not isinstance(envelope, dict) or envelope.get("status") != "pending":
            return None
        if envelope.get("candidate_id") != row_id:
            return None
        return target
