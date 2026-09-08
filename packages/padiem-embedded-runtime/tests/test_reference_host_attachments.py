"""S5 reference-host attachment journey tests (network-free, fixture-driven)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from reference_host.demo_host import run_attachment_journey

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "s5_attachment_fixture.json"
)


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class AttachmentJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.journey = run_attachment_journey(load_fixture())

    def test_journey_never_breaks_host_primary_flow(self) -> None:
        self.assertEqual(self.journey["host_primary_journey"], "unbroken")

    def test_normal_path_orders_dedups_and_hints(self) -> None:
        normal = self.journey["paths"]["selections_normal"]
        self.assertEqual(normal["status"], "ready")
        self.assertEqual(normal["dropped_count"], 0)
        names = [s["name"] for s in normal["selections"]]
        self.assertEqual(names, ["photo.png", "scan 01.jpeg", "diagram.webp", "notes.pdf"])
        labels = [s["label"] for s in normal["selections"]]
        self.assertEqual(labels, ["[1]", "[2]", "[3]", "[4]"])
        self.assertIn("SUPPORTED_MEDIA_TYPE", normal["selections"][0]["hints"])
        self.assertEqual(normal["selections"][3]["hints"], ["UNSUPPORTED_SHARED_MEDIA_TYPE"])

    def test_empty_path_is_empty_status(self) -> None:
        empty = self.journey["paths"]["selections_empty"]
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["selections"], [])

    def test_degraded_path_drops_safely(self) -> None:
        degraded = self.journey["paths"]["selections_degraded"]
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["dropped_count"], 6)
        self.assertEqual([s["name"] for s in degraded["selections"]], ["ok.png"])
        self.assertNotIn("evil", json.dumps(degraded))
        self.assertNotIn("Users", json.dumps(degraded))

    def test_lifecycle_flow_is_deterministic(self) -> None:
        flow = self.journey["paths"]["lifecycle_flow"]
        self.assertEqual(
            [step["state"] for step in flow],
            ["idle", "selecting", "validating", "ready", "uploaded", "failed"],
        )
        self.assertFalse(any(step["degraded"] for step in flow))
        self.assertEqual(flow[5]["reason_code"], "UPLOAD_REJECTED")

    def test_malformed_lifecycle_degrades_without_raising(self) -> None:
        malformed = self.journey["paths"]["lifecycle_malformed"]
        self.assertTrue(malformed["degraded"])
        self.assertEqual(malformed["state"], "idle")
        self.assertEqual(malformed["reason_code"], "INVALID_HOST_INPUT")
        self.assertNotIn("exploded", json.dumps(malformed))

    def test_ref_paths_present_and_reject(self) -> None:
        valid = self.journey["paths"]["ref_valid"]
        self.assertEqual(valid["status"], "presented")
        self.assertTrue(valid["label"].startswith("att_"))
        invalid = self.journey["paths"]["ref_invalid"]
        self.assertEqual(invalid["status"], "rejected")
        self.assertEqual(invalid["reason_code"], "URL_SHAPED_REF")
        self.assertEqual(invalid["label"], "")

    def test_journey_is_repeatable(self) -> None:
        again = run_attachment_journey(load_fixture())
        self.assertEqual(again, self.journey)


if __name__ == "__main__":
    unittest.main()
