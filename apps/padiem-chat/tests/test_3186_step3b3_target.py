"""#3186 STEP 3-B3: real private candidate-owner and CP tenant mapping."""

from types import SimpleNamespace

import pytest

from padiem_control_plane.auth_sessions import AuthSessionState
from padiem_control_plane.tenants import TenantMembershipState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from app.b66_quote_skill_provisioning import ResolvedB66ProvisioningTarget
from app.b66_saved_skill_candidate_authority import (
    B66CanonicalCandidateTargetResolver,
)

CID = "b66cand_" + "c" * 32
TENANT = "tenant_" + "a" * 32


def store(private_owner):
    stub = SimpleNamespace()
    stub.read_private_candidate_owner = lambda candidate_id, **_: private_owner
    return stub


def authority(state=AuthSessionState.ACTIVE, tenant=TENANT):
    snapshot = SimpleNamespace(
        state=state,
        subject=CanonicalSubjectRef(SubjectType.USER, "google-subject-1"),
        tenant_id=tenant,
    )
    membership_state = TenantMembershipState.ACTIVE
    def membership(**kwargs):
        return SimpleNamespace(state=membership_state)

    auth = SimpleNamespace(
        resolve_current_auth_session=lambda **kwargs: snapshot,
        resolve_active_tenant_membership=membership,
    )
    return auth


@pytest.mark.asyncio
async def test_cp_maps_pending_candidate_target():
    pending = {
        "status": "pending",
        "user_id": "usr_" + "u" * 31,
        "workspace_id": "space_" + "w" * 24,
    }
    resolver = B66CanonicalCandidateTargetResolver(
        candidate_store=store(pending),
        identity_authority=authority(),
        product_id="b62",
    )
    target = await resolver(None, CID)
    assert isinstance(target, ResolvedB66ProvisioningTarget)
    assert target.tenant_id == TENANT
    assert target.canonical_subject_id == "google-subject-1"


@pytest.mark.asyncio
async def test_missing_cp_authority_fails_closed():
    pending = {
        "status": "pending",
        "user_id": "usr_" + "u" * 31,
        "workspace_id": "space_" + "w" * 24,
    }
    resolver = B66CanonicalCandidateTargetResolver(
        candidate_store=store(pending),
        identity_authority=None,
        product_id="b62",
    )
    assert await resolver(None, CID) is None


@pytest.mark.asyncio
async def test_non_pending_or_inactive_session_fails_closed():
    pending = {
        "status": "approved",
        "user_id": "usr_" + "u" * 31,
        "workspace_id": "space_" + "w" * 24,
    }
    resolver = B66CanonicalCandidateTargetResolver(
        candidate_store=store(pending),
        identity_authority=authority(state=AuthSessionState.EXPIRED),
        product_id="b62",
    )
    assert await resolver(None, CID) is None
