"""#3989: preserve all always-on Operations Policy Guard checks while batching pytest."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/operations-policy-guard.yml"

ORIGINAL_PYTEST_TARGETS = (
    "docs/operations/tests",
    ".github/tests/test_pr_contract_guard.py",
    ".github/tests/test_r2_credential_authority_split.py",
    ".github/tests/test_b62_pr_preview_trigger_scope.py",
    ".github/tests/test_b62_worker_deploy_trigger_scope.py",
    ".github/tests/test_3989_engine_living_learning_ci_scope.py",
    ".github/tests/test_cross_lane_test_dependency_guard.py",
    ".github/tests/test_frozen_source_checkout_byte_guard.py",
    ".github/tests/test_verify_import_origin.py",
    "tools/b66_generic/tests/test_b66_generic_archive_bounds.py",
)
BATCH_CONTRACT = ".github/tests/test_3989_operations_guard_pytest_batch.py"


class OperationsGuardBatchContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.policy = cls.source.split("\n  policy-consistency:\n", 1)[1].split(
            "\n  pr-contract:\n", 1
        )[0]
        cls.reporter = cls.source.split("\n  pr-contract:\n", 1)[1]

    def test_both_original_job_ids_names_and_always_pr_trigger_remain(self):
        self.assertIn("name: Operations Policy Guard", self.source)
        self.assertIn("\non:\n  pull_request:\n  workflow_dispatch:", self.source)
        self.assertIn("name: Operating policy consistency", self.policy)
        self.assertIn("name: Pull request contract report", self.reporter)
        self.assertIn("if: always()", self.reporter)
        self.assertIn("run: python .github/scripts/pr_contract_guard.py", self.reporter)
        self.assertIn("sparse-checkout: |", self.reporter)
        self.assertIn("sparse-checkout-cone-mode: false", self.reporter)
        self.assertIn(".github/scripts/pr_contract_guard.py", self.reporter)
        # The blocking policy tests must continue using the entire repository.
        self.assertNotIn("sparse-checkout:", self.policy)
        self.assertEqual(self.reporter.count("uses: actions/checkout@v4"), 1)
        self.assertIn("PR_CONTRACT_GUARD_MODE=REPORT_BY_DEFAULT", self.reporter)
        self.assertIn("  cancel-in-progress: true", self.source)
        self.assertIn("contents: read", self.source)

    def test_every_original_pytest_target_retained_exactly_once(self):
        # Both source-owner contracts require these exact independent CI
        # invocations. Preserve them instead of editing those tests.
        self.assertIn(
            "run: python -m pytest -q docs/operations/tests", self.policy
        )
        self.assertIn(
            "run: python -m pytest -q "
            ".github/tests/test_3989_engine_living_learning_ci_scope.py",
            self.policy,
        )
        self.assertEqual(self.policy.count("python -m pytest -q"), 3)
        block = self.policy.split(
            "      - name: Run remaining policy and security contract tests", 1
        )[1].split("      - name: Record guard scope", 1)[0]
        self.assertIn("python -m pytest -q", block)
        for target in (*ORIGINAL_PYTEST_TARGETS[1:5],
                       *ORIGINAL_PYTEST_TARGETS[6:], BATCH_CONTRACT):
            with self.subTest(target=target):
                self.assertEqual(block.count("\n            " + target), 1)
        # The two independently owned suites are not needlessly re-collected.
        for target in (ORIGINAL_PYTEST_TARGETS[0], ORIGINAL_PYTEST_TARGETS[5]):
            self.assertNotIn("\n            " + target, block)
        for forbidden in (
            "--ignore", "--deselect", "--continue-on-collection-errors",
            " -x ", " -k ", " --lf", "--last-failed", "--maxfail",
            "continue-on-error:", "|| true",
        ):
            self.assertNotIn(forbidden, block)

    def test_direct_fail_closed_script_guards_still_run(self):
        for script in (
            ".github/scripts/cross_lane_test_dependency_guard.py",
            ".github/scripts/frozen_source_checkout_byte_guard.py",
        ):
            self.assertIn("run: python " + script, self.policy)
            self.assertEqual(self.policy.count("run: python " + script), 1)
        self.assertIn("OPERATIONS_POLICY_GUARD=PASSED", self.policy)
        self.assertIn("CROSS_LANE_DEPENDENCY_GUARD=ENFORCED", self.policy)
        self.assertIn("FROZEN_SOURCE_PIN_GUARD=ENFORCED", self.policy)
        self.assertIn("PRODUCTION_MUTATION=NO", self.policy)


if __name__ == "__main__":
    unittest.main()
