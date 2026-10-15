from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .auth_routes import auth_ready, current_user_id
from .b66_member_admin import D1B66MemberAdminStore
from .b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from .b66_saved_skill_candidate_store import (
    SavedQuoteSkillCandidateStore,
    SavedQuoteSkillCandidateStoreError,
)
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")

# A browser-supplied target is never accepted by this boundary. It only exposes
# the verified customer scope returned by the server-trusted candidate record or
# by a separately supplied canonical-tenant resolver.
class D1B66SavedQuoteSkillCandidateOperatorAuthority:
    def __init__(
        self,
        *,
        member_admin_store: Any,
        candidate_store: SavedQuoteSkillCandidateStore | None,
        canonical_target_resolver: Any = None,
        grant_ttl_minutes: int = 5,
    ) -> None:
        if not isinstance(member_admin_store, D1B66MemberAdminStore):
            raise ValueError("verified B66 member admin store is required")
        if grant_ttl_minutes < 1 or grant_ttl_minutes > 15:
            raise ValueError("grant lifetime must be bounded to 1-15 minutes")
        self._member_admin_store = member_admin_store
        self._candidate_store = candidate_store
        self._canonical_target_resolver = canonical_target_resolver
        self._grant_ttl_minutes = grant_ttl_minutes

    async def _admin_uid(self, request: Any) -> str | None:
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

    async def issue_operator_grant(self, request: Any) -> TrustedB66ProvisioningGrant | None:
        admin_uid = await self._admin_uid(request)
        if admin_uid is None:
            return None
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(minutes=self._grant_ttl_minutes)
        grant_ref = "b66candgrant_" + uuid.uuid4().hex
        if not _REF_RE.fullmatch(grant_ref):
            raise RuntimeError("operator grant reference is invalid")
        authority_ref = "b66-admin-session"
        if not isinstance(self._member_admin_store.admin_email, str):
            return None
        return TrustedB66ProvisioningGrant(
            grant_ref=grant_ref,
            operator_subject=CanonicalSubjectRef(SubjectType.USER, admin_uid),
            authority_ref=authority_ref,
            allowed_actions=(B66ProvisioningAction.REVIEW_CANDIDATE,),
            issued_at=issued_at,
            expires_at=expires_at,
        )

    async def resolve_operator_target(
        self, request: Any, candidate_id: str
    ) -> ResolvedB66ProvisioningTarget | None:
        store = self._candidate_store
        if store is None:
            return None
        get_fn = getattr(store, "get_operator_candidate", None)
        if not callable(get_fn):
            return None
        try:
            row = get_fn(candidate_id=candidate_id)
            candidate = await row if hasattr(row, "__await__") else row
        except Exception:
            return None
        if not isinstance(candidate, dict):
            return None
        if candidate.get("status") != "pending":
            return None
        user_id = candidate.get("user_id")
        workspace_id = candidate.get("workspace_id")
        if not isinstance(user_id, str) or not isinstance(workspace_id, str):
            return None
        if not isinstance(candidate_id, str):
            return None
        resolver = self._canonical_target_resolver
        if not callable(resolver):
            # There is no trusted server record mapping this verified customer
            # account to a canonical tenant. Fail closed instead of synthesizing.
            return None
        try:
            value = resolver(request=request, candidate=candidate, candidate_id=candidate_id)
            if hasattr(value, "__await__"):
                value = await value
        except Exception:
            return None
        if not isinstance(value, ResolvedB66ProvisioningTarget):
            return None
        # The candidate's server-proven owner/workspace remain authoritative.
        if value.user_id != user_id or value.workspace_id != workspace_id:
            return None
        return value
