from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.cloud_execution_plan import CloudM1ExecutionPlan
from kagent.cloud_usage_metering import (
    B54_CREDIT_DEBIT_AUTHORITY,
    B54_PRICING_AUTHORITY,
    ESTIMATED_PROVIDER_COST_SUPPORTED,
    REAL_BILLING_API_CONFIGURED,
    TrustedResourceUsageObservation,
    build_usage_receipt,
)
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


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


def observation(p=None, **changes):
    p = p or plan()
    values = dict(
        observation_id="usage_obs_1",
        plan_id=p.plan_id,
        run_id=p.run_id,
        workspace_id=p.workspace_id,
        plan_fingerprint=p.fingerprint,
        wall_time_ms=120000,
        cpu_time_ms=45000,
        peak_memory_mib=512,
        disk_read_bytes=1000,
        disk_write_bytes=2000,
        network_egress_bytes=0,
        observed_at=NOW,
        authority_ref="trusted:sandbox-meter",
        evidence_ref="evidence:usage-1",
    )
    values.update(changes)
    return TrustedResourceUsageObservation(**values)


class CloudUsageMeteringTests(unittest.TestCase):
    def test_exact_plan_bound_observation_builds_measured_receipt(self):
        p = plan()
        receipt = build_usage_receipt(plan=p, observation=observation(p))
        safe = receipt.safe_dict()
        self.assertEqual(safe["wall_time_ms"], 120000)
        self.assertEqual(safe["network_egress_bytes"], 0)
        self.assertTrue(safe["measured"])
        self.assertTrue(safe["control_plane_handoff_only"])
        self.assertEqual(len(safe["receipt_fingerprint"]), 64)

    def test_negative_bool_and_network_egress_metrics_fail_closed(self):
        with self.assertRaises(ContractError):
            observation(wall_time_ms=-1)
        with self.assertRaises(ContractError):
            observation(cpu_time_ms=True)
        with self.assertRaises(ContractError):
            observation(network_egress_bytes=1)

    def test_plan_run_workspace_and_fingerprint_mismatch_fail_closed(self):
        p = plan()
        for changes in (
            {"plan_id": "plan_other"},
            {"run_id": "run_other"},
            {"workspace_id": "ws_other"},
            {"plan_fingerprint": "b" * 64},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ContractError):
                    build_usage_receipt(plan=p, observation=observation(p, **changes))

    def test_b54_has_no_pricing_credit_or_provider_cost_authority(self):
        self.assertFalse(B54_PRICING_AUTHORITY)
        self.assertFalse(B54_CREDIT_DEBIT_AUTHORITY)
        self.assertFalse(ESTIMATED_PROVIDER_COST_SUPPORTED)
        self.assertFalse(REAL_BILLING_API_CONFIGURED)


if __name__ == "__main__":
    unittest.main()
