from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from kagent.cloudflare_connector import (
    BILLING_MUTATION_SUPPORTED,
    DNS_DEFAULT_WRITE_SUPPORTED,
    GLOBAL_API_KEY_SUPPORTED,
    MEMBERSHIP_MUTATION_SUPPORTED,
    PRODUCTION_MUTATION_CONFIGURED,
    RAW_CLOUDFLARE_TOKEN_IN_B54,
    REAL_CLOUDFLARE_ADAPTER_CONFIGURED,
    SECRET_READBACK_SUPPORTED,
    CloudflareBuildTriggerProjection,
    CloudflareCredentialProjection,
    CloudflareCredentialSubject,
    CloudflareEnvironment,
    CloudflareMutationAction,
    CloudflareMutationReceipt,
    CloudflarePagesDeployment,
    CloudflarePagesReleaseState,
    CloudflareProductionMutationPlan,
    CloudflareResourceBinding,
    CloudflareResourceKind,
    CloudflareWorkerDeployment,
    CloudflareWorkerReleaseState,
    CloudflareWorkerVersion,
    PagesDeploymentEnvironment,
    WorkerTrafficVersion,
)
from kagent.connector_trust import ConnectorWriteIntent
from kagent.contracts import ContractError

NOW = datetime(2026, 9, 3, 7, 30, tzinfo=timezone.utc)
DIGEST = hashlib.sha256(b"artifact").hexdigest()
BINDINGS = hashlib.sha256(b"bindings").hexdigest()
COMMAND = hashlib.sha256(b"command").hexdigest()


class CloudflareCredentialAndBindingTests(unittest.TestCase):
    def test_credential_projection_is_secret_free_and_resource_scoped(self):
        credential = CloudflareCredentialProjection(
            credential_ref="credential_1",
            subject=CloudflareCredentialSubject.ACCOUNT,
            permission_refs=("workers_scripts.read", "pages.read"),
            account_refs=("account_1",),
            zone_refs=("zone_1",),
        )
        rendered = credential.safe_dict()
        self.assertFalse(rendered["raw_token"])
        self.assertFalse(rendered["global_api_key"])
        self.assertFalse(rendered["broad_all_accounts"])
        with self.assertRaises(ContractError):
            CloudflareCredentialProjection(
                credential_ref="credential_2",
                subject=CloudflareCredentialSubject.ACCOUNT,
                permission_refs=("workers_scripts.read",),
                account_refs=("account_1",),
                broad_all_accounts=True,
            )

    def test_workers_builds_configuration_permission_requires_user_subject(self):
        with self.assertRaises(ContractError):
            CloudflareCredentialProjection(
                credential_ref="credential_1",
                subject=CloudflareCredentialSubject.ACCOUNT,
                permission_refs=("workers_builds_configuration.edit",),
                account_refs=("account_1",),
            )
        CloudflareCredentialProjection(
            credential_ref="credential_1",
            subject=CloudflareCredentialSubject.USER,
            permission_refs=("workers_builds_configuration.edit",),
            account_refs=("account_1",),
        )

    def test_binding_requires_exact_non_wildcard_resources(self):
        binding = CloudflareResourceBinding(
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            account_ref="account_1",
            worker_refs=("worker_1",),
            pages_project_refs=("pages_1",),
            zone_refs=("zone_1",),
        )
        binding.require_resource(CloudflareResourceKind.WORKER, "worker_1")
        with self.assertRaises(ContractError):
            binding.require_resource(CloudflareResourceKind.WORKER, "worker_2")
        with self.assertRaises(ContractError):
            CloudflareResourceBinding(
                binding_ref="binding_2",
                workspace_ref="workspace_1",
                account_ref="account_1",
                worker_refs=("*",),
            )


class CloudflareReleaseStateTests(unittest.TestCase):
    def worker_version(self, version_ref: str) -> CloudflareWorkerVersion:
        return CloudflareWorkerVersion(
            worker_ref="worker_1",
            version_ref=version_ref,
            created_at=NOW,
            source_revision_ref="git_abc123",
            compatibility_date="2026-09-01",
            bindings_fingerprint=BINDINGS,
        )

    def test_workers_versions_and_deployments_are_distinct_and_traffic_totals_100(self):
        current = CloudflareWorkerDeployment(
            worker_ref="worker_1",
            deployment_ref="deployment_2",
            created_at=NOW,
            traffic=(WorkerTrafficVersion("version_2", 100),),
            active=True,
        )
        state = CloudflareWorkerReleaseState(
            worker_ref="worker_1",
            current_deployment=current,
            versions=(self.worker_version("version_1"), self.worker_version("version_2")),
            rollback_target_version_ref="version_1",
        )
        self.assertEqual(state.current_deployment.deployment_ref, "deployment_2")
        self.assertEqual(state.rollback_target_version_ref, "version_1")
        with self.assertRaises(ContractError):
            CloudflareWorkerDeployment(
                worker_ref="worker_1",
                deployment_ref="bad",
                created_at=NOW,
                traffic=(WorkerTrafficVersion("version_1", 60), WorkerTrafficVersion("version_2", 30)),
                active=True,
            )

    def test_pages_preview_is_never_a_rollback_target(self):
        current = CloudflarePagesDeployment(
            project_ref="pages_1",
            deployment_ref="prod_2",
            environment=PagesDeploymentEnvironment.PRODUCTION,
            successful=True,
            production_active=True,
            created_at=NOW,
        )
        old_prod = CloudflarePagesDeployment(
            project_ref="pages_1",
            deployment_ref="prod_1",
            environment=PagesDeploymentEnvironment.PRODUCTION,
            successful=True,
            production_active=False,
            created_at=NOW,
        )
        preview = CloudflarePagesDeployment(
            project_ref="pages_1",
            deployment_ref="preview_1",
            environment=PagesDeploymentEnvironment.PREVIEW,
            successful=True,
            production_active=False,
            created_at=NOW,
        )
        CloudflarePagesReleaseState(
            project_ref="pages_1",
            current_production=current,
            recent_deployments=(old_prod, preview),
            rollback_target_deployment_ref="prod_1",
        )
        with self.assertRaises(ContractError):
            CloudflarePagesReleaseState(
                project_ref="pages_1",
                current_production=current,
                recent_deployments=(old_prod, preview),
                rollback_target_deployment_ref="preview_1",
            )


class CloudflareBuildProjectionTests(unittest.TestCase):
    def test_build_projection_exposes_root_watch_paths_and_env_names_not_values(self):
        trigger = CloudflareBuildTriggerProjection(
            worker_ref="worker_1",
            trigger_ref="trigger_prod",
            environment=CloudflareEnvironment.PRODUCTION,
            root_directory="apps/korean-ai-platform",
            branch_includes=("main",),
            branch_excludes=(),
            path_includes=("apps/korean-ai-platform/*",),
            path_excludes=("docs/*",),
            build_command_fingerprint=COMMAND,
            deploy_command_fingerprint=COMMAND,
            environment_variable_names=("NODE_VERSION", "PUBLIC_ORIGIN"),
        )
        rendered = trigger.safe_dict()
        self.assertEqual(rendered["root_directory"], "apps/korean-ai-platform")
        self.assertEqual(rendered["path_includes"], ["apps/korean-ai-platform/*"])
        self.assertFalse(rendered["environment_variable_values_present"])
        self.assertFalse(rendered["build_token_present"])
        with self.assertRaises(ContractError):
            CloudflareBuildTriggerProjection(
                worker_ref="worker_1",
                trigger_ref="trigger_bad",
                environment=CloudflareEnvironment.PRODUCTION,
                root_directory="../outside",
                branch_includes=("main",),
                branch_excludes=(),
                path_includes=("*",),
                path_excludes=(),
                build_command_fingerprint=COMMAND,
                deploy_command_fingerprint=COMMAND,
                environment_variable_names=(),
            )


class CloudflareProductionGateTests(unittest.TestCase):
    def binding(self) -> CloudflareResourceBinding:
        return CloudflareResourceBinding(
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            account_ref="account_1",
            worker_refs=("worker_1",),
            pages_project_refs=("pages_1",),
        )

    def intent(self, *, tool_name: str, target_ref: str, expected: str) -> ConnectorWriteIntent:
        return ConnectorWriteIntent(
            connector_id="cloudflare",
            binding_ref="binding_1",
            actor_ref="actor_1",
            tool_name=tool_name,
            target_ref=target_ref,
            payload_fingerprint=DIGEST,
            idempotency_key="idem_1",
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            requested_at=NOW,
            expected_version_ref=expected,
        )

    def test_production_plan_binds_current_target_recovery_and_exact_resource(self):
        plan = CloudflareProductionMutationPlan(
            intent=self.intent(tool_name="production_deploy", target_ref="worker_1", expected="deployment_1"),
            action=CloudflareMutationAction.PRODUCTION_DEPLOY,
            account_ref="account_1",
            resource_kind=CloudflareResourceKind.WORKER,
            resource_ref="worker_1",
            expected_current_release_ref="deployment_1",
            target_release_ref="version_2",
            source_revision_ref="git_abc123",
            artifact_fingerprint=DIGEST,
            bounded_diff_ref="diff_1",
            recovery_target_ref="version_1",
            smoke_plan_ref="smoke_1",
            rollback_compatibility_checked=True,
        )
        plan.validate_binding(self.binding())
        rendered = plan.safe_dict()
        self.assertTrue(rendered["explicit_p01_approval"])
        self.assertTrue(rendered["post_action_readback_required"])
        self.assertTrue(rendered["post_action_smoke_required"])

    def test_production_plan_rejects_stale_expected_state_and_dns_generic_action(self):
        with self.assertRaises(ContractError):
            CloudflareProductionMutationPlan(
                intent=self.intent(tool_name="production_deploy", target_ref="worker_1", expected="deployment_old"),
                action=CloudflareMutationAction.PRODUCTION_DEPLOY,
                account_ref="account_1",
                resource_kind=CloudflareResourceKind.WORKER,
                resource_ref="worker_1",
                expected_current_release_ref="deployment_1",
                target_release_ref="version_2",
                source_revision_ref="git_abc123",
                artifact_fingerprint=DIGEST,
                bounded_diff_ref="diff_1",
                recovery_target_ref="version_1",
                smoke_plan_ref="smoke_1",
                rollback_compatibility_checked=True,
            )
        with self.assertRaises(ContractError):
            CloudflareProductionMutationPlan(
                intent=self.intent(tool_name="dns_update", target_ref="zone_1", expected="dns_state_1"),
                action=CloudflareMutationAction.DNS_UPDATE,
                account_ref="account_1",
                resource_kind=CloudflareResourceKind.ZONE,
                resource_ref="zone_1",
                expected_current_release_ref="dns_state_1",
                target_release_ref="dns_state_2",
                source_revision_ref="git_abc123",
                artifact_fingerprint=DIGEST,
                bounded_diff_ref="diff_1",
                recovery_target_ref="dns_state_1",
                smoke_plan_ref="smoke_1",
                rollback_compatibility_checked=True,
            )

    def test_receipt_requires_exact_readback_and_passing_smoke(self):
        receipt = CloudflareMutationReceipt(
            action=CloudflareMutationAction.PRODUCTION_DEPLOY,
            resource_ref="worker_1",
            before_release_ref="deployment_1",
            after_release_ref="version_2",
            expected_target_release_ref="version_2",
            recovery_target_ref="version_1",
            provider_request_ref="request_1",
            readback_evidence_ref="readback_1",
            smoke_evidence_ref="smoke_evidence_1",
            smoke_passed=True,
            completed_at=NOW,
        )
        self.assertTrue(receipt.safe_dict()["smoke_passed"])
        with self.assertRaises(ContractError):
            CloudflareMutationReceipt(
                action=CloudflareMutationAction.PRODUCTION_DEPLOY,
                resource_ref="worker_1",
                before_release_ref="deployment_1",
                after_release_ref="version_wrong",
                expected_target_release_ref="version_2",
                recovery_target_ref="version_1",
                provider_request_ref="request_1",
                readback_evidence_ref="readback_1",
                smoke_evidence_ref="smoke_evidence_1",
                smoke_passed=True,
                completed_at=NOW,
            )
        with self.assertRaises(ContractError):
            CloudflareMutationReceipt(
                action=CloudflareMutationAction.PRODUCTION_DEPLOY,
                resource_ref="worker_1",
                before_release_ref="deployment_1",
                after_release_ref="version_2",
                expected_target_release_ref="version_2",
                recovery_target_ref="version_1",
                provider_request_ref="request_1",
                readback_evidence_ref="readback_1",
                smoke_evidence_ref="smoke_evidence_1",
                smoke_passed=False,
                completed_at=NOW,
            )

    def test_forbidden_default_nonclaims_are_explicit(self):
        self.assertFalse(RAW_CLOUDFLARE_TOKEN_IN_B54)
        self.assertFalse(GLOBAL_API_KEY_SUPPORTED)
        self.assertFalse(SECRET_READBACK_SUPPORTED)
        self.assertFalse(DNS_DEFAULT_WRITE_SUPPORTED)
        self.assertFalse(BILLING_MUTATION_SUPPORTED)
        self.assertFalse(MEMBERSHIP_MUTATION_SUPPORTED)
        self.assertFalse(REAL_CLOUDFLARE_ADAPTER_CONFIGURED)
        self.assertFalse(PRODUCTION_MUTATION_CONFIGURED)


if __name__ == "__main__":
    unittest.main()
