"""Source-only guard for #3990: never auto-route public PRs to a runner."""
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "infra/ci-runner-3990"
WORKFLOW = ROOT / ".github/workflows/ci-3990-ephemeral-runner-benchmark.yml"
BENCH = ROOT / ".github/scripts/ci_runner_3990_benchmark.py"


class EphemeralRunnerPilotContract(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text(encoding="utf-8")
        self.doc = yaml.load(self.source, Loader=yaml.BaseLoader)
        self.host = (BASE / "cloud-init-ubuntu2404-x64.yaml").read_text(encoding="utf-8")
        self.install = (BASE / "run-once-ubuntu2404-x64.sh").read_text(encoding="utf-8")
        self.guide = (BASE / "README.md").read_text(encoding="utf-8")

    def test_dispatch_only_on_main_never_on_public_pr(self):
        self.assertEqual(set(self.doc["on"]), {"workflow_dispatch"})
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(set(self.doc["jobs"]), {"validate", "benchmark"})
        for job in self.doc["jobs"].values():
            self.assertIn("github.ref == 'refs/heads/main'", job["if"])
        self.assertNotIn("pull_request:", self.source)
        self.assertNotIn("pull_request_target", self.source)
        self.assertNotIn("secrets.", self.source)
        self.assertNotIn("wrangler", self.source.lower())
        self.assertEqual(self.doc["concurrency"]["cancel-in-progress"], "false")

    def test_hosted_is_default_and_user_opt_in_to_pilot(self):
        options = self.doc["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(options["target"]["default"], "github-hosted")
        self.assertEqual(options["target"]["options"], ["github-hosted", "ephemeral"])
        self.assertEqual(options["runner_label"]["default"], "")
        self.assertEqual(self.doc["jobs"]["validate"]["runs-on"], "ubuntu-24.04")
        benchmark = self.doc["jobs"]["benchmark"]
        self.assertIn("self-hosted", benchmark["runs-on"])
        self.assertIn("Linux", benchmark["runs-on"])
        self.assertIn("X64", benchmark["runs-on"])
        self.assertIn("ubuntu-24.04", benchmark["runs-on"])
        self.assertIn("inputs.runner_label", benchmark["runs-on"])
        self.assertIn("needs", benchmark)
        self.assertIn("padiem-pilot-", self.source)
        self.assertIn("persist-credentials: false", self.source)
        self.assertIn("timeout-minutes: 23", self.source)

    def test_single_use_ephemeral_install_disallows_root_and_credentials(self):
        self.assertIn('id -un)', self.install)
        self.assertIn('"padiem-runner"', self.install)
        self.assertIn("x86_64", self.install)
        self.assertIn('"24.04"', self.install)
        self.assertIn("sha256sum --check --status", self.install)
        self.assertIn("actions/runner/releases/download/", self.install)
        self.assertIn("--ephemeral", self.install)
        self.assertIn("--disableupdate", self.install)
        self.assertNotIn("--replace", self.install)
        self.assertIn("IFS= read -r token", self.install)
        self.assertIn("1500s ./run.sh", self.install)
        self.assertIn("RUNNER_REPO_URL", self.install)
        self.assertNotIn("gh auth login", self.install)

    def test_vm_rejects_privilege_and_metadata_access(self):
        init = yaml.load(self.host, Loader=yaml.BaseLoader)
        self.assertIn("padiem-runner", self.host)
        self.assertIn("169.254.169.254/32", self.host)
        self.assertIn("100.100.100.200/32", self.host)
        self.assertEqual(init["ssh_pwauth"], "false")
        self.assertEqual(init["disable_root"], "true")
        self.assertEqual(init["users"][1]["sudo"], [])
        self.assertNotIn("ssh_authorized_keys", self.host)
        self.assertNotIn("runner-registration-token", self.host)

    def test_benchmark_has_three_bounded_source_only_trials(self):
        self.assertIn("range(1, 4)", BENCH.read_text(encoding="utf-8"))
        self.assertIn("timeout=180", BENCH.read_text(encoding="utf-8"))
        self.assertIn("refs/heads/main", BENCH.read_text(encoding="utf-8"))
        self.assertIn("test_b62_1819_product_surface_certification.py", BENCH.read_text(encoding="utf-8"))
        self.assertIn("test_b62_1887_post_certification_hardening.py", BENCH.read_text(encoding="utf-8"))
        self.assertIn("uv sync --locked --extra dev", self.source)
        self.assertIn("actions/upload-artifact@v4", self.source)
        for path in (
            "apps/padiem-chat/uv.lock",
            "apps/padiem-chat/tests/test_b62_1819_product_surface_certification.py",
            "apps/padiem-chat/tests/test_b62_1887_post_certification_hardening.py",
        ):
            self.assertTrue((ROOT / path).is_file(), path)

    def test_activation_is_explicitly_blocked_until_vm_exists(self):
        self.assertIn("STATE=SOURCE_READY_NOT_PROVISIONED", self.guide)
        self.assertIn("PUBLIC", self.guide)
        self.assertIn("no OCI/GCP", self.guide)
        self.assertIn("destroy", self.guide.lower())
        self.assertIn("#3523", self.guide)
        self.assertIn("No blanket runs-on switch", self.guide)


if __name__ == "__main__":
    unittest.main()