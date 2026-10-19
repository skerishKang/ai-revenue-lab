"""Regression and mutation-negative tests for documentation CI authority guard."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "docs/operations/scripts"))
from document_authority_integrity import (
    HUBS,
    SCOPED_DOCS,
    inspect_ci_contract,
    inspect_content,
    inspect_links,
    scan_repository,
)


class DocumentationIntegrityCITests(unittest.TestCase):
    def test_real_repository_current_documentation_is_consistent(self):
        self.assertEqual(scan_repository(ROOT), [])

    def test_model_inventory_in_root_is_blocked(self):
        bad = inspect_content("docs/README.md", "OWNER_GOOGLE_FOUR = gemini-9.9-synthetic-test\n")
        self.assertTrue(any("copied-model-ID" in item for item in bad), bad)
        self.assertTrue(any("copied-volatile-status" in item for item in bad), bad)

    def test_volatile_status_in_product_is_blocked(self):
        bad = inspect_content("docs/products/b66/README.md", "MERGED_SOURCE_PLUS = some-route\n")
        self.assertTrue(any("copied-volatile-status" in item for item in bad), bad)

    def test_outdated_google_unmerged_claim_is_blocked(self):
        bad = inspect_content("docs/README.md", "LOCAL Google registration not merged")
        self.assertTrue(any("stale-source-claim" in item for item in bad), bad)

    def test_duplicate_owner_approval_rule_in_product_is_blocked(self):
        bad = inspect_content(
            "apps/korean-ai-code-agent/README.md",
            "MODEL_DECISION_AUTHORITY=OWNER_ONLY\n"
            "DEFAULT_AGENT_ACTION=STOP_AND_ASK_OWNER\n",
        )
        self.assertTrue(any("duplicate-owner-policy" in item for item in bad), bad)

    def test_non_model_prose_is_allowed(self):
        self.assertEqual(
            inspect_content("docs/README.md", "Refer to B14 catalog for actual Gemini model IDs.\n"),
            [],
        )

    def test_missing_relative_link_is_blocked(self):
        bad = inspect_links(
            ROOT, "docs/README.md", "[broken](nonexistent-guard-fixture-zz.md)",
        )
        self.assertTrue(any("missing-link-target" in item for item in bad), bad)

    def test_parent_traversal_link_is_blocked(self):
        bad = inspect_links(
            ROOT, "docs/README.md", "[escape](../../../../../../outside-zz.md)",
        )
        self.assertTrue(any("escaped-repository" in item for item in bad), bad)

    def test_http_links_are_not_fetched(self):
        self.assertEqual(
            inspect_links(
                ROOT,
                "docs/README.md",
                "[outside](https://example.com/readme) [valid](models/README.md)",
            ),
            [],
        )

    def test_guard_is_collected_by_existing_readonly_pull_request_ci(self):
        workflow = (ROOT / ".github/workflows/operations-policy-guard.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(inspect_ci_contract(workflow), [])
        self.assertIn("docs/operations/tests", workflow)
        self.assertEqual(len(HUBS), 6)
        self.assertGreaterEqual(len(SCOPED_DOCS), 10)

    def test_trigger_or_collection_removal_is_blocked(self):
        workflow = (ROOT / ".github/workflows/operations-policy-guard.yml").read_text(
            encoding="utf-8"
        )
        malformed = workflow.replace(
            "python -m pytest -q docs/operations/tests",
            "python -m pytest -q .github/tests",
            1,
        )
        self.assertTrue(any("document-tests-not-collected" in x
                            for x in inspect_ci_contract(malformed)))
        malformed = workflow.replace("  pull_request:", "  other_event:", 1)
        self.assertTrue(any("pull_request-trigger-missing" in x
                            for x in inspect_ci_contract(malformed)))

    def test_ci_rejects_new_paths_filter(self):
        workflow = (ROOT / ".github/workflows/operations-policy-guard.yml").read_text(
            encoding="utf-8"
        )
        altered = workflow.replace(
            "  pull_request:\n",
            "  pull_request:\n    paths:\n      - 'docs/**'\n",
            1,
        )
        self.assertTrue(any("document-guard-trigger-path-filtered" in x
                            for x in inspect_ci_contract(altered)))

    def test_cli_runs_without_external_services(self):
        script = ROOT / "docs/operations/scripts/document_authority_integrity.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DOC_AUTHORITY_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
