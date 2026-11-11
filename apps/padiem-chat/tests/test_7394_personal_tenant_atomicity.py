"""#7394 item 2 — two concurrent first logins share one personal tenant.

The old bridge read memberships, created a tenant, and assigned membership in
three separate RPCs. Two first logins could both read zero and mint two active
memberships; the next login then failed closed as ambiguous. The bridge now
uses the authority's one-transaction ``ensure_personal_tenant_membership`` RPC.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

from app.control_plane_identity import ensure_personal_tenant_membership

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
SUBJECT = CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_7394_atomicity")
TENANT_ID = "tenant_" + "a" * 32


class AtomicAuthority:
    """Authority double whose ensure path is one lock-protected decision.

    The old three RPCs are booby-trapped: calling them fails the test, so the
    race regression is visible if the bridge falls back to the old sequence.
    """

    def __init__(self) -> None:
        self.tenant_id = None
        self.ensure_calls = 0
        self.old_calls: list[str] = []
        self.lock = asyncio.Lock()

    async def ensure_personal_tenant_membership(
        self, *, canonical_subject_id: str, role: str | None = None
    ) -> tuple[str, TenantMembership]:
        async with self.lock:
            self.ensure_calls += 1
            if self.tenant_id is None:
                self.tenant_id = TENANT_ID
            membership = TenantMembership(
                tenant_id=self.tenant_id,
                canonical_subject_id=canonical_subject_id,
                state=TenantMembershipState.ACTIVE,
                role=TenantMembershipRole(role or TenantMembershipRole.OWNER.value),
            )
            return self.tenant_id, membership

    async def resolve_active_memberships(self, *, canonical_subject_id: str):
        self.old_calls.append("resolve_active_memberships")
        return ()

    async def create_tenant(self):
        self.old_calls.append("create_tenant")
        return TENANT_ID

    async def assign_tenant_membership(self, *, tenant_id, canonical_subject_id, role=None):
        self.old_calls.append("assign_tenant_membership")
        raise AssertionError("the racy three-step path must not run")


@pytest.mark.asyncio
async def test_two_concurrent_first_logins_share_one_personal_tenant():
    authority = AtomicAuthority()

    first, second = await asyncio.gather(
        ensure_personal_tenant_membership(authority, subject=SUBJECT, now=NOW),
        ensure_personal_tenant_membership(authority, subject=SUBJECT, now=NOW),
    )

    assert first == second == TENANT_ID
    assert authority.tenant_id == TENANT_ID
    assert authority.ensure_calls == 2
    assert authority.old_calls == []


@pytest.mark.asyncio
async def test_the_bridge_still_falls_back_for_an_older_authority():
    """Authorities without the new RPC keep the reviewed three-step behavior."""

    class LegacyAuthority:
        def __init__(self) -> None:
            self.tenant_id = None

        async def resolve_active_memberships(self, *, canonical_subject_id: str):
            return () if self.tenant_id is None else (self.tenant_id,)

        async def create_tenant(self):
            self.tenant_id = TENANT_ID
            return TENANT_ID

        async def assign_tenant_membership(self, *, tenant_id, canonical_subject_id, role=None):
            return TenantMembership(
                tenant_id=tenant_id,
                canonical_subject_id=canonical_subject_id,
                state=TenantMembershipState.ACTIVE,
                role=TenantMembershipRole(role),
            )

    authority = LegacyAuthority()
    assert await ensure_personal_tenant_membership(authority, subject=SUBJECT, now=NOW) == TENANT_ID
