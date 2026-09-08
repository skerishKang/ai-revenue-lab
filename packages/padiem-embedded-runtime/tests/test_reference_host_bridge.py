"""Focused contract tests: reference-host S3 bridge journeys (deterministic)."""

import json
import os
import unittest

from reference_host.demo_host import run_bridge_journey

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "s3_bridge_fixture.json"
)


class ReferenceHostBridgeTests(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE_PATH, encoding="utf-8") as handle:
            self.fixture = json.load(handle)

    def test_four_paths_are_deterministic(self):
        first = run_bridge_journey(self.fixture)
        second = run_bridge_journey(self.fixture)
        self.assertEqual(first, second)
        json.dumps(first)

    def test_normal_path_ready_and_untrusted(self):
        paths = run_bridge_journey(self.fixture)["paths"]
        self.assertEqual(paths["normal"]["status"], "ready")
        self.assertTrue(paths["normal"]["accepted"])
        self.assertEqual(paths["normal"]["shell_state"], "closed")
        self.assertEqual(paths["normal"]["dropped_reserved_count"], 2)

    def test_incompatible_version_disables(self):
        paths = run_bridge_journey(self.fixture)["paths"]
        self.assertEqual(paths["incompatible"]["status"], "disabled")
        self.assertEqual(paths["incompatible"]["reason_code"], "VERSION_INCOMPATIBLE")
        self.assertEqual(paths["incompatible"]["shell_state"], "disabled")

    def test_malformed_context_degrades(self):
        paths = run_bridge_journey(self.fixture)["paths"]
        self.assertEqual(paths["malformed"]["status"], "degraded")
        self.assertEqual(paths["malformed"]["reason_code"], "CONTEXT_MALFORMED")

    def test_disabled_path_keeps_host_journey(self):
        result = run_bridge_journey(self.fixture)
        self.assertEqual(result["paths"]["disabled"]["status"], "disabled")
        self.assertEqual(result["host_primary_journey"], "unbroken")


if __name__ == "__main__":
    unittest.main()
