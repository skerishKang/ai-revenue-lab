from __future__ import annotations

from pathlib import Path
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "architecture" / "B54_CLOUD_M1_SANDBOX_THREAT_MODEL_1405.md"


class CloudM1ThreatModelDocTests(unittest.TestCase):
    def test_threat_model_doc_exists_and_conforms(self):
        self.assertTrue(DOC_PATH.exists(), f"{DOC_PATH} must exist")
        content = DOC_PATH.read_text(encoding="utf-8")

        # Required issue reference and milestone
        self.assertIn("#1405", content)
        self.assertIn("Cloud M1", content)
        self.assertIn("ACT-A", content)

        # Invariants section
        required_invariants = [
            "NETWORK_DEFAULT = OFF",
            "PRIVILEGED_RUNTIME = FALSE",
            "HOST_MOUNTS = FALSE",
            "RUNTIME_SOCKET_EXPOSED = FALSE",
            "HOST_SECRET_INHERITANCE = NONE",
            "CROSS_RUN_REUSE = FORBIDDEN",
            "EXACT_REVISION_BINDING = REQUIRED",
            "TERMINAL_RESURRECTION = FORBIDDEN",
            "REAL_PROVIDER_SELECTED = NO",
            "REAL_PROVIDER_CALLS = 0",
            "PROVIDER_CREDENTIALS = 0",
            "PRODUCTION_MUTATION = 0",
        ]
        for inv in required_invariants:
            self.assertIn(inv, content, f"Missing invariant: {inv}")

        # Threat vector coverage
        required_threats = [
            "Untrusted Repository",
            "Cross-Run / Multi-Tenant Contamination",
            "Supply-Chain & Network Exfiltration",
            "Artifact Poisoning & Resource Exhaustion",
            "Terminal Escape & Control Sequence Poisoning",
            "Metadata & Cloud Credential Harvesting",
            "Bounded Resource Limits & Teardown Guarantees",
        ]
        for threat in required_threats:
            self.assertIn(threat, content, f"Missing threat category: {threat}")

        # Provider acceptance controls
        required_controls = [
            "isolation_primitive",
            "server_owned_lifecycle",
            "exact_revision_materialization",
            "checkout_hooks_disabled",
            "network_deny_by_default",
            "egress_policy_enforced",
            "privileged_runtime_disabled",
            "host_mounts_disabled",
            "runtime_socket_hidden",
            "provider_metadata_blocked",
            "host_secret_inheritance_disabled",
            "dedicated_workspace_per_run",
            "cross_run_reuse_disabled",
            "cpu_limit_enforced",
            "memory_limit_enforced",
            "disk_limit_enforced",
            "process_limit_enforced",
            "ttl_enforced",
            "cancellation_kills_workload",
            "teardown_guaranteed",
            "artifact_allowlist_enforced",
            "artifact_size_limit_enforced",
            "terminal_output_bounded",
            "terminal_output_sanitized",
            "image_or_snapshot_provenance",
            "run_lease_audit_correlation",
            "preview_ports_private_by_default",
        ]
        for ctrl in required_controls:
            self.assertIn(f"`{ctrl}`", content, f"Missing acceptance control: {ctrl}")

        # Conformance checks on markdown syntax
        lines = content.splitlines()
        non_empty = [line.strip() for line in lines if line.strip()]
        self.assertTrue(non_empty)
        last_line = non_empty[-1]
        self.assertNotEqual(last_line, "`", "Document must not end with a dangling backtick")
        self.assertTrue(not last_line.startswith("`") or last_line.startswith("```"))

        # Check code fence balance
        fences = [line.strip() for line in lines if line.strip().startswith("```")]
        self.assertEqual(len(fences) % 2, 0, f"Unbalanced code fences: {fences}")

        # Check for control characters
        raw_bytes = DOC_PATH.read_bytes()
        bad_control_chars = [b for b in raw_bytes if b < 32 and b not in (9, 10, 13)]
        self.assertEqual(bad_control_chars, [], f"Control characters detected: {bad_control_chars}")


if __name__ == "__main__":
    unittest.main()
