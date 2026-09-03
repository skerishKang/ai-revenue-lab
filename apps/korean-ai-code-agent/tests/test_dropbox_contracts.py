from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from kagent.contracts import ContractError
from kagent.dropbox_contracts import (
    DROPBOX_APP_FOLDER_PREFERRED_WHEN_SUFFICIENT,
    DROPBOX_DISPLAY_PATH_IS_AUTHORITY,
    DROPBOX_PROVIDER_CONTENT_HASH_IS_SHA256,
    DROPBOX_RAW_OAUTH_TOKEN_IN_B54,
    DROPBOX_STRICT_CONFLICT_REQUIRED,
    DROPBOX_WHOLE_ACCOUNT_MODEL_VISIBILITY,
    DROPBOX_WHOLE_TREE_SYNC_SUPPORTED,
    DropboxAccessModel,
    DropboxMetadataProjection,
    DropboxMutationApproval,
    DropboxMutationCapability,
    DropboxMutationMaterial,
    DropboxMutationPreflightDecision,
    DropboxMutationReceipt,
    DropboxResourceKind,
    DropboxResourceRef,
    DropboxScopeProjection,
    dropbox_mutation_preflight,
)

NOW = datetime(2026, 9, 3, 5, 40, tzinfo=timezone.utc)
PAYLOAD_HASH = hashlib.sha256(b"payload").hexdigest()
DROPBOX_CONTENT_HASH = "a" * 64


class DropboxContractTests(unittest.TestCase):
    def folder(self, ref: str = "id:folder_1", namespace: str = "ns_1") -> DropboxResourceRef:
        return DropboxResourceRef(namespace, ref, DropboxResourceKind.FOLDER)

    def file(self, ref: str = "id:file_1", namespace: str = "ns_1") -> DropboxResourceRef:
        return DropboxResourceRef(namespace, ref, DropboxResourceKind.FILE)

    def scope(self) -> DropboxScopeProjection:
        return DropboxScopeProjection(
            binding_ref="binding_dropbox_1",
            workspace_ref="workspace_1",
            account_ref="dropbox_account_1",
            access_model=DropboxAccessModel.FULL_DROPBOX,
            root_namespace_ref="ns_1",
            home_namespace_ref="ns_1",
            allowed_resources=(self.folder(), self.file()),
        )

    def metadata(self, rev: str = "rev_001") -> DropboxMetadataProjection:
        return DropboxMetadataProjection(
            binding_ref="binding_dropbox_1",
            workspace_ref="workspace_1",
            resource=self.file(),
            display_path="/Projects/report.txt",
            name="report.txt",
            size_bytes=100,
            rev=rev,
            provider_content_hash=DROPBOX_CONTENT_HASH,
            server_modified_at=NOW,
        )

    def test_scope_uses_namespace_resource_identity_not_display_path(self):
        scope = self.scope()
        same_name_other_namespace = self.file("id:file_1", "ns_other")
        self.assertTrue(scope.allows(self.file()))
        self.assertFalse(scope.allows(same_name_other_namespace))
        rendered = scope.safe_dict()
        self.assertFalse(rendered["display_path_is_authority"])
        self.assertFalse(rendered["whole_account_model_visibility"])

    def test_team_space_keeps_root_and_home_namespace_distinct(self):
        team_scope = DropboxScopeProjection(
            binding_ref="binding_team_1",
            workspace_ref="workspace_1",
            account_ref="dropbox_account_1",
            access_model=DropboxAccessModel.TEAM_SPACE,
            root_namespace_ref="team_root_7",
            home_namespace_ref="home_1",
            allowed_resources=(self.folder(namespace="team_root_7"),),
        )
        self.assertNotEqual(team_scope.root_namespace_ref, team_scope.home_namespace_ref)
        self.assertTrue(team_scope.allows_namespace("team_root_7"))

    def test_provider_content_hash_is_not_mislabelled_sha256(self):
        rendered = self.metadata().safe_dict()
        self.assertEqual(rendered["provider_content_hash_algorithm"], "dropbox-content-hash")
        self.assertFalse(rendered["provider_content_hash_is_sha256"])
        self.assertFalse(DROPBOX_PROVIDER_CONTENT_HASH_IS_SHA256)

    def test_update_requires_exact_rev_and_strict_conflict(self):
        with self.assertRaises(ContractError):
            DropboxMutationMaterial(
                binding_ref="binding_dropbox_1",
                workspace_ref="workspace_1",
                capability=DropboxMutationCapability.UPDATE_FILE,
                source=self.file(),
                target_parent=None,
                target_name="",
                payload_sha256=PAYLOAD_HASH,
                expected_rev=None,
            )
        with self.assertRaises(ContractError):
            DropboxMutationMaterial(
                binding_ref="binding_dropbox_1",
                workspace_ref="workspace_1",
                capability=DropboxMutationCapability.UPDATE_FILE,
                source=self.file(),
                target_parent=None,
                target_name="",
                payload_sha256=PAYLOAD_HASH,
                expected_rev="rev_001",
                strict_conflict=False,
            )

    def test_exact_rev_update_passes_and_stale_rev_fails(self):
        material = DropboxMutationMaterial(
            binding_ref="binding_dropbox_1",
            workspace_ref="workspace_1",
            capability=DropboxMutationCapability.UPDATE_FILE,
            source=self.file(),
            target_parent=None,
            target_name="",
            payload_sha256=PAYLOAD_HASH,
            expected_rev="rev_001",
            strict_conflict=True,
        )
        approval = DropboxMutationApproval(
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            material_fingerprint=material.material_fingerprint,
            approved_at=NOW,
        )
        intent = ConnectorWriteIntent(
            connector_id="dropbox",
            binding_ref="binding_dropbox_1",
            actor_ref="actor_1",
            tool_name="dropbox.update_file",
            target_ref=material.target_ref,
            payload_fingerprint=material.material_fingerprint,
            idempotency_key="dropbox_update_1",
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            requested_at=NOW,
            expected_version_ref=material.version_ref,
        )
        self.assertEqual(
            dropbox_mutation_preflight(
                scope=self.scope(), material=material, approval=approval, intent=intent, current_source=self.metadata("rev_001")
            ),
            DropboxMutationPreflightDecision.ALLOW,
        )
        self.assertEqual(
            dropbox_mutation_preflight(
                scope=self.scope(), material=material, approval=approval, intent=intent, current_source=self.metadata("rev_002")
            ),
            DropboxMutationPreflightDecision.STALE_REV,
        )
        self.assertTrue(DROPBOX_STRICT_CONFLICT_REQUIRED)

    def test_upload_add_requires_allowed_parent_and_no_overwrite_rev(self):
        material = DropboxMutationMaterial(
            binding_ref="binding_dropbox_1",
            workspace_ref="workspace_1",
            capability=DropboxMutationCapability.UPLOAD_ADD,
            source=None,
            target_parent=self.folder(),
            target_name="new.txt",
            payload_sha256=PAYLOAD_HASH,
        )
        approval = DropboxMutationApproval(
            approval_ref="approval_add_1",
            evidence_ref="evidence_add_1",
            material_fingerprint=material.material_fingerprint,
            approved_at=NOW,
        )
        intent = ConnectorWriteIntent(
            connector_id="dropbox",
            binding_ref="binding_dropbox_1",
            actor_ref="actor_1",
            tool_name="dropbox.upload_add",
            target_ref=material.target_ref,
            payload_fingerprint=material.material_fingerprint,
            idempotency_key="dropbox_add_1",
            approval_ref="approval_add_1",
            evidence_ref="evidence_add_1",
            requested_at=NOW,
            expected_version_ref=material.version_ref,
        )
        self.assertEqual(
            dropbox_mutation_preflight(scope=self.scope(), material=material, approval=approval, intent=intent),
            DropboxMutationPreflightDecision.ALLOW,
        )

        outside = DropboxMutationMaterial(
            binding_ref="binding_dropbox_1",
            workspace_ref="workspace_1",
            capability=DropboxMutationCapability.UPLOAD_ADD,
            source=None,
            target_parent=self.folder("id:outside", "ns_other"),
            target_name="new.txt",
            payload_sha256=PAYLOAD_HASH,
        )
        outside_approval = DropboxMutationApproval(
            approval_ref="approval_add_2",
            evidence_ref="evidence_add_2",
            material_fingerprint=outside.material_fingerprint,
            approved_at=NOW,
        )
        outside_intent = ConnectorWriteIntent(
            connector_id="dropbox",
            binding_ref="binding_dropbox_1",
            actor_ref="actor_1",
            tool_name="dropbox.upload_add",
            target_ref=outside.target_ref,
            payload_fingerprint=outside.material_fingerprint,
            idempotency_key="dropbox_add_2",
            approval_ref="approval_add_2",
            evidence_ref="evidence_add_2",
            requested_at=NOW,
            expected_version_ref=outside.version_ref,
        )
        self.assertEqual(
            dropbox_mutation_preflight(scope=self.scope(), material=outside, approval=outside_approval, intent=outside_intent),
            DropboxMutationPreflightDecision.OUT_OF_SCOPE,
        )

    def test_cross_namespace_move_is_rejected(self):
        with self.assertRaises(ContractError):
            DropboxMutationMaterial(
                binding_ref="binding_dropbox_1",
                workspace_ref="workspace_1",
                capability=DropboxMutationCapability.MOVE,
                source=self.file(namespace="ns_1"),
                target_parent=self.folder(namespace="ns_2"),
                target_name="moved.txt",
                payload_sha256=PAYLOAD_HASH,
            )

    def test_receipt_requires_exact_target_and_keeps_provider_hash_named_correctly(self):
        target = "dropbox:ns_1:file:id:file_1"
        receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_1",
            connector_id="dropbox",
            binding_ref="binding_dropbox_1",
            idempotency_key="dropbox_update_1",
            provider_operation_ref="dropbox_op_1",
            target_ref=target,
            committed_at=NOW,
            evidence_ref="provider_evidence_1",
        )
        wrapped = DropboxMutationReceipt(
            connector_receipt=receipt,
            capability=DropboxMutationCapability.UPDATE_FILE,
            approved_target_ref=target,
            result_resource=self.file(),
            result_rev="rev_002",
            result_provider_content_hash=DROPBOX_CONTENT_HASH,
        )
        self.assertEqual(wrapped.result_rev, "rev_002")
        with self.assertRaises(ContractError):
            DropboxMutationReceipt(
                connector_receipt=receipt,
                capability=DropboxMutationCapability.UPDATE_FILE,
                approved_target_ref="dropbox:ns_1:file:id:other",
                result_resource=self.file(),
                result_rev="rev_002",
                result_provider_content_hash=DROPBOX_CONTENT_HASH,
            )

    def test_nonclaims_remain_fail_closed(self):
        self.assertTrue(DROPBOX_APP_FOLDER_PREFERRED_WHEN_SUFFICIENT)
        self.assertFalse(DROPBOX_WHOLE_ACCOUNT_MODEL_VISIBILITY)
        self.assertFalse(DROPBOX_DISPLAY_PATH_IS_AUTHORITY)
        self.assertFalse(DROPBOX_WHOLE_TREE_SYNC_SUPPORTED)
        self.assertFalse(DROPBOX_RAW_OAUTH_TOKEN_IN_B54)


if __name__ == "__main__":
    unittest.main()
