"""Focused contract tests: host-context bridge pipeline (S3)."""

import json
import unittest

from padiem_embedded_runtime import SidecarContractError
from padiem_embedded_runtime.bootstrap import parse_bootstrap_config
from padiem_embedded_runtime.bridge import intake_host_payload
from padiem_embedded_runtime.diagnostics import (
    REASON_BOOTSTRAP_REJECTED,
    REASON_CONTEXT_MALFORMED,
    REASON_OK,
    REASON_SHELL_DISABLED,
    REASON_VERSION_INCOMPATIBLE,
    STATUS_DEGRADED,
    STATUS_DISABLED,
    STATUS_READY,
)
from padiem_embedded_runtime.lifecycle import EmbeddedShell


def bootstrap(**overrides):
    raw = {
        "host_id": "bridge-host-01",
        "shell_version": "0.2.0",
        "locale": "ko",
        "features": ["context-panel"],
        "contract_version": "1.0",
    }
    raw.update(overrides)
    return raw


def shell_for(raw=None) -> EmbeddedShell:
    source = raw if raw is not None else bootstrap()
    stripped = {k: v for k, v in source.items() if k != "contract_version"}
    return EmbeddedShell(parse_bootstrap_config(stripped))


class HostContextBridgeTests(unittest.TestCase):
    def test_valid_path_projects_allowlisted_fields_only(self):
        outcome = intake_host_payload(
            bootstrap(),
            {"theme": "dark", "role": "admin", "tenant_id": "t-9", "surface": "panel"},
            shell_for(),
        )
        self.assertTrue(outcome.accepted)
        self.assertEqual(outcome.status, STATUS_READY)
        self.assertEqual(outcome.diagnostics.reason_code, REASON_OK)
        assert outcome.projection is not None
        public = outcome.projection.to_public_dict()
        self.assertEqual(public["trust_level"], "untrusted")
        self.assertEqual(public["context_fields"], {"theme": "dark", "surface": "panel"})
        self.assertEqual(sorted(public["dropped_reserved"]), ["role", "tenant_id"])
        self.assertNotIn("admin", json.dumps(public))
        self.assertNotIn("t-9", json.dumps(public))
        json.dumps(outcome.to_public_dict())

    def test_incompatible_version_disables_shell_fail_safe(self):
        shell = shell_for()
        outcome = intake_host_payload(
            bootstrap(contract_version="2.0"), {"theme": "dark"}, shell
        )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.status, STATUS_DISABLED)
        self.assertEqual(outcome.diagnostics.reason_code, REASON_VERSION_INCOMPATIBLE)
        self.assertIsNone(outcome.projection)
        self.assertEqual(shell.state, STATUS_DISABLED)
        guarded = shell.guard_open_interaction()
        self.assertIsNotNone(guarded)
        self.assertEqual(guarded.fallback, "host-primary-continue")

    def test_missing_version_is_unsupported_not_error(self):
        shell = shell_for()
        raw = bootstrap()
        del raw["contract_version"]
        outcome = intake_host_payload(raw, {"theme": "dark"}, shell)
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.status, STATUS_DISABLED)
        self.assertEqual(shell.state, STATUS_DISABLED)

    def test_malformed_context_degrades_without_disabling(self):
        shell = shell_for()
        outcome = intake_host_payload(bootstrap(), {"count": 3}, shell)
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.status, STATUS_DEGRADED)
        self.assertEqual(outcome.diagnostics.reason_code, REASON_CONTEXT_MALFORMED)
        self.assertIsNone(outcome.projection)
        self.assertNotEqual(shell.state, STATUS_DISABLED)

    def test_rejected_bootstrap_disables_with_public_reason_only(self):
        shell = shell_for()
        raw = bootstrap(shell_version="1.0")
        outcome = intake_host_payload(raw, {"theme": "dark"}, shell)
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.status, STATUS_DISABLED)
        self.assertEqual(outcome.diagnostics.reason_code, REASON_BOOTSTRAP_REJECTED)
        self.assertIsNone(outcome.projection)
        self.assertEqual(shell.state, STATUS_DISABLED)
        public = json.dumps(outcome.to_public_dict())
        self.assertNotIn("shell_version must be", public)
        self.assertNotIn("MAJOR.MINOR.PATCH", public)

    def test_disabled_shell_stays_disabled_and_host_safe(self):
        shell = shell_for()
        shell.disable("ops hold")
        outcome = intake_host_payload(bootstrap(), {"theme": "dark"}, shell)
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.status, STATUS_DISABLED)
        self.assertEqual(outcome.diagnostics.reason_code, REASON_SHELL_DISABLED)
        self.assertEqual(shell.state, STATUS_DISABLED)

    def test_non_mapping_bootstrap_never_raises(self):
        outcome = intake_host_payload("not-a-mapping", {"theme": "dark"}, shell_for())
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.status, STATUS_DISABLED)
        self.assertEqual(outcome.diagnostics.reason_code, REASON_BOOTSTRAP_REJECTED)

    def test_bridge_requires_validated_shell(self):
        with self.assertRaises(SidecarContractError):
            intake_host_payload(bootstrap(), {}, "not-a-shell")

    def test_deterministic_repeat(self):
        first = intake_host_payload(
            bootstrap(), {"theme": "dark"}, shell_for()
        ).to_public_dict()
        second = intake_host_payload(
            bootstrap(), {"theme": "dark"}, shell_for()
        ).to_public_dict()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
