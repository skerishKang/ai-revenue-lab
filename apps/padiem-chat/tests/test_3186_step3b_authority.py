"""#3186 STEP3B: host-only grant and target adapter, provider-free."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from app import b66_saved_skill_candidate_authority as module
from app.b66_member_admin import D1B66MemberAdminStore
from app.b66_quote_skill_provisioning import (
    B66ProvisioningAction, ResolvedB66ProvisioningTarget, TrustedB66ProvisioningGrant,
)
from app.b66_saved_skill_candidate_authority import D1B66SavedQuoteSkillCandidateOperatorAuthority

A = "usr_" + "a" * 32
B = "usr_" + "b" * 32
CID = "b66cand_" + "c" * 32


def staff_store():
    store = D1B66MemberAdminStore(MagicMock(), admin_email="admin@example.test")
    store.is_google_admin = AsyncMock(side_effect=lambda uid: uid == A)
    return store


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def grant(uid=A, *, age_minutes=2, expires_in_minutes=4, action=B66ProvisioningAction.REVIEW_CANDIDATE):
    now = datetime.now(timezone.utc)
    return TrustedB66ProvisioningGrant(
        grant_ref="reviewed_auth_" + "d" * 32,
        operator_subject=CanonicalSubjectRef(SubjectType.USER, uid),
        authority_ref="trusted_host_issuer",
        allowed_actions=(action,),
        issued_at=now-timedelta(minutes=age_minutes),
        expires_at=now+timedelta(minutes=expires_in_minutes),
    )


@pytest.mark.asyncio
async def test_staff_identity_never_mints_grant_without_independent_host_authority(monkeypatch):
    monkeypatch.setattr(module, "auth_ready", lambda _: True)
    monkeypatch.setattr(module, "current_user_id", lambda _: A)
    authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
        member_admin_store=staff_store(), candidate_store=None,
    )
    assert await authority.issue_operator_grant(request()) is None
    assert await authority.resolve_operator_target(request(), CID) is None


@pytest.mark.asyncio
async def test_only_reviewed_active_grant_for_the_exact_operator_is_accepted(monkeypatch):
    monkeypatch.setattr(module, "auth_ready", lambda _: True)
    monkeypatch.setattr(module, "current_user_id", lambda _: A)
    issuer = lambda **kwargs: grant()
    authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
        member_admin_store=staff_store(), candidate_store=None,
        trusted_review_grant_issuer=issuer,
    )
    assert isinstance(await authority.issue_operator_grant(request()), TrustedB66ProvisioningGrant)
    for bad in [
        lambda **kw: grant(uid=B),
        lambda **kw: grant(age_minutes=20, expires_in_minutes=3),
        lambda **kw: grant(age_minutes=20, expires_in_minutes=-1),
        lambda **kw: grant(action=B66ProvisioningAction.ASSIGN),
    ]:
        authority._trusted_review_grant_issuer = bad
        assert await authority.issue_operator_grant(request()) is None
    monkeypatch.setattr(module, "current_user_id", lambda _: B)
    authority._trusted_review_grant_issuer = issuer
    assert await authority.issue_operator_grant(request()) is None


@pytest.mark.asyncio
async def test_canonical_target_must_match_private_owner_scoped_pending_envelope(monkeypatch):
    monkeypatch.setattr(module, "auth_ready", lambda _: True)
    monkeypatch.setattr(module, "current_user_id", lambda _: A)
    store = SimpleNamespace(read_candidate_envelope=AsyncMock(return_value={
        "candidate_id":CID, "status":"pending",
    }))
    owner = ResolvedB66ProvisioningTarget(
        user_id=B, workspace_id="owner:"+B,
        tenant_id="tenant_"+"d"*32, canonical_subject_id="subject_B",
    )
    authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
        member_admin_store=staff_store(), candidate_store=store,
        canonical_target_resolver=lambda **kwargs: owner,
    )
    assert await authority.resolve_operator_target(request(),CID) == owner
    store.read_candidate_envelope.assert_awaited_once_with(
        user_id=B,workspace_id="owner:"+B,candidate_id=CID,
    )
    store.read_candidate_envelope.return_value = None
    assert await authority.resolve_operator_target(request(),CID) is None
    store.read_candidate_envelope.return_value = {"candidate_id":CID,"status":"approved"}
    assert await authority.resolve_operator_target(request(),CID) is None
    store.read_candidate_envelope.return_value = {"candidate_id":CID,"status":"pending"}
    authority._canonical_target_resolver = None
    assert await authority.resolve_operator_target(request(),CID) is None
    assert await authority.resolve_operator_target(request(),"bad-browser-id") is None


def test_factory_keeps_operator_write_disabled_without_trusted_host_resolvers():
    from app.app_factory import create_app
    from app.config import Settings
    settings = Settings.from_values(
        runtime_mode="mock",auth_mode="google",public_base_url="https://chat.example.test",
        google_client_id="client",google_client_secret="synthetic-only",
        session_secret="synthetic-only-session-secret-123456",session_max_age_seconds=3600,
        live_enabled="false",
    )
    app = create_app(settings=settings,b66_admin_google_email="admin@example.test")
    assert app.state.b66_operator_grant_resolver is None
    assert app.state.b66_operator_target_resolver is None
