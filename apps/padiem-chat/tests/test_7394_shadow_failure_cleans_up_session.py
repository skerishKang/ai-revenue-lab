"""#7394 item 3 — a shadow save failure ends the canonical session it orphaned.

``_write_identity_shadow_after_login`` binds one verified login to exactly one
canonical Control Plane session and then writes the local shadow pointer. When
the pointer write fails, no logout of this login can ever name the session, so
before the issuance refusal it survived unrevocable until its own expiry. The
failure path now ends the session best-effort (the cleanup must never mask the
establishment failure itself) and refuses the issuance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from padiem_control_plane import AuthSessionSnapshot, ProductIdentityLink
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

from app.auth_routes import (
    CanonicalSessionEstablishmentFailed,
    _write_identity_shadow_after_login,
)

USER_ID = "usr_" + "a" * 32
TENANT_ID = "tenant_" + "c" * 32


class RecordingAuthority:
    """Canonical authority double that records establishment and revocation."""

    def __init__(self):
        self.sessions: dict[str, AuthSessionSnapshot] = {}
        self.revoked: list[tuple[str, str]] = []
        self.counter = 0

    def resolve_or_create_product_link(self, *, product_id, product_user_id, auth_provider, provider_subject):
        return ProductIdentityLink(
            product_id=product_id,
            product_user_id=product_user_id,
            canonical_subject_id="sub_" + product_user_id[4:],
        )

    def resolve_active_memberships(self, *, canonical_subject_id):
        return (TENANT_ID,)

    def create_tenant(self):
        return TENANT_ID

    def assign_tenant_membership(self, *, tenant_id, canonical_subject_id, role=None):
        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )

    def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )

    def establish_auth_session(self, *, product_id, subject, authenticated_at, not_after):
        self.counter += 1
        snapshot = AuthSessionSnapshot(
            session_id="sess_%032x" % self.counter,
            product_id=product_id,
            subject=subject,
            issued_at=authenticated_at,
            expires_at=not_after,
            tenant_id=TENANT_ID,
        )
        self.sessions[snapshot.session_id] = snapshot
        return snapshot

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoked.append((product_id, session_id))
        self.sessions.pop(session_id, None)
        return True


class FailingShadowStore:
    async def save_projection(self, bridged):
        raise RuntimeError("synthetic shadow store failure")


def _request(authority):
    state = SimpleNamespace(
        control_plane_identity_authority=authority,
        identity_shadow_store=FailingShadowStore(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


async def _establish_and_fail(authority):
    now = datetime.now(timezone.utc)
    await _write_identity_shadow_after_login(
        _request(authority),
        product_user_id=USER_ID,
        provider="google",
        provider_subject="google-sub-7394",
        authenticated_at=now,
        expires_at=now + timedelta(seconds=3600),
    )


@pytest.mark.asyncio
async def test_shadow_save_failure_revokes_the_orphaned_session_best_effort():
    authority = RecordingAuthority()

    with pytest.raises(CanonicalSessionEstablishmentFailed):
        await _establish_and_fail(authority)

    # The canonical session was minted and then ended: it is not left behind
    # unrevocable, and the revocation names exactly the session the bridge
    # established for this login.
    assert len(authority.revoked) == 1
    product_id, session_id = authority.revoked[0]
    assert product_id == "b62"
    assert authority.sessions == {}


@pytest.mark.asyncio
async def test_a_failed_cleanup_still_refuses_the_issuance():
    """A revoke that itself fails must not mask the establishment failure."""

    class BrokenRevoker(RecordingAuthority):
        async def revoke_auth_session(self, *, product_id, session_id):
            raise RuntimeError("synthetic revocation failure")

    authority = BrokenRevoker()

    with pytest.raises(CanonicalSessionEstablishmentFailed):
        await _establish_and_fail(authority)

    assert authority.revoked == []
