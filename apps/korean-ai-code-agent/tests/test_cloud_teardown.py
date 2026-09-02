from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.cloud_execution_plan import CloudM1ExecutionPlan, CloudM1Stage
from kagent.cloud_teardown import (
    FALSE_CLEAN_TEARDOWN_SUPPORTED,
    REAL_TEARDOWN_PROBE_CONFIGURED,
    CloudM1TeardownReceipt,
    TrustedTeardownObservation,
)
from kagent.cloud_stage_receipts import CloudStageOutcome
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
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
    )


def observation(**kwargs):
    values = dict(
        observation_id="obs_1",
        plan_id="plan_1",
        run_id="run_1",
        sandbox_lease_ref="sandbox:1",
        computer_ref="computer:1",
        observed_at=NOW,
        process_tree_killed=True,
        active_child_process_count=0,
        workspace_destroyed=True,
        sandbox_terminal=True,
        computer_terminal=True,
        preview_shares_terminal=True,
        human_control_terminal=True,
        artifacts_finalized=True,
        authority_ref="provider-attestation:1",
    )
    values.update(kwargs)
    return TrustedTeardownObservation(**values)


class CloudTeardownTests(unittest.TestCase):
    def test_all_required_controls_produce_clean_success_stage_receipt(self):
        p = plan()
        obs = observation()
        self.assertTrue(obs.clean)
        receipt = CloudM1TeardownReceipt.from_observation(receipt_id="teardown_1", plan=p, observation=obs)
        self.assertTrue(receipt.clean)
        stage = receipt.as_stage_receipt(event_id="event_teardown_1")
        self.assertEqual(stage.stage, CloudM1Stage.TEARDOWN)
        self.assertEqual(stage.outcome, CloudStageOutcome.SUCCEEDED)
        self.assertEqual(stage.plan_fingerprint, p.fingerprint)

    def test_each_incomplete_control_prevents_clean_teardown(self):
        cases = (
            {"process_tree_killed": False},
            {"active_child_process_count": 1},
            {"workspace_destroyed": False},
            {"sandbox_terminal": False},
            {"computer_terminal": False},
            {"preview_shares_terminal": False},
            {"human_control_terminal": False},
            {"artifacts_finalized": False},
        )
        p = plan()
        for index, changes in enumerate(cases):
            with self.subTest(changes=changes):
                obs = observation(observation_id=f"obs_{index}", **changes)
                self.assertFalse(obs.clean)
                receipt = CloudM1TeardownReceipt.from_observation(receipt_id=f"receipt_{index}", plan=p, observation=obs)
                self.assertFalse(receipt.clean)
                self.assertEqual(receipt.as_stage_receipt(event_id=f"event_{index}").outcome, CloudStageOutcome.FAILED)

    def test_observation_identity_must_match_plan(self):
        p = plan()
        with self.assertRaises(ContractError):
            CloudM1TeardownReceipt.from_observation(receipt_id="r1", plan=p, observation=observation(plan_id="other_plan"))
        with self.assertRaises(ContractError):
            CloudM1TeardownReceipt.from_observation(receipt_id="r2", plan=p, observation=observation(run_id="other_run"))

    def test_child_process_count_is_bounded_and_boolean_rejected(self):
        for value in (-1, True, 1_000_001):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    observation(active_child_process_count=value)

    def test_no_computer_requires_terminal_truth_not_unknown_state(self):
        with self.assertRaises(ContractError):
            observation(computer_ref=None, computer_terminal=False)
        obs = observation(computer_ref=None, computer_terminal=True)
        self.assertTrue(obs.clean)

    def test_safe_receipt_contains_hash_and_no_raw_provider_or_credential_payload(self):
        receipt = CloudM1TeardownReceipt.from_observation(receipt_id="teardown_1", plan=plan(), observation=observation())
        rendered = receipt.safe_dict()
        self.assertEqual(len(rendered["evidence_sha256"]), 64)
        self.assertFalse(rendered["raw_runtime_payload"])
        self.assertFalse(rendered["provider_endpoint"])
        self.assertFalse(rendered["credential_value"])
        self.assertFalse(rendered["false_clean_teardown_supported"])
        self.assertFalse(REAL_TEARDOWN_PROBE_CONFIGURED)
        self.assertFalse(FALSE_CLEAN_TEARDOWN_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
