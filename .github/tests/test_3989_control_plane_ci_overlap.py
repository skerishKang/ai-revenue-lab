"""#3989: retain Control Plane full pytest and all six Worker packages."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/padiem-control-plane-ci.yml"
SCRIPT = ROOT / ".github/scripts/control_plane_ci_overlap_3989.sh"

CONFIGS = (
    "wrangler.local-agent-broker.jsonc",
    "wrangler.local-agent-broker-edge.jsonc",
    "wrangler.google-oauth.jsonc",
    "wrangler.google-oauth-edge.jsonc",
    "wrangler.identity-authority.jsonc",
    "wrangler.engine-admission-authority.jsonc",
)
OUTPUTS = (
    "b54-state-dry-run", "b54-edge-dry-run",
    "b54-google-oauth-state-dry-run", "b54-google-oauth-edge-dry-run",
    "control-plane-identity-dry-run", "control-plane-engine-admission-dry-run",
)
PROOFS = (
    "LOCAL_AGENT_WORKER_PACKAGING_PREFLIGHT=PASS",
    "GOOGLE_OAUTH_WORKER_PACKAGING_PREFLIGHT=PASS",
    "CONTROL_PLANE_IDENTITY_WORKER_PACKAGING_PREFLIGHT=PASS",
    "CONTROL_PLANE_ENGINE_ADMISSION_WORKER_PACKAGING_PREFLIGHT=PASS",
    "PRIVATE_SERVICE_BINDING_RPC=YES",
    "SERVER_OWNED_CONNECTOR_CONTEXT=YES",
    "CLIENT_ACTOR_ACCOUNT_WORKSPACE_AUTHORITY=NO",
    "PROVIDER_SUBJECT_PERSISTED=NO",
    "PUBLIC_ROUTE_CONFIGURED=NO",
    "PRODUCTION_MUTATION=NO",
)

class ControlPlaneCiOverlapContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wf = WORKFLOW.read_text(encoding="utf-8")
        cls.sh = SCRIPT.read_text(encoding="utf-8")

    def test_required_scope_stays_exact(self):
        for v in ("name: Padiem Control Plane CI", "  control-plane-contracts:",
                  "Assert foundation package has no runtime side-effect client",
                  "Compile Control Plane contracts", "Install Control Plane package",
                  "Set up Node for Python Worker packaging", "Install uv for Python Worker packaging",
                  "cancel-in-progress: true", "contents: read",
                  "packages/padiem-control-plane/**", "control_plane_ci_overlap_3989.sh"):
            self.assertIn(v, self.wf)

    def test_all_six_builds_and_full_proofs_survive(self):
        self.assertEqual(len(re.findall(r"run_package wrangler\.[\w.-]+\.jsonc ", self.sh)), 6)
        for config, output in zip(CONFIGS, OUTPUTS):
            self.assertIn("run_package " + config + " " + output, self.sh)
            self.assertTrue((ROOT / "packages/padiem-control-plane" / config).is_file())
        for marker in PROOFS:
            self.assertIn(marker, self.sh)
        for marker in ("workers-py>=1.17.1,<2", "--dry-run", "--secrets-file"):
            self.assertIn(marker, self.sh)

    def test_two_mandatory_results_and_no_mutating_checkout(self):
        for marker in ('cp -a "$repo_root/packages/padiem-control-plane" "$scratch/padiem-control-plane"',
                       'cd "$repo_root/packages/padiem-control-plane"', 'cd "$work"',
                       "pytest -q", 'wait "$tests_pid" || tests_status=$?',
                       'wait "$packages_pid" || packages_status=$?',
                       'if [[ "$tests_status" -ne 0 || "$packages_status" -ne 0 ]]',
                       'CONTROL_PLANE_CI_OVERLAP=PASS', 'test ! -e "$config"',
                       'test -d "$scratch/$output_name"', "trap cleanup EXIT"):
            self.assertIn(marker, self.sh)
        for forbidden in ("--deselect", "--ignore", " -k ", " --lf",
                          "continue-on-error:", "|| true", "set +e"):
            self.assertNotIn(forbidden, self.sh)

if __name__ == "__main__":
    unittest.main()
