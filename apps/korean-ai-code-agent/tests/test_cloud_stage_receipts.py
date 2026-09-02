from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.cloud_execution_plan import CloudM1ExecutionPlan, CloudM1Stage, FIXED_CLOUD_M1_STAGE_ORDER
from kagent.cloud_stage_receipts import (
    AUTOMATIC_STAGE_RETRY_SUPPORTED,
    POST_FAILURE_STAGE_CONTINUATION_SUPPORTED,
    CloudExecutionTerminal,
    CloudM1StageReceipt,
    CloudM1StageReceiptLedger,
    CloudStageOutcome,
)
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 5, 0, tzinfo=timezone.utc)
REV = "abcdef1234567890abcdef1234567890abcdef12"


def plan(*, draft_pr_requested=False):
    return CloudM1ExecutionPlan(
        plan_id="plan_1",
        run_id="run_1",
        workspace_id="ws_1",
        repository_ref="skerishKang/example",
        input_revision=REV,
        verification_command_ids=("verify_unit",),
        artifact_policy_ref="artifact-policy:m1",
        draft_pr_requested=draft_pr_requested,
    )


def receipt(p, stage, outcome=CloudStageOutcome.SUCCEEDED, index=0, *, event_id=None, observed_at=None):
    return CloudM1StageReceipt(
        event_id=event_id or f"event_{index}_{stage.value}",
        plan_id=p.plan_id,
        plan_fingerprint=p.fingerprint,
        stage=stage,
        outcome=outcome,
        observed_at=observed_at or NOW + timedelta(seconds=index),
        evidence_ref=f"evidence:{index}:{stage.value}",
        summary_code=f"stage_{outcome.value}",
    )


class CloudStageReceiptTests(unittest.TestCase):
    def test_all_success_with_unrequested_draft_pr_skip_completes_after_teardown(self):
        p = plan(draft_pr_requested=False)
        ledger = CloudM1StageReceiptLedger(p)
        for index, stage in enumerate(FIXED_CLOUD_M1_STAGE_ORDER):
            outcome = CloudStageOutcome.SKIPPED if stage is CloudM1Stage.OPTIONAL_DRAFT_PR else CloudStageOutcome.SUCCEEDED
            projection = ledger.append(receipt(p, stage, outcome, index))
        self.assertEqual(projection.terminal, CloudExecutionTerminal.COMPLETED)
        self.assertIsNone(projection.next_stage)
        self.assertIn(CloudM1Stage.TEARDOWN, projection.completed_stages)

    def test_requested_draft_pr_cannot_be_skipped(self):
        p = plan(draft_pr_requested=True)
        ledger = CloudM1StageReceiptLedger(p)
        for index, stage in enumerate(FIXED_CLOUD_M1_STAGE_ORDER[:8]):
            ledger.append(receipt(p, stage, CloudStageOutcome.SUCCEEDED, index))
        with self.assertRaises(ContractError):
            ledger.append(receipt(p, CloudM1Stage.OPTIONAL_DRAFT_PR, CloudStageOutcome.SKIPPED, 8))

    def test_out_of_order_receipt_is_rejected(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        with self.assertRaises(ContractError):
            ledger.append(receipt(p, CloudM1Stage.SANDBOX_READY, index=1))

    def test_exact_replay_is_idempotent_and_conflicting_replay_rejected(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        first = receipt(p, CloudM1Stage.ADMISSION, index=0, event_id="event_same")
        before = ledger.append(first)
        replay = ledger.append(first)
        self.assertEqual(before, replay)
        self.assertEqual(replay.receipt_count, 1)
        conflict = receipt(
            p,
            CloudM1Stage.ADMISSION,
            outcome=CloudStageOutcome.FAILED,
            index=0,
            event_id="event_same",
        )
        with self.assertRaises(ContractError):
            ledger.append(conflict)

    def test_failure_forces_teardown_and_blocks_post_failure_continuation(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        ledger.append(receipt(p, CloudM1Stage.ADMISSION, index=0))
        projection = ledger.append(receipt(p, CloudM1Stage.REPOSITORY_MATERIALIZATION, CloudStageOutcome.FAILED, 1))
        self.assertEqual(projection.next_stage, CloudM1Stage.TEARDOWN)
        self.assertEqual(projection.failed_stage, CloudM1Stage.REPOSITORY_MATERIALIZATION)
        with self.assertRaises(ContractError):
            ledger.append(receipt(p, CloudM1Stage.SANDBOX_READY, index=2))
        final = ledger.append(receipt(p, CloudM1Stage.TEARDOWN, CloudStageOutcome.SUCCEEDED, 3))
        self.assertEqual(final.terminal, CloudExecutionTerminal.FAILED_CLEANED_UP)
        self.assertFalse(AUTOMATIC_STAGE_RETRY_SUPPORTED)
        self.assertFalse(POST_FAILURE_STAGE_CONTINUATION_SUPPORTED)

    def test_teardown_failure_is_visible_terminal(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        ledger.append(receipt(p, CloudM1Stage.ADMISSION, CloudStageOutcome.FAILED, 0))
        final = ledger.append(receipt(p, CloudM1Stage.TEARDOWN, CloudStageOutcome.FAILED, 1))
        self.assertEqual(final.terminal, CloudExecutionTerminal.TEARDOWN_FAILED)
        self.assertIsNone(final.next_stage)

    def test_monotonic_time_and_plan_correlation_are_enforced(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        ledger.append(receipt(p, CloudM1Stage.ADMISSION, index=2))
        with self.assertRaises(ContractError):
            ledger.append(receipt(p, CloudM1Stage.REPOSITORY_MATERIALIZATION, index=1))
        other = plan()
        bad = CloudM1StageReceipt(
            event_id="bad_plan",
            plan_id="other_plan",
            plan_fingerprint=other.fingerprint,
            stage=CloudM1Stage.REPOSITORY_MATERIALIZATION,
            outcome=CloudStageOutcome.SUCCEEDED,
            observed_at=NOW + timedelta(seconds=3),
            evidence_ref="evidence:bad",
            summary_code="stage_succeeded",
        )
        with self.assertRaises(ContractError):
            ledger.append(bad)

    def test_safe_receipts_have_no_raw_runtime_payload(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        ledger.append(receipt(p, CloudM1Stage.ADMISSION, index=0))
        rendered = ledger.safe_receipts()[0]
        self.assertFalse(rendered["raw_runtime_payload"])
        self.assertFalse(rendered["raw_diff"])
        self.assertFalse(rendered["tool_args"])
        self.assertFalse(rendered["hidden_reasoning"])


if __name__ == "__main__":
    unittest.main()
