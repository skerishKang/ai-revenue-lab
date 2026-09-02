from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_pilot import CaseStudyConsent, MetricDirection, PilotMetricSummary
from kagent.ops_pilot_export import (
    CURRENCY_MINOR_DEFAULT_EXPORT_SUPPORTED,
    EXTERNAL_EXPORT_WITHOUT_CONSENT_SUPPORTED,
    RAW_PILOT_TELEMETRY_EXPORT_SUPPORTED,
    PilotExportPurpose,
    PilotPrivacyExportPolicy,
    build_privacy_safe_pilot_export,
)


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


if __name__ == "__main__":
    unittest.main()
