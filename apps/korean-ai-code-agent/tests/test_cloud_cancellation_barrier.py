from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.cloud_execution_plan import CloudM1ExecutionPlan, CloudM1Stage
from kagent.cloud_stage_receipts import (
    B54_CANONICAL_P01_CANCELLATION_AUTHORITY,
    POST_CANCELLATION_OUTPUT_SUPPORTED,
    CloudExecutionTerminal,
    CloudM1StageReceipt,
    CloudM1StageReceiptLedger,
    CloudStageOutcome,
)
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 7, 0, tzinfo=timezone.utc)
REV = "abcdef1234567890abcdef1234567890abcdef12"


def plan():
    return CloudM1ExecutionPlan(
        plan_id="plan_1",
        run_id="run_1",
        workspace_id="ws_1",
        repository_ref="skerishKang/example",
        input_revision=REV,
        verification_command_ids=("verify_unit",),
        artifact_policy_ref="artifact-policy:m1",
        draft_pr_requested=True,
    )


def receipt(p, stage, *, outcome=CloudStageOutcome.SUCCEEDED, event_id=None, seconds=0):
    return CloudM1StageReceipt(
        event_id=event_id or f"event_{stage.value}_{seconds}",
        plan_id=p.plan_id,
        plan_fingerprint=p.fingerprint,
        stage=stage,
        outcome=outcome,
        observed_at=NOW + timedelta(seconds=seconds),
        evidence_ref=f"evidence:{stage.value}:{seconds}",
        summary_code=f"stage_{outcome.value}",
    )


class CloudCancellationBarrierTests(unittest.TestCase):
    def test_cancellation_before_work_forces_teardown(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        projection = ledger.request_cancellation(
            cancellation_ref="cancel:1",
            run_id=p.run_id,
            observed_at=NOW,
        )
        self.assertEqual(projection.next_stage, CloudM1Stage.TEARDOWN)
        self.assertEqual(projection.cancellation_ref, "cancel:1")
        final = ledger.append(receipt(p, CloudM1Stage.TEARDOWN, seconds=1))
        self.assertEqual(final.terminal, CloudExecutionTerminal.CANCELLED_CLEANED_UP)

    def test_cancellation_after_progress_blocks_all_forward_output_stages(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        ledger.append(receipt(p, CloudM1Stage.ADMISSION, seconds=1))
        ledger.append(receipt(p, CloudM1Stage.REPOSITORY_MATERIALIZATION, seconds=2))
        cancelled = ledger.request_cancellation(
            cancellation_ref="cancel:1",
            run_id=p.run_id,
            observed_at=NOW + timedelta(seconds=3),
        )
        self.assertEqual(cancelled.next_stage, CloudM1Stage.TEARDOWN)
        for stage in (
            CloudM1Stage.SANDBOX_READY,
            CloudM1Stage.P01_EXECUTION,
            CloudM1Stage.VERIFICATION,
            CloudM1Stage.ARTIFACT_COLLECTION,
            CloudM1Stage.VERIFIED_DIFF,
            CloudM1Stage.OPTIONAL_DRAFT_PR,
        ):
            with self.subTest(stage=stage):
                with self.assertRaises(ContractError):
                    ledger.append(receipt(p, stage, seconds=4))
        final = ledger.append(receipt(p, CloudM1Stage.TEARDOWN, seconds=5))
        self.assertEqual(final.terminal, CloudExecutionTerminal.CANCELLED_CLEANED_UP)
        self.assertFalse(POST_CANCELLATION_OUTPUT_SUPPORTED)

    def test_exact_cancel_replay_is_idempotent_and_conflicting_replay_is_rejected(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        first = ledger.request_cancellation(cancellation_ref="cancel:1", run_id=p.run_id, observed_at=NOW)
        replay = ledger.request_cancellation(cancellation_ref="cancel:1", run_id=p.run_id, observed_at=NOW)
        self.assertEqual(first, replay)
        with self.assertRaises(ContractError):
            ledger.request_cancellation(cancellation_ref="cancel:2", run_id=p.run_id, observed_at=NOW)
        with self.assertRaises(ContractError):
            ledger.request_cancellation(cancellation_ref="cancel:1", run_id=p.run_id, observed_at=NOW + timedelta(seconds=1))

    def test_wrong_run_stale_cancel_and_post_terminal_cancel_fail_closed(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        ledger.append(receipt(p, CloudM1Stage.ADMISSION, seconds=2))
        with self.assertRaises(ContractError):
            ledger.request_cancellation(cancellation_ref="cancel:1", run_id="run_other", observed_at=NOW + timedelta(seconds=3))
        with self.assertRaises(ContractError):
            ledger.request_cancellation(cancellation_ref="cancel:1", run_id=p.run_id, observed_at=NOW + timedelta(seconds=1))
        ledger.request_cancellation(cancellation_ref="cancel:1", run_id=p.run_id, observed_at=NOW + timedelta(seconds=3))
        ledger.append(receipt(p, CloudM1Stage.TEARDOWN, seconds=4))
        with self.assertRaises(ContractError):
            ledger.request_cancellation(cancellation_ref="cancel:1", run_id=p.run_id, observed_at=NOW + timedelta(seconds=5))

    def test_teardown_failure_after_cancel_is_visible(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        ledger.request_cancellation(cancellation_ref="cancel:1", run_id=p.run_id, observed_at=NOW)
        final = ledger.append(receipt(p, CloudM1Stage.TEARDOWN, outcome=CloudStageOutcome.FAILED, seconds=1))
        self.assertEqual(final.terminal, CloudExecutionTerminal.TEARDOWN_FAILED)

    def test_existing_execution_failure_remains_failure_terminal_even_if_cancel_then_cleanup(self):
        p = plan()
        ledger = CloudM1StageReceiptLedger(p)
        ledger.append(receipt(p, CloudM1Stage.ADMISSION, outcome=CloudStageOutcome.FAILED, seconds=1))
        ledger.request_cancellation(cancellation_ref="cancel:after-failure", run_id=p.run_id, observed_at=NOW + timedelta(seconds=2))
        final = ledger.append(receipt(p, CloudM1Stage.TEARDOWN, seconds=3))
        self.assertEqual(final.terminal, CloudExecutionTerminal.FAILED_CLEANED_UP)

    def test_b54_does_not_claim_canonical_p01_cancellation_authority(self):
        rendered = CloudM1StageReceiptLedger(plan()).projection().safe_dict()
        self.assertFalse(rendered["p01_cancellation_authority"])
        self.assertFalse(rendered["automatic_resume"])
        self.assertFalse(rendered["automatic_redispatch"])
        self.assertFalse(B54_CANONICAL_P01_CANCELLATION_AUTHORITY)


if __name__ == "__main__":
    unittest.main()
