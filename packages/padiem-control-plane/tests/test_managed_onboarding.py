"""Tests for the promoted CP managed-onboarding projection (#1563).

Behavioural cases are ported from the reviewed B54-side suite
(``apps/korean-ai-code-agent/tests/test_managed_onboarding.py``) with the
fail-closed composition semantics kept exact. Pure offline validation;
network-free.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.managed_onboarding import (
    BILLING_AUTHORITY,
    CLIENT_ASSERTED_ENTITLEMENT_SUPPORTED,
    MEMBERSHIP_AUTHORITY,
    OAUTH_IMPLEMENTED_HERE,
    RAW_PROVIDER_KEY_INPUT_SUPPORTED,
    ConnectorBinding,
    ManagedCloudOnboardingService,
    ManagedOnboardingProjection,
    ModelCredentialMode,
    OnboardingStatus,
    OpsDeliveryMode,
    OpsExecutionProfile,
    SecretReference,
    TrustedAccountSessionProjection,
    TrustedWorkspaceEntitlementProjection,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
SERVICE = ManagedCloudOnboardingService()


def session(**changes) -> TrustedAccountSessionProjection:
    values = dict(
        session_ref="session_1",
        account_ref="account_1",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
        authority_ref="control-plane:session",
    )
    values.update(changes)
    return TrustedAccountSessionProjection(**values)


def entitlement(**changes) -> TrustedWorkspaceEntitlementProjection:
    values = dict(
        entitlement_ref="entitlement_1",
        account_ref="account_1",
        workspace_id="ws_1",
        org_ref="org_1",
        managed_cloud_allowed=True,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
        authority_ref="control-plane:entitlement",
    )
    values.update(changes)
    return TrustedWorkspaceEntitlementProjection(**values)


def connector(connector_id: str = "gmail", *, enabled: bool = True) -> ConnectorBinding:
    return ConnectorBinding(
        connector_id=connector_id,
        account_ref="account_1",
        credential_ref=SecretReference(secret_ref="secretref:gmail-oauth", purpose="connector-credential"),
        enabled=enabled,
    )


def test_trusted_session_and_entitlement_build_managed_profile() -> None:
    result = SERVICE.build(session=session(), entitlement=entitlement(), now=NOW)
    assert result.profile.delivery_mode is OpsDeliveryMode.CLOUD_MANAGED
    assert result.profile.model_credential_mode is ModelCredentialMode.PADIEM_MANAGED
    assert result.profile.entitlement_ref == "entitlement_1"
    assert result.profile.model_secret_ref is None
    assert result.profile.requires_user_provider_key_input is False
    assert result.profile.dedicated_ai_workstation_required is False
    safe = result.safe_dict()
    assert safe["managed_default"] is True
    assert safe["raw_provider_key_input"] is False
    assert safe["oauth_implemented_here"] is False
    assert safe["billing_authority"] is False
    assert safe["membership_authority"] is False
    assert safe["projection"]["status"] == "connectors_optional"
    assert safe["projection"]["provider_api_key_required_for_managed"] is False


def test_account_mismatch_denied_and_entitlement_must_allow_managed() -> None:
    with pytest.raises(ControlPlaneContractError, match="account mismatch"):
        SERVICE.build(session=session(), entitlement=entitlement(account_ref="account_other"), now=NOW)
    with pytest.raises(ControlPlaneContractError, match="does not allow Managed Cloud"):
        SERVICE.build(session=session(), entitlement=entitlement(managed_cloud_allowed=False), now=NOW)


def test_future_or_expired_session_and_entitlement_fail_closed() -> None:
    with pytest.raises(ControlPlaneContractError, match="not currently active"):
        SERVICE.build(
            session=session(issued_at=NOW + timedelta(minutes=1), expires_at=NOW + timedelta(hours=1)),
            entitlement=entitlement(),
            now=NOW,
        )
    with pytest.raises(ControlPlaneContractError, match="not currently active"):
        SERVICE.build(session=session(expires_at=NOW), entitlement=entitlement(), now=NOW)
    with pytest.raises(ControlPlaneContractError, match="not currently active"):
        SERVICE.build(session=session(), entitlement=entitlement(expires_at=NOW), now=NOW)


def test_secret_like_trusted_refs_fail_closed() -> None:
    with pytest.raises(ControlPlaneContractError, match="bounded safe reference"):
        session(session_ref="token=should-not-be-here")
    with pytest.raises(ControlPlaneContractError, match="bounded safe reference"):
        entitlement(entitlement_ref="api_key=should-not-be-here")
    with pytest.raises(ControlPlaneContractError, match="opaque reference, never a raw secret"):
        connector().credential_ref.__class__(secret_ref="sk-live-should-not-be-here", purpose="connector-credential")


def test_connectors_bind_opaquely_and_count_only_enabled() -> None:
    result = SERVICE.build(
        session=session(),
        entitlement=entitlement(),
        now=NOW,
        connectors=(connector("gmail"), connector("drive", enabled=False)),
    )
    assert result.projection.connector_count == 1
    assert result.projection.status is OnboardingStatus.READY
    assert result.safe_dict()["projection"]["status"] == "ready"
    assert len(result.profile.safe_dict()["connectors"]) == 2
    first = result.profile.safe_dict()["connectors"][0]
    assert first["connector_id"] == "gmail"
    assert first["credential_ref"] == {"secret_ref": "secretref:gmail-oauth", "purpose": "connector-credential"}


def test_duplicate_connector_ids_are_rejected() -> None:
    with pytest.raises(ControlPlaneContractError, match="must be unique"):
        SERVICE.build(session=session(), entitlement=entitlement(), now=NOW, connectors=(connector("gmail"), connector("gmail")))


def test_supplier_count_is_bounded() -> None:
    result = SERVICE.build(session=session(), entitlement=entitlement(), now=NOW, supplier_count=7)
    assert result.projection.supplier_count == 7
    with pytest.raises(ControlPlaneContractError, match="bounded non-negative integer"):
        SERVICE.build(session=session(), entitlement=entitlement(), now=NOW, supplier_count=-1)
    with pytest.raises(ControlPlaneContractError, match="bounded non-negative integer"):
        SERVICE.build(session=session(), entitlement=entitlement(), now=NOW, supplier_count=True)


def test_managed_profile_invariants_hold_on_direct_construction() -> None:
    with pytest.raises(ControlPlaneContractError, match="must not carry a model secret reference"):
        OpsExecutionProfile(
            workspace_id="ws_1",
            account_ref="account_1",
            org_ref=None,
            delivery_mode=OpsDeliveryMode.CLOUD_MANAGED,
            model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
            entitlement_ref="entitlement_1",
            model_secret_ref=SecretReference(secret_ref="secretref:model", purpose="model"),
        )
    with pytest.raises(ControlPlaneContractError, match="requires a trusted entitlement reference"):
        OpsExecutionProfile(
            workspace_id="ws_1",
            account_ref="account_1",
            org_ref=None,
            delivery_mode=OpsDeliveryMode.CLOUD_MANAGED,
            model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
        )


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ControlPlaneContractError, match="timezone-aware"):
        session(issued_at=datetime(2026, 9, 3, 12, 0))
    with pytest.raises(ControlPlaneContractError, match="timezone-aware"):
        entitlement(expires_at=datetime(2026, 9, 3, 13, 0))
    with pytest.raises(ControlPlaneContractError, match="timezone-aware"):
        SERVICE.build(session=session(), entitlement=entitlement(), now=datetime(2026, 9, 3, 12, 0))


def test_inverted_session_window_is_rejected() -> None:
    with pytest.raises(ControlPlaneContractError, match="must follow issued_at"):
        session(issued_at=NOW, expires_at=NOW - timedelta(minutes=1))


def test_builder_rejects_wrong_types() -> None:
    with pytest.raises(ControlPlaneContractError, match="session projection is required"):
        SERVICE.build(session="not-a-session", entitlement=entitlement(), now=NOW)
    with pytest.raises(ControlPlaneContractError, match="entitlement projection is required"):
        SERVICE.build(session=session(), entitlement="not-an-entitlement", now=NOW)
    with pytest.raises(ControlPlaneContractError, match="trusted ConnectorBinding values"):
        SERVICE.build(session=session(), entitlement=entitlement(), now=NOW, connectors=("not-a-binding",))


def test_onboarding_status_enum_is_bounded() -> None:
    assert {item.value for item in OnboardingStatus} == {
        "account_required",
        "workspace_required",
        "connectors_optional",
        "ready",
    }
    assert ManagedOnboardingProjection().status is OnboardingStatus.ACCOUNT_REQUIRED
    assert ManagedOnboardingProjection(account_ref="account_1").status is OnboardingStatus.WORKSPACE_REQUIRED


def test_onboarding_claims_no_membership_billing_oauth_or_provider_key_authority() -> None:
    assert CLIENT_ASSERTED_ENTITLEMENT_SUPPORTED is False
    assert RAW_PROVIDER_KEY_INPUT_SUPPORTED is False
    assert OAUTH_IMPLEMENTED_HERE is False
    assert BILLING_AUTHORITY is False
    assert MEMBERSHIP_AUTHORITY is False
