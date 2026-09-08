from __future__ import annotations

import re

import pytest

from padiem_control_plane.tenants import (
    CanonicalTenant,
    CanonicalTenantState,
    ControlPlaneTenantError,
    TenantMembership,
    TenantMembershipState,
)


def test_server_issued_tenant_id() -> None:
    tenant = CanonicalTenant(
        tenant_id="tenant_0123456789abcdef0123456789abcdef",
        state=CanonicalTenantState.ACTIVE,
    )
    assert re.fullmatch(r"tenant_[0-9a-f]{32}", tenant.tenant_id)
    assert tenant.state is CanonicalTenantState.ACTIVE
    assert tenant.created_at is None


def test_tenant_alias_product_rejected() -> None:
    with pytest.raises(ControlPlaneTenantError):
        CanonicalTenant(tenant_id="b62")


def test_tenant_alias_subject_rejected() -> None:
    with pytest.raises(ControlPlaneTenantError):
        TenantMembership(tenant_id="tenant_0123456789abcdef0123456789abcdef", canonical_subject_id="tenant_0123456789abcdef0123456789abcdef")