"""Regression for trusted COM2 touch auto canary (#5210).

Keep source-policy assertions narrow: the workflow must not execute PR code
on the host, must validate exact same-repo PR SHA, and must skip closed PRs.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
AUTO = ROOT / ".github/workflows/com2-b62-touch-auto.yml"
HOSTED = ROOT / ".github/workflows/b62-browser-qa-unified.yml"

class TouchAutoCanaryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auto = AUTO.read_text(encoding="utf-8")
        cls.hosted = HOSTED.read_text(encoding="utf-8")

    def test_trusted_policy_event_independent_from_hosted_qa(self):
        self.assertIn('workflows: ["COM2 PR Policy Trigger"]', self.auto)
        self.assertIn("github.event.workflow_run.event == 'pull_request'", self.auto)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.auto)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", self.auto)

    def test_closed_pr_race_skips_checkout_and_execution(self):
        self.assertIn('if len(valid)!=1:', self.auto)
        self.assertIn('print("skip")', self.auto)
        self.assertIn('if [[ "$PR" == skip ]]', self.auto)
        self.assertIn('echo "selected=false"', self.auto)
        self.assertGreaterEqual(self.auto.count("if: steps.target.outputs.selected == 'true'"), 2)

    def test_exact_sha_and_isolated_execution(self):
        self.assertIn('p["head"]["sha"]==sha', self.auto)
        self.assertIn('p["head"]["repo"]["full_name"]==repo', self.auto)
        self.assertIn("persist-credentials: false", self.auto)
        self.assertIn("sudo -n /usr/local/sbin/padiem-ci-b62-touch-check", self.auto)
        self.assertIn("if-no-files-found: ignore", self.auto)

    def test_hosted_mobile_fallback_kept(self):
        self.assertRegex(self.hosted, r"(?m)^  mobile-touch-target-qa:$")
        self.assertIn("runs-on: ubuntu-24.04", self.hosted)
        self.assertIn("Verify 390x844 mobile touch targets", self.hosted)

    def test_failed_touch_dispatch_is_scoped_and_does_not_hide_failure(self):
        self.assertIn('actions: write', self.auto)
        self.assertIn("steps.run_touch.outcome == 'failure'", self.auto)
        self.assertIn('failure() && steps.target.outputs.selected', self.auto)
        self.assertIn('if [[ "$PR" == skip ]]', self.auto)
        self.assertIn('p["head"]["sha"]==os.environ["EXPECTED"]', self.auto)
        self.assertIn('p["head"]["repo"]["full_name"]==os.environ["GITHUB_REPOSITORY"]', self.auto)
        self.assertIn('b62-mobile-touch-hosted-fallback.yml/dispatches', self.auto)
        self.assertIn('"expected_sha":os.environ["EXPECTED"]', self.auto)
        self.assertIn('if [[ "$RESULT" == success ]]; then state=success; else state=failure; fi', self.auto)
if __name__ == "__main__":
    unittest.main()
