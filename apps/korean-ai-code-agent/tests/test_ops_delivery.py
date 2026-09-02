from __future__ import annotations

import unittest

from kagent.contracts import ContractError
from kagent.ops_delivery import (
    ConnectorBinding,
    ManagedOnboardingProjection,
    ModelCredentialMode,
    OnboardingStatus,
    OpsDeliveryMode,
    OpsExecutionProfile,
    SecretReference,
)


class OpsDeliveryModeTests(unittest.TestCase):
    def test_cloud_managed_requires_entitlement_and_no_user_key(self):
        profile = OpsExecutionProfile(
            workspace_id="ws_1",
            account_ref="user:123",
            org_ref="org:acme",
            delivery_mode=OpsDeliveryMode.CLOUD_MANAGED,
            model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
            entitlement_ref="entitlement:claw-pro",
        )
        self.assertFalse(profile.requires_user_provider_key_input)
        self.assertFalse(profile.dedicated_ai_workstation_required)
        rendered = profile.safe_dict()
        self.assertFalse(rendered["raw_secret_values"])
        self.assertIsNone(rendered["model_secret_ref"])
        with self.assertRaises(ContractError):
            OpsExecutionProfile(
                workspace_id="ws_1",
                account_ref="user:123",
                org_ref=None,
                delivery_mode=OpsDeliveryMode.CLOUD_MANAGED,
                model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
            )

    def test_cloud_managed_cannot_carry_byok_reference(self):
        with self.assertRaises(ContractError):
            OpsExecutionProfile(
                workspace_id="ws_1",
                account_ref="user:123",
                org_ref=None,
                delivery_mode=OpsDeliveryMode.CLOUD_MANAGED,
                model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
                entitlement_ref="entitlement:free",
                model_secret_ref=SecretReference("vault:model:key1", "model-provider"),
            )

    def test_byok_uses_opaque_reference_not_raw_secret(self):
        profile = OpsExecutionProfile(
            workspace_id="ws_1",
            account_ref="user:123",
            org_ref=None,
            delivery_mode=OpsDeliveryMode.CLOUD_BYOK,
            model_credential_mode=ModelCredentialMode.SECRET_REFERENCE,
            model_secret_ref=SecretReference("vault:model:key1", "model-provider"),
        )
        self.assertTrue(profile.requires_user_provider_key_input)
        self.assertEqual(profile.model_secret_ref.secret_ref, "vault:model:key1")
        for value in (
            "sk-secretvalue123",
            "Bearer abcdefghijklmnopqrstuvwxyz",
            "token=abcdefghijk",
            "api_key=abcdefghijk",
            "password=abcdefghijk",
        ):
            with self.assertRaises(ContractError):
                SecretReference(value, "model-provider")

    def test_byok_requires_secret_reference(self):
        with self.assertRaises(ContractError):
            OpsExecutionProfile(
                workspace_id="ws_1",
                account_ref="user:123",
                org_ref=None,
                delivery_mode=OpsDeliveryMode.CLOUD_BYOK,
                model_credential_mode=ModelCredentialMode.SECRET_REFERENCE,
            )

    def test_local_and_self_hosted_preserve_non_managed_modes(self):
        local = OpsExecutionProfile(
            workspace_id="ws_1",
            account_ref="user:123",
            org_ref=None,
            delivery_mode=OpsDeliveryMode.LOCAL,
            model_credential_mode=ModelCredentialMode.LOCAL_OR_SELF_HOSTED,
        )
        self_hosted = OpsExecutionProfile(
            workspace_id="ws_1",
            account_ref="user:123",
            org_ref="org:enterprise",
            delivery_mode=OpsDeliveryMode.SELF_HOSTED,
            model_credential_mode=ModelCredentialMode.SECRET_REFERENCE,
            model_secret_ref=SecretReference("vault:enterprise:model", "model-provider"),
        )
        self.assertEqual(local.delivery_mode, OpsDeliveryMode.LOCAL)
        self.assertEqual(self_hosted.delivery_mode, OpsDeliveryMode.SELF_HOSTED)
        with self.assertRaises(ContractError):
            OpsExecutionProfile(
                workspace_id="ws_1",
                account_ref="user:123",
                org_ref=None,
                delivery_mode=OpsDeliveryMode.LOCAL,
                model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
            )

    def test_connector_credentials_are_references_only(self):
        connector = ConnectorBinding(
            connector_id="email-primary",
            account_ref="connector-account:1",
            credential_ref=SecretReference("vault:connector:email1", "email-send"),
        )
        profile = OpsExecutionProfile(
            workspace_id="ws_1",
            account_ref="user:123",
            org_ref=None,
            delivery_mode=OpsDeliveryMode.CLOUD_MANAGED,
            model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
            entitlement_ref="entitlement:pro",
            connectors=(connector,),
        )
        rendered = str(profile.safe_dict())
        self.assertIn("vault:connector:email1", rendered)
        self.assertNotIn("secretvalue", rendered)
        with self.assertRaises(ContractError):
            ConnectorBinding(
                connector_id="email-primary",
                account_ref="connector-account:1",
                credential_ref=SecretReference("sk-rawsecretvalue", "email-send"),
            )

    def test_duplicate_connector_ids_fail_closed(self):
        connector = ConnectorBinding(
            connector_id="email-primary",
            account_ref="connector-account:1",
            credential_ref=SecretReference("vault:connector:email1", "email-send"),
        )
        with self.assertRaises(ContractError):
            OpsExecutionProfile(
                workspace_id="ws_1",
                account_ref="user:123",
                org_ref=None,
                delivery_mode=OpsDeliveryMode.CLOUD_MANAGED,
                model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
                entitlement_ref="entitlement:pro",
                connectors=(connector, connector),
            )

    def test_onboarding_is_login_first_and_keyless_for_managed(self):
        empty = ManagedOnboardingProjection()
        self.assertEqual(empty.status, OnboardingStatus.ACCOUNT_REQUIRED)
        account = ManagedOnboardingProjection(account_ref="user:123")
        self.assertEqual(account.status, OnboardingStatus.WORKSPACE_REQUIRED)
        workspace = ManagedOnboardingProjection(account_ref="user:123", workspace_id="ws_1")
        self.assertEqual(workspace.status, OnboardingStatus.CONNECTORS_OPTIONAL)
        ready = ManagedOnboardingProjection(
            account_ref="user:123",
            workspace_id="ws_1",
            supplier_count=12,
            connector_count=1,
        )
        self.assertEqual(ready.status, OnboardingStatus.READY)
        self.assertFalse(ready.safe_dict()["provider_api_key_required_for_managed"])


if __name__ == "__main__":
    unittest.main()
