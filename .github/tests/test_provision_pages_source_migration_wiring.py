from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "provision-approved-business-pages.yml"


class ProvisionPagesSourceMigrationWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_dispatch_contract_exposes_fail_closed_modes(self) -> None:
        self.assertIn("existing_project_action:", self.text)
        self.assertIn("- verify-only", self.text)
        self.assertIn("- migrate-source", self.text)
        self.assertIn("expected_old_source_directory:", self.text)
        self.assertIn('EXPECTED_OLD_SOURCE_DIRECTORY: ${{ inputs.expected_old_source_directory }}', self.text)

    def test_trusted_checkout_contains_both_validators(self) -> None:
        self.assertIn(".github/scripts/validate_pages_provisioning.py", self.text)
        self.assertIn(".github/scripts/validate_pages_source_migration.py", self.text)
        self.assertIn("ref: ${{ github.workflow_sha }}", self.text)
        self.assertIn("persist-credentials: false", self.text)

    def test_exact_migration_owner_authority_is_required_before_cloudflare_mutation(self) -> None:
        authority_index = self.text.index("Verify exact source-migration owner authority")
        patch_index = self.text.index("-X PATCH")
        self.assertLess(authority_index, patch_index)
        self.assertIn("SOURCE_MIGRATION_APPROVED", (
            Path(__file__).resolve().parents[1] / "scripts" / "validate_pages_source_migration.py"
        ).read_text(encoding="utf-8"))

    def test_migration_prechecks_old_contract_before_patch(self) -> None:
        patch_index = self.text.index("-X PATCH")
        before_patch = self.text[:patch_index]
        self.assertIn('--source-directory "${EXPECTED_OLD_SOURCE_DIRECTORY}"', before_patch)
        self.assertIn("validate_pages_provisioning.py cloudflare-project", before_patch)
        self.assertIn("validate_pages_source_migration.py patch-payload", before_patch)

    def test_patch_is_followed_by_get_and_new_contract_verification(self) -> None:
        patch_index = self.text.index("-X PATCH")
        after_patch = self.text[patch_index:]
        self.assertIn("post-migration lookup failed", after_patch)
        self.assertIn("validate_pages_provisioning.py cloudflare-project", after_patch)
        self.assertIn('--source-directory "${SOURCE_DIRECTORY}"', after_patch)
        self.assertIn("source-migrated-and-identity-verified", after_patch)

    def test_migrate_source_never_creates_or_deletes_project(self) -> None:
        self.assertIn(
            "migrate-source requires an existing Pages project; refusing create/recreate.",
            self.text,
        )
        self.assertNotIn("--request DELETE", self.text)
        self.assertNotIn("curl -X DELETE", self.text)

        migrate_guard = self.text.index(
            'if test "${EXISTING_PROJECT_ACTION}" = "migrate-source"; then'
        )
        create_call = self.text.index("--request POST", migrate_guard)
        refusal = self.text.index("refusing create/recreate", migrate_guard)
        self.assertLess(refusal, create_call)

    def test_verify_only_existing_project_remains_no_mutation(self) -> None:
        self.assertIn('if test "${EXISTING_PROJECT_ACTION}" = "verify-only"; then', self.text)
        self.assertIn('migration_result="verify-only-no-mutation"', self.text)

    def test_summary_records_migration_contract_without_secrets(self) -> None:
        for field in (
            "Existing-project action",
            "Expected old source",
            "Approved new source",
            "Source migration result",
        ):
            self.assertIn(field, self.text)
        self.assertNotIn("CLOUDFLARE_API_TOKEN}`", self.text)


if __name__ == "__main__":
    unittest.main()
