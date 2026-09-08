"""S6 reference-host approval journey tests (network-free, fixture-driven)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from reference_host.demo_host import run_approval_journey

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "s6_approval_fixture.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class ApprovalJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.journey = run_approval_journey(load_fixture())

    def test_journey_never_breaks_host_primary_flow(self) -> None:
        self.assertEqual(self.journey["host_primary_journey"], "unbroken")

    def test_normal_path_orders_dedups_and_labels(self) -> None:
        normal = self.journey["paths"]["proposals_normal"]
        self.assertEqual(normal["status"], "ready")
        self.assertEqual(normal["dropped_count"], 0)
        ids = [p["proposal_id"] for p in normal["proposals"]]
        self.assertEqual(ids, ["prop_1001", "prop_1002"])
        self.assertEqual([p["label"] for p in normal["proposals"]], ["[1]", "[2]"])

    def test_empty_path_is_empty_status(self) -> None:
        empty = self.journey["paths"]["proposals_empty"]
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["proposals"], [])

    def test_degraded_path_drops_safely(self) -> None:
        degraded = self.journey["paths"]["proposals_degraded"]
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["dropped_count"], 6)
        self.assertEqual(
            [p["proposal_id"] for p in degraded["proposals"]], ["prop_ok"]
        )
        self.assertEqual(
            degraded["drop_reasons"], ["INVALID_FIELD", "MALFORMED_ITEM"]
        )
        blob = json.dumps(degraded)
        for banned in ("leak.example", "diff --git", "tool_args", "Users", "args"):
            self.assertNotIn(banned, blob)

    def test_intent_flow_stages_allowlisted_intents(self) -> None:
        flow = self.journey["paths"]["intent_flow"]
        self.assertEqual(
            [step["intent"] for step in flow],
            ["approve", "confirm", "cancel", "reject"],
        )
        self.assertTrue(all(step["status"] == "staged" for step in flow))
        self.assertTrue(all(step["reason_code"] == "" for step in flow))

    def test_malformed_intent_rejected_without_echo(self) -> None:
        malformed = self.journey["paths"]["intent_malformed"]
        self.assertEqual(malformed["status"], "rejected")
        self.assertEqual(malformed["reason_code"], "INVALID_INTENT")
        self.assertEqual(malformed["intent"], "")
        self.assertNotIn("force_execute", json.dumps(malformed))

    def test_state_flow_is_deterministic(self) -> None:
        flow = self.journey["paths"]["state_flow"]
        self.assertEqual(
            [step["state"] for step in flow],
            ["pending", "approved", "rejected", "expired", "unavailable"],
        )
        self.assertFalse(any(step["degraded"] for step in flow))
        self.assertEqual(flow[2]["reason_code"], "USER_REJECTED")
        self.assertEqual(flow[3]["reason_code"], "AUTHORITY_TIMEOUT")
        self.assertEqual(flow[4]["reason_code"], "AUTHORITY_UNAVAILABLE")

    def test_malformed_state_degrades_to_unavailable(self) -> None:
        malformed = self.journey["paths"]["state_malformed"]
        self.assertTrue(malformed["degraded"])
        self.assertEqual(malformed["state"], "unavailable")
        self.assertEqual(malformed["reason_code"], "INVALID_HOST_INPUT")
        self.assertNotIn("auto_approved", json.dumps(malformed))

    def test_reference_paths_present_and_reject(self) -> None:
        valid = self.journey["paths"]["reference_valid"]
        self.assertEqual(valid["status"], "presented")
        self.assertEqual(valid["label"], "evidence_9f2c1a7b")
        invalid = self.journey["paths"]["reference_invalid"]
        self.assertEqual(invalid["status"], "rejected")
        self.assertEqual(invalid["reason_code"], "URL_SHAPED_REFERENCE")
        self.assertEqual(invalid["label"], "")
        self.assertNotIn("authority.example", json.dumps(invalid))

    def test_journey_is_repeatable(self) -> None:
        again = run_approval_journey(load_fixture())
        self.assertEqual(again, self.journey)


if __name__ == "__main__":
    unittest.main()
