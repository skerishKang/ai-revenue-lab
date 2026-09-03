from __future__ import annotations

import unittest

from kagent.contracts import ContractError
from kagent.execution_target_router import (
    B14_ROUTER_DUPLICATED,
    CLIENT_PREFERENCE_IS_AUTHORITY,
    P01_ORCHESTRATION_DUPLICATED,
    PRODUCTION_MUTATION,
    REAL_EXECUTION_PERFORMED_BY_ROUTER,
    RESULT_APPLY_IS_SEPARATE_WRITE,
    WHOLE_DISK_SYNC_SUPPORTED,
    ExecutionPreference,
    ExecutionTarget,
    ExecutionTargetRequest,
    HybridInputManifest,
    SourceLocation,
    resolve_execution_target,
)


def manifest(**kwargs):
    values = dict(
        manifest_id="manifest_1",
        root_ref="root_1",
        paths=("src/app.py", "tests/test_app.py"),
    )
    values.update(kwargs)
    return HybridInputManifest(**values)


def request(**kwargs):
    values = dict(
        run_id="run_1",
        source_ref="source_1",
        source_location=SourceLocation.CLOUD,
        preference=ExecutionPreference.AUTO,
        local_device_online=False,
        local_capability_granted=False,
        cloud_sandbox_available=True,
        cloud_sandbox_conformant=True,
        transfer_allowed=False,
        requires_local_only_tool=False,
        isolation_required=False,
        hybrid_manifest=None,
    )
    values.update(kwargs)
    return ExecutionTargetRequest(**values)


class ExecutionTargetRouterTests(unittest.TestCase):
    def test_cloud_source_uses_conformant_cloud_sandbox(self):
        decision = resolve_execution_target(request())
        self.assertEqual(decision.target, ExecutionTarget.CLOUD_SANDBOX)
        self.assertEqual(decision.reason_code, "cloud_source_cloud_ready")
        self.assertIsNone(decision.hybrid_manifest_ref)

    def test_local_source_uses_authorized_online_local_agent(self):
        decision = resolve_execution_target(
            request(
                source_location=SourceLocation.LOCAL,
                local_device_online=True,
                local_capability_granted=True,
                cloud_sandbox_available=False,
                cloud_sandbox_conformant=False,
            )
        )
        self.assertEqual(decision.target, ExecutionTarget.LOCAL_AGENT)
        self.assertEqual(decision.reason_code, "local_source_local_ready")

    def test_local_only_tool_never_silently_falls_back_to_cloud(self):
        decision = resolve_execution_target(
            request(
                source_location=SourceLocation.LOCAL,
                requires_local_only_tool=True,
                local_device_online=False,
                local_capability_granted=True,
                cloud_sandbox_available=True,
                cloud_sandbox_conformant=True,
                transfer_allowed=True,
                hybrid_manifest=manifest(),
            )
        )
        self.assertEqual(decision.target, ExecutionTarget.NO_SAFE_TARGET)
        self.assertEqual(decision.reason_code, "local_only_tool_unavailable")

    def test_local_isolation_requires_explicit_bounded_hybrid_manifest(self):
        no_manifest = resolve_execution_target(
            request(
                source_location=SourceLocation.LOCAL,
                isolation_required=True,
                transfer_allowed=True,
            )
        )
        self.assertEqual(no_manifest.target, ExecutionTarget.NO_SAFE_TARGET)
        self.assertEqual(no_manifest.reason_code, "hybrid_manifest_required")

        decision = resolve_execution_target(
            request(
                source_location=SourceLocation.LOCAL,
                isolation_required=True,
                transfer_allowed=True,
                hybrid_manifest=manifest(),
            )
        )
        self.assertEqual(decision.target, ExecutionTarget.HYBRID)
        self.assertEqual(decision.hybrid_manifest_ref, "manifest_1")
        self.assertEqual(decision.reason_code, "local_source_isolated_in_cloud")

    def test_transfer_forbidden_blocks_hybrid_even_if_cloud_is_ready(self):
        decision = resolve_execution_target(
            request(
                source_location=SourceLocation.LOCAL,
                isolation_required=True,
                transfer_allowed=False,
                hybrid_manifest=manifest(),
            )
        )
        self.assertEqual(decision.target, ExecutionTarget.NO_SAFE_TARGET)
        self.assertEqual(decision.reason_code, "local_transfer_forbidden")

    def test_local_offline_can_use_bounded_hybrid_only_when_transfer_is_allowed(self):
        decision = resolve_execution_target(
            request(
                source_location=SourceLocation.LOCAL,
                local_device_online=False,
                local_capability_granted=True,
                transfer_allowed=True,
                hybrid_manifest=manifest(),
            )
        )
        self.assertEqual(decision.target, ExecutionTarget.HYBRID)
        self.assertEqual(decision.reason_code, "local_offline_bounded_cloud_transfer")

    def test_cloud_preference_cannot_widen_local_source_transfer_authority(self):
        decision = resolve_execution_target(
            request(
                source_location=SourceLocation.LOCAL,
                preference=ExecutionPreference.CLOUD,
                local_device_online=True,
                local_capability_granted=True,
                transfer_allowed=False,
            )
        )
        self.assertEqual(decision.target, ExecutionTarget.LOCAL_AGENT)
        self.assertEqual(decision.reason_code, "cloud_preference_not_authority")

    def test_local_preference_cannot_widen_cloud_source_transfer_authority(self):
        decision = resolve_execution_target(
            request(
                source_location=SourceLocation.CLOUD,
                preference=ExecutionPreference.LOCAL,
                local_device_online=True,
                local_capability_granted=True,
                transfer_allowed=False,
            )
        )
        self.assertEqual(decision.target, ExecutionTarget.CLOUD_SANDBOX)
        self.assertEqual(decision.reason_code, "cloud_source_transfer_forbidden")

    def test_mixed_source_requires_both_local_authority_and_conformant_cloud(self):
        missing_local = resolve_execution_target(
            request(
                source_location=SourceLocation.MIXED,
                transfer_allowed=True,
                hybrid_manifest=manifest(),
                local_device_online=False,
                local_capability_granted=True,
            )
        )
        self.assertEqual(missing_local.target, ExecutionTarget.NO_SAFE_TARGET)
        self.assertEqual(missing_local.reason_code, "mixed_source_local_unavailable")

        decision = resolve_execution_target(
            request(
                source_location=SourceLocation.MIXED,
                transfer_allowed=True,
                hybrid_manifest=manifest(),
                local_device_online=True,
                local_capability_granted=True,
            )
        )
        self.assertEqual(decision.target, ExecutionTarget.HYBRID)
        self.assertEqual(decision.reason_code, "mixed_source_bounded_hybrid")

    def test_manifest_rejects_traversal_credentials_private_keys_and_windows_absolute_paths(self):
        invalid_paths = (
            "../secret.txt",
            ".env",
            "src/.ssh/config",
            "keys/private.pem",
            "C:/Users/alice/project/file.txt",
            r"D:\workspace\repo\file.txt",
        )
        for path in invalid_paths:
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    manifest(paths=(path,))

    def test_manifest_is_explicit_bounded_and_result_apply_is_separate(self):
        item = manifest()
        rendered = item.safe_dict()
        self.assertFalse(rendered["whole_disk_sync"])
        self.assertFalse(rendered["credential_paths_allowed"])
        self.assertFalse(rendered["apply_results_back_automatically"])

        with self.assertRaises(ContractError):
            manifest(paths=tuple(f"src/file_{index}.txt" for index in range(257)))
        with self.assertRaises(ContractError):
            manifest(paths=("src/App.py", "src/app.py"))

    def test_decision_public_evidence_preserves_execution_location_without_claiming_other_authority(self):
        decision = resolve_execution_target(request())
        rendered = decision.safe_dict()
        self.assertEqual(rendered["target"], "cloud_sandbox")
        self.assertEqual(rendered["reason_code"], "cloud_source_cloud_ready")
        self.assertFalse(rendered["model_provider_route"])
        self.assertFalse(rendered["p01_execution_authority"])
        self.assertTrue(rendered["result_apply_is_separate_write"])

    def test_router_boundary_non_claims_are_explicit(self):
        self.assertFalse(B14_ROUTER_DUPLICATED)
        self.assertFalse(P01_ORCHESTRATION_DUPLICATED)
        self.assertFalse(CLIENT_PREFERENCE_IS_AUTHORITY)
        self.assertFalse(WHOLE_DISK_SYNC_SUPPORTED)
        self.assertTrue(RESULT_APPLY_IS_SEPARATE_WRITE)
        self.assertFalse(REAL_EXECUTION_PERFORMED_BY_ROUTER)
        self.assertFalse(PRODUCTION_MUTATION)


if __name__ == "__main__":
    unittest.main()
