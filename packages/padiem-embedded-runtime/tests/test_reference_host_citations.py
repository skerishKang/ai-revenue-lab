"""Focused contract tests: reference-host S4 citation journeys (deterministic)."""

import json
import os
import unittest

from reference_host.demo_host import run_citation_journey

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "s4_citation_fixture.json"
)


class ReferenceHostCitationTests(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE_PATH, encoding="utf-8") as handle:
            self.fixture = json.load(handle)

    def test_three_paths_are_deterministic(self):
        first = run_citation_journey(self.fixture)
        second = run_citation_journey(self.fixture)
        self.assertEqual(first, second)
        json.dumps(first)

    def test_normal_path_orders_dedups_and_labels(self):
        paths = run_citation_journey(self.fixture)["paths"]
        normal = paths["normal"]
        self.assertEqual(normal["status"], "ready")
        labels = [c["label"] for c in normal["citations"]]
        self.assertEqual(labels, ["[1]", "[2]", "[3]"])
        self.assertEqual(normal["dropped_count"], 0)

    def test_empty_path_is_empty(self):
        paths = run_citation_journey(self.fixture)["paths"]
        self.assertEqual(paths["empty"]["status"], "empty")
        self.assertEqual(paths["empty"]["citations"], [])

    def test_degraded_path_drops_without_leaking(self):
        paths = run_citation_journey(self.fixture)["paths"]
        degraded = paths["degraded"]
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["dropped_count"], 3)
        self.assertEqual(len(degraded["citations"]), 1)
        public = json.dumps(degraded)
        self.assertNotIn("api_key", public)
        self.assertNotIn("unknown field", public)

    def test_host_journey_unbroken(self):
        self.assertEqual(
            run_citation_journey(self.fixture)["host_primary_journey"], "unbroken"
        )


if __name__ == "__main__":
    unittest.main()
