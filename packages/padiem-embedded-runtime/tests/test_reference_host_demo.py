"""Focused contract tests: reference host demo journey (S2)."""

import json
import os
import unittest

from reference_host.demo_host import run_demo

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "..", "fixtures", "demo_host_fixture.json")


class ReferenceHostDemoTests(unittest.TestCase):
    def test_deterministic_demo_journey(self):
        with open(FIXTURE_PATH, encoding="utf-8") as handle:
            fixture = json.load(handle)
        first = run_demo(fixture)
        second = run_demo(fixture)
        self.assertEqual(first, second)
        self.assertEqual(first["host_id"], "demo-host-01")
        self.assertEqual(first["final_state"], "disabled")
        self.assertEqual(first["host_primary_journey"], "unbroken")

        kinds = [step["step"] for step in first["steps"]]
        self.assertEqual(
            kinds,
            [
                "mount",
                "open",
                "opened",
                "context_received",
                "notice_posted",
                "close",
                "closed_event",
                "disable",
                "open_while_disabled",
            ],
        )
        context_step = first["steps"][3]
        self.assertEqual(context_step["dropped_reserved_count"], 2)
        last = first["steps"][-1]
        self.assertTrue(last["refused"])
        self.assertEqual(last["fallback"], "host-primary-continue")
        json.dumps(first)


if __name__ == "__main__":
    unittest.main()
