from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_pilot import (
    CaseStudyConsent,
    EvidenceQuality,
    MetricDefinition,
    MetricDirection,
    MetricUnit,
    PilotKpiEngine,
    PilotObservation,
    PilotPhase,
    default_pilot_metric_definitions,
)


NOW = datetime(2026, 9, 2, 16, 30, tzinfo=timezone.utc)


class PilotKpiTests(unittest.TestCase):
    def engine(self):
        return PilotKpiEngine(default_pilot_metric_definitions())

    def observation(
        self,
        observation_id,
        *,
        phase,
        value,
        quality=EvidenceQuality.MEASURED,
        metric_key="request_to_rfq_minutes",
        version=1,
        workspace_id="ws_1",
    ):
        return PilotObservation(
            observation_id=observation_id,
            workspace_id=workspace_id,
            phase=phase,
            metric_key=metric_key,
            metric_definition_version=version,
            value=Decimal(str(value)),
            observed_at=NOW,
            evidence_ref=f"evidence:{observation_id}",
            quality=quality,
            workflow_ref=f"workflow:{observation_id}",
        )

    def test_measured_baseline_and_after_are_compared(self):
        engine = self.engine()
        engine.add(self.observation("b1", phase=PilotPhase.BASELINE, value="60"))
        engine.add(self.observation("b2", phase=PilotPhase.BASELINE, value="40"))
        engine.add(self.observation("s1", phase=PilotPhase.SHADOW, value="20"))
        summary = engine.summarize(workspace_id="ws_1", metric_key="request_to_rfq_minutes")
        self.assertEqual(summary.baseline_average, Decimal("50"))
        self.assertEqual(summary.current_average, Decimal("20"))
        self.assertEqual(summary.absolute_change, Decimal("-30"))
        self.assertEqual(summary.percent_change, Decimal("-60"))
        self.assertTrue(summary.measured_comparison_available)

    def test_estimates_do_not_pollute_measured_delta(self):
        engine = self.engine()
        engine.add(self.observation("b1", phase=PilotPhase.BASELINE, value="60"))
        engine.add(self.observation("estimate", phase=PilotPhase.SHADOW, value="1", quality=EvidenceQuality.ESTIMATED))
        engine.add(self.observation("live", phase=PilotPhase.LIVE, value="30"))
        summary = engine.summarize(workspace_id="ws_1", metric_key="request_to_rfq_minutes")
        self.assertEqual(summary.current_average, Decimal("30"))
        self.assertEqual(summary.estimated_count, 1)

    def test_unknown_metric_definition_fails_closed(self):
        engine = self.engine()
        with self.assertRaises(ContractError):
            engine.add(self.observation("x", phase=PilotPhase.BASELINE, value="1", metric_key="unknown"))

    def test_definition_version_drift_cannot_be_silently_compared(self):
        defs = default_pilot_metric_definitions() + (
            MetricDefinition(
                "request_to_rfq_minutes",
                2,
                "요청→RFQ 시간 v2",
                MetricUnit.MINUTES,
                MetricDirection.LOWER_IS_BETTER,
                "새 정의",
            ),
        )
        engine = PilotKpiEngine(defs)
        engine.add(self.observation("v1", phase=PilotPhase.BASELINE, value="50", version=1))
        engine.add(self.observation("v2", phase=PilotPhase.LIVE, value="20", version=2))
        with self.assertRaisesRegex(ContractError, "versioned cohorts"):
            engine.summarize(workspace_id="ws_1", metric_key="request_to_rfq_minutes")

    def test_binary_float_values_are_rejected(self):
        with self.assertRaises(ContractError):
            PilotObservation(
                observation_id="x",
                workspace_id="ws_1",
                phase=PilotPhase.BASELINE,
                metric_key="request_to_rfq_minutes",
                metric_definition_version=1,
                value=1.2,  # type: ignore[arg-type]
                observed_at=NOW,
                evidence_ref="evidence:x",
            )

    def test_zero_baseline_does_not_invent_percent_change(self):
        engine = self.engine()
        engine.add(self.observation("b", phase=PilotPhase.BASELINE, value="0"))
        engine.add(self.observation("l", phase=PilotPhase.LIVE, value="10"))
        summary = engine.summarize(workspace_id="ws_1", metric_key="request_to_rfq_minutes")
        self.assertEqual(summary.absolute_change, Decimal("10"))
        self.assertIsNone(summary.percent_change)

    def test_evidence_refs_only_include_measured_rows(self):
        engine = self.engine()
        engine.add(self.observation("b", phase=PilotPhase.BASELINE, value="10"))
        engine.add(self.observation("e", phase=PilotPhase.SHADOW, value="9", quality=EvidenceQuality.ESTIMATED))
        engine.add(self.observation("l", phase=PilotPhase.LIVE, value="8"))
        summary = engine.summarize(workspace_id="ws_1", metric_key="request_to_rfq_minutes")
        self.assertEqual(summary.evidence_refs, ("evidence:b", "evidence:l"))

    def test_public_case_study_requires_explicit_matching_consent(self):
        engine = self.engine()
        engine.add(self.observation("b", phase=PilotPhase.BASELINE, value="50"))
        engine.add(self.observation("l", phase=PilotPhase.LIVE, value="25"))
        denied = CaseStudyConsent(workspace_id="ws_1", consent_ref="consent:1", approved=False)
        with self.assertRaises(ContractError):
            engine.build_public_case_study(
                workspace_id="ws_1",
                workspace_alias="익명 제조기업 A",
                metric_keys=("request_to_rfq_minutes",),
                consent=denied,
                generated_at=NOW,
            )
        approved = CaseStudyConsent(
            workspace_id="ws_1",
            consent_ref="consent:2",
            approved=True,
            approved_at=NOW,
        )
        projection = engine.build_public_case_study(
            workspace_id="ws_1",
            workspace_alias="익명 제조기업 A",
            metric_keys=("request_to_rfq_minutes",),
            consent=approved,
            generated_at=NOW,
        )
        self.assertTrue(projection.anonymized)
        self.assertNotIn("evidence_refs", str(projection.measured_metrics))

    def test_public_case_study_cannot_mix_another_workspace_consent(self):
        engine = self.engine()
        engine.add(self.observation("b", phase=PilotPhase.BASELINE, value="50"))
        engine.add(self.observation("l", phase=PilotPhase.LIVE, value="25"))
        other = CaseStudyConsent(
            workspace_id="ws_2",
            consent_ref="consent:other",
            approved=True,
            approved_at=NOW,
        )
        with self.assertRaises(ContractError):
            engine.build_public_case_study(
                workspace_id="ws_1",
                workspace_alias="익명 제조기업 A",
                metric_keys=("request_to_rfq_minutes",),
                consent=other,
                generated_at=NOW,
            )

    def test_duplicate_observation_ids_fail_closed(self):
        engine = self.engine()
        row = self.observation("same", phase=PilotPhase.BASELINE, value="10")
        engine.add(row)
        with self.assertRaises(ContractError):
            engine.add(row)


if __name__ == "__main__":
    unittest.main()
