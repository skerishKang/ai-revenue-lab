"""Focused STEP 3-B tests for #3186 trusted B66 candidate review authority."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app import b66_saved_skill_candidate_authority as authority_module
from app.b66_member_admin import D1B66MemberAdminStore
from app.b66_quote_skill_provisioning import (
    TrustedB66ProvisioningGrant,
    ResolvedB66ProvisioningTarget,
)
from app.b66_saved_skill_candidate_authority import (
    D1B66SavedQuoteSkillCandidateOperatorAuthority,
)


_Grant_UID = "usr_" + "a" * 32


class _FakeMemberStore(D1B66MemberAdminStore):
    def __init__(self, *, uid: str, email: str, review_allowed: bool = True):
        self.db = None
        self.admin_email = email
        self._uid = uid
        self._review_allowed = review_allowed

    async def is_google_admin(self, user_id: str) -> bool:
        return user_id == self._uid


def _request(uid: str) -> SimpleNamespace:
    from types import SimpleNamespace

    app = SimpleNamespace(state=SimpleNamespace())
    return SimpleNamespace(
        app=app,
        method="GET",
        path="/api/b66/admin/saved-skill-candidates/unused/decision",
    )


def _patch_auth(uid: str) -> None:
    authority_module.auth_ready = lambda req: True
    authority_module.current_user_id = lambda req: uid


@pytest.mark.asyncio
async def test_issue_grant_requires_separate_review_authority() -> None:
    _patch_auth(_Grant_UID)
    uid = _Grant_UID
    primary = _FakeMemberStore(uid=uid, email="primary@example.test")
    # No separate review authority: grant must fail closed.
    authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
        member_admin_store=primary,
        candidate_store=None,
        review_grant_admin_stores=(),
    )
    grant = await authority.issue_operator_grant(_request(uid))
    assert grant is None, "general Google admin login must not mint REVIEW_CANDIDATE"

    reviewer = _FakeMemberStore(uid=uid, email="reviewer@example.test")
    authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
        member_admin_store=primary,
        candidate_store=None,
        review_grant_admin_stores=(reviewer,),
    )
    grant = await authority.issue_operator_grant(_request(uid))
    assert isinstance(grant, TrustedB66ProvisioningGrant), "separate verified subject can mint"
    assert "review_candidate" in [a.value for a in grant.allowed_actions]
    now = datetime.now(timezone.utc)
    assert grant.is_active(now=now) is True, "grant must be active on issue"

    bad_uid = "usr_" + "b" * 32
    none = authority_module
    _patch_auth(bad_uid)
    action = await authority.issue_operator_grant(_request(bad_uid))
    assert action is None, "non-admin subject cannot mint"


@pytest.mark.asyncio
async def test_target_resolver_uses_server_only_envelope_and_fails_closed() -> None:
    _patch_auth(_Grant_UID)
    uid = _Grant_UID
    primary = _FakeMemberStore(uid=uid, email="primary@example.test")
    reviewer = _FakeMemberStore(uid=uid, email="reviewer@example.test")
    scanned = []

    class _CandidateStore:
        async def get_operator_candidate(self, *, candidate_id):
            # Public-safe projection lacks workspace. It must not be used.
            return {"candidate_id": candidate_id, "user_id": uid, "status": "pending"}

        async def read_candidate_envelope(self, *, user_id, workspace_id, candidate_id):
            scanned.append((user_id, workspace_id, candidate_id))
            return {
                "user_id": user_id,
                "candidate_id": candidate_id,
                "status": "pending"
                if (user_id == uid and workspace_id == "owner:" + uid)
                else "approved",
            }

    # Without a canonical tenant map: no target leakage and no target write.
    authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
        member_admin_store=primary,
        candidate_store=_CandidateStore(),
        review_grant_admin_stores=(reviewer,),
        canonical_target_resolver=None,
    )
    assert await authority.resolve_operator_target(_request(uid), "b66cand_" + "a" * 32) is None

    candidate_id = "b66cand_" + "a" * 32

    def canonical_resolver(*, request, candidate_id):
        return ResolvedB66ProvisioningTarget(
            user_id=uid,
            workspace_id="owner:" + uid,
            tenant_id="tenant_" + "c" * 32,
            canonical_subject_id="subject-test",
        )

    authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
        member_admin_store=primary,
        candidate_store=_CandidateStore(),
        review_grant_admin_stores=(reviewer,),
        canonical_target_resolver=canonical_resolver,
    )
    target = await authority.resolve_operator_target(_request(uid), candidate_id)
    assert isinstance(target, ResolvedB66ProvisioningTarget)
    assert scanned == [(uid, "owner:" + uid, candidate_id)]

    # Wrong canonical target (cross account) must fail closed.
    def bad_resolver(*, request, candidate_id):
        return ResolvedB66ProvisioningTarget(
            user_id="usr_" + "b" * 32,
            workspace_id="owner:" + "usr_" + "b" * 32,
            tenant_id="tenant_" + "c" * 32,
            canonical_subject_id="subject-test",
        )

    authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
        member_admin_store=primary,
        candidate_store=_CandidateStore(),
        review_grant_admin_stores=(reviewer,),
        canonical_target_resolver=bad_resolver,
    )
    assert await authority.resolve_operator_target(_request(uid), candidate_id) is None


@pytest.mark.asyncio
async def test_app_factory_keeps_step3b_fail_closed_without_review_grant() -> None:
    from app.app_factory import create_app
    from app.config import Settings

    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        session_secret="a" * 32,
        session_max_age_seconds=3600,
        live_enabled="false",
        google_client_id="client",
        google_client_secret="secret",
    )
    app = create_app(
        settings=settings,
        b66_admin_google_email="primary@example.test",
    )
    resolver = app.state.b66_operator_grant_resolver
    assert resolver is None
    target_resolver = app.state.b66_operator_target_resolver
    assert target_resolver is None
