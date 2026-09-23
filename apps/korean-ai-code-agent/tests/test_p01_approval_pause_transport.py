from __future__ import annotations

import unittest

from kagent.p01_approval_pause_transport import (
    EngineApprovalPauseWireError,
    split_engine_approval_pause_wire,
)


_ENGINE_REF = "cont_EngineOpaqueRef_01"

_PAUSE = {
    "status": "paused",
    "continuation_id": "pause_001",
    "run_id": "orch_001",
    "trace_id": "trace_001",
    "step_index": 1,
    "agent_id": "b54-padiem-claw",
    "tool_id": "tool_1",
    "requirement": "user_confirmation",
    "approval_scope": ["tool.execute"],
    "created_at": "2026-09-02T10:00:00+00:00",
    "expires_at": "2026-09-03T10:00:00+00:00",
}


def _payload(
    *,
    pause: object | None = _PAUSE,
    ref: object | None = _ENGINE_REF,
    state: object | None = None,
    events: list | None = None,
) -> dict:
    return {
        "app_id": "b54-padiem-claw",
        "execution": {"answer": "", "route": {}, "metadata": {}},
        "context": {"trace_id": "trace_001"},
        "events": events
        if events is not None
        else [
            {
                "event_id": "evt_1",
                "run_id": "orch_001",
                "trace_id": "trace_001",
                "app_id": "b54-padiem-claw",
                "kind": "run_started",
                "sequence": 1,
                "message": None,
                "timestamp_iso": "2026-09-02T10:00:00+00:00",
            },
            {
                "event_id": "evt_2",
                "run_id": "orch_001",
                "trace_id": "trace_001",
                "app_id": "b54-padiem-claw",
                "kind": "approval_paused",
                "sequence": 2,
                "message": None,
                "timestamp_iso": "2026-09-02T10:00:01+00:00",
            },
        ],
        "approval_pause": pause,
        "continuation_ref": ref,
        "continuation_state": state,
        "state_machine": {"current_state": None, "transitions": []},
    }


class SplitEngineApprovalPauseWireTests(unittest.TestCase):
    def test_completed_payload_without_pause_keys_is_returned_unchanged(self):
        payload = _payload(pause=None, ref=None, state=None, events=[
            {
                "event_id": "evt_1",
                "run_id": "orch_001",
                "trace_id": "trace_001",
                "app_id": "b54-padiem-claw",
                "kind": "run_started",
                "sequence": 1,
                "message": None,
                "timestamp_iso": "2026-09-02T10:00:00+00:00",
            }
        ])
        stripped, wire = split_engine_approval_pause_wire(payload)
        self.assertIs(stripped, payload)
        self.assertIsNone(wire)

    def test_engine_pause_wire_is_stripped_and_opaque_ref_round_trips(self):
        payload = _payload()
        stripped, wire = split_engine_approval_pause_wire(payload)
        self.assertIsNot(stripped, payload)
        self.assertNotIn("approval_pause", stripped)
        self.assertNotIn("continuation_ref", stripped)
        self.assertNotIn("continuation_state", stripped)
        self.assertIn("events", stripped)
        assert wire is not None
        self.assertEqual(wire.continuation_ref, _ENGINE_REF)
        self.assertEqual(wire.approval_pause["continuation_id"], "pause_001")
        self.assertIsNone(wire.continuation_state)
        # Original payload keys are not mutated by the shallow strip.
        self.assertEqual(payload["continuation_ref"], _ENGINE_REF)

    def test_optional_continuation_state_is_preserved_on_wire_only(self):
        payload = _payload(state={"status": "resumable", "decision_id": None})
        stripped, wire = split_engine_approval_pause_wire(payload)
        self.assertNotIn("continuation_state", stripped)
        assert wire is not None
        assert wire.continuation_state is not None
        self.assertEqual(wire.continuation_state["status"], "resumable")

    def test_missing_continuation_ref_fails_closed(self):
        with self.assertRaises(EngineApprovalPauseWireError) as caught:
            split_engine_approval_pause_wire(_payload(ref=None))
        self.assertEqual(caught.exception.code, "missing_continuation_ref")

    def test_malformed_continuation_ref_fails_closed(self):
        for bad in ("not-a-ref", "cont_short", 123, ""):
            with self.subTest(bad=bad), self.assertRaises(EngineApprovalPauseWireError) as caught:
                split_engine_approval_pause_wire(_payload(ref=bad))
            self.assertEqual(caught.exception.code, "malformed_continuation_ref")

    def test_continuation_without_pause_fails_closed(self):
        with self.assertRaises(EngineApprovalPauseWireError) as caught:
            split_engine_approval_pause_wire(
                _payload(pause=None, ref=_ENGINE_REF, events=[])
            )
        self.assertEqual(caught.exception.code, "continuation_without_pause")

        with self.assertRaises(EngineApprovalPauseWireError) as caught:
            split_engine_approval_pause_wire(
                _payload(
                    pause=None,
                    ref=None,
                    state={"status": "resumable", "decision_id": None},
                    events=[],
                )
            )
        self.assertEqual(caught.exception.code, "continuation_without_pause")

    def test_pause_without_lifecycle_evidence_fails_closed(self):
        with self.assertRaises(EngineApprovalPauseWireError) as caught:
            split_engine_approval_pause_wire(
                _payload(
                    events=[
                        {
                            "event_id": "evt_1",
                            "run_id": "orch_001",
                            "trace_id": "trace_001",
                            "app_id": "b54-padiem-claw",
                            "kind": "run_started",
                            "sequence": 1,
                            "message": None,
                            "timestamp_iso": "2026-09-02T10:00:00+00:00",
                        }
                    ]
                )
            )
        self.assertEqual(caught.exception.code, "pause_without_lifecycle_evidence")

    def test_unknown_extra_authority_fields_fail_closed(self):
        pause = dict(_PAUSE)
        pause["invocation_sha256"] = "deadbeef"
        with self.assertRaises(EngineApprovalPauseWireError) as caught:
            split_engine_approval_pause_wire(_payload(pause=pause))
        self.assertEqual(caught.exception.code, "unknown_extra_authority_fields")

        with self.assertRaises(EngineApprovalPauseWireError) as caught:
            split_engine_approval_pause_wire(
                _payload(state={"status": "resumable", "authority": "forged"})
            )
        self.assertEqual(caught.exception.code, "unknown_extra_authority_fields")

    def test_pause_run_identity_mismatch_fails_closed(self):
        pause = dict(_PAUSE)
        pause["run_id"] = "orch_other"
        with self.assertRaises(EngineApprovalPauseWireError) as caught:
            split_engine_approval_pause_wire(_payload(pause=pause))
        self.assertEqual(caught.exception.code, "correlation_mismatch")

    def test_non_mapping_payload_fails_closed(self):
        with self.assertRaises(EngineApprovalPauseWireError) as caught:
            split_engine_approval_pause_wire(["not", "a", "mapping"])  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, "invalid_engine_result")


if __name__ == "__main__":
    unittest.main()
