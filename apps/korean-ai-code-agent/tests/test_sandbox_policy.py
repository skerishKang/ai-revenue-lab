from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.contracts import (
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from kagent.sandbox import DeterministicFakeSandboxProvider, SandboxLeaseError
from kagent.sandbox_policy import (
    IsolationPrimitive,
    PRODUCTION_SANDBOX_CLAIM,
    REAL_SANDBOX_PROVIDER_CALLS,
    REAL_SANDBOX_PROVIDER_SELECTED,
    SandboxArtifactManifest,
    SandboxArtifactPolicy,
    SandboxArtifactRef,
    SandboxFilesystemPolicy,
    SandboxLeaseSecurityPolicy,
    SandboxNetworkPolicy,
    SandboxProviderAcceptanceGate,
    SandboxProviderAssessment,
    SandboxProviderCapabilities,
    SandboxResourceLimits,
    VerifiedDiffEvidenceContract,
)


class SandboxPolicyContractTests(unittest.TestCase):
    def test_network_policy_default_off(self):
        self.assertTrue(SandboxNetworkPolicy.OFF.is_deny_by_default)
        self.assertEqual(SandboxNetworkPolicy.OFF.value, "off")
        policy = SandboxLeaseSecurityPolicy()
        self.assertEqual(policy.network_policy, SandboxNetworkPolicy.OFF)
        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(network_policy=SandboxNetworkPolicy.RESTRICTED)

    def test_filesystem_policy_disallows_host_mounts_and_socket(self):
        fs = SandboxFilesystemPolicy()
        self.assertFalse(fs.host_mounts_allowed)
        self.assertFalse(fs.runtime_socket_exposed)
        self.assertFalse(fs.workspace_reuse_allowed)
        self.assertTrue(fs.checkout_hooks_disabled)

        with self.assertRaises(ContractError):
            SandboxFilesystemPolicy(host_mounts_allowed=True)
        with self.assertRaises(ContractError):
            SandboxFilesystemPolicy(runtime_socket_exposed=True)
        with self.assertRaises(ContractError):
            SandboxFilesystemPolicy(workspace_reuse_allowed=True)
        with self.assertRaises(ContractError):
            SandboxFilesystemPolicy(checkout_hooks_disabled=False)

    def test_security_policy_disallows_privileged_and_secret_inheritance(self):
        policy = SandboxLeaseSecurityPolicy()
        self.assertFalse(policy.privileged_runtime_allowed)
        self.assertFalse(policy.host_secret_inheritance_allowed)
        self.assertFalse(policy.provider_metadata_access_allowed)

        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(privileged_runtime_allowed=True)
        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(host_secret_inheritance_allowed=True)
        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(provider_metadata_access_allowed=True)

    def test_resource_limits_bounds(self):
        limits = SandboxResourceLimits()
        self.assertEqual(limits.max_cpu_cores, 4)
        self.assertEqual(limits.max_ttl_seconds, 3600)
        with self.assertRaises(ContractError):
            SandboxResourceLimits(max_ttl_seconds=5000)
        with self.assertRaises(ContractError):
            SandboxResourceLimits(max_cpu_cores=0)

    def test_artifact_policy_bounds_and_sanitization(self):
        art_policy = SandboxArtifactPolicy()
        self.assertTrue(art_policy.terminal_output_sanitized)
        with self.assertRaises(ContractError):
            SandboxArtifactPolicy(terminal_output_sanitized=False)
        with self.assertRaises(ContractError):
            SandboxArtifactPolicy(max_artifact_bytes=200 * 1024 * 1024)

    def test_acceptance_gate_validates_lease_request(self):
        gate = SandboxProviderAcceptanceGate()
        valid_req = SandboxLeaseRequest(
            run_id="run_101",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
            requested_revision="1234567890abcdef",
            ttl_seconds=1200,
            network_policy=NetworkPolicy.OFF,
        )
        gate.validate_lease_request(valid_req)

        # Missing exact requested revision
        with self.assertRaises(ContractError):
            gate.validate_lease_request(
                SandboxLeaseRequest(
                    run_id="run_102",
                    execution_mode=ExecutionMode.CLOUD,
                    repository_ref="skerishKang/example",
                    requested_revision=None,
                    network_policy=NetworkPolicy.OFF,
                )
            )

        # Non-default network policy
        with self.assertRaises(ContractError):
            gate.validate_lease_request(
                SandboxLeaseRequest(
                    run_id="run_103",
                    execution_mode=ExecutionMode.CLOUD,
                    repository_ref="skerishKang/example",
                    requested_revision="1234567890abcdef",
                    network_policy=NetworkPolicy.RESTRICTED,
                )
            )

    def test_verified_diff_evidence_contract(self):
        evidence = VerifiedDiffEvidenceContract(
            run_id="run_101",
            lease_id="lease_101",
            repository_ref="skerishKang/ai-revenue-lab",
            input_revision="1234567890abcdef1234567890abcdef12345678",
            changed_files=("apps/kagent/src/app.py", "tests/test_app.py"),
            unified_diff_sha256="a" * 64,
            verification_command_id="pytest_allowlisted",
            verification_exit_code=0,
            verification_output_sha256="b" * 64,
            terminal_reason="completed",
            final_revision_ref="final_sha_123",
        )
        safe = evidence.safe_dict()
        self.assertEqual(safe["run_id"], "run_101")
        self.assertFalse(safe["raw_diff_in_projection"])
        self.assertFalse(safe["raw_terminal_output_in_projection"])

    def test_one_active_lease_and_no_resurrection(self):
        now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        req = SandboxLeaseRequest(
            run_id="run_lifecycle",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="repo/test",
            requested_revision="abcdef123",
            ttl_seconds=600,
        )
        lease = provider.allocate(req)
        self.assertEqual(lease.state, SandboxLeaseState.RESERVED)

        # Cannot allocate second lease for same active run
        with self.assertRaises(SandboxLeaseError):
            provider.allocate(req)

        # Release lease
        released = provider.release(lease.lease_id, run_id="run_lifecycle")
        self.assertEqual(released.state, SandboxLeaseState.RELEASED)

        # Cannot resurrect or re-release released lease
        with self.assertRaises(SandboxLeaseError):
            provider.release(lease.lease_id, run_id="run_lifecycle")

    def test_zero_real_provider_mutation_in_act_a(self):
        self.assertFalse(REAL_SANDBOX_PROVIDER_SELECTED)
        self.assertEqual(REAL_SANDBOX_PROVIDER_CALLS, 0)
        self.assertFalse(PRODUCTION_SANDBOX_CLAIM)


if __name__ == "__main__":
    unittest.main()
