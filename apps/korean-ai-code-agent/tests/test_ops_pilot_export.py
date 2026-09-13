from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_pilot import (
    CaseStudyConsent,
    EvidenceQuality,
    MetricDirection,
    PilotMetricSummary,
    PilotObservation,
    PilotPhase,
)
from kagent.ops_pilot_export import (
    CURRENCY_MINOR_DEFAULT_EXPORT_SUPPORTED,
    EXTERNAL_EXPORT_WITHOUT_CONSENT_SUPPORTED,
    RAW_PILOT_TELEMETRY_EXPORT_SUPPORTED,
    PilotExportPurpose,
    PilotPrivacyExportPolicy,
    PrivacySafePilotMetric,
    build_privacy_safe_pilot_export,
)
from kagent.ops_pilot_telemetry import PilotTelemetryKind, WorkflowTelemetryEvent


NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)


def summary(
    metric_key="request_to_po_minutes",
    *,
    baseline_count=5,
    current_count=6,
    baseline="100",
    current="40",
    estimated_count=0,
):
    baseline_value = Decimal(baseline) if baseline is not None else None
    current_value = Decimal(current) if current is not None else None
    absolute = None if baseline_value is None or current_value is None else current_value - baseline_value
    percent = None
    if absolute is not None and baseline_value != 0:
        percent = (absolute / baseline_value) * Decimal(100)
    return PilotMetricSummary(
        metric_key=metric_key,
        definition_version=1,
        baseline_measured_count=baseline_count,
        current_measured_count=current_count,
        estimated_count=estimated_count,
        baseline_average=baseline_value,
        current_average=current_value,
        absolute_change=absolute,
        percent_change=percent,
        direction=MetricDirection.LOWER_IS_BETTER,
        evidence_refs=("private:evidence:1", "private:evidence:2"),
    )


def consent(*, approved=True, workspace_id="ws_1"):
    return CaseStudyConsent(
        workspace_id=workspace_id,
        consent_ref="consent:case-study-1",
        approved=approved,
        approved_at=NOW if approved else None,
    )


class PilotPrivacyExportTests(unittest.TestCase):
    def test_internal_export_contains_aggregate_only_and_no_private_refs(self):
        export = build_privacy_safe_pilot_export(
            export_id="export_1",
            workspace_id="ws_1",
            workspace_alias="Design Partner A",
            purpose=PilotExportPurpose.INTERNAL_ANALYSIS,
            summaries=(summary(),),
            generated_at=NOW,
        )
        rendered = export.safe_dict()
        self.assertEqual(rendered["workspace_alias"], "Design Partner A")
        self.assertFalse(rendered["workspace_id_exported"])
        self.assertFalse(rendered["workflow_refs_exported"])
        self.assertFalse(rendered["event_ids_exported"])
        self.assertFalse(rendered["evidence_refs_exported"])
        self.assertFalse(rendered["counterparty_data_exported"])
        self.assertFalse(rendered["raw_messages_exported"])
        self.assertNotIn("private:evidence", str(rendered))
        self.assertFalse(rendered["publish_permission_implied"])

    def test_k_threshold_suppresses_small_cohort(self):
        with self.assertRaises(ContractError):
            build_privacy_safe_pilot_export(
                export_id="export_small",
                workspace_id="ws_1",
                workspace_alias="Pilot A",
                purpose=PilotExportPurpose.INTERNAL_ANALYSIS,
                summaries=(summary(baseline_count=4, current_count=10),),
                generated_at=NOW,
            )
        policy = PilotPrivacyExportPolicy(minimum_measured_count=3)
        export = build_privacy_safe_pilot_export(
            export_id="export_small_allowed",
            workspace_id="ws_1",
            workspace_alias="Pilot A",
            purpose=PilotExportPurpose.INTERNAL_ANALYSIS,
            summaries=(summary(baseline_count=3, current_count=3),),
            generated_at=NOW,
            policy=policy,
        )
        self.assertEqual(export.minimum_measured_count, 3)

    def test_currency_minor_metric_is_excluded_by_default(self):
        export = build_privacy_safe_pilot_export(
            export_id="export_1",
            workspace_id="ws_1",
            workspace_alias="Pilot A",
            purpose=PilotExportPurpose.INTERNAL_ANALYSIS,
            summaries=(summary(), summary(metric_key="workflow_cost_minor", baseline="1000", current="700")),
            generated_at=NOW,
        )
        rendered = export.safe_dict()
        self.assertEqual([item["metric_key"] for item in rendered["metrics"]], ["request_to_po_minutes"])
        self.assertIn("workflow_cost_minor", rendered["suppressed_metric_keys"])
        self.assertFalse(CURRENCY_MINOR_DEFAULT_EXPORT_SUPPORTED)

    def test_external_export_requires_matching_approved_consent(self):
        kwargs = dict(
            export_id="external_1",
            workspace_id="ws_1",
            workspace_alias="Anonymized Pilot",
            purpose=PilotExportPurpose.EXTERNAL_CASE_STUDY,
            summaries=(summary(),),
            generated_at=NOW,
        )
        with self.assertRaises(ContractError):
            build_privacy_safe_pilot_export(**kwargs)
        with self.assertRaises(ContractError):
            build_privacy_safe_pilot_export(**kwargs, consent=consent(approved=False))
        with self.assertRaises(ContractError):
            build_privacy_safe_pilot_export(**kwargs, consent=consent(workspace_id="ws_other"))
        export = build_privacy_safe_pilot_export(**kwargs, consent=consent())
        rendered = export.safe_dict()
        self.assertEqual(rendered["consent_ref"], "consent:case-study-1")
        self.assertTrue(rendered["publish_permission_implied"])
        self.assertFalse(EXTERNAL_EXPORT_WITHOUT_CONSENT_SUPPORTED)

    def test_estimated_only_or_missing_comparison_is_suppressed(self):
        with self.assertRaises(ContractError):
            build_privacy_safe_pilot_export(
                export_id="estimated_only",
                workspace_id="ws_1",
                workspace_alias="Pilot A",
                purpose=PilotExportPurpose.INTERNAL_ANALYSIS,
                summaries=(summary(baseline_count=0, current_count=0, baseline=None, current=None, estimated_count=10),),
                generated_at=NOW,
            )

    def test_duplicate_metric_version_fails_closed(self):
        with self.assertRaises(ContractError):
            build_privacy_safe_pilot_export(
                export_id="dup",
                workspace_id="ws_1",
                workspace_alias="Pilot A",
                purpose=PilotExportPurpose.INTERNAL_ANALYSIS,
                summaries=(summary(), summary()),
                generated_at=NOW,
            )

    def test_raw_telemetry_export_is_explicitly_unsupported(self):
        self.assertFalse(RAW_PILOT_TELEMETRY_EXPORT_SUPPORTED)

    # ---- #1538 adversarial proofs ----

    def _internal(self, summaries, *, workspace_id="ws_1", alias="Pilot A"):
        return build_privacy_safe_pilot_export(
            export_id="export_adv",
            workspace_id=workspace_id,
            workspace_alias=alias,
            purpose=PilotExportPurpose.INTERNAL_ANALYSIS,
            summaries=summaries,
            generated_at=NOW,
        )

    def _raw_observation(self):
        return PilotObservation(
            observation_id="obs_raw_1",
            workspace_id="ws_1",
            phase=PilotPhase.BASELINE,
            metric_key="request_to_po_minutes",
            metric_definition_version=1,
            value=Decimal("42"),
            observed_at=NOW,
            evidence_ref="evidence:raw-secret",
            quality=EvidenceQuality.MEASURED,
            workflow_ref="wf:raw-secret",
        )

    def _raw_event(self):
        return WorkflowTelemetryEvent(
            event_id="evt_raw_1",
            workspace_id="ws_1",
            workflow_ref="wf:raw-secret",
            phase=PilotPhase.BASELINE,
            kind=PilotTelemetryKind.REQUEST_INGESTED,
            occurred_at=NOW,
            evidence_ref="evidence:raw-secret",
            subject_ref=None,
        )

    def test_raw_telemetry_and_non_summary_inputs_are_rejected(self):
        for raw in (self._raw_observation(), self._raw_event(), {"metric_key": "x"}, "not-a-summary"):
            with self.assertRaises(ContractError):
                self._internal((raw,))
        with self.assertRaises(ContractError):
            self._internal((summary(), self._raw_observation()))
        with self.assertRaises(ContractError):
            PrivacySafePilotMetric.from_summary(self._raw_observation())
        with self.assertRaises(ContractError):
            self._internal([summary()])

    def test_workspace_id_value_never_appears_in_rendered_output(self):
        rendered = self._internal((summary(),), workspace_id="ws_super_secret_9").safe_dict()
        self.assertNotIn("ws_super_secret_9", str(rendered))
        self.assertEqual(rendered["workspace_alias"], "Pilot A")

    def test_planted_refs_and_forbidden_keys_never_serialized(self):
        leaky_refs = (
            "wf:workflow-secret-77",
            "evidence:evidence-secret-88",
            "counterparty:supplier-kim",
            "message:raw-message-body",
            "obs:observation-secret-99",
        )
        tagged = PilotMetricSummary(
            metric_key="manual_touches",
            definition_version=1,
            baseline_measured_count=8,
            current_measured_count=9,
            estimated_count=0,
            baseline_average=Decimal("7"),
            current_average=Decimal("3"),
            absolute_change=Decimal("-4"),
            percent_change=Decimal("-57.14285714285714285714285714"),
            direction=MetricDirection.LOWER_IS_BETTER,
            evidence_refs=leaky_refs,
        )
        rendered = self._internal((tagged,)).safe_dict()
        blob = str(rendered)
        for ref in leaky_refs:
            self.assertNotIn(ref, blob)

        forbidden_keys = {
            "workspace_id",
            "evidence_refs",
            "workflow_ref",
            "workflow_refs",
            "event_ids",
            "observation_id",
            "counterparty",
            "messages",
            "raw_observations",
            "estimated_count",
            "subject_ref",
        }

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    self.assertNotIn(key, forbidden_keys)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(rendered)

    def test_k_threshold_suppresses_each_small_cohort_independently(self):
        good = summary("time_to_first_reply_minutes")
        small_baseline = summary("queue_depth", baseline_count=4, current_count=9, baseline="12", current="9")
        small_current = summary("manual_touches", baseline_count=9, current_count=4, baseline="7", current="3")
        rendered = self._internal((good, small_baseline, small_current)).safe_dict()
        self.assertEqual([item["metric_key"] for item in rendered["metrics"]], ["time_to_first_reply_minutes"])
        self.assertEqual(rendered["suppressed_metric_keys"], ["manual_touches", "queue_depth"])
        blob = str(rendered)
        for suppressed_average in ("'12'", "'9'", "'7'", "'3'"):
            self.assertNotIn(suppressed_average, blob)

    def test_estimated_material_never_exported(self):
        rendered = self._internal((summary(estimated_count=99),)).safe_dict()
        self.assertNotIn("estimated", str(rendered).lower())
        for item in rendered["metrics"]:
            self.assertNotIn("estimated_count", item)

    def test_unknown_new_field_does_not_leak_automatically(self):
        class _ExtendedSummary(PilotMetricSummary):
            pass

        extended = _ExtendedSummary(
            metric_key="request_to_po_minutes",
            definition_version=1,
            baseline_measured_count=5,
            current_measured_count=6,
            estimated_count=0,
            baseline_average=Decimal("100"),
            current_average=Decimal("40"),
            absolute_change=Decimal("-60"),
            percent_change=Decimal("-60"),
            direction=MetricDirection.LOWER_IS_BETTER,
            evidence_refs=(),
        )
        object.__setattr__(extended, "future_raw_field", "raw-future-secret-42")
        rendered = self._internal((extended,)).safe_dict()
        self.assertNotIn("raw-future-secret-42", str(rendered))
        self.assertNotIn("future_raw_field", str(rendered))
        self.assertEqual(
            sorted(rendered["metrics"][0].keys()),
            sorted(
                [
                    "metric_key",
                    "definition_version",
                    "baseline_measured_count",
                    "current_measured_count",
                    "baseline_average",
                    "current_average",
                    "absolute_change",
                    "percent_change",
                    "direction",
                    "evidence_refs_exported",
                    "workflow_refs_exported",
                    "raw_observations_exported",
                ]
            ),
        )

    def test_output_is_deterministic(self):
        first = self._internal((summary("b_key"), summary("a_key"))).safe_dict()
        second = self._internal((summary("b_key"), summary("a_key"))).safe_dict()
        self.assertEqual(first, second)

    def test_default_policy_threshold_is_five(self):
        self.assertEqual(PilotPrivacyExportPolicy().minimum_measured_count, 5)
        rendered = self._internal(
            (
                summary("edge_ok", baseline_count=5, current_count=5),
                summary("edge_low", baseline_count=5, current_count=4),
            )
        ).safe_dict()
        self.assertEqual([item["metric_key"] for item in rendered["metrics"]], ["edge_ok"])
        self.assertEqual(rendered["suppressed_metric_keys"], ["edge_low"])
        self.assertEqual(rendered["minimum_measured_count"], 5)


if __name__ == "__main__":
    unittest.main()
