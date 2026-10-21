"""B62 browser QA planner regressions run in COM2's isolated offline image.

This is the same eleven test-module set formerly executed on GitHub-hosted
B62 plan jobs. The GitHub-hosted plan continues to classify exact PR changes.
"""
import sys
import unittest

MODULES = (
    "test_b62_browser_qa_unified.py",
    "test_3989_b62_visual_leaf_smoke.py",
    "test_3989_b62_owner_leaf_browser_base.py",
    "test_3989_b62_headless_shell_install.py",
    "test_3989_b66_quote_css_scope.py",
    "test_3989_claw_manual_css_scope.py",
    "test_3989_claw_quote_css_scope.py",
    "test_4459_b62_ui_only_css_scope.py",
    "test_4459_b62_ui_mixed_scope.py",
    "test_3989_b62_browser_tail_parallel.py",
    "test_3989_b62_glass_timing_ownership.py",
)


def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(
        loader.discover(".github/tests", pattern=module) for module in MODULES
    )
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(
        f"COM2_B62_PLANNER_TESTS={result.testsRun} "
        f"FAILURES={len(result.failures)} ERRORS={len(result.errors)}"
    )
    return 0 if result.wasSuccessful() and result.testsRun > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
