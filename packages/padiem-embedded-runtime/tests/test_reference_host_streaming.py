"""S7 reference-host streaming journey tests (network-free, fixture-driven)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from reference_host.demo_host import run_streaming_journey

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "s7_streaming_fixture.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class StreamingJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.journey = run_streaming_journey(load_fixture())

    def test_journey_never_breaks_host_primary_flow(self) -> None:
        self.assertEqual(self.journey["host_primary_journey"], "unbroken")

    def test_lifecycle_flow_orders_fresh_duplicate_and_conflict(self) -> None:
        feed = self.journey["paths"]["lifecycle_flow"]
        self.assertEqual(
            [entry["ordering"] for entry in feed],
            [
                "fresh",
                "fresh",
                "fresh",
                "fresh",
                "duplicate",
                "conflict",
                "fresh",
                "fresh",
                "fresh",
                "conflict",
            ],
        )
        self.assertEqual([entry["sequence"] for entry in feed[:4]], [1, 2, 3, 4])
        self.assertEqual(feed[1]["run_status"], "running")

    def test_conflicts_degrade_without_advancing(self) -> None:
        feed = self.journey["paths"]["lifecycle_flow"]
        for index in (5, 9):
            conflict = feed[index]
            self.assertTrue(conflict["degraded"])
            self.assertEqual(conflict["run_status"], "unavailable")
            self.assertEqual(conflict["reason_code"], "OUT_OF_ORDER_REPLAY")
        self.assertEqual(feed[6]["sequence"], 5)

    def test_malformed_event_degrades_without_leak(self) -> None:
        malformed = self.journey["paths"]["lifecycle_malformed"]
        self.assertTrue(malformed["degraded"])
        self.assertEqual(malformed["reason_code"], "INVALID_HOST_INPUT")
        self.assertNotIn("provider_raw_delta", json.dumps(malformed))
        self.assertNotIn("raw provider bytes", json.dumps(malformed))

    def test_error_flow_presents_allowlisted_reasons(self) -> None:
        flow = self.journey["paths"]["error_flow"]
        presented = [item for item in flow if item["status"] == "presented"]
        self.assertEqual(
            [item["reason_code"] for item in presented],
            [
                "RUN_FAILED",
                "RUN_TIMED_OUT",
                "RUN_CANCELLED",
                "STREAM_INTERRUPTED",
                "UPSTREAM_UNAVAILABLE",
            ],
        )

    def test_error_flow_rejects_unsafe_inputs_without_echo(self) -> None:
        flow = self.journey["paths"]["error_flow"]
        rejected = [item for item in flow if item["status"] == "rejected"]
        self.assertEqual(
            [item["reason_code"] for item in rejected],
            [
                "INVALID_REASON_CODE",
                "INVALID_SUMMARY",
                "INVALID_RUN_ID",
                "UNKNOWN_FIELDS",
            ],
        )
        blob = json.dumps(rejected)
        for banned in ("leak.example", "Traceback", "upstream response body", "run s7 01"):
            self.assertNotIn(banned, blob)

    def test_affordance_flow_stages_only_permitted_states(self) -> None:
        flow = self.journey["paths"]["affordance_flow"]
        staged = [item for item in flow if item["status"] == "staged"]
        self.assertEqual(
            [(item["affordance"], item["run_id"]) for item in staged],
            [("retry", "run_s7_01"), ("reconnect", "run_s7_01"), ("cancel", "run_s7_01")],
        )
        self.assertTrue(all(item["reason_code"] == "" for item in staged))

    def test_affordance_flow_rejections_are_reason_coded(self) -> None:
        flow = self.journey["paths"]["affordance_flow"]
        rejected = [item for item in flow if item["status"] == "rejected"]
        self.assertEqual(
            [item["reason_code"] for item in rejected],
            [
                "STATE_DOES_NOT_PERMIT",
                "STATE_DOES_NOT_PERMIT",
                "INVALID_AFFORDANCE",
                "INVALID_RUN_ID",
                "INVALID_RUN_STATUS",
            ],
        )
        blob = json.dumps(rejected)
        self.assertNotIn("force_execute", blob)
        self.assertNotIn("succeeded", blob)

    def test_journey_is_repeatable(self) -> None:
        again = run_streaming_journey(load_fixture())
        self.assertEqual(again, self.journey)

    def test_invalid_fixture_shapes_raise_contract_errors(self) -> None:
        fixture = load_fixture()
        for key in ("lifecycle_flow", "error_flow", "affordance_flow", "lifecycle_malformed"):
            with self.subTest(key=key):
                broken = dict(fixture)
                broken[key] = "invalid-shape"
                with self.assertRaises(Exception):
                    run_streaming_journey(broken)


if __name__ == "__main__":
    unittest.main()
