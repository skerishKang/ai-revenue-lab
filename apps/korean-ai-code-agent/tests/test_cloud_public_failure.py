from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.cloud_execution_plan import CloudM1ExecutionPlan, CloudM1Stage
from kagent.cloud_public_failure import (
    AUTOMATIC_FAILURE_RETRY_SUPPORTED,
    RAW_PROVIDER_FAILURE_UI_SUPPORTED,
    RAW_TERMINAL_FAILURE_UI_SUPPORTED,
    PublicCloudFailureCategory,
    project_public_failure,
)
from kagent.cloud_stage_receipts import CloudM1StageReceipt, CloudStageOutcome
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)


def plan():
    return CloudM1ExecutionPlan(
        plan_id="plan_1",
        run_id="run_1",
        workspace_id="ws_1",
        repository_ref="skerishKang/example",
        input_revision="a" * 40,
        verification_command_ids=("verify_unit",),
        artifact_policy_ref="artifact_policy_1",
    )


def failed(stage, *, summary_code="stage_failed"):
    p = plan()
    return CloudM1StageReceipt(
        event_id=f"evt_{stage.value}",
        plan_id=p.plan_id,
        plan_fingerprint=p.fingerprint,
        stage=stage,
        outcome=CloudStageOutcome.FAILED,
        observed_at=NOW,
        evidence_ref="evidence:failure-1",
        summary_code=summary_code,
    )


class PublicCloudFailureTests(unittest.TestCase):
    def test_stage_categories_are_fixed_and_teardown_is_distinct(self):
        p = plan()
        expected = {
            CloudM1Stage.ADMISSION: PublicCloudFailureCategory.POLICY_OR_ADMISSION_FAILED,
            CloudM1Stage.REPOSITORY_MATERIALIZATION: PublicCloudFailureCategory.REPOSITORY_MATERIALIZATION_FAILED,
            CloudM1Stage.SANDBOX_READY: PublicCloudFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
            CloudM1Stage.AGENT_COMPUTER_READY: PublicCloudFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
            CloudM1Stage.P01_EXECUTION: PublicCloudFailureCategory.AGENT_EXECUTION_FAILED,
            CloudM1Stage.VERIFICATION: PublicCloudFailureCategory.VERIFICATION_FAILED,
            CloudM1Stage.ARTIFACT_COLLECTION: PublicCloudFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
            CloudM1Stage.VERIFIED_DIFF: PublicCloudFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
            CloudM1Stage.OPTIONAL_DRAFT_PR: PublicCloudFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
            CloudM1Stage.TEARDOWN: PublicCloudFailureCategory.TEARDOWN_FAILED,
        }
        for stage, category in expected.items():
            with self.subTest(stage=stage):
                projection = project_public_failure(failed(stage), expected_plan_id=p.plan_id, expected_plan_fingerprint=p.fingerprint)
                self.assertEqual(projection.category, category)
                self.assertFalse(projection.retryable)

    def test_non_failed_or_wrong_plan_receipt_is_rejected(self):
        p = plan()
        ok = CloudM1StageReceipt(
            event_id="evt_ok",
            plan_id=p.plan_id,
            plan_fingerprint=p.fingerprint,
            stage=CloudM1Stage.ADMISSION,
            outcome=CloudStageOutcome.SUCCEEDED,
            observed_at=NOW,
            evidence_ref="evidence:ok",
            summary_code="ok",
        )
        with self.assertRaises(ContractError):
            project_public_failure(ok, expected_plan_id=p.plan_id, expected_plan_fingerprint=p.fingerprint)
        with self.assertRaises(ContractError):
            project_public_failure(failed(CloudM1Stage.P01_EXECUTION), expected_plan_id="plan_other", expected_plan_fingerprint=p.fingerprint)

    def test_unbounded_raw_error_shape_is_not_accepted_as_summary_code(self):
        with self.assertRaises(ContractError):
            failed(CloudM1Stage.P01_EXECUTION, summary_code="Traceback: token=should-not-appear")

    def test_safe_projection_contains_no_raw_failure_payload(self):
        p = plan()
        safe = project_public_failure(failed(CloudM1Stage.VERIFICATION), expected_plan_id=p.plan_id, expected_plan_fingerprint=p.fingerprint).safe_dict()
        self.assertFalse(safe["raw_provider_error"])
        self.assertFalse(safe["raw_terminal_output"])
        self.assertFalse(safe["raw_diff"])
        self.assertFalse(safe["tool_args"])
        self.assertFalse(safe["credentials"])
        self.assertFalse(safe["hidden_reasoning"])
        self.assertFalse(safe["automatic_retry"])
        self.assertFalse(RAW_PROVIDER_FAILURE_UI_SUPPORTED)
        self.assertFalse(RAW_TERMINAL_FAILURE_UI_SUPPORTED)
        self.assertFalse(AUTOMATIC_FAILURE_RETRY_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
