"""#4139 cross-product PC enrollment guard — common Control Plane, never Claw-owned."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.connector_enrollment_owner_policy import (
    CONNECTOR_REGISTRATION_GRANTS_P01_READ,
    CONNECTOR_REGISTRATION_GRANTS_P01_WRITE,
    CONNECTOR_REGISTRATION_MINTS_PRODUCT_ACCESS,
    CONNECTOR_REGISTRATION_PRODUCT_NEUTRAL_AUTHORITY,
    REVIEWED_CONNECTOR_ENROLLMENT_LOGIN_PRODUCTS,
    require_canonical_connector_owner_session,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef, ControlPlaneContractError, SubjectType,
)
from padiem_control_plane.tenants import TenantMembershipRole

NOW = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)


def canonical(product: str = "b54-padiem-claw") -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="session.verified.owner",
        product_id=product,
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id="subject.verified.owner",
        ),
        tenant_id="tenant.verified.owner",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
    )


def admitted(session: AuthSessionSnapshot, role=TenantMembershipRole.OWNER):
    return require_canonical_connector_owner_session(
        session=session, membership_role=role, now=NOW,
    )


def test_existing_verified_b54_bridge_preserves_canonical_owner_admission():
    session = canonical()
    assert admitted(session) is session
    assert REVIEWED_CONNECTOR_ENROLLMENT_LOGIN_PRODUCTS == frozenset({"b54-padiem-claw"})


@pytest.mark.parametrize("product", [
    "b62", "b66", "b66-padiem-quote", "padiem-chat", "padiem-engine",
    "B14", "claw", "unknown-product",
])
def test_new_product_id_never_autorizes_shared_pc_enrollment(product):
    with pytest.raises(ControlPlaneContractError) as caught:
        admitted(canonical(product))
    assert caught.value.code == "connector_enrollment_consent_session_denied"


@pytest.mark.parametrize("role", [
    TenantMembershipRole.VIEWER, TenantMembershipRole.OPERATOR,
    TenantMembershipRole.APPROVER, None, "owner", True,
])
def test_product_session_cannot_self_assert_tenant_owner(role):
    with pytest.raises(ControlPlaneContractError) as caught:
        admitted(canonical(), role=role)
    assert caught.value.code == "connector_enrollment_owner_required"


def test_revoked_or_expired_canonical_session_denies_pc_registration():
    for session in (
        replace(canonical(), state=AuthSessionState.REVOKED),
        replace(canonical(), state=AuthSessionState.EXPIRED),
        replace(canonical(), expires_at=NOW),
    ):
        with pytest.raises(ControlPlaneContractError) as caught:
            admitted(session)
        assert caught.value.code == "connector_enrollment_consent_session_denied"


def test_no_tenant_and_nonhuman_subject_cannot_register_shared_pc():
    no_tenant = replace(canonical(), tenant_id=None)
    service_subject = replace(canonical(), subject=CanonicalSubjectRef(
        subject_type=SubjectType.SERVICE, subject_id="svc.automated",
    ))
    for session in (no_tenant, service_subject):
        with pytest.raises(ControlPlaneContractError) as caught:
            admitted(session)
        assert caught.value.code == "connector_enrollment_consent_session_denied"


def test_platform_registration_never_grants_any_product_or_p01_permission():
    assert CONNECTOR_REGISTRATION_PRODUCT_NEUTRAL_AUTHORITY is True
    assert CONNECTOR_REGISTRATION_MINTS_PRODUCT_ACCESS is False
    assert CONNECTOR_REGISTRATION_GRANTS_P01_READ is False
    assert CONNECTOR_REGISTRATION_GRANTS_P01_WRITE is False
