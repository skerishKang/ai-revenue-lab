from __future__ import annotations

import unittest

from kagent.cloud_execution_plan import (
    CLIENT_CONTROLLED_STAGE_ORDER_SUPPORTED,
    CLIENT_CONTROLLED_TEARDOWN_OMISSION_SUPPORTED,
    FIXED_CLOUD_M1_STAGE_ORDER,
    REAL_CLOUD_M1_PLAN_EXECUTION_CONFIGURED,
    CloudM1ExecutionPlan,
    CloudM1Stage,
)
from kagent.contracts import ContractError, NetworkPolicy


REV = "abcdef1234567890abcdef1234567890abcdef12"


def make_plan(**kwargs):
    values = dict(
        plan_id="plan_1",
        run_id="run_1",
        workspace_id="ws_1",
        repository_ref="skerishKang/example",
        input_revision=REV,
        verification_command_ids=("verify_unit",),
        artifact_policy_ref="artifact-policy:m1",
    )
    values.update(kwargs)
    return CloudM1ExecutionPlan(**values)


class CloudExecutionPlanTests(unittest.TestCase):
    def test_stage_order_is_fixed_and_teardown_is_mandatory(self):
        plan = make_plan()
        self.assertEqual(plan.stages, FIXED_CLOUD_M1_STAGE_ORDER)
        self.assertEqual(plan.stages[0], CloudM1Stage.ADMISSION)
        self.assertEqual(plan.stages[-1], CloudM1Stage.TEARDOWN)
        self.assertFalse(CLIENT_CONTROLLED_STAGE_ORDER_SUPPORTED)
        self.assertFalse(CLIENT_CONTROLLED_TEARDOWN_OMISSION_SUPPORTED)
        rendered = plan.safe_dict()
        self.assertTrue(rendered["teardown_mandatory"])

    def test_reordered_or_missing_teardown_stage_fails_closed(self):
        with self.assertRaises(ContractError):
            make_plan(stages=tuple(reversed(FIXED_CLOUD_M1_STAGE_ORDER)))
        with self.assertRaises(ContractError):
            make_plan(stages=FIXED_CLOUD_M1_STAGE_ORDER[:-1])

    def test_exact_40_hex_revision_and_network_off_are_required(self):
        for revision in ("main", "abcdef1", "g" * 40):
            with self.subTest(revision=revision):
                with self.assertRaises(ContractError):
                    make_plan(input_revision=revision)
        with self.assertRaises(ContractError):
            make_plan(network_policy=NetworkPolicy.RESTRICTED)

    def test_verification_commands_are_server_refs_not_arbitrary_shell(self):
        with self.assertRaises(ContractError):
            make_plan(verification_command_ids=())
        with self.assertRaises(ContractError):
            make_plan(verification_command_ids=("verify_unit", "verify_unit"))
        with self.assertRaises(ContractError):
            make_plan(verification_command_ids=("bash -c rm",))

    def test_preview_ports_are_bounded_unique_and_explicit(self):
        plan = make_plan(browser_required=True, preview_ports=(3000, 4173))
        self.assertEqual(plan.preview_ports, (3000, 4173))
        for ports in ((1023,), (65536,), (3000, 3000)):
            with self.subTest(ports=ports):
                with self.assertRaises(ContractError):
                    make_plan(preview_ports=ports)

    def test_fingerprint_changes_with_material_execution_inputs(self):
        base = make_plan()
        variants = (
            make_plan(input_revision="1234567890abcdef1234567890abcdef12345678"),
            make_plan(verification_command_ids=("verify_unit", "verify_contract")),
            make_plan(artifact_policy_ref="artifact-policy:strict"),
            make_plan(browser_required=True),
            make_plan(preview_ports=(3000,)),
            make_plan(draft_pr_requested=True),
        )
        for changed in variants:
            with self.subTest(fingerprint=changed.fingerprint):
                self.assertNotEqual(base.fingerprint, changed.fingerprint)

    def test_safe_projection_contains_no_credentials_routes_prompt_or_tool_state(self):
        rendered = make_plan(draft_pr_requested=True).safe_dict()
        self.assertFalse(rendered["credentials_in_plan"])
        self.assertFalse(rendered["provider_route_in_plan"])
        self.assertFalse(rendered["raw_task_prompt_in_plan"])
        self.assertFalse(rendered["tool_args_in_plan"])
        self.assertFalse(rendered["hidden_reasoning_in_plan"])
        self.assertFalse(rendered["arbitrary_shell_in_plan"])
        self.assertFalse(rendered["real_execution"])
        self.assertFalse(REAL_CLOUD_M1_PLAN_EXECUTION_CONFIGURED)


if __name__ == "__main__":
    unittest.main()
