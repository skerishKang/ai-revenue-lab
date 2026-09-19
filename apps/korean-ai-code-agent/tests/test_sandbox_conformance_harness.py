from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.contracts import (
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    SandboxLease,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from kagent.sandbox import (
    DeterministicFakeSandboxProvider,
    SandboxLeaseError,
)
from kagent.sandbox_conformance import (
    IsolationPrimitive,
    SandboxArtifactManifest,
    SandboxArtifactRef,
    SandboxProviderCapabilities,
    SandboxSecurityPolicy,
    VerifiedDiffEvidence,
)
from kagent.sandbox_conformance_harness import (
    ConformanceStatus,
    SandboxProviderConformanceHarness,
    validate_lease_request_against_cloud_m1_policy,
    validate_provider_capabilities_against_cloud_m1_policy,
    validate_verified_diff_evidence,
)


class SandboxConformanceHarnessTests(unittest.TestCase):
    def valid_capabilities(self, **overrides) -> SandboxProviderCapabilities:
        values = dict(
            provider_id="fake_microvm_provider",
            isolation_primitive=IsolationPrimitive.MICROVM,
            server_owned_lifecycle=True,
            exact_revision_materialization=True,
            checkout_hooks_disabled=True,
            network_deny_by_default=True,
            egress_policy_enforced=True,
            privileged_runtime_disabled=True,
            host_mounts_disabled=True,
            runtime_socket_hidden=True,
            provider_metadata_blocked=True,
            host_secret_inheritance_disabled=True,
            dedicated_workspace_per_run=True,
            cross_run_reuse_disabled=True,
            cpu_limit_enforced=True,
            memory_limit_enforced=True,
            disk_limit_enforced=True,
            process_limit_enforced=True,
            ttl_enforced=True,
            cancellation_kills_workload=True,
            teardown_guaranteed=True,
            artifact_allowlist_enforced=True,
            artifact_size_limit_enforced=True,
            terminal_output_bounded=True,
            terminal_output_sanitized=True,
            image_or_snapshot_provenance=True,
            run_lease_audit_correlation=True,
            preview_ports_private_by_default=True,
        )
        values.update(overrides)
        return SandboxProviderCapabilities(**values)

    def test_harness_accepts_fully_conforming_candidate(self):
        harness = SandboxProviderConformanceHarness()
        caps = self.valid_capabilities()
        report = harness.evaluate_capabilities(caps)
        self.assertTrue(report.overall_conforming)
        self.assertEqual(report.failed_controls, ())
        self.assertEqual(report.isolation_primitive, IsolationPrimitive.MICROVM)
        safe = report.safe_dict()
        self.assertFalse(safe["real_provider_selected"])
        self.assertEqual(safe["real_provider_calls"], 0)
        self.assertFalse(safe["production_claim"])

    def test_harness_rejects_missing_network_or_security_controls(self):
        harness = SandboxProviderConformanceHarness()
        caps = self.valid_capabilities(
            network_deny_by_default=False,
            privileged_runtime_disabled=False,
            host_mounts_disabled=False,
            runtime_socket_hidden=False,
            provider_metadata_blocked=False,
            host_secret_inheritance_disabled=False,
            cross_run_reuse_disabled=False,
        )
        report = harness.evaluate_capabilities(caps)
        self.assertFalse(report.overall_conforming)
        self.assertIn("network_deny_by_default", report.failed_controls)
        self.assertIn("privileged_runtime_disabled", report.failed_controls)
        self.assertIn("host_mounts_disabled", report.failed_controls)
        self.assertIn("runtime_socket_hidden", report.failed_controls)
        self.assertIn("provider_metadata_blocked", report.failed_controls)
        self.assertIn("host_secret_inheritance_disabled", report.failed_controls)
        self.assertIn("cross_run_reuse_disabled", report.failed_controls)

        with self.assertRaises(ContractError):
            validate_provider_capabilities_against_cloud_m1_policy(caps)

    def test_harness_rejects_unknown_isolation_primitive(self):
        harness = SandboxProviderConformanceHarness()
        caps = self.valid_capabilities(isolation_primitive=IsolationPrimitive.UNKNOWN)
        report = harness.evaluate_capabilities(caps)
        self.assertFalse(report.overall_conforming)
        self.assertIn("isolation_primitive", report.failed_controls)

    def test_harness_evaluates_lease_lifecycle_and_rejects_resurrection(self):
        harness = SandboxProviderConformanceHarness()
        now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        req = SandboxLeaseRequest(
            run_id="run_lifecycle_test",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/ai-revenue-lab",
            requested_revision="abcdef1234567890abcdef1234567890abcdef12",
            ttl_seconds=900,
            network_policy=NetworkPolicy.OFF,
        )
        # Full lifecycle check passes
        ok = harness.evaluate_lease_lifecycle(provider, req)
        self.assertTrue(ok)

    def test_lease_request_validation_enforces_cloud_and_exact_revision(self):
        # Valid lease request passes
        valid = SandboxLeaseRequest(
            run_id="run_req_1",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/ai-revenue-lab",
            requested_revision="abcdef1234567890abcdef1234567890abcdef12",
            ttl_seconds=1800,
            network_policy=NetworkPolicy.OFF,
        )
        validate_lease_request_against_cloud_m1_policy(valid)

        # Non-cloud execution mode rejected
        with self.assertRaises(ContractError):
            validate_lease_request_against_cloud_m1_policy(
                SandboxLeaseRequest(
                    run_id="run_req_2",
                    execution_mode=ExecutionMode.LOCAL,
                    repository_ref="skerishKang/ai-revenue-lab",
                    requested_revision="abcdef1234567890abcdef1234567890abcdef12",
                    ttl_seconds=1800,
                    network_policy=NetworkPolicy.OFF,
                )
            )

        # Missing exact requested revision rejected
        with self.assertRaises(ContractError):
            validate_lease_request_against_cloud_m1_policy(
                SandboxLeaseRequest(
                    run_id="run_req_3",
                    execution_mode=ExecutionMode.CLOUD,
                    repository_ref="skerishKang/ai-revenue-lab",
                    requested_revision=None,
                    network_policy=NetworkPolicy.OFF,
                )
            )

        # Non-default network policy rejected
        with self.assertRaises(ContractError):
            validate_lease_request_against_cloud_m1_policy(
                SandboxLeaseRequest(
                    run_id="run_req_4",
                    execution_mode=ExecutionMode.CLOUD,
                    repository_ref="skerishKang/ai-revenue-lab",
                    requested_revision="abcdef1234567890abcdef1234567890abcdef12",
                    network_policy=NetworkPolicy.RESTRICTED,
                )
            )

    def test_artifact_manifest_evaluation(self):
        harness = SandboxProviderConformanceHarness()
        valid_manifest = SandboxArtifactManifest(
            run_id="run_art_1",
            lease_id="lease_art_1",
            artifacts=(
                SandboxArtifactRef("art_1", "diff", 1024, "a" * 64),
                SandboxArtifactRef("art_2", "test_report", 2048, "b" * 64),
            ),
            terminal_output_bytes=4096,
            terminal_output_sanitized=True,
        )
        self.assertTrue(harness.evaluate_artifact_manifest(valid_manifest))

        unsanitized_manifest = SandboxArtifactManifest(
            run_id="run_art_2",
            lease_id="lease_art_2",
            artifacts=(),
            terminal_output_bytes=1024,
            terminal_output_sanitized=False,
        )
        self.assertFalse(harness.evaluate_artifact_manifest(unsanitized_manifest))

    def test_validate_verified_diff_evidence(self):
        evidence = VerifiedDiffEvidence(
            run_id="run_vde_1",
            lease_id="lease_vde_1",
            repository_ref="skerishKang/ai-revenue-lab",
            input_revision="abcdef1234567890abcdef1234567890abcdef12",
            changed_files=("apps/kagent/src/app.py",),
            unified_diff_sha256="c" * 64,
            verification_command_id="pytest_allowlisted",
            verification_exit_code=0,
            verification_output_sha256="d" * 64,
            terminal_reason="completed",
        )
        safe = validate_verified_diff_evidence(evidence)
        self.assertEqual(safe["run_id"], "run_vde_1")
        self.assertFalse(safe["raw_diff_in_projection"])
        self.assertFalse(safe["raw_terminal_output_in_projection"])


CANCEL_START = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)


class NoCancelProvider(DeterministicFakeSandboxProvider):
    """Satisfies ``SandboxLeasePort`` and exposes no cancel operation at all."""

    cancel = None  # type: ignore[assignment]


class DeclarationOnlyCancelProvider(DeterministicFakeSandboxProvider):
    """Reports a cancellation it did not perform: the lease stays RESERVED."""

    def cancel(self, lease_id: str, *, run_id: str) -> SandboxLease:
        lease = self.get(lease_id)
        if lease.run_id != run_id:
            raise SandboxLeaseError("lease belongs to a different run")
        return lease


class CrossRunCancelProvider(DeterministicFakeSandboxProvider):
    """Cancels any lease, ignoring which run owns it."""

    def cancel(self, lease_id: str, *, run_id: str) -> SandboxLease:
        return super().cancel(lease_id, run_id=self.get(lease_id).run_id)


class RepeatableCancelProvider(DeterministicFakeSandboxProvider):
    """Answers a second cancel of a terminal lease with another success."""

    def cancel(self, lease_id: str, *, run_id: str) -> SandboxLease:
        lease = self.get(lease_id)
        if lease.state is not SandboxLeaseState.RESERVED:
            return lease
        return super().cancel(lease_id, run_id=run_id)


class CancellationConformanceTests(unittest.TestCase):
    """#1405 / #2790: conformance drives ``cancel``; it does not read a claim."""

    def harness(self) -> SandboxProviderConformanceHarness:
        return SandboxProviderConformanceHarness()

    def request(self, run_id: str = "run_cancel_conformance") -> SandboxLeaseRequest:
        return SandboxLeaseRequest(
            run_id=run_id,
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/ai-revenue-lab",
            requested_revision="abcdef1234567890abcdef1234567890abcdef12",
            ttl_seconds=900,
            network_policy=NetworkPolicy.OFF,
        )

    def fake(self, provider_type=DeterministicFakeSandboxProvider):
        return provider_type(clock=lambda: CANCEL_START)

    def test_deterministic_fake_passes_the_cancellation_exercise(self):
        self.assertTrue(
            self.harness().evaluate_cancellation(self.fake(), self.request())
        )

    def test_missing_cancel_operation_fails_closed(self):
        harness = self.harness()
        provider = self.fake(NoCancelProvider)
        self.assertFalse(harness.evaluate_cancellation(provider, self.request()))
        # The rest of the lifecycle is sound; the absent operation is what fails
        # the run, so a provider cannot conform on the strength of its claim.
        self.assertTrue(harness.evaluate_lease_lifecycle(self.fake(), self.request()))
        self.assertFalse(harness.evaluate_lease_lifecycle(provider, self.request()))

    def test_cancel_that_leaves_the_lease_reserved_fails_closed(self):
        harness = self.harness()
        provider = self.fake(DeclarationOnlyCancelProvider)
        self.assertFalse(harness.evaluate_cancellation(provider, self.request()))
        # …and the lease it "cancelled" is still an active lease for that run.
        lease = provider.allocate(self.request("run_still_live"))
        provider.cancel(lease.lease_id, run_id="run_still_live")
        self.assertIs(provider.get(lease.lease_id).state, SandboxLeaseState.RESERVED)

    def test_cancel_that_ignores_the_owning_run_fails_closed(self):
        self.assertFalse(
            self.harness().evaluate_cancellation(
                self.fake(CrossRunCancelProvider), self.request()
            )
        )

    def test_cancel_that_can_be_repeated_fails_closed(self):
        self.assertFalse(
            self.harness().evaluate_cancellation(
                self.fake(RepeatableCancelProvider), self.request()
            )
        )

    def test_declared_capability_alone_does_not_make_a_provider_conform(self):
        """The declaration path and the operation path must not be confused."""
        harness = self.harness()
        declared = SandboxProviderCapabilities(
            provider_id="declaring_provider",
            isolation_primitive=IsolationPrimitive.MICROVM,
            **{
                name: True
                for name in SandboxProviderCapabilities.__dataclass_fields__
                if name not in {"provider_id", "isolation_primitive"}
            },
        )
        # Every control is claimed true, so the boolean report conforms…
        self.assertTrue(harness.evaluate_capabilities(declared).overall_conforming)
        # …which is exactly why the lifecycle has to call cancel() itself.
        self.assertFalse(
            harness.evaluate_lease_lifecycle(self.fake(NoCancelProvider), self.request())
        )


if __name__ == "__main__":
    unittest.main()
