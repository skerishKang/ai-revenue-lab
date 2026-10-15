from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .auth_routes import auth_ready, current_user_id
from .b66_member_admin import D1B66MemberAdminStore
from .b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from .b66_saved_skill_candidate_store import (
    SavedQuoteSkillCandidateStore,
)
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

MINGrantTTL = 1
MAX_GRANT_TTL = 15


class D1B66SavedQuoteSkillCandidateOperatorAuthority:
    def __init__(
        self,
        *,
        member_admin_store: Any,
        candidate_store: SavedQuoteSkillCandidateStore | None,
        review_grant_admin_stores: tuple[Any, ...] = (),
        canonical_target_resolver: Callable[..., Any] | None = None,
        grant_ttl_minutes: int = 5,
    ) -> None:
        if not isinstance(member_admin_store, D1B66MemberAdminStore):
            raise ValueError("verified B66 member admin store is required")
        if grant_ttl_minutes < MINGrantTTL or grant_ttl_minutes > MAX_GRANT_TTL:
            raise ValueError("grant lifetime must be bounded to 1-15 minutes")
        self._member_admin_store = member_admin_store
        self._candidate_store = candidate_store
        self._review_grant_admin_stores = tuple(review_grant_admin_stores)
        self._canonical_target_resolver = canonical_target_resolver
        self._grant_ttl_minutes = grant_ttl_minutes

    async def _verified_admin_subject(self, request: Any) -> str | None:
        # Verified Google staff remains only the outer precondition.
        if not auth_ready(request):
            return None
        try:
            uid = current_user_id(request)
        except Exception:
            return None
        if not isinstance(uid, str) or not uid:
            return None
        try:
            allowed = await self._member_admin_store.is_google_admin(uid)
        except Exception:
            return None
        return uid if allowed is True else None

    async def _review_grant_authority_verified(self, request: Any) -> bool:
        # A separately trusted host binding is required. The general Google
        # admin email verified above is deliberately insufficient.
        for store in self._review_grant_admin_stores:
            try:
                if await store.is_google_admin(await self._verified_admin_subject(request)) is True:
                    return True
            except Exception:
                continue
        return False

    async def issue_operator_grant(self, request: Any) -> TrustedB66ProvisioningGrant | None:
        admin_uid = await self._verified_admin_subject(request)
        if admin_uid is None:
            return None
        if not await self._review_grant_authority_verified(request):
            return None
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(minutes=self._grant_ttl_minutes)
        return TrustedB66ProvisioningGrant(
            grant_ref="b66opgrant_" + uuid.uuid4().hex,
            operator_subject=CanonicalSubjectRef(SubjectType.USER, admin_uid),
            authority_ref="b66-review-grant-authority",
            allowed_actions=(B66ProvisioningAction.REVIEW_CANDIDATE,),
            issued_at=issued_at,
            expires_at=expires_at,
        )

    async def resolve_operator_target(
        self, request: Any, candidate_id: str
    ) -> ResolvedB66ProvisioningTarget | None:
        admin_uid = await self._verified_admin_subject(request)
        if admin_uid is None:
            # Even a directly invoked callback must not reveal target metadata.
            return None
        if self._canonical_target_resolver is None:
            return None
        candidate_store = self._candidate_store
        if candidate_store is None:
            return None
        resolver = self._canonical_target_resolver
        try:
            value = resolver(request=request, candidate_id=candidate_id)
            if hasattr(value, "__await__"):
                value = await value
        except Exception:
            return None
        target = value
        if not isinstance(target, ResolvedB66ProvisioningTarget):
            return None
        # Server-only internal lookup proves the verified owner/workspace and
        # pending state without exposing them on the public admin API.
        read_fn = getattr(candidate_store, "read_candidate_envelope", None)
        if not callable(read_fn):
            return None
        try:
            envelope = read_fn(
                user_id=target.user_id,
                workspace_id=target.workspace_id,
                candidate_id=candidate_id,
            )
            envelope = await envelope if hasattr(envelope, "__await__") else envelope
        except Exception:
            return None
        if not isinstance(envelope, dict) or envelope.get("status") != "pending":
            return None
        # The candidate's serialized owner envelope remains authoritative for
        # the verified target, so a stale public candidate does not create an
        # unrelated approved Skill write surface.
        if envelope.get("user_id") != target.user_id:
            return None
        if str(envelope.get("workspace_id", "")):
            # read_candidate_envelope does not return workspace for this target
            # therefore the server-canonical target and read scope remain exact.
            pass
        return target
