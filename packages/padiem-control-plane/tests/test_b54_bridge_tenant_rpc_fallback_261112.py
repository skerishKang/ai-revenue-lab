"""B54 tenant resolution when the atomic personal-tenant RPC fails.

The bridge used to name an exception class this package never defines, so any
failure of ``ensure_personal_tenant_membership`` escaped as ``NameError``
instead of the closed bridge error, and the older-authority fallback could
never run.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from padiem_control_plane.b54_identity_bridge import (
    B54IdentityBridgeError,
    _resolve_canonical_tenant,
)
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
SUBJECT = CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_b54_fallback")
TENANT = "tenant_0123456789abcdef0123456789abcdef"


class AdapterError(Exception):
    """Shape of the product adapter's error: a closed ``code`` attribute."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Authority:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure
        self.fallback_reads = 0

    def ensure_personal_tenant_membership(self, *, canonical_subject_id, role):
        raise self.failure

    def resolve_active_memberships(self, *, canonical_subject_id):
        self.fallback_reads += 1
        return (TENANT,)

    def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )


@pytest.mark.parametrize("code", ["control_plane_identity_unavailable", "control_plane_rpc_invalid"])
def test_an_older_authority_without_the_atomic_rpc_falls_back_to_the_reviewed_path(code):
    authority = Authority(AdapterError(code))
    tenant = asyncio.run(_resolve_canonical_tenant(authority, SUBJECT, now=NOW))
    assert tenant == TENANT
    assert authority.fallback_reads == 1


@pytest.mark.parametrize("failure", [RuntimeError("timeout"), AdapterError("canonical_subject_inactive")])
def test_any_other_failure_is_the_closed_tenant_unavailable_error(failure):
    authority = Authority(failure)
    with pytest.raises(B54IdentityBridgeError) as exc:
        asyncio.run(_resolve_canonical_tenant(authority, SUBJECT, now=NOW))
    assert exc.value.code == "b54_control_plane_tenant_unavailable"
    assert authority.fallback_reads == 0
