from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.contracts import (
    ClawTaskIntent,
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    SandboxLeaseRequest,
    exact_commit_revision,
)
from kagent.repository_materialization import _sha as materialization_sha
from kagent.sandbox_conformance import (
    PRODUCTION_SANDBOX_CLAIM,
    REAL_SANDBOX_PROVIDER_CALLS,
    REAL_SANDBOX_PROVIDER_SELECTED,
    IsolationPrimitive,
    SandboxArtifactManifest,
    SandboxArtifactRef,
    SandboxProviderCapabilities,
    SandboxProviderConformanceGate,
    SandboxSecurityPolicy,
    VerifiedDiffEvidence,
)


class SandboxConformanceTests(unittest.TestCase):
    def capabilities(self, **overrides):
        values = dict(
            provider_id="candidate_1",
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

    def test_fully_declared_candidate_passes_provider_neutral_gate(self):
        assessment = SandboxProviderConformanceGate().require_accepted(self.capabilities())
        self.assertTrue(assessment.accepted_for_cloud_m1)
        self.assertEqual(assessment.missing_controls, ())
        self.assertEqual(assessment.policy_version, "claw-cloud-m1-sandbox.v1")

    def test_each_false_security_control_is_visible_and_rejects_candidate(self):
        capabilities = self.capabilities(
            runtime_socket_hidden=False,
            provider_metadata_blocked=False,
            cancellation_kills_workload=False,
        )
        assessment = SandboxProviderConformanceGate().assess(capabilities)
        self.assertFalse(assessment.accepted_for_cloud_m1)
        self.assertEqual(
            assessment.missing_controls,
            (
                "runtime_socket_hidden",
                "provider_metadata_blocked",
                "cancellation_kills_workload",
            ),
        )
        with self.assertRaisesRegex(ContractError, "runtime_socket_hidden"):
            SandboxProviderConformanceGate().require_accepted(capabilities)

    def test_unknown_isolation_primitive_fails_even_if_booleans_claim_true(self):
        assessment = SandboxProviderConformanceGate().assess(
            self.capabilities(isolation_primitive=IsolationPrimitive.UNKNOWN)
        )
        self.assertFalse(assessment.accepted_for_cloud_m1)
        self.assertIn("known_isolation_primitive", assessment.missing_controls)

    def test_policy_itself_cannot_be_relaxed_by_client_configuration(self):
        with self.assertRaises(ContractError):
            SandboxSecurityPolicy(privileged_runtime_allowed=True)
        with self.assertRaises(ContractError):
            SandboxSecurityPolicy(host_mounts_allowed=True)
        with self.assertRaises(ContractError):
            SandboxSecurityPolicy(runtime_socket_exposed=True)
        with self.assertRaises(ContractError):
            SandboxSecurityPolicy(host_secret_inheritance_allowed=True)
        with self.assertRaises(ContractError):
            SandboxSecurityPolicy(workspace_reuse_allowed=True)
        with self.assertRaises(ContractError):
            SandboxSecurityPolicy(network_default=NetworkPolicy.RESTRICTED)

    def test_cloud_m1_lease_requires_network_off_exact_revision_and_bounded_ttl(self):
        gate = SandboxProviderConformanceGate()
        good = SandboxLeaseRequest(
            run_id="run_1",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
            requested_revision="abcdef1234567890abcdef1234567890abcdef12",
            ttl_seconds=900,
            network_policy=NetworkPolicy.OFF,
        )
        gate.validate_lease_request(good)
        # A missing revision is now refused at the lease contract itself, so a
        # Cloud M1 request that cannot be built also cannot reach a provider.
        with self.assertRaisesRegex(ContractError, "exact 40-hex commit SHA"):
            SandboxLeaseRequest(
                run_id="run_2",
                execution_mode=ExecutionMode.CLOUD,
                repository_ref="skerishKang/example",
                requested_revision=None,
                network_policy=NetworkPolicy.OFF,
            )
        # The gate keeps its own independent check (#2775): prove it still
        # rejects a non-exact revision on a request the contract layer allows,
        # so the two layers cannot silently drift if either is edited later.
        with self.assertRaisesRegex(ContractError, "exact immutable"):
            gate.validate_lease_request(
                SandboxLeaseRequest(
                    run_id="run_2b",
                    execution_mode=ExecutionMode.LOCAL,
                    repository_ref="skerishKang/example",
                    requested_revision=None,
                    network_policy=NetworkPolicy.OFF,
                )
            )
        with self.assertRaisesRegex(ContractError, "network"):
            gate.validate_lease_request(
                SandboxLeaseRequest(
                    run_id="run_3",
                    execution_mode=ExecutionMode.CLOUD,
                    repository_ref="skerishKang/example",
                    requested_revision="abcdef1234567890abcdef1234567890abcdef12",
                    network_policy=NetworkPolicy.RESTRICTED,
                )
            )

    def test_artifact_manifest_enforces_count_size_output_and_sanitization(self):
        policy = SandboxSecurityPolicy(
            max_artifact_bytes=1024,
            max_artifact_count=2,
            max_terminal_output_bytes=1024,
        )
        manifest = SandboxArtifactManifest(
            run_id="run_1",
            lease_id="lease_1",
            artifacts=(
                SandboxArtifactRef("artifact_1", "diff", 512, "a" * 64),
                SandboxArtifactRef("artifact_2", "test", 1024, "b" * 64),
            ),
            terminal_output_bytes=1024,
            terminal_output_sanitized=True,
        )
        manifest.validate_against(policy)
        self.assertEqual(manifest.total_artifact_bytes, 1536)

        with self.assertRaisesRegex(ContractError, "artifact size"):
            SandboxArtifactManifest(
                run_id="run_1",
                lease_id="lease_1",
                artifacts=(SandboxArtifactRef("artifact_big", "diff", 1025, "c" * 64),),
                terminal_output_bytes=100,
                terminal_output_sanitized=True,
            ).validate_against(policy)
        with self.assertRaisesRegex(ContractError, "sanitized"):
            SandboxArtifactManifest(
                run_id="run_1",
                lease_id="lease_1",
                artifacts=(),
                terminal_output_bytes=100,
                terminal_output_sanitized=False,
            ).validate_against(policy)

    def test_verified_diff_is_hash_and_correlation_evidence_not_raw_output(self):
        evidence = VerifiedDiffEvidence(
            run_id="run_1",
            lease_id="lease_1",
            repository_ref="skerishKang/example",
            input_revision="0123456789abcdef",
            changed_files=("src/app.py", "tests/test_app.py"),
            unified_diff_sha256="a" * 64,
            verification_command_id="pytest_allowlisted",
            verification_exit_code=0,
            verification_output_sha256="b" * 64,
            terminal_reason="completed",
            final_revision_ref="workspace_final_1",
        )
        rendered = evidence.safe_dict()
        self.assertEqual(rendered["input_revision"], "0123456789abcdef")
        self.assertEqual(rendered["changed_files"], ["src/app.py", "tests/test_app.py"])
        self.assertFalse(rendered["raw_diff_in_projection"])
        self.assertFalse(rendered["raw_terminal_output_in_projection"])
        self.assertNotIn("provider", rendered)
        with self.assertRaises(ContractError):
            VerifiedDiffEvidence(
                run_id="run_1",
                lease_id="lease_1",
                repository_ref="skerishKang/example",
                input_revision="0123456789abcdef",
                changed_files=("src/app.py", "src/app.py"),
                unified_diff_sha256="a" * 64,
                verification_command_id="pytest_allowlisted",
                verification_exit_code=0,
                verification_output_sha256="b" * 64,
                terminal_reason="completed",
            )

    def test_provider_manifest_contains_no_endpoint_or_credential_authority(self):
        fields = set(self.capabilities().__dataclass_fields__)
        self.assertNotIn("endpoint", fields)
        self.assertNotIn("credential", fields)
        self.assertNotIn("account_id", fields)
        rendered = str(self.capabilities().safe_dict())
        self.assertNotIn("https://", rendered)

    def test_no_real_provider_selection_call_or_production_claim(self):
        self.assertFalse(REAL_SANDBOX_PROVIDER_SELECTED)
        self.assertEqual(REAL_SANDBOX_PROVIDER_CALLS, 0)
        self.assertFalse(PRODUCTION_SANDBOX_CLAIM)


class ExactRevisionBoundaryTests(unittest.TestCase):
    """#2775: the lease boundary must actually mean "exact immutable revision"."""

    SHA = "abcdef1234567890abcdef1234567890abcdef12"

    REJECTED = (
        "main",
        "refs/heads/main",
        "v1.2.3",
        "abcdef1",            # abbreviated hash: still resolvable to many commits
        "",
        "   ",
        None,
        12345,
        SHA + "0",            # 41 chars
        SHA[:39],             # 39 chars
        "ghobcdef1234567890abcdef1234567890abcdef1",  # non-hex inside length
    )

    def _request(self, revision, mode=ExecutionMode.CLOUD):
        return SandboxLeaseRequest(
            run_id="run_rev",
            execution_mode=mode,
            repository_ref="skerishKang/example",
            requested_revision=revision,
            network_policy=NetworkPolicy.OFF,
        )

    def test_mutable_and_malformed_revisions_are_rejected_everywhere(self):
        gate = SandboxProviderConformanceGate()
        for value in self.REJECTED:
            with self.subTest(revision=value):
                with self.assertRaises(ContractError):
                    exact_commit_revision(value, "requested_revision")
                # Cloud M1 lease request cannot even be constructed.
                with self.assertRaises(ContractError):
                    self._request(value)
                # The gate rejects it independently of the contract layer.
                with self.assertRaises(ContractError):
                    gate.validate_lease_request(self._request(value, ExecutionMode.LOCAL))

    def test_exact_sha_is_accepted_and_normalized_deterministically(self):
        self.assertEqual(exact_commit_revision(self.SHA), self.SHA)
        upper = self.SHA.upper()
        self.assertEqual(exact_commit_revision(upper), self.SHA)
        self.assertEqual(exact_commit_revision(f"  {upper} "), self.SHA)
        # idempotent: normalizing an accepted value again cannot change it
        once = exact_commit_revision(upper)
        self.assertEqual(exact_commit_revision(once), once)
        request = self._request(upper)
        self.assertEqual(request.requested_revision, self.SHA)

    def test_lease_boundary_and_materialization_cannot_drift_apart(self):
        # Both layers must accept/reject the identical corpus: a revision the
        # lease calls exact while acquisition calls unusable (or the reverse) is
        # the drift this issue exists to prevent.
        for value in self.REJECTED + (self.SHA, self.SHA.upper()):
            with self.subTest(revision=value):
                contract_ok = True
                try:
                    expected = exact_commit_revision(value, "requested_revision")
                except ContractError:
                    contract_ok = False
                    expected = None
                mat_ok = True
                try:
                    produced = materialization_sha(value, "commit_sha")
                except ContractError:
                    mat_ok = False
                    produced = None
                self.assertIs(contract_ok, mat_ok)
                self.assertEqual(expected, produced)

    def test_no_second_revision_regex_was_introduced(self):
        import inspect

        from kagent import contracts, repository_materialization, sandbox_conformance

        for module in (repository_materialization, sandbox_conformance):
            source = inspect.getsource(module)
            self.assertNotIn("{40}$", source, module.__name__)
        self.assertIn("{40}$", inspect.getsource(contracts))

    def test_local_intent_may_stay_unpinned_but_a_cloud_lease_may_not(self):
        # Scope guard: this child tightens the lease boundary only. Product
        # intent may still name a branch for later resolution by acquisition.
        intent = ClawTaskIntent(
            task_id="task_rev",
            task="메인 브랜치에서 확인해줘",
            repository_ref="skerishKang/example",
            execution_mode=ExecutionMode.LOCAL,
            requested_revision="main",
        )
        self.assertEqual(intent.requested_revision, "main")
        with self.assertRaises(ContractError):
            self._request("main")


if __name__ == "__main__":
    unittest.main()
