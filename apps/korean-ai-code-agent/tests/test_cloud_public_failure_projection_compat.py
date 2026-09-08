"""B54 compatibility tests: shared Core projection vs the Cloud M1 scaffold (#1558).

Proves semantic parity between the promoted shared primitive
(``padiem_ai_core.public_failure_projection``) and the B54 product scaffold
(``kagent.cloud_public_failure``) without moving the B54 lifecycle into the
Engine authority: the Cloud M1 stage names stay in B54 and are supplied to the
shared primitive as a product stage mapping.

Stdlib unittest only: the canonical KAgent CI runs
``python -m unittest discover -s tests`` without pytest installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from kagent.cloud_execution_plan import CloudM1Stage
from kagent.cloud_public_failure import (
    _STAGE_CATEGORY,
    PublicCloudFailureCategory,
    project_public_failure,
)
from kagent.cloud_stage_receipts import CloudM1StageReceipt, CloudStageOutcome
from kagent.contracts import ContractError
from padiem_ai_core.public_failure_projection import (
    PublicFailureCategory,
    StageFailureReceipt,
    StageOutcome,
    project_stage_failure,
)

_PLAN_ID = "claw-plan-1558"
_FINGERPRINT = hashlib.sha256(b"claw-plan-material").hexdigest()

# Product-owned projection of the B54 Cloud M1 lifecycle onto shared categories.
CLOUD_M1_TO_SHARED_CATEGORY = {
    CloudM1Stage.ADMISSION.value: PublicFailureCategory.POLICY_OR_ADMISSION_FAILED,
    CloudM1Stage.REPOSITORY_MATERIALIZATION.value: PublicFailureCategory.REPOSITORY_MATERIALIZATION_FAILED,
    CloudM1Stage.SANDBOX_READY.value: PublicFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
    CloudM1Stage.AGENT_COMPUTER_READY.value: PublicFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
    CloudM1Stage.P01_EXECUTION.value: PublicFailureCategory.AGENT_EXECUTION_FAILED,
    CloudM1Stage.VERIFICATION.value: PublicFailureCategory.VERIFICATION_FAILED,
    CloudM1Stage.ARTIFACT_COLLECTION.value: PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.VERIFIED_DIFF.value: PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.OPTIONAL_DRAFT_PR.value: PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.TEARDOWN.value: PublicFailureCategory.TEARDOWN_FAILED,
}


def _now() -> datetime:
    return datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


def _b54_receipt(
    stage: CloudM1Stage,
    outcome: CloudStageOutcome = CloudStageOutcome.FAILED,
    summary_code: str | None = None,
) -> CloudM1StageReceipt:
    return CloudM1StageReceipt(
        event_id=f"evt-{stage.value}",
        plan_id=_PLAN_ID,
        plan_fingerprint=_FINGERPRINT,
        stage=stage,
        outcome=outcome,
        observed_at=_now(),
        evidence_ref=f"ev-{stage.value}",
        summary_code=summary_code or f"claw.{stage.value}.failed",
    )


def _shared_receipt(
    stage_value: str,
    outcome: StageOutcome = StageOutcome.FAILED,
    summary_code: str | None = None,
) -> StageFailureReceipt:
    return StageFailureReceipt(
        plan_id=_PLAN_ID,
        plan_fingerprint=_FINGERPRINT,
        stage_id=stage_value,
        outcome=outcome,
        summary_code=summary_code or f"claw.{stage_value}.failed",
        event_id=f"evt-{stage_value}",
        evidence_ref=f"ev-{stage_value}",
    )


def _project_shared(receipt_value: StageFailureReceipt):
    return project_stage_failure(
        receipt_value,
        expected_plan_id=_PLAN_ID,
        expected_plan_fingerprint=_FINGERPRINT,
        stage_categories=CLOUD_M1_TO_SHARED_CATEGORY,
    )


class CloudPublicFailureProjectionCompatTests(unittest.TestCase):
    def test_shared_stage_mapping_matches_b54_scaffold_for_every_stage(self) -> None:
        b54_map = {stage.value: category.value for stage, category in _STAGE_CATEGORY.items()}
        shared_map = {stage: category.value for stage, category in CLOUD_M1_TO_SHARED_CATEGORY.items()}
        self.assertEqual(shared_map, b54_map)
        self.assertEqual(set(shared_map), {stage.value for stage in CloudM1Stage})

    def test_both_layers_project_the_same_category_for_every_stage(self) -> None:
        for stage in CloudM1Stage:
            with self.subTest(stage=stage.value):
                b54_projection = project_public_failure(
                    _b54_receipt(stage),
                    expected_plan_id=_PLAN_ID,
                    expected_plan_fingerprint=_FINGERPRINT,
                )
                shared_projection = _project_shared(_shared_receipt(stage.value))
                self.assertEqual(b54_projection.category.value, shared_projection.category.value)
                self.assertEqual(b54_projection.summary_code, shared_projection.summary_code)
                self.assertFalse(b54_projection.retryable)
                self.assertFalse(shared_projection.retryable)
                if stage is CloudM1Stage.TEARDOWN:
                    self.assertIs(shared_projection.category, PublicFailureCategory.TEARDOWN_FAILED)

    def test_shared_public_dict_keeps_b54_inert_flags(self) -> None:
        public = _project_shared(_shared_receipt(CloudM1Stage.TEARDOWN.value)).to_public_dict()
        b54_public = project_public_failure(
            _b54_receipt(CloudM1Stage.TEARDOWN),
            expected_plan_id=_PLAN_ID,
            expected_plan_fingerprint=_FINGERPRINT,
        ).safe_dict()
        for key in (
            "raw_provider_error",
            "raw_terminal_output",
            "raw_diff",
            "tool_args",
            "credentials",
            "hidden_reasoning",
            "automatic_retry",
        ):
            self.assertIs(public[key], False)
            self.assertIs(b54_public[key], False)

    def test_non_failed_receipt_rejected_by_both_layers(self) -> None:
        pairs = [
            (CloudStageOutcome.SUCCEEDED, StageOutcome.SUCCEEDED, "claw.verification.done"),
            (CloudStageOutcome.SKIPPED, StageOutcome.SKIPPED, "claw.verification.skipped"),
        ]
        for b54_outcome, shared_outcome, code in pairs:
            with self.subTest(outcome=b54_outcome.value):
                with self.assertRaisesRegex(ContractError, "only failed stage receipt"):
                    project_public_failure(
                        _b54_receipt(CloudM1Stage.VERIFICATION, outcome=b54_outcome, summary_code=code),
                        expected_plan_id=_PLAN_ID,
                        expected_plan_fingerprint=_FINGERPRINT,
                    )
                with self.assertRaisesRegex(ValueError, "only a failed stage receipt"):
                    _project_shared(
                        _shared_receipt(
                            CloudM1Stage.VERIFICATION.value,
                            outcome=shared_outcome,
                            summary_code=code,
                        )
                    )

    def test_plan_binding_rejected_by_both_layers(self) -> None:
        with self.assertRaisesRegex(ContractError, "does not bind expected plan"):
            project_public_failure(
                _b54_receipt(CloudM1Stage.P01_EXECUTION),
                expected_plan_id="other-plan",
                expected_plan_fingerprint=_FINGERPRINT,
            )
        with self.assertRaisesRegex(ValueError, "does not bind the expected plan"):
            project_stage_failure(
                _shared_receipt(CloudM1Stage.P01_EXECUTION.value),
                expected_plan_id="other-plan",
                expected_plan_fingerprint=_FINGERPRINT,
                stage_categories=CLOUD_M1_TO_SHARED_CATEGORY,
            )

    def test_raw_failure_text_rejected_by_both_layers(self) -> None:
        raw = "RuntimeError: sandbox vm-77 crashed at /srv/secret with key sk-123456"
        with self.assertRaises(ContractError):
            _b54_receipt(CloudM1Stage.SANDBOX_READY, summary_code=raw)
        with self.assertRaisesRegex(ValueError, "bounded server-owned public-safe code"):
            _shared_receipt(CloudM1Stage.SANDBOX_READY.value, summary_code=raw)

    def test_projection_categories_are_fixed_public_values(self) -> None:
        for stage in CloudM1Stage:
            with self.subTest(stage=stage.value):
                projection = _project_shared(_shared_receipt(stage.value))
                self.assertIsInstance(projection.category, PublicFailureCategory)
                self.assertIsInstance(
                    PublicCloudFailureCategory(projection.category.value),
                    PublicCloudFailureCategory,
                )


if __name__ == "__main__":
    unittest.main()
