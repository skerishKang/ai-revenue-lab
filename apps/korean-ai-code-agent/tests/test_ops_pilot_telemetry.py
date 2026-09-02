from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_pilot import PilotKpiEngine, PilotPhase, default_pilot_metric_definitions
from kagent.ops_pilot_telemetry import (
    ESTIMATED_TELEMETRY_OBSERVATIONS_SUPPORTED,
    WORKFLOW_COST_AUTOCAPTURE_SUPPORTED,
    PilotMeasurementBridge,
    PilotTelemetryKind,
    WorkflowTelemetryEvent,
)


NOW = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)


class PilotTelemetryTests(unittest.TestCase):
    def event(
        self,
        event_id,
        kind,
        minutes,
        *,
        workflow_ref="workflow_1",
        workspace_id="ws_1",
        phase=PilotPhase.SHADOW,
        subject_ref=None,
    ):
        return WorkflowTelemetryEvent(
            event_id=event_id,
            workspace_id=workspace_id,
            workflow_ref=workflow_ref,
            phase=phase,
            kind=kind,
            occurred_at=NOW + timedelta(minutes=minutes),
            evidence_ref=f"evidence:{event_id}",
            subject_ref=subject_ref,
        )

    def test_request_to_rfq_and_po_are_exact_measured_durations(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("request", PilotTelemetryKind.REQUEST_INGESTED, 0))
        bridge.add(self.event("rfq_ready", PilotTelemetryKind.RFQ_READY, 12))
        bridge.add(self.event("po_ready", PilotTelemetryKind.PO_READY, 55))
        observations = bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")
        by_metric = {item.observation.metric_key: item for item in observations}
        self.assertEqual(by_metric["request_to_rfq_minutes"].observation.value, Decimal("12"))
        self.assertEqual(by_metric["request_to_po_minutes"].observation.value, Decimal("55"))
        self.assertEqual(by_metric["request_to_rfq_minutes"].observation.quality.value, "measured")
        self.assertEqual(
            by_metric["request_to_rfq_minutes"].source_event_ids,
            ("request", "rfq_ready"),
        )

    def test_supplier_response_is_correlated_by_exact_subject_ref(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("sent_a", PilotTelemetryKind.RFQ_SENT, 1, subject_ref="rfq_a"))
        bridge.add(self.event("recv_a", PilotTelemetryKind.SUPPLIER_QUOTE_RECEIVED, 31, subject_ref="rfq_a"))
        bridge.add(self.event("sent_b", PilotTelemetryKind.RFQ_SENT, 5, subject_ref="rfq_b"))
        bridge.add(self.event("recv_b", PilotTelemetryKind.SUPPLIER_QUOTE_RECEIVED, 65, subject_ref="rfq_b"))
        observations = bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")
        values = sorted(
            item.observation.value
            for item in observations
            if item.observation.metric_key == "supplier_response_minutes"
        )
        self.assertEqual(values, [Decimal("30"), Decimal("60")])

    def test_completed_workflow_allows_measured_zero_counts(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("done", PilotTelemetryKind.WORKFLOW_COMPLETED, 30))
        observations = bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")
        by_metric = {item.observation.metric_key: item.observation.value for item in observations}
        self.assertEqual(by_metric["manual_reentry_count"], Decimal(0))
        self.assertEqual(by_metric["automation_retry_count"], Decimal(0))
        self.assertEqual(by_metric["owner_intervention_count"], Decimal(0))

    def test_counts_are_not_assumed_zero_before_explicit_completion(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("retry", PilotTelemetryKind.AUTOMATION_RETRY, 2))
        observations = bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")
        self.assertFalse(
            any(item.observation.metric_key == "automation_retry_count" for item in observations)
        )

    def test_completed_workflow_counts_explicit_operational_events(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("reentry_1", PilotTelemetryKind.MANUAL_REENTRY, 2))
        bridge.add(self.event("reentry_2", PilotTelemetryKind.MANUAL_REENTRY, 3))
        bridge.add(self.event("retry_1", PilotTelemetryKind.AUTOMATION_RETRY, 4))
        bridge.add(self.event("owner_1", PilotTelemetryKind.OWNER_INTERVENTION, 5))
        bridge.add(self.event("done", PilotTelemetryKind.WORKFLOW_COMPLETED, 20))
        observations = bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")
        by_metric = {item.observation.metric_key: item.observation.value for item in observations}
        self.assertEqual(by_metric["manual_reentry_count"], Decimal(2))
        self.assertEqual(by_metric["automation_retry_count"], Decimal(1))
        self.assertEqual(by_metric["owner_intervention_count"], Decimal(1))

    def test_extraction_correction_rate_uses_only_reviewed_fields(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("field_1", PilotTelemetryKind.EXTRACTION_FIELD_CONFIRMED, 1))
        bridge.add(self.event("field_2", PilotTelemetryKind.EXTRACTION_FIELD_CONFIRMED, 2))
        bridge.add(self.event("field_3", PilotTelemetryKind.EXTRACTION_FIELD_CORRECTED, 3))
        observations = bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")
        correction = next(
            item for item in observations if item.observation.metric_key == "extraction_correction_rate"
        )
        self.assertEqual(correction.observation.value, Decimal(100) / Decimal(3))
        self.assertEqual(len(correction.source_event_ids), 3)

    def test_duplicate_singleton_and_correlated_milestones_fail_closed(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("request_1", PilotTelemetryKind.REQUEST_INGESTED, 0))
        bridge.add(self.event("request_2", PilotTelemetryKind.REQUEST_INGESTED, 1))
        with self.assertRaisesRegex(ContractError, "duplicate singleton"):
            bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")

        bridge = PilotMeasurementBridge()
        bridge.add(self.event("sent_1", PilotTelemetryKind.RFQ_SENT, 0, subject_ref="rfq_1"))
        bridge.add(self.event("sent_2", PilotTelemetryKind.RFQ_SENT, 1, subject_ref="rfq_1"))
        with self.assertRaisesRegex(ContractError, "duplicate correlated"):
            bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")

    def test_negative_milestone_duration_fails_closed(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("request", PilotTelemetryKind.REQUEST_INGESTED, 10))
        bridge.add(self.event("rfq_ready", PilotTelemetryKind.RFQ_READY, 5))
        with self.assertRaisesRegex(ContractError, "precede"):
            bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")

    def test_workflow_cannot_span_pilot_phases(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("request", PilotTelemetryKind.REQUEST_INGESTED, 0, phase=PilotPhase.BASELINE))
        bridge.add(self.event("rfq_ready", PilotTelemetryKind.RFQ_READY, 1, phase=PilotPhase.SHADOW))
        with self.assertRaisesRegex(ContractError, "multiple pilot phases"):
            bridge.derive(workspace_id="ws_1", workflow_ref="workflow_1")

    def test_pair_events_require_subject_and_singletons_forbid_subject(self):
        with self.assertRaises(ContractError):
            self.event("sent", PilotTelemetryKind.RFQ_SENT, 0)
        with self.assertRaises(ContractError):
            self.event("request", PilotTelemetryKind.REQUEST_INGESTED, 0, subject_ref="rfq_1")

    def test_event_replay_is_idempotent_but_conflict_fails_closed(self):
        bridge = PilotMeasurementBridge()
        event = self.event("same", PilotTelemetryKind.REQUEST_INGESTED, 0)
        bridge.add(event)
        bridge.add(event)
        with self.assertRaises(ContractError):
            bridge.add(self.event("same", PilotTelemetryKind.RFQ_READY, 1))

    def test_derived_ids_are_deterministic_and_source_evidence_is_preserved(self):
        first = PilotMeasurementBridge()
        second = PilotMeasurementBridge()
        events = (
            self.event("request", PilotTelemetryKind.REQUEST_INGESTED, 0),
            self.event("rfq", PilotTelemetryKind.RFQ_READY, 5),
        )
        for event in events:
            first.add(event)
            second.add(event)
        a = first.derive(workspace_id="ws_1", workflow_ref="workflow_1")[0]
        b = second.derive(workspace_id="ws_1", workflow_ref="workflow_1")[0]
        self.assertEqual(a.observation.observation_id, b.observation.observation_id)
        self.assertEqual(a.observation.evidence_ref, b.observation.evidence_ref)
        self.assertEqual(a.source_evidence_refs, ("evidence:request", "evidence:rfq"))

    def test_capture_into_existing_pilot_engine_keeps_definition_authority(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("request", PilotTelemetryKind.REQUEST_INGESTED, 0, phase=PilotPhase.BASELINE))
        bridge.add(self.event("rfq", PilotTelemetryKind.RFQ_READY, 10, phase=PilotPhase.BASELINE))
        engine = PilotKpiEngine(default_pilot_metric_definitions())
        derived = bridge.capture_into(engine, workspace_id="ws_1", workflow_ref="workflow_1")
        self.assertEqual(len(derived), 1)
        summary = engine.summarize(workspace_id="ws_1", metric_key="request_to_rfq_minutes")
        self.assertEqual(summary.baseline_average, Decimal("10"))
        self.assertIsNone(summary.current_average)

    def test_workspace_and_workflow_scope_are_isolated(self):
        bridge = PilotMeasurementBridge()
        bridge.add(self.event("a_req", PilotTelemetryKind.REQUEST_INGESTED, 0, workflow_ref="workflow_a"))
        bridge.add(self.event("a_rfq", PilotTelemetryKind.RFQ_READY, 10, workflow_ref="workflow_a"))
        bridge.add(self.event("b_req", PilotTelemetryKind.REQUEST_INGESTED, 0, workflow_ref="workflow_b"))
        bridge.add(self.event("b_rfq", PilotTelemetryKind.RFQ_READY, 50, workflow_ref="workflow_b"))
        a = bridge.derive(workspace_id="ws_1", workflow_ref="workflow_a")
        b = bridge.derive(workspace_id="ws_1", workflow_ref="workflow_b")
        self.assertEqual(a[0].observation.value, Decimal("10"))
        self.assertEqual(b[0].observation.value, Decimal("50"))

    def test_no_cost_autocapture_or_estimated_telemetry(self):
        self.assertFalse(WORKFLOW_COST_AUTOCAPTURE_SUPPORTED)
        self.assertFalse(ESTIMATED_TELEMETRY_OBSERVATIONS_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
