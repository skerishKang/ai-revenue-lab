from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.managed_onboarding import (
    BILLING_AUTHORITY_IN_B54,
    CLIENT_ASSERTED_ENTITLEMENT_SUPPORTED,
    OAUTH_IMPLEMENTED_IN_B54,
    RAW_PROVIDER_KEY_INPUT_SUPPORTED,
    ManagedClawOnboardingService,
    TrustedAccountSessionProjection,
    TrustedWorkspaceEntitlementProjection,
)
from kagent.ops_delivery import ModelCredentialMode, OpsDeliveryMode


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def session(**changes):
    values = dict(
        session_ref="session_1",
        account_ref="account_1",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
        authority_ref="control-plane:session",
    )
    values.update(changes)
    return TrustedAccountSessionProjection(**values)


def entitlement(**changes):
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


class ManagedOnboardingTests(unittest.TestCase):
    def test_trusted_session_and_entitlement_build_managed_profile(self):
        result = ManagedClawOnboardingService().build(session=session(), entitlement=entitlement(), now=NOW)
        self.assertEqual(result.profile.delivery_mode, OpsDeliveryMode.CLOUD_MANAGED)
        self.assertEqual(result.profile.model_credential_mode, ModelCredentialMode.PADIEM_MANAGED)
        self.assertEqual(result.profile.entitlement_ref, "entitlement_1")
        self.assertIsNone(result.profile.model_secret_ref)
        self.assertFalse(result.profile.requires_user_provider_key_input)
        safe = result.safe_dict()
        self.assertTrue(safe["managed_default"])
        self.assertFalse(safe["raw_provider_key_input"])

    def test_account_mismatch_denied_and_entitlement_must_allow_managed(self):
        with self.assertRaises(ContractError):
            ManagedClawOnboardingService().build(session=session(), entitlement=entitlement(account_ref="account_other"), now=NOW)
        with self.assertRaises(ContractError):
            ManagedClawOnboardingService().build(session=session(), entitlement=entitlement(managed_cloud_allowed=False), now=NOW)

    def test_future_or_expired_session_and_entitlement_fail_closed(self):
        with self.assertRaises(ContractError):
            ManagedClawOnboardingService().build(session=session(issued_at=NOW + timedelta(minutes=1), expires_at=NOW + timedelta(hours=1)), entitlement=entitlement(), now=NOW)
        with self.assertRaises(ContractError):
            ManagedClawOnboardingService().build(session=session(expires_at=NOW), entitlement=entitlement(), now=NOW)
        with self.assertRaises(ContractError):
            ManagedClawOnboardingService().build(session=session(), entitlement=entitlement(expires_at=NOW), now=NOW)

    def test_secret_like_trusted_refs_fail_closed(self):
        with self.assertRaises(ContractError):
            session(session_ref="token=should-not-be-here")
        with self.assertRaises(ContractError):
            entitlement(entitlement_ref="api_key=should-not-be-here")

    def test_b54_onboarding_does_not_claim_control_plane_or_provider_authority(self):
        self.assertFalse(CLIENT_ASSERTED_ENTITLEMENT_SUPPORTED)
        self.assertFalse(RAW_PROVIDER_KEY_INPUT_SUPPORTED)
        self.assertFalse(OAUTH_IMPLEMENTED_IN_B54)
        self.assertFalse(BILLING_AUTHORITY_IN_B54)


if __name__ == "__main__":
    unittest.main()
