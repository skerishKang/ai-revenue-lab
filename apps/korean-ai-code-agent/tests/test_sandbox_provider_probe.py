from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError, ExecutionMode, NetworkPolicy, SandboxLeaseRequest
from kagent.sandbox_conformance import IsolationPrimitive
from kagent.sandbox_provider_evidence import capability_control_names
from kagent.sandbox_provider_probe import (
    PROVIDER_ACCOUNT_AUTHORIZATION_CONFIGURED,
    PROVIDER_LIVE_PROBE_EXECUTION_CONFIGURED,
    PRODUCTION_APPROVAL_FROM_LIVE_PROBE_PLAN_SUPPORTED,
    PROVIDER_SELECTION_FROM_LAUNCH_PROFILE_SUPPORTED,
    CloudM1ProviderLaunchProfile,
    ControlProbeSpec,
    ProbeMethod,
    ProviderLaunchSetting,
    ProviderProbeControlObservation,
    SandboxProviderCandidate,
    SandboxProviderLiveProbePlan,
    SandboxProviderLiveProbeResult,
    build_candidate_launch_profile,
    build_live_probe_plan,
)
from kagent.sandbox_provider_review import ProviderEvidenceStatus


NOW = datetime(2026, 9, 3, 1, 50, tzinfo=timezone.utc)


def lease(**kwargs):
    values = dict(
        run_id="run-fixture",
        execution_mode=ExecutionMode.CLOUD,
        repository_ref="repo:fixture",
        requested_revision="0123456789abcdef",
        ttl_seconds=900,
        network_policy=NetworkPolicy.OFF,
    )
    values.update(kwargs)
    return SandboxLeaseRequest(**values)


def observations(*, override_control=None, override_status=None, stale_control=None):
    result = []
    for control in capability_control_names():
        status = (
            override_status
            if control == override_control and override_status is not None
            else ProviderEvidenceStatus.VERIFIED
        )
        observed_at = NOW - timedelta(minutes=5)
        expires_at = NOW + timedelta(hours=1)
        if control == stale_control:
            observed_at = NOW - timedelta(hours=2)
            expires_at = NOW - timedelta(seconds=1)
        result.append(
            ProviderProbeControlObservation(
                control=control,
                status=status,
                evidence_ref=f"evidence:live/{control}",
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    return tuple(result)


def result_for(profile, plan, **kwargs):
    values = dict(
        candidate=profile.candidate,
        profile_ref=profile.profile_ref,
        plan_ref=plan.plan_ref,
        result_ref=f"result:live/{profile.candidate.value}/fixture",
        isolation_primitive=IsolationPrimitive.MICROVM,
        observations=observations(),
    )
    values.update(kwargs)
    return SandboxProviderLiveProbeResult(**values)


class CloudM1ProviderLaunchProfileTests(unittest.TestCase):
    def test_all_candidate_profiles_are_request_shape_only_and_fail_closed(self):
        for candidate in SandboxProviderCandidate:
            with self.subTest(candidate=candidate.value):
                profile = build_candidate_launch_profile(candidate)
                rendered = profile.safe_dict()
                self.assertTrue(profile.request_shape_ready)
                self.assertFalse(profile.live_execution_ready)
                self.assertTrue(rendered["network_off_enforced"])
                self.assertTrue(rendered["ephemeral_workspace_enforced"])
                self.assertTrue(rendered["persistent_storage_disabled"])
                self.assertTrue(rendered["secret_injection_disabled"])
                self.assertTrue(rendered["snapshot_reuse_disabled"])
                self.assertTrue(rendered["public_ports_disabled"])
                self.assertTrue(rendered["cross_run_reuse_disabled"])
                self.assertTrue(rendered["explicit_teardown_required"])
                self.assertFalse(rendered["provider_selected"])
                self.assertFalse(rendered["deployment_approval"])
                self.assertFalse(rendered["production_ready_claim"])
                self.assertFalse(rendered["credential_fields"])
                self.assertFalse(rendered["provider_endpoint_fields"])
                self.assertTrue(profile.unresolved_live_requirements)

    def test_provider_specific_network_and_lifecycle_settings_are_locked(self):
        modal = build_candidate_launch_profile(SandboxProviderCandidate.MODAL).setting_map
        self.assertIs(modal["block_network"], True)
        self.assertIs(modal["secret_injection"], False)
        self.assertIs(modal["snapshot_reuse"], False)

        daytona = build_candidate_launch_profile(SandboxProviderCandidate.DAYTONA).setting_map
        self.assertIs(daytona["networkBlockAll"], True)
        self.assertIs(daytona["ephemeral"], True)
        self.assertIs(daytona["shared_persistence"], False)

        runloop = build_candidate_launch_profile(SandboxProviderCandidate.RUNLOOP).setting_map
        self.assertEqual(runloop["network_policy"], "explicit_deny_all")
        self.assertIs(runloop["suspend_resume"], False)
        self.assertIs(runloop["explicit_teardown"], True)

        e2b = build_candidate_launch_profile(SandboxProviderCandidate.E2B).setting_map
        self.assertIs(e2b["allow_internet_access"], False)
        self.assertEqual(e2b["timeout_action"], "kill")
        self.assertIs(e2b["auto_resume"], False)

    def test_cloud_m1_profile_rejects_weakened_shape_duplicate_or_secret_material(self):
        base = build_candidate_launch_profile(SandboxProviderCandidate.E2B)
        with self.assertRaises(ContractError):
            CloudM1ProviderLaunchProfile(
                candidate=base.candidate,
                profile_ref=base.profile_ref,
                settings=base.settings,
                unresolved_live_requirements=base.unresolved_live_requirements,
                network_off_enforced=False,
            )
        with self.assertRaises(ContractError):
            CloudM1ProviderLaunchProfile(
                candidate=base.candidate,
                profile_ref=base.profile_ref,
                settings=base.settings + (base.settings[0],),
                unresolved_live_requirements=base.unresolved_live_requirements,
            )
        with self.assertRaises(ContractError):
            ProviderLaunchSetting(
                key="credential",
                expected_value="token=should-not-be-here",
                source_ref="policy:fixture",
            )
        with self.assertRaises(ContractError):
            build_candidate_launch_profile(SandboxProviderCandidate.MODAL, max_ttl_seconds=3601)

    def test_lease_validation_accepts_only_cloud_exact_revision_network_off_and_profile_ttl(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.MODAL, max_ttl_seconds=900)
        profile.validate_lease_request(lease())

        with self.assertRaises(ContractError):
            profile.validate_lease_request(lease(execution_mode=ExecutionMode.LOCAL))
        with self.assertRaises(ContractError):
            profile.validate_lease_request(lease(requested_revision=None))
        with self.assertRaises(ContractError):
            profile.validate_lease_request(lease(network_policy=NetworkPolicy.RESTRICTED))
        with self.assertRaises(ContractError):
            profile.validate_lease_request(lease(ttl_seconds=901))


class CloudM1ProviderLiveProbePlanTests(unittest.TestCase):
    def test_generated_plan_has_complete_exact_control_coverage(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.RUNLOOP)
        plan = build_live_probe_plan(profile)
        self.assertEqual(
            set(item.control for item in plan.probes),
            set(capability_control_names()),
        )
        plan.validate_profile(profile)
        rendered = plan.safe_dict()
        self.assertTrue(rendered["complete_control_coverage"])
        self.assertFalse(rendered["real_provider_call_executed"])
        self.assertFalse(rendered["provider_selected"])
        self.assertFalse(rendered["security_certification"])
        self.assertFalse(rendered["deployment_approval"])

    def test_probe_methods_match_control_type(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.E2B)
        by_control = {item.control: item.method for item in build_live_probe_plan(profile).probes}
        self.assertIs(by_control["network_deny_by_default"], ProbeMethod.IN_SANDBOX_NEGATIVE_TEST)
        self.assertIs(by_control["teardown_guaranteed"], ProbeMethod.LIFECYCLE_OBSERVATION)
        self.assertIs(by_control["cpu_limit_enforced"], ProbeMethod.PROVIDER_API_OBSERVATION)
        self.assertIs(by_control["terminal_output_sanitized"], ProbeMethod.ARTIFACT_VERIFICATION)
        self.assertIs(by_control["exact_revision_materialization"], ProbeMethod.ADAPTER_ASSERTION)

    def test_incomplete_duplicate_and_profile_mismatch_fail_closed(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.MODAL)
        full = build_live_probe_plan(profile)
        with self.assertRaises(ContractError):
            SandboxProviderLiveProbePlan(
                candidate=profile.candidate,
                plan_ref="plan:fixture/missing",
                launch_profile_ref=profile.profile_ref,
                probes=full.probes[:-1],
            )
        with self.assertRaises(ContractError):
            SandboxProviderLiveProbePlan(
                candidate=profile.candidate,
                plan_ref="plan:fixture/duplicate",
                launch_profile_ref=profile.profile_ref,
                probes=full.probes + (full.probes[0],),
            )
        other = build_candidate_launch_profile(SandboxProviderCandidate.DAYTONA)
        with self.assertRaises(ContractError):
            full.validate_profile(other)

    def test_unknown_control_and_bad_probe_ttl_fail_closed(self):
        with self.assertRaises(ContractError):
            ControlProbeSpec(
                control="invented_control",
                probe_id="probe:bad",
                method=ProbeMethod.ADAPTER_ASSERTION,
                success_criterion_ref="criterion:bad",
            )
        with self.assertRaises(ContractError):
            ControlProbeSpec(
                control=capability_control_names()[0],
                probe_id="probe:bad-ttl",
                method=ProbeMethod.ADAPTER_ASSERTION,
                success_criterion_ref="criterion:bad-ttl",
                evidence_ttl_seconds=59,
            )


class CloudM1ProviderLiveProbeResultTests(unittest.TestCase):
    def test_verified_current_complete_live_result_promotes_through_existing_v2_and_v1_gates(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.E2B)
        plan = build_live_probe_plan(profile)
        live_result = result_for(profile, plan)
        reviewed = live_result.to_evidence_review(plan, profile)
        self.assertTrue(reviewed.eligible_for_acceptance(NOW))
        pack = reviewed.promote_to_v1(NOW)
        assessment = pack.assess()
        self.assertTrue(assessment.accepted_for_cloud_m1)
        self.assertEqual(assessment.missing_controls, ())

    def test_unproven_unsupported_and_stale_live_observations_remain_blockers(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.E2B)
        plan = build_live_probe_plan(profile)
        names = capability_control_names()

        unproven = result_for(
            profile,
            plan,
            observations=observations(
                override_control=names[0],
                override_status=ProviderEvidenceStatus.UNPROVEN,
            ),
        ).to_evidence_review(plan, profile)
        self.assertIn(f"{names[0]}:unproven", unproven.acceptance_blockers(NOW))

        unsupported = result_for(
            profile,
            plan,
            observations=observations(
                override_control=names[1],
                override_status=ProviderEvidenceStatus.NOT_SUPPORTED,
            ),
        ).to_evidence_review(plan, profile)
        self.assertIn(f"{names[1]}:not_supported", unsupported.acceptance_blockers(NOW))

        stale = result_for(
            profile,
            plan,
            observations=observations(stale_control=names[2]),
        ).to_evidence_review(plan, profile)
        self.assertIn(f"{names[2]}:stale_or_future", stale.acceptance_blockers(NOW))

    def test_result_requires_exact_provider_plan_and_profile_correlation(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.MODAL)
        plan = build_live_probe_plan(profile)
        live_result = result_for(profile, plan)

        other_profile = build_candidate_launch_profile(SandboxProviderCandidate.DAYTONA)
        other_plan = build_live_probe_plan(other_profile)
        with self.assertRaises(ContractError):
            live_result.to_evidence_review(other_plan, other_profile)

        wrong_plan = SandboxProviderLiveProbeResult(
            candidate=profile.candidate,
            profile_ref=profile.profile_ref,
            plan_ref="plan:wrong",
            result_ref="result:wrong-plan",
            isolation_primitive=IsolationPrimitive.MICROVM,
            observations=observations(),
        )
        with self.assertRaises(ContractError):
            wrong_plan.to_evidence_review(plan, profile)

        wrong_profile = SandboxProviderLiveProbeResult(
            candidate=profile.candidate,
            profile_ref="profile:wrong",
            plan_ref=plan.plan_ref,
            result_ref="result:wrong-profile",
            isolation_primitive=IsolationPrimitive.MICROVM,
            observations=observations(),
        )
        with self.assertRaises(ContractError):
            wrong_profile.to_evidence_review(plan, profile)

    def test_incomplete_duplicate_result_and_bad_time_fail_closed(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.RUNLOOP)
        plan = build_live_probe_plan(profile)
        full = observations()
        with self.assertRaises(ContractError):
            result_for(profile, plan, observations=full[:-1])
        with self.assertRaises(ContractError):
            result_for(profile, plan, observations=full + (full[0],))
        with self.assertRaises(ContractError):
            ProviderProbeControlObservation(
                control=capability_control_names()[0],
                status=ProviderEvidenceStatus.VERIFIED,
                evidence_ref="evidence:bad-time",
                observed_at=NOW,
                expires_at=NOW,
            )

    def test_safe_result_projection_contains_no_raw_authority_or_provider_payload(self):
        profile = build_candidate_launch_profile(SandboxProviderCandidate.E2B)
        plan = build_live_probe_plan(profile)
        rendered = result_for(profile, plan).safe_dict()
        self.assertFalse(rendered["provider_selected"])
        self.assertFalse(rendered["security_certification"])
        self.assertFalse(rendered["deployment_approval"])
        self.assertFalse(rendered["production_ready_claim"])
        self.assertFalse(rendered["raw_provider_payload"])
        self.assertFalse(rendered["credential_fields"])
        self.assertFalse(rendered["provider_endpoint_fields"])
        self.assertFalse(PROVIDER_LIVE_PROBE_EXECUTION_CONFIGURED)
        self.assertFalse(PROVIDER_ACCOUNT_AUTHORIZATION_CONFIGURED)
        self.assertFalse(PROVIDER_SELECTION_FROM_LAUNCH_PROFILE_SUPPORTED)
        self.assertFalse(PRODUCTION_APPROVAL_FROM_LIVE_PROBE_PLAN_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
