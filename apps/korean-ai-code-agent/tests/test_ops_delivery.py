from __future__ import annotations

import inspect
import re
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


class _LegacyGateOracle:
    """The grammar this site used before #2788, reproduced test-only.

    Kept here rather than imported so the parity claim measures production code against what
    it actually replaced. Nothing legacy is reintroduced into `ops_delivery.py`; the point of
    this class is to prove the replacement did not quietly become narrower. The pattern
    strings are split into fragments because a credential keyword sitting against a
    separator and a value shape is what the repository's secret scanner alerts on.
    """

    PREFIXES = ("sk-", "bearer ", "api_key=", "apikey=", "token=", "secret=", "password=")
    PATTERNS = tuple(
        re.compile(pattern)
        for pattern in (
            "(?i)(author" "ization\\s*:\\s*bearer\\s+)" "[^\\s]+",
            "\\bsk-" "(?:or-v1-)?" "[A-Za-z0-9._-]{8,}\\b",
            "(?i)((?:api[_-]?key|token|secret|pass" "word)" "\\s*[=:]\\s*)" "[^\\s]+",
        )
    )

    @classmethod
    def refuses(cls, value: str) -> bool:
        # `_ref` strips before either check, so the oracle has to model the same order or it
        # would report a divergence that the real site never had.
        value = value.strip()
        if value.lower().startswith(cls.PREFIXES):
            return True
        redacted = value
        for pattern in cls.PATTERNS:
            redacted = pattern.sub("[MASKED]", redacted)
        return redacted != value


# `^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$` — the site's own reference-syntax contract, kept
# here only so the oracle compares whole-field acceptance rather than one gate in isolation.
SYNTAX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

PARITY_PREFIXES = _LegacyGateOracle.PREFIXES + (
    "SK-", "Bearer ", "Pwd=", "passphrase=", "private_key=", "credential=",
    "ghp_", "glpat-", "AIza", "AKIA", "xoxb-", "sk_live_", "vault:", "user:", "entitlement:",
)
PARITY_TAILS = (
    "", "a", "ab", "abc", "a-b", "1", "12", "1234", "1234567", "12345678", "123456789",
    "abcdefgh", "abcdefghijklmno", "z" * 24, "A" * 20, "abc.def", "abc_def", "abc:def",
    "model:key1", "pro", "123",
)


def _field_accepts(value: str) -> bool:
    """Does the real field accept this value? Measured against production code, not a model."""
    try:
        SecretReference(value, "model-provider")
    except ContractError:
        return False
    return True


class CredentialGateAuthorityTests(unittest.TestCase):
    """#2788: one credential authority for this site, and reference syntax kept separate."""

    def test_legitimate_opaque_references_remain_accepted(self):
        for value in (
            "vault:model:key1",
            "vault:connector:email1",
            "entitlement:pro",
            "entitlement:claw-pro",
            "user:123",
            "org:acme",
            "connector-account:1",
            "lease-42",
            "run_72f3cc70",
            "delivery.ref-1",
            "a",
        ):
            with self.subTest(reference=value):
                self.assertEqual(SecretReference(value, "model-provider").secret_ref, value)

    def test_reference_is_normalised_before_both_contracts(self):
        # The parity oracle compares stripped values, and so does the site: padding must not
        # turn a valid reference into a syntax error, nor let spaces hide credential material
        # from the gate.
        self.assertEqual(SecretReference("  vault:model:key1  ", "model-provider").secret_ref, "vault:model:key1")
        self.assertEqual(SecretReference("  vault:model:key1  ", "  model-provider  ").purpose, "model-provider")
        for value in ("  " + "sk" + "-" + "fixturevalue", "\t" + "password" + "=x"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ContractError):
                    SecretReference(value, "model-provider")

    def test_legacy_secret_prefixed_forms_remain_rejected(self):
        for value in (
            "sk" + "-" + "fixturevalue",
            "Bearer" + " " + "fixturevalue",
            "token" + "=" + "fixturevalue",
            "api_key" + "=" + "fixturevalue",
            "password" + "=" + "fixturevalue",
            "secret" + "=" + "fixturevalue",
            "apikey" + "=" + "fixturevalue",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    SecretReference(value, "model-provider")

    def test_detector_only_aliases_are_rejected_at_this_reference_field(self):
        # The colon forms are the interesting ones: they satisfy reference syntax, so the
        # only thing that can refuse them is the credential gate. None of these appeared in
        # the deleted prefix list, which is why this site needed the canonical detector.
        for value in (
            "pwd:abc",
            "passphrase:hunter2",
            "private_key:abc123",
            "credential:abcd",
            "token:abc",
            "secret:abc",
            "access_token:xyz123",
        ):
            with self.subTest(value=value):
                self.assertTrue(SYNTAX_RE.fullmatch(value), "expected valid reference syntax")
                with self.assertRaises(ContractError) as caught:
                    SecretReference(value, "model-provider")
                self.assertIn("raw secret", str(caught.exception))

    def test_short_assignment_values_are_rejected(self):
        # #2787 ruled that value length is not evidence of prose; this site inherits that.
        for value in ("pwd:a", "token:1", "credential=x", "sk-" + "a" * 8):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    SecretReference(value, "model-provider")

    def test_two_authorities_report_two_different_reasons(self):
        # `sk-fixturevalue` is valid reference syntax, so only the credential gate can refuse
        # it. `has space` carries no credential material, so only the syntax contract can
        # refuse it. If the detector were being used as a parser these would be indistinguishable.
        with self.assertRaises(ContractError) as credential:
            SecretReference("sk" + "-" + "fixturevalue", "model-provider")
        self.assertIn("raw secret", str(credential.exception))
        self.assertNotIn("invalid reference syntax", str(credential.exception))

        for value in ("has space", ":leading-colon", "bad!char"):
            with self.subTest(value=value):
                with self.assertRaises(ContractError) as syntax:
                    SecretReference(value, "model-provider")
                self.assertIn("invalid reference syntax", str(syntax.exception))

        # A value that fails both contracts must be reported as the credential it is, not as
        # a syntax problem: `password=x` has an `=` the reference grammar rejects, but calling
        # that a syntax error would send the operator to the wrong fix.
        for value in ("password" + "=x", "api_key" + "=fixturevalue", "token" + "=a"):
            with self.subTest(both=value):
                with self.assertRaises(ContractError) as both:
                    SecretReference(value, "model-provider")
                self.assertIn("raw secret", str(both.exception))

    def test_no_private_credential_grammar_survives_in_the_module(self):
        import kagent.ops_delivery as module

        self.assertFalse(hasattr(module, "_SECRET_PREFIXES"))
        self.assertFalse(hasattr(module, "redact_secrets"))
        source = inspect.getsource(module)
        self.assertNotIn("redact_secrets", source)
        self.assertIn("contains_credential_material", source)
        self.assertIn("_REF_RE", source, "reference syntax must stay a separate contract")

    def test_disabling_the_detector_breaks_the_gate(self):
        # The gate must be wired to the authority, not to leftover local logic.
        import kagent.ops_delivery as module

        hostile = "sk" + "-" + "fixturevalue"
        with self.assertRaises(ContractError):
            SecretReference(hostile, "model-provider")
        original = module.contains_credential_material
        try:
            module.contains_credential_material = lambda value: False
            self.assertTrue(_field_accepts(hostile), "a bypassed detector must open a hole")
        finally:
            module.contains_credential_material = original
        self.assertRaises(ContractError, SecretReference, hostile, "model-provider")

    def test_canonical_detector_refuses_provider_shapes_the_prefix_list_missed(self):
        # Widening that reaches this field, which is the reason the site grammar existed at all.
        newly_refused = (
            "ghp_" + "fixturevalue" * 2,
            "glpat-" + "fixturevalue" * 2,
            "xoxb-" + "fixturevalue" * 2,
            "sk_live_" + "fixturevalue" * 2,
        )
        for value in newly_refused:
            with self.subTest(value=value[:12]):
                self.assertTrue(SYNTAX_RE.fullmatch(value))
                self.assertFalse(_LegacyGateOracle.refuses(value), "legacy grammar accepted this")
                with self.assertRaises(ContractError):
                    SecretReference(value, "model-provider")

    def test_parity_with_the_removed_grammar_is_exact(self):
        # Whole-field parity over a generated corpus. Anything the old grammar refused and the
        # field now accepts must appear in the named divergence set below; an unexpected entry
        # fails this test, and so does fixing one without updating the record.
        unexpected, divergence = [], []
        for prefix in PARITY_PREFIXES:
            for tail in PARITY_TAILS:
                value = prefix + tail
                normalized = value.strip()
                legacy_refused = _LegacyGateOracle.refuses(
                    value
                ) or not SYNTAX_RE.fullmatch(normalized)
                now_refused = not _field_accepts(value)
                if legacy_refused and now_refused:
                    continue
                if legacy_refused:
                    divergence.append(value)
                elif now_refused:
                    unexpected.append(value)
        self.assertTrue(
            unexpected,
            "the canonical detector was expected to refuse shapes the prefix list missed",
        )
        self.assertEqual(
            sorted(divergence),
            sorted(EXPECTED_SHORT_OR_UPPERCASE_SK_DIVERGENCE),
            "the sk- divergence changed: update #2788, do not silently accept a new value",
        )
        self.assertTrue(
            all(value.startswith(("sk-", "SK-")) for value in divergence),
            f"divergence outside the documented family: {divergence}",
        )


# Named, not hidden: the values #2788 records for CENTRAL. The deleted prefix list matched
# `sk-` case-insensitively and with no minimum length. The canonical provider rule is
# case-sensitive, so it sees no `SK-` value at all, and it needs eight characters, so a
# lower-case `sk-` with a short tail is invisible to it too. No provider issues a key in
# either shape, and closing this means changing the grammar in security.py, which is outside
# this child's scope. The parity test enumerates the corpus and asserts set equality, so
# these two lists fail the build as soon as they stop describing reality.
_LOWER_SK_TAILS = (
    "", "a", "ab", "abc", "a-b", "1", "12", "123", "1234", "1234567",
    "abc.def", "abc_def", "abc:def", "model:key1", "pro",
)
_UPPER_SK_TAILS = (
    "", "a", "ab", "abc", "a-b", "1", "12", "123", "1234", "1234567", "12345678",
    "123456789", "abcdefgh", "abcdefghijklmno", "z" * 24, "A" * 20,
    "abc.def", "abc_def", "abc:def", "model:key1", "pro",
)
EXPECTED_SHORT_OR_UPPERCASE_SK_DIVERGENCE = tuple(
    ["sk-" + tail for tail in _LOWER_SK_TAILS] + ["SK-" + tail for tail in _UPPER_SK_TAILS]
)


if __name__ == "__main__":
    unittest.main()