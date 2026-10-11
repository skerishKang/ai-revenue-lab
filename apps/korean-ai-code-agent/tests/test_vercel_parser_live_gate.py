"""Source-only tests for the future Vercel isolated-parser live probe gate."""

from __future__ import annotations

import unittest

from kagent.contracts import ContractError
from kagent.sandbox_provider_probe import (
    SandboxProviderCandidate,
    build_candidate_launch_profile,
    build_live_probe_plan,
)
from kagent.vercel_parser_live_gate import (
    PARSER_HARD_DEADLINE_SECONDS,
    VERCEL_PARSER_CENTRAL_CONFIRMATION,
    VERCEL_PARSER_LIVE_DISPATCH_TRIGGERED,
    build_vercel_parser_live_probe_gate,
)

MAIN = "89d93ecdc7a71973d92d397afe9ae5e417986006"


class VercelParserLiveProbeGateTests(unittest.TestCase):
    def build(self, **overrides):
        values = dict(
            exact_main_sha=MAIN,
            central_confirmation=VERCEL_PARSER_CENTRAL_CONFIRMATION,
            parser_deadline_seconds=30,
            sandbox_ttl_seconds=120,
        )
        values.update(overrides)
        return build_vercel_parser_live_probe_gate(**values)

    def test_reuses_canonical_vercel_profile_probe_plan_and_parser_contract(self):
        gate = self.build()
        profile = build_candidate_launch_profile(SandboxProviderCandidate.VERCEL_SANDBOX)
        plan = build_live_probe_plan(profile)
        self.assertEqual(gate.profile.profile_ref, profile.profile_ref)
        self.assertEqual(gate.plan.plan_ref, plan.plan_ref)
        self.assertEqual(gate.plan.probes, plan.probes)
        self.assertEqual(gate.parser_request_contract, "padiem_ai_core.isolated_parser_client")
        self.assertEqual(gate.parser_response_contract, "padiem_ai_core.isolated_parser_client")
        self.assertEqual(PARSER_HARD_DEADLINE_SECONDS, 30)

    def test_profile_is_fresh_nonpersistent_deny_all_and_no_guest_secrets(self):
        gate = self.build()
        settings = gate.profile.setting_map
        self.assertEqual(settings["networkPolicy"], "deny-all")
        self.assertIs(settings["persistent"], False)
        self.assertEqual(settings["public_port_count"], 0)
        self.assertEqual(settings["guest_secret_count"], 0)
        self.assertIs(settings["snapshot_reuse"], False)
        self.assertIs(settings["fork_reuse"], False)
        self.assertIs(settings["getOrCreate"], False)
        self.assertIs(settings["resume"], False)
        self.assertEqual(settings["teardown_sequence"], "stop_then_permanent_delete")

    def test_safe_projection_retains_every_runtime_blocker(self):
        rendered = self.build().safe_dict()
        self.assertEqual(rendered["candidate"], "vercel_sandbox")
        self.assertEqual(rendered["plan_ref"], "plan:cloud-m1/vercel_sandbox/live-probe-v1")
        self.assertEqual(rendered["parser_deadline_seconds"], 30)
        self.assertEqual(rendered["sandbox_ttl_seconds"], 120)
        self.assertTrue(rendered["metadata_negative_test_required"])
        self.assertTrue(rendered["process_tree_death_required"])
        self.assertTrue(rendered["non_resurrection_required"])
        self.assertTrue(rendered["resource_limits_required"])
        self.assertFalse(rendered["live_dispatch_allowed"])
        self.assertFalse(rendered["provider_selected"])
        self.assertFalse(rendered["production_parser_binding"])
        self.assertFalse(rendered["production_ready_claim"])
        self.assertEqual(rendered["provider_calls"], 0)
        self.assertEqual(rendered["sandbox_allocations"], 0)
        self.assertEqual(rendered["credential_bindings"], 0)
        self.assertEqual(rendered["production_mutations"], 0)

    def test_confirmation_exact_main_deadline_and_ttl_fail_closed(self):
        for overrides in (
            {"exact_main_sha": "main"},
            {"central_confirmation": "YES"},
            {"parser_deadline_seconds": 29},
            {"parser_deadline_seconds": 31},
            {"sandbox_ttl_seconds": 59},
            {"sandbox_ttl_seconds": 301},
            {"sandbox_ttl_seconds": 30},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ContractError):
                    self.build(**overrides)

    def test_source_builder_never_dispatches_calls_provider_or_binds_production(self):
        rendered = self.build().safe_dict()
        self.assertFalse(VERCEL_PARSER_LIVE_DISPATCH_TRIGGERED)
        self.assertFalse(rendered["live_dispatch_allowed"])
        self.assertFalse(rendered["production_parser_binding"])


if __name__ == "__main__":
    unittest.main()
