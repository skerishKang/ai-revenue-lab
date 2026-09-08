"""S7 streaming lifecycle/error/retry presentation contract tests (network-free)."""

from __future__ import annotations

import unittest

from padiem_embedded_runtime.errors import SidecarContractError
from padiem_embedded_runtime.streaming_lifecycle import (
    MAX_EVENT_SEQUENCE,
    ORDER_CONFLICT,
    ORDER_DUPLICATE,
    ORDER_FRESH,
    PHASE_UNAVAILABLE,
    PUBLIC_ERROR_REASON_CODES,
    REASON_INVALID_HOST_INPUT,
    REASON_OUT_OF_ORDER_REPLAY,
    STATUS_PRESENTED,
    STATUS_REJECTED,
    STATUS_STAGED,
    StreamFeedGuard,
    StreamLifecyclePresentation,
    RetryAffordancePresentation,
    present_public_error,
    present_retry_affordance,
    present_stream_lifecycle,
)

VALID_EVENT = {
    "kind": "run_status_changed",
    "run_status": "running",
    "stream_id": "stm_s7_01",
    "run_id": "run_s7_01",
    "event_id": "evt_s7_01",
    "sequence": 1,
    "summary": "Run is streaming",
}


def event_with(**overrides: object) -> dict:
    return {**VALID_EVENT, **overrides}


class PresentStreamLifecycleTests(unittest.TestCase):
    def test_valid_event_projects_all_bounded_fields(self) -> None:
        view = present_stream_lifecycle(VALID_EVENT)
        self.assertFalse(view.degraded)
        self.assertEqual(view.kind, "run_status_changed")
        self.assertEqual(view.run_status, "running")
        self.assertEqual(view.sequence, 1)
        self.assertEqual(view.to_public_dict()["event_id"], "evt_s7_01")

    def test_non_status_kind_without_run_status_is_unavailable_not_degraded(self) -> None:
        view = present_stream_lifecycle(event_with(kind="artifact_ready", run_status=""))
        self.assertFalse(view.degraded)
        self.assertEqual(view.kind, "artifact_ready")
        self.assertEqual(view.run_status, PHASE_UNAVAILABLE)

    def test_unknown_kind_degrades_to_invalid_host_input(self) -> None:
        view = present_stream_lifecycle(event_with(kind="provider_raw_delta"))
        self.assertTrue(view.degraded)
        self.assertEqual(view.run_status, PHASE_UNAVAILABLE)
        self.assertEqual(view.reason_code, REASON_INVALID_HOST_INPUT)

    def test_status_kind_requires_allowlisted_run_status(self) -> None:
        for run_status in ("succeeded", "", "RUNNING", 7):
            with self.subTest(run_status=run_status):
                view = present_stream_lifecycle(event_with(run_status=run_status))
                self.assertEqual(view.reason_code, REASON_INVALID_HOST_INPUT)

    def test_non_mapping_input_degrades_without_raising(self) -> None:
        view = present_stream_lifecycle("not-a-mapping")  # type: ignore[arg-type]
        self.assertEqual(view.reason_code, REASON_INVALID_HOST_INPUT)

    def test_unknown_field_degrades(self) -> None:
        view = present_stream_lifecycle({**VALID_EVENT, "payload": "raw"})
        self.assertEqual(view.reason_code, REASON_INVALID_HOST_INPUT)

    def test_guarded_summaries_never_pass(self) -> None:
        for summary in (
            "see https://leak.example/x",
            "diff --git a/x b/x",
            "api_key rotated",
            "Traceback here",
            "<b>bold</b>",
            "s" * (280 + 1),
        ):
            with self.subTest(summary=summary):
                view = present_stream_lifecycle(event_with(summary=summary))
                self.assertEqual(view.reason_code, REASON_INVALID_HOST_INPUT)

    def test_bad_sequences_degrade(self) -> None:
        for sequence in (True, -1, MAX_EVENT_SEQUENCE + 1, "1"):
            with self.subTest(sequence=sequence):
                view = present_stream_lifecycle(event_with(sequence=sequence))
                self.assertEqual(view.reason_code, REASON_INVALID_HOST_INPUT)

    def test_path_or_space_shaped_identifiers_degrade(self) -> None:
        for name in ("stream_id", "run_id", "event_id", "trace_id", "subject_ref"):
            with self.subTest(name=name):
                view = present_stream_lifecycle(event_with(**{name: "bad id /x"}))
                self.assertEqual(view.reason_code, REASON_INVALID_HOST_INPUT)


class PresentationDataclassGuardTests(unittest.TestCase):
    def test_direct_construction_rejects_unknown_kind(self) -> None:
        with self.assertRaises(SidecarContractError):
            StreamLifecyclePresentation(kind="provider_raw_delta")

    def test_bare_construction_requires_kind_when_not_degraded(self) -> None:
        with self.assertRaises(SidecarContractError):
            StreamLifecyclePresentation()

    def test_degraded_view_requires_reason(self) -> None:
        with self.assertRaises(SidecarContractError):
            StreamLifecyclePresentation(degraded=True)

    def test_sequence_bound_is_enforced(self) -> None:
        with self.assertRaises(SidecarContractError):
            StreamLifecyclePresentation(sequence=MAX_EVENT_SEQUENCE + 1)

    def test_staged_affordance_with_reason_is_rejected(self) -> None:
        with self.assertRaises(SidecarContractError):
            RetryAffordancePresentation(
                status=STATUS_STAGED, affordance="retry", run_id="r_1", reason_code="X"
            )

    def test_rejected_affordance_never_echoes(self) -> None:
        with self.assertRaises(SidecarContractError):
            RetryAffordancePresentation(
                status=STATUS_REJECTED, affordance="retry", reason_code="INVALID_RUN_ID"
            )


class StreamFeedGuardTests(unittest.TestCase):
    def test_requires_lifecycle_presentation(self) -> None:
        with self.assertRaises(SidecarContractError):
            StreamFeedGuard().observe("nope")  # type: ignore[arg-type]

    def test_fresh_duplicate_and_conflict_orderings(self) -> None:
        guard = StreamFeedGuard()
        first = present_stream_lifecycle(VALID_EVENT)
        self.assertEqual(guard.observe(first)[1], ORDER_FRESH)
        self.assertEqual(guard.observe(first)[1], ORDER_DUPLICATE)
        later = present_stream_lifecycle(event_with(sequence=0, event_id="evt_s7_00"))
        projected, ordering = guard.observe(later)
        self.assertEqual(ordering, ORDER_CONFLICT)
        self.assertEqual(projected.reason_code, REASON_OUT_OF_ORDER_REPLAY)

    def test_same_sequence_different_event_conflicts(self) -> None:
        guard = StreamFeedGuard()
        guard.observe(present_stream_lifecycle(VALID_EVENT))
        rival = present_stream_lifecycle(event_with(event_id="evt_s7_99"))
        self.assertEqual(guard.observe(rival)[1], ORDER_CONFLICT)

    def test_conflict_does_not_advance_feed_state(self) -> None:
        guard = StreamFeedGuard()
        guard.observe(present_stream_lifecycle(VALID_EVENT))
        guard.observe(present_stream_lifecycle(event_with(sequence=0, event_id="evt_old")))
        replay = present_stream_lifecycle(VALID_EVENT)
        self.assertEqual(guard.observe(replay)[1], ORDER_DUPLICATE)

    def test_stream_switch_conflicts(self) -> None:
        guard = StreamFeedGuard()
        guard.observe(present_stream_lifecycle(VALID_EVENT))
        other = present_stream_lifecycle(event_with(stream_id="stm_other", sequence=2))
        self.assertEqual(guard.observe(other)[1], ORDER_CONFLICT)

    def test_degraded_and_sequenceless_views_pass_through_unadvanced(self) -> None:
        guard = StreamFeedGuard()
        degraded = present_stream_lifecycle(event_with(kind="provider_raw_delta"))
        self.assertEqual(guard.observe(degraded), (degraded, ORDER_FRESH))
        no_seq = present_stream_lifecycle(event_with(sequence=None, event_id="evt_s7_02"))
        self.assertEqual(guard.observe(no_seq)[1], ORDER_FRESH)
        first = present_stream_lifecycle(VALID_EVENT)
        self.assertEqual(guard.observe(first)[1], ORDER_FRESH)

    def test_forward_jump_is_passed_through_not_fabricated(self) -> None:
        guard = StreamFeedGuard()
        guard.observe(present_stream_lifecycle(VALID_EVENT))
        jumped = present_stream_lifecycle(event_with(sequence=50, event_id="evt_s7_50"))
        projected, ordering = guard.observe(jumped)
        self.assertEqual(ordering, ORDER_FRESH)
        self.assertEqual(projected.sequence, 50)


class PresentPublicErrorTests(unittest.TestCase):
    def test_every_allowlisted_reason_presents(self) -> None:
        for reason in sorted(PUBLIC_ERROR_REASON_CODES):
            with self.subTest(reason=reason):
                view = present_public_error({"reason_code": reason, "run_id": "run_s7_01"})
                self.assertEqual(view.status, STATUS_PRESENTED)
                self.assertEqual(view.reason_code, reason)

    def test_rejections_are_reason_coded_and_never_echo(self) -> None:
        cases = [
            ("not-a-mapping", "MALFORMED_INPUT"),
            ({"reason_code": "RUN_FAILED", "traceback": "x"}, "UNKNOWN_FIELDS"),
            ({"reason_code": "PROVIDER_HTTP_500"}, "INVALID_REASON_CODE"),
            ({"reason_code": "RUN_FAILED", "run_id": "bad id"}, "INVALID_RUN_ID"),
            ({"reason_code": "RUN_FAILED", "summary": "http://a.test"}, "INVALID_SUMMARY"),
        ]
        for raw, reason in cases:
            with self.subTest(raw=raw):
                view = present_public_error(raw)
                self.assertEqual(view.status, STATUS_REJECTED)
                self.assertEqual(view.reason_code, reason)
                self.assertEqual(view.run_id, "")
                self.assertEqual(view.summary, "")

    def test_rejected_view_never_carries_raw_material(self) -> None:
        view = present_public_error(
            {"reason_code": "RUN_FAILED", "summary": "diff --git a/x b/x"}
        )
        blob = str(view.to_public_dict())
        self.assertNotIn("diff --git", blob)


class PresentRetryAffordanceTests(unittest.TestCase):
    def test_permitted_matrix_stages(self) -> None:
        cases = [
            ("retry", "failed"),
            ("retry", "timed_out"),
            ("reconnect", "cancelled"),
            ("cancel", "waiting_approval"),
        ]
        for affordance, run_status in cases:
            with self.subTest(affordance=affordance, run_status=run_status):
                view = present_retry_affordance(
                    {"affordance": affordance, "run_id": "run_s7_01", "run_status": run_status}
                )
                self.assertEqual(view.status, STATUS_STAGED)
                self.assertEqual(view.affordance, affordance)
                self.assertEqual(view.reason_code, "")

    def test_matrix_rejections(self) -> None:
        cases = [
            ({"affordance": "retry", "run_id": "r_1", "run_status": "running"}, "STATE_DOES_NOT_PERMIT"),
            ({"affordance": "cancel", "run_id": "r_1", "run_status": "completed"}, "STATE_DOES_NOT_PERMIT"),
            ({"affordance": "force", "run_id": "r_1", "run_status": "failed"}, "INVALID_AFFORDANCE"),
            ({"affordance": "retry", "run_id": "bad id", "run_status": "failed"}, "INVALID_RUN_ID"),
            ({"affordance": "retry", "run_id": "r_1", "run_status": "succeeded"}, "INVALID_RUN_STATUS"),
            ({"affordance": "retry", "run_id": "r_1", "run_status": "failed", "x": 1}, "UNKNOWN_FIELDS"),
        ]
        for raw, reason in cases:
            with self.subTest(raw=raw):
                view = present_retry_affordance(raw)
                self.assertEqual(view.status, STATUS_REJECTED)
                self.assertEqual(view.reason_code, reason)
                self.assertEqual(view.affordance, "")
                self.assertEqual(view.run_id, "")

    def test_malformed_input_rejects(self) -> None:
        view = present_retry_affordance(None)  # type: ignore[arg-type]
        self.assertEqual(view.reason_code, "MALFORMED_INPUT")

    def test_staged_affordance_carries_no_reason(self) -> None:
        view = present_retry_affordance(
            {"affordance": "retry", "run_id": "r_1", "run_status": "failed"}
        )
        self.assertEqual(view.status, STATUS_STAGED)
        self.assertEqual(view.reason_code, "")


if __name__ == "__main__":
    unittest.main()
