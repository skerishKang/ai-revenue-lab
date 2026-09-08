"""B53 reference-host conformance journey tests.

The journey must be deterministic, network-free, and host-safe end to end:
valid input is handed off to IP-SIDECAR projections, malformed input
degrades, and the fail-safe disable path never breaks the host journey.
"""

import json
import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP_ROOT.parents[1]
sys.path.insert(0, str(_APP_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "packages" / "padiem-embedded-runtime"))

from app import reference_host  # noqa: E402


class ReferenceHostJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = reference_host.load_fixture()
        cls.journey = reference_host.run_conformance_journey(cls.fixture)
        cls.paths = cls.journey["paths"]

    def test_fixture_and_journey_are_json_serializable(self):
        json.dumps(self.journey, ensure_ascii=False)

    def test_journey_is_deterministic(self):
        second = reference_host.run_conformance_journey(self.fixture)
        self.assertEqual(self.journey, second)
        self.assertEqual(self.journey["host_primary_journey"], "unbroken")

    def test_host_context_handoff(self):
        intake = self.paths["intake_valid"]
        self.assertTrue(intake["accepted"])
        self.assertEqual(intake["status"], "ready")
        self.assertEqual(intake["projection"]["trust_level"], "untrusted")
        self.assertEqual(intake["projection"]["context_fields"]["page"], "settlement-dashboard")
        self.assertEqual(sorted(intake["projection"]["dropped_reserved"]), ["role", "tenant_id"])
        self.assertEqual(self.paths["shell_state_after_valid"], "closed")

    def test_malformed_context_degrades_without_breaking_host(self):
        intake = self.paths["intake_malformed"]
        self.assertFalse(intake["accepted"])
        self.assertEqual(intake["status"], "degraded")
        self.assertIsNone(intake["projection"])
        self.assertEqual(self.paths["shell_state_after_malformed"], "closed")
        self.assertEqual(self.paths["diagnostics"]["reason_code"], "CONTEXT_MALFORMED")

    def test_stream_feed_ordering_and_degradation(self):
        orderings = [entry["ordering"] for entry in self.paths["stream_feed"]]
        self.assertEqual(orderings, ["fresh", "fresh", "duplicate", "conflict", "fresh"])
        conflict = self.paths["stream_feed"][3]
        self.assertTrue(conflict["degraded"])
        self.assertEqual(conflict["reason_code"], "OUT_OF_ORDER_REPLAY")
        malformed = self.paths["stream_malformed"]
        self.assertTrue(malformed["degraded"])
        self.assertEqual(malformed["run_status"], "unavailable")
        self.assertEqual(malformed["reason_code"], "INVALID_HOST_INPUT")

    def test_public_error_and_retry_affordance_are_public_safe(self):
        presented, rejected = self.paths["error_flow"]
        self.assertEqual(presented["status"], "presented")
        self.assertEqual(presented["reason_code"], "RUN_FAILED")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["reason_code"], "INVALID_REASON_CODE")
        self.assertEqual(rejected["run_id"], "")
        self.assertEqual(rejected["summary"], "")
        staged, denied = self.paths["affordance_flow"]
        self.assertEqual(staged["status"], "staged")
        self.assertEqual(staged["affordance"], "retry")
        self.assertEqual(denied["status"], "rejected")
        self.assertEqual(denied["reason_code"], "STATE_DOES_NOT_PERMIT")
        self.assertEqual(denied["affordance"], "")

    def test_citation_presentation(self):
        normal = self.paths["citations_normal"]
        self.assertEqual(normal["status"], "ready")
        self.assertEqual([c["label"] for c in normal["citations"]], ["[1]", "[2]"])
        degraded = self.paths["citations_degraded"]
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["dropped_count"], 2)

    def test_attachment_selection_and_ref_presentation(self):
        normal = self.paths["selections_normal"]
        self.assertEqual(normal["status"], "ready")
        png = [s for s in normal["selections"] if s["name"] == "photo.png"][0]
        self.assertIn("OVER_SHARED_IMAGE_BOUND", png["hints"])
        degraded = self.paths["selections_degraded"]
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["dropped_count"], 2)
        valid = self.paths["attachment_ref_valid"]
        self.assertEqual(valid["status"], "presented")
        self.assertEqual(valid["label"], "att_Zm9vYmFyMTIzNDU2Nzg5MDEy")
        invalid = self.paths["attachment_ref_invalid"]
        self.assertEqual(invalid["status"], "rejected")
        self.assertEqual(invalid["reason_code"], "URL_SHAPED_REF")
        self.assertEqual(invalid["label"], "")

    def test_approval_proposal_intent_and_state(self):
        proposals = self.paths["approval_proposals_normal"]
        self.assertEqual(proposals["status"], "ready")
        self.assertEqual(proposals["proposals"][0]["label"], "[1]")
        staged, rejected = self.paths["approval_intent_flow"]
        self.assertEqual(staged["status"], "staged")
        self.assertEqual(staged["intent"], "approve")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["reason_code"], "INVALID_INTENT")
        self.assertEqual(rejected["proposal_id"], "")
        pending, expired = self.paths["approval_state_flow"]
        self.assertEqual(pending["state"], "pending")
        self.assertEqual(expired["reason_code"], "AUTHORITY_TIMEOUT")
        malformed = self.paths["approval_state_malformed"]
        self.assertEqual(malformed["state"], "unavailable")
        self.assertTrue(malformed["degraded"])

    def test_failsafe_disable_ends_journey(self):
        disable = self.paths["disable"]
        self.assertTrue(disable["ok"])
        self.assertEqual(disable["state"], "disabled")
        self.assertEqual(disable["fallback"], "host-primary-continue")
        self.assertEqual(self.paths["shell_state_after_disable"], "disabled")

    def test_non_mapping_fixture_rejected(self):
        with self.assertRaises(Exception):
            reference_host.run_conformance_journey(["not", "a", "mapping"])


if __name__ == "__main__":
    unittest.main()
