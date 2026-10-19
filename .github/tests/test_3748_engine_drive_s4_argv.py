"""#3748 / #3873: Drive S4 served-version argv and PR-only source contract.

The existing live S4 job is manual-only; these tests never access Cloudflare,
Engine, Google Drive or credentials. The guard subprocess consumes only a
synthetic local version-detail fixture and prints bounded name/type markers.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-engine-drive-s4-readonly-gate.yml"
GUARD = ROOT / ".github/scripts/b54_engine_served_version_guard.py"
ID = "-canonical-safe-v1"
SECRET = "S4-FIXTURE-DO-NOT-PRINT"
DB = "6b77ad02-bc27-488f-bb97-6325f6750cba"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _fixture() -> dict:
    return {
        "success": True,
        "result": {
            "id": ID,
            "resources": {
                "bindings": [
                    {"name": "PADIEM_ENGINE_CALLER_REGISTRY_V1", "type": "secret_text", "text": SECRET},
                    {"name": "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY", "type": "secret_text", "text": "synthetic-overlay-hidden"},
                    {"name": "ENGINE_CONNECTOR_GRANTS", "type": "d1", "id": DB},
                    {"name": "CONTROL_PLANE_GOOGLE_OAUTH", "type": "service", "service": "padiem-google-oauth-state"},
                ]
            },
        },
    }


def _cli(*active_version_flags: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "synthetic-version.json"
        path.write_text(json.dumps(_fixture()), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(GUARD),
                "verify",
                "--version-settings",
                str(path),
                *active_version_flags,
                "--require-drive-runtime-bindings",
                "--expect-overlay",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )


class DriveS4SourceContract(unittest.TestCase):
    def test_exactly_one_unambiguous_workflow_argv(self) -> None:
        src = _workflow()
        self.assertEqual(src.count('--active-version="${active_version}"'), 1)
        self.assertNotIn('--active-version "${active_version}"', src)

    def test_source_job_is_PR_only_and_excludes_network(self) -> None:
        src = _workflow()
        self.assertIn("  pull_request:\n    paths:", src)
        self.assertIn('.github/workflows/b54-engine-drive-s4-readonly-gate.yml', src)
        self.assertIn('.github/tests/test_3748_engine_drive_s4_argv.py', src)
        job = src.split("\n  source-contract:\n", 1)[1].split("\n  drive-s4-readonly:\n", 1)[0]
        self.assertIn("if: github.event_name == 'pull_request'", job)
        self.assertIn("github.event.pull_request.head.sha", job)
        self.assertIn("python .github/tests/test_3748_engine_drive_s4_argv.py", job)
        self.assertIn("S4_ARGV_SOURCE_CONTRACT=PASS", job)
        self.assertIn("LIVE_ENGINE_REQUESTS=0", job)
        for forbidden in ("curl ", "urllib", "wrangler ", "workflow_dispatch", "secrets.", "/internal/v1/"):
            self.assertNotIn(forbidden, job)

    def test_original_live_gate_remains_manual_and_bounded(self) -> None:
        src = _workflow()
        live = src.split("\n  drive-s4-readonly:\n", 1)[1]
        self.assertIn("github.event_name == 'workflow_dispatch'", live)
        self.assertIn("github.event.inputs.confirmation == 'RUN_B54_ENGINE_DRIVE_S4_READONLY_ONCE'", live)
        self.assertIn("environment: production", live)
        self.assertIn("S4_EXACT_MAIN=PASS", live)
        self.assertIn("--require-drive-runtime-bindings", live)
        self.assertIn("--expect-overlay", live)
        self.assertIn('\"tool_id\": \"tool:google:drive.a11_smoke_unregistered@1\"', live)
        self.assertIn("S4_DRIVE_CLASSIFICATION=DRIVE_REGISTRY_PROVEN", live)
        self.assertIn("DRIVE_PROVIDER_CALLS=0", live)
        self.assertIn("D1_MUTATION=0", live)
        self.assertIn("OAUTH_MUTATION=0", live)

    def test_real_guard_accepts_safe_leading_hyphen_with_equal_form(self) -> None:
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9._-]{1,64}", ID))
        result = _cli(f"--active-version={ID}")
        self.assertEqual(result.returncode, 0, result.stderr)
        for marker in (
            "B54_ENGINE_SERVED_VERSION_GUARD=PASS",
            "ENGINE_CONNECTOR_GRANTS_SERVED_BINDING=PRESENT:d1",
            "CONTROL_PLANE_GOOGLE_OAUTH_SERVED_BINDING=PRESENT:service",
            "DRIVE_RUNTIME_BINDINGS_VALIDATED=YES",
        ):
            self.assertIn(marker, result.stdout)

    def test_real_guard_rejects_spaced_argv_as_argparse_error(self) -> None:
        result = _cli("--active-version", ID)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("expected one argument", result.stderr)
        self.assertNotIn("DRIVE_RUNTIME_BINDINGS_VALIDATED=YES", result.stdout)

    def test_real_guard_rejects_mismatched_version(self) -> None:
        result = _cli("--active-version=-different-safe-id")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("B54_ENGINE_SERVED_VERSION_GUARD=FAIL", result.stderr)
        self.assertNotIn("DRIVE_RUNTIME_BINDINGS_VALIDATED=YES", result.stdout)

    def test_fixture_values_never_appear_in_guard_output(self) -> None:
        for args in ((f"--active-version={ID}",), ("--active-version", ID), ("--active-version=-different-safe-id",)):
            result = _cli(*args)
            both = result.stdout + result.stderr
            for value in (SECRET, DB, "synthetic-overlay-hidden"):
                with self.subTest(args=args, value=value):
                    self.assertNotIn(value, both)


if __name__ == "__main__":
    unittest.main()
