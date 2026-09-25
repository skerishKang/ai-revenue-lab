"""Source-only contract tests for the future GCP Seoul N2 live probe gate."""

from __future__ import annotations

import unittest

from kagent.contracts import ContractError
from kagent.gcp_seoul_n2_live_gate import (
    GCP_N2_CENTRAL_CONFIRMATION,
    GCP_N2_LIVE_DISPATCH_TRIGGERED,
    build_gcp_seoul_n2_live_probe_gate,
)
from kagent.sandbox_provider_probe import (
    SandboxProviderCandidate,
    build_candidate_launch_profile,
    build_live_probe_plan,
)


MAIN = "60b743d04e838b75a0b389b5d4f45dee5de67fe9"


class GCPSeoulN2LiveProbeGateTests(unittest.TestCase):
    def build(self, **overrides):
        values = dict(
            exact_main_sha=MAIN,
            central_confirmation=GCP_N2_CENTRAL_CONFIRMATION,
            zone="asia-northeast3-a",
            ttl_seconds=900,
        )
        values.update(overrides)
        return build_gcp_seoul_n2_live_probe_gate(**values)

    def test_source_gate_reuses_canonical_profile_and_plan(self):
        gate = self.build()
        profile = build_candidate_launch_profile(SandboxProviderCandidate.GCP_SEOUL_N2)
        plan = build_live_probe_plan(profile)
        self.assertEqual(gate.profile.profile_ref, profile.profile_ref)
        self.assertEqual(gate.plan.plan_ref, plan.plan_ref)
        self.assertEqual(gate.plan.probes, plan.probes)
        self.assertTrue(gate.metadata_negative_test_required)
        self.assertTrue(gate.process_tree_death_required)
        self.assertTrue(gate.non_resurrection_required)

    def test_safe_projection_is_closed_and_contains_no_authority_or_payload(self):
        rendered = self.build().safe_dict()
        self.assertEqual(rendered["candidate"], "gcp_seoul_n2")
        self.assertEqual(rendered["plan_ref"], "plan:cloud-m1/gcp_seoul_n2/live-probe-v1")
        self.assertEqual(rendered["zone"], "asia-northeast3-a")
        self.assertEqual(rendered["ttl_action"], "DELETE")
        self.assertEqual(rendered["ttl_seconds"], 900)
        self.assertEqual(rendered["resource_lineage"], "single_fresh_resource_lineage")
        self.assertEqual(rendered["provider_calls"], 0)
        self.assertEqual(rendered["workflow_dispatches"], 0)
        self.assertEqual(rendered["cloud_resources_created"], 0)
        self.assertEqual(rendered["credential_bindings"], 0)
        self.assertEqual(rendered["production_mutations"], 0)
        self.assertFalse(rendered["live_dispatch_allowed"])
        self.assertFalse(rendered["provider_selected"])
        self.assertFalse(rendered["deployment_approval"])
        self.assertFalse(rendered["production_ready_claim"])
        for forbidden in ("project_id", "account_id", "credential", "service_account", "endpoint", "raw_payload"):
            self.assertNotIn(forbidden, rendered)

    def test_every_future_runtime_control_remains_unproven(self):
        rendered = self.build().safe_dict()
        for key in (
            "metadata_negative_test_required",
            "process_tree_death_required",
            "non_resurrection_required",
        ):
            self.assertIs(rendered[key], True)
        self.assertIs(GCP_N2_LIVE_DISPATCH_TRIGGERED, False)

    def test_confirmation_exact_main_zone_and_ttl_fail_closed(self):
        for overrides in (
            {"exact_main_sha": "main"},
            {"central_confirmation": "YES"},
            {"zone": "us-central1-a"},
            {"zone": "asia-northeast3-d"},
            {"ttl_seconds": 901},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ContractError):
                    self.build(**overrides)

    def test_source_builder_does_not_dispatch_or_call_provider(self):
        gate = self.build()
        self.assertFalse(gate.safe_dict()["live_dispatch_allowed"])
        self.assertFalse(GCP_N2_LIVE_DISPATCH_TRIGGERED)


if __name__ == "__main__":
    unittest.main()
