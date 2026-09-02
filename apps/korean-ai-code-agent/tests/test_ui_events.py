from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ui_events import (
    AG_UI_RUNTIME_DEPENDENCY_CONFIGURED,
    B62_EXECUTION_AUTHORITY,
    UI_STREAM_CONTAINS_HIDDEN_RUNTIME_STATE,
    ClawUiEvent,
    ClawUiEventKind,
    ClawUiEventStream,
)


NOW = datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc)


def event(sequence=1, *, event_id=None, kind=ClawUiEventKind.RUN_STATUS_CHANGED, run_id="run_1", occurred_at=None, summary="Run preparing"):
    return ClawUiEvent(
        event_id=event_id or f"evt_{sequence}",
        stream_id="stream_1",
        sequence=sequence,
        run_id=run_id,
        kind=kind,
        occurred_at=occurred_at or NOW + timedelta(seconds=sequence),
        summary=summary,
        subject_ref="subject_1",
        trace_id="trace_1",
    )


class UiEventTests(unittest.TestCase):
    def test_safe_event_projection_contains_no_hidden_runtime_payload(self):
        rendered = event().safe_dict()
        self.assertFalse(rendered["hidden_reasoning"])
        self.assertFalse(rendered["tool_arguments"])
        self.assertFalse(rendered["tool_results"])
        self.assertFalse(rendered["raw_diff"])
        self.assertFalse(rendered["raw_terminal_output"])
        self.assertFalse(rendered["credential_values"])
        self.assertFalse(rendered["execution_authority"])

    def test_summary_is_bounded_and_secret_like_content_fails_closed(self):
        with self.assertRaises(ContractError):
            event(summary="x" * 1001)
        with self.assertRaises(ContractError):
            event(summary="api_key=value_should_not_be_here")

    def test_sequence_is_contiguous_and_time_monotonic(self):
        stream = ClawUiEventStream()
        stream.append(event(1))
        with self.assertRaises(ContractError):
            stream.append(event(3))
        stream.append(event(2))
        with self.assertRaises(ContractError):
            stream.append(event(3, occurred_at=NOW))

    def test_stream_cannot_mix_run_identity(self):
        stream = ClawUiEventStream()
        stream.append(event(1))
        with self.assertRaises(ContractError):
            stream.append(event(2, run_id="run_2"))

    def test_exact_replay_is_idempotent_but_conflicting_event_id_fails(self):
        stream = ClawUiEventStream()
        first = event(1)
        stream.append(first)
        stream.append(first)
        self.assertEqual(len(stream.events("stream_1")), 1)
        with self.assertRaises(ContractError):
            stream.append(event(2, event_id="evt_1", summary="Different"))

    def test_all_public_event_kinds_are_supported_without_arbitrary_payload(self):
        stream = ClawUiEventStream()
        for index, kind in enumerate(ClawUiEventKind, start=1):
            stream.append(event(index, kind=kind, summary=f"Public status {kind.value}"))
        exported = stream.safe_export("stream_1")
        self.assertEqual(len(exported["events"]), len(tuple(ClawUiEventKind)))
        self.assertFalse(exported["ag_ui_canonical_authority"])
        self.assertFalse(exported["b62_execution_authority"])
        for item in exported["events"]:
            self.assertNotIn("payload", item)

    def test_event_fingerprint_changes_with_material_public_content(self):
        first = event(1)
        second = event(1, summary="Another status")
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_ag_ui_and_b62_do_not_gain_runtime_authority(self):
        self.assertFalse(AG_UI_RUNTIME_DEPENDENCY_CONFIGURED)
        self.assertFalse(B62_EXECUTION_AUTHORITY)
        self.assertFalse(UI_STREAM_CONTAINS_HIDDEN_RUNTIME_STATE)


if __name__ == "__main__":
    unittest.main()
