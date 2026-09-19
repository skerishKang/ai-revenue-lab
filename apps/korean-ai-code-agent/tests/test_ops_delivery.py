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
        secret_like_values = (
            "sk" + "-" + "fixturevalue",
            "Bearer" + " " + "fixturevalue",
            "token" + "=" + "fixturevalue",
            "api_key" + "=" + "fixturevalue",
            "password" + "=" + "fixturevalue",
        )
        for value in secret_like_values:
            with self.assertRaises(ContractError):
                SecretReference(value, "model-provider")

    def test_legacy_credential_prefix_rejection_parity(self):
        for value in (
            "sk" + "-fixturevalue",
            "Bearer" + " fixturevalue",
            "api_key" + "=fixturevalue",
            "apikey" + "=fixturevalue",
            "token" + "=fixturevalue",
            "secret" + "=fixturevalue",
            "password" + "=fixturevalue",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    SecretReference(value, "model-provider")

    def test_canonical_detector_aliases_and_short_assignments_are_rejected(self):
        for value in (
            "pwd=ab",
            "passphrase=x",
            "private_key=z",
            "credential=q",
            "token=x",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    SecretReference(value, "model-provider")

    def test_opaque_references_still_pass_and_reference_syntax_stays_strict(self):
        for value in ("vault:model:key1", "secret-ref_01", "account:primary/model"):
            with self.subTest(value=value):
                self.assertEqual(SecretReference(value, "model-provider").secret_ref, value)
        for value in ("vault ref", "vault?model", "vault=model"):
            with self.subTest(value=value):
                with self.assertRaises(ContractError) as caught:
                    SecretReference(value, "model-provider")
                self.assertIn("invalid reference syntax", str(caught.exception))

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
        self.assertNotIn("fixturevalue", rendered)
        with self.assertRaises(ContractError):
            ConnectorBinding(
                connector_id="email-primary",
                account_ref="connector-account:1",
                credential_ref=SecretReference("sk" + "-" + "fixturevalue", "email-send"),
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


class GateAuthorityRegressionTests(unittest.TestCase):
    """#2793. Three properties of the reference gate that nothing on main pinned.

    Recovered from the superseded #2792, which measured them while reconciling this site's
    duplicate credential grammar. They are written against current behaviour only: no legacy
    grammar, no generated parity corpus, and no introspection of production source, because
    those would freeze an implementation that has already been replaced.
    """

    def test_reference_is_normalised_before_either_contract(self):
        # Padding must not turn a valid reference into a syntax error...
        self.assertEqual(
            SecretReference("  vault:model:key1  ", "model-provider").secret_ref,
            "vault:model:key1",
        )
        # ...and must not become an escape hatch around the credential gate.
        for value in ("  " + "password" + "=x", "\ttoken" + "=fixturevalue"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ContractError) as caught:
                    SecretReference(value, "model-provider")
                self.assertIn("raw secret", str(caught.exception))

    def test_credential_error_takes_precedence_over_syntax_error(self):
        # `password=x` also violates the reference grammar, since `=` is not an allowed
        # character. Calling that a formatting problem would send an operator to fix the
        # syntax of a leaked credential, so the credential check answers first.
        for value in ("password" + "=x", "api_key" + "=fixturevalue", "token" + "=a"):
            with self.subTest(value=value):
                with self.assertRaises(ContractError) as caught:
                    SecretReference(value, "model-provider")
                self.assertIn("raw secret", str(caught.exception))
                self.assertNotIn("invalid reference syntax", str(caught.exception))
        # The other direction still holds: a syntax-only value is not called a secret.
        with self.assertRaises(ContractError) as syntax:
            SecretReference("vault ref", "model-provider")
        self.assertIn("invalid reference syntax", str(syntax.exception))
        self.assertNotIn("raw secret", str(syntax.exception))

    def test_provider_shaped_values_are_rejected_by_the_detector_at_this_field(self):
        # Every value below is well-formed reference syntax, so the only thing that can
        # refuse it is the canonical detector. The deleted site grammar recognised none of
        # these shapes, which is the coverage that reconciliation was meant to buy.
        for value in (
            "ghp" + "_" + "fixturevalue" * 2,
            "glpat" + "-" + "fixturevalue" * 2,
            "xoxb" + "-" + "fixturevalue" * 2,
            "sk_live" + "_" + "fixturevalue" * 2,
        ):
            with self.subTest(prefix=value[:6]):
                with self.assertRaises(ContractError) as caught:
                    SecretReference(value, "model-provider")
                self.assertIn("raw secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
