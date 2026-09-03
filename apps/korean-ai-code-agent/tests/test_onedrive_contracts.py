from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import unittest

from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from kagent.contracts import ContractError
from kagent.onedrive_contracts import (
    MICROSOFT_GRAPH_REQUIRED,
    ONEDRIVE_APP_FOLDER_PERSONAL_NARROW_MODE,
    ONEDRIVE_LEGACY_FILES_READWRITE_SELECTED_FOR_DIRECT_GRAPH,
    ONEDRIVE_PATH_IS_AUTHORITY,
    ONEDRIVE_RAW_OAUTH_TOKEN_IN_B54,
    ONEDRIVE_RAW_UPLOAD_SESSION_URL_IN_B54,
    ONEDRIVE_SELECTED_RESOURCE_SCOPE_PREFERRED,
    ONEDRIVE_WHOLE_TENANT_MODEL_VISIBILITY,
    OneDriveConflictBehavior,
    OneDriveItemProjection,
    OneDriveKind,
    OneDriveMutationApproval,
    OneDriveMutationCapability,
    OneDriveMutationMaterial,
    OneDriveMutationPreflightDecision,
    OneDriveMutationReceipt,
    OneDrivePermissionMode,
    OneDriveResourceKind,
    OneDriveResourceRef,
    OneDriveScopeProjection,
    OneDriveUploadSessionProjection,
    onedrive_mutation_preflight,
)

NOW = datetime(2026, 9, 3, 5, 50, tzinfo=timezone.utc)
PAYLOAD_HASH = hashlib.sha256(b"payload").hexdigest()
EMPTY_HASH = hashlib.sha256(b"").hexdigest()


class OneDriveContractTests(unittest.TestCase):
    def folder(self, ref: str = "folder_1", drive: str = "drive_1") -> OneDriveResourceRef:
        return OneDriveResourceRef(drive, ref, OneDriveResourceKind.FOLDER)

    def file(self, ref: str = "file_1", drive: str = "drive_1") -> OneDriveResourceRef:
        return OneDriveResourceRef(drive, ref, OneDriveResourceKind.FILE)

    def scope(self) -> OneDriveScopeProjection:
        return OneDriveScopeProjection(
            binding_ref="binding_onedrive_1",
            workspace_ref="workspace_1",
            account_ref="account_1",
            kind=OneDriveKind.BUSINESS,
            drive_ref="drive_1",
            permission_mode=OneDrivePermissionMode.SELECTED_RESOURCE,
            allowed_resources=(self.folder(), self.file()),
            tenant_ref="tenant_1",
        )

    def state(self, etag: str = '"etag-1"') -> OneDriveItemProjection:
        return OneDriveItemProjection(
            binding_ref="binding_onedrive_1",
            workspace_ref="workspace_1",
            resource=self.file(),
            name="report.docx",
            display_path="/Shared/report.docx",
            size_bytes=1024,
            etag=etag,
            ctag='"ctag-1"',
            modified_at=NOW,
        )

    def test_drive_kinds_and_tenant_site_binding_are_explicit(self):
        personal = OneDriveScopeProjection(
            binding_ref="binding_personal",
            workspace_ref="workspace_1",
            account_ref="msa_1",
            kind=OneDriveKind.PERSONAL,
            drive_ref="personal_drive",
            permission_mode=OneDrivePermissionMode.APP_FOLDER_PERSONAL,
            allowed_resources=(self.folder("app_root", "personal_drive"),),
        )
        self.assertEqual(personal.kind, OneDriveKind.PERSONAL)
        with self.assertRaises(ContractError):
            OneDriveScopeProjection(
                binding_ref="binding_sp",
                workspace_ref="workspace_1",
                account_ref="account_1",
                kind=OneDriveKind.SHAREPOINT,
                drive_ref="drive_sp",
                permission_mode=OneDrivePermissionMode.SELECTED_RESOURCE,
                allowed_resources=(self.folder("folder_sp", "drive_sp"),),
                tenant_ref="tenant_1",
            )
        sharepoint = OneDriveScopeProjection(
            binding_ref="binding_sp",
            workspace_ref="workspace_1",
            account_ref="account_1",
            kind=OneDriveKind.SHAREPOINT,
            drive_ref="drive_sp",
            permission_mode=OneDrivePermissionMode.SELECTED_RESOURCE,
            allowed_resources=(self.folder("folder_sp", "drive_sp"),),
            tenant_ref="tenant_1",
            site_ref="site_1",
        )
        self.assertEqual(sharepoint.site_ref, "site_1")

    def test_scope_is_driveitem_allowlist_not_path_authority(self):
        self.assertTrue(self.scope().allows(self.file()))
        self.assertFalse(self.scope().allows(self.file("file_1", "drive_other")))
        rendered = self.scope().safe_dict()
        self.assertFalse(rendered["whole_tenant_model_visibility"])
        self.assertFalse(rendered["path_is_authority"])

    def test_model_projection_hashes_raw_etag_ctag(self):
        rendered = self.state().safe_dict()
        self.assertIsNotNone(rendered["etag_sha256"])
        self.assertIsNotNone(rendered["ctag_sha256"])
        self.assertFalse(rendered["raw_etag_present"])
        self.assertFalse(rendered["raw_ctag_present"])
        self.assertNotIn('"etag-1"', str(rendered))

    def test_update_content_requires_exact_etag_and_detects_stale_state(self):
        current = self.state()
        material = OneDriveMutationMaterial(
            binding_ref="binding_onedrive_1",
            workspace_ref="workspace_1",
            capability=OneDriveMutationCapability.UPDATE_CONTENT,
            source=self.file(),
            target_parent=None,
            target_name="",
            payload_sha256=PAYLOAD_HASH,
            expected_etag_sha256=current.etag_sha256,
        )
        approval = OneDriveMutationApproval(
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            material_fingerprint=material.material_fingerprint,
            approved_at=NOW,
        )
        intent = ConnectorWriteIntent(
            connector_id="onedrive",
            binding_ref="binding_onedrive_1",
            actor_ref="actor_1",
            tool_name="onedrive.update_content",
            target_ref=material.target_ref,
            payload_fingerprint=material.material_fingerprint,
            idempotency_key="onedrive_update_1",
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            requested_at=NOW,
            expected_version_ref=material.version_ref,
        )
        self.assertEqual(
            onedrive_mutation_preflight(
                scope=self.scope(), material=material, approval=approval, intent=intent, current_source=current
            ),
            OneDriveMutationPreflightDecision.ALLOW,
        )
        self.assertEqual(
            onedrive_mutation_preflight(
                scope=self.scope(), material=material, approval=approval, intent=intent, current_source=self.state('"etag-2"')
            ),
            OneDriveMutationPreflightDecision.STALE_ETAG,
        )

    def test_existing_move_and_delete_require_etag(self):
        with self.assertRaises(ContractError):
            OneDriveMutationMaterial(
                binding_ref="binding_onedrive_1",
                workspace_ref="workspace_1",
                capability=OneDriveMutationCapability.MOVE,
                source=self.file(),
                target_parent=self.folder(),
                target_name="moved.docx",
                payload_sha256=EMPTY_HASH,
            )
        with self.assertRaises(ContractError):
            OneDriveMutationMaterial(
                binding_ref="binding_onedrive_1",
                workspace_ref="workspace_1",
                capability=OneDriveMutationCapability.DELETE,
                source=self.file(),
                target_parent=None,
                target_name="",
                payload_sha256=EMPTY_HASH,
            )

    def test_new_upload_defaults_fail_conflict_and_resumable_url_stays_secret(self):
        material = OneDriveMutationMaterial(
            binding_ref="binding_onedrive_1",
            workspace_ref="workspace_1",
            capability=OneDriveMutationCapability.UPLOAD_NEW,
            source=None,
            target_parent=self.folder(),
            target_name="new.bin",
            payload_sha256=PAYLOAD_HASH,
            conflict_behavior=OneDriveConflictBehavior.FAIL,
            resumable_upload=True,
            defer_commit=True,
        )
        self.assertEqual(material.conflict_behavior, OneDriveConflictBehavior.FAIL)
        session = OneDriveUploadSessionProjection(
            session_ref="upload_session_1",
            binding_ref="binding_onedrive_1",
            workspace_ref="workspace_1",
            target_ref=material.target_ref,
            expires_at=NOW + timedelta(hours=1),
            defer_commit=True,
        )
        rendered = session.safe_dict()
        self.assertFalse(rendered["raw_upload_url_present"])
        with self.assertRaises(ContractError):
            OneDriveMutationMaterial(
                binding_ref="binding_onedrive_1",
                workspace_ref="workspace_1",
                capability=OneDriveMutationCapability.UPLOAD_NEW,
                source=None,
                target_parent=self.folder(),
                target_name="new.bin",
                payload_sha256=PAYLOAD_HASH,
                conflict_behavior=OneDriveConflictBehavior.REPLACE,
            )

    def test_cross_drive_move_is_rejected(self):
        current = self.state()
        with self.assertRaises(ContractError):
            OneDriveMutationMaterial(
                binding_ref="binding_onedrive_1",
                workspace_ref="workspace_1",
                capability=OneDriveMutationCapability.MOVE,
                source=self.file(),
                target_parent=self.folder("folder_other", "drive_other"),
                target_name="moved.docx",
                payload_sha256=EMPTY_HASH,
                expected_etag_sha256=current.etag_sha256,
            )

    def test_receipt_requires_exact_target_and_no_live_tag_after_delete(self):
        target = "onedrive:drive_1:file:file_1"
        connector_receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_1",
            connector_id="onedrive",
            binding_ref="binding_onedrive_1",
            idempotency_key="delete_1",
            provider_operation_ref="graph_op_1",
            target_ref=target,
            committed_at=NOW,
            evidence_ref="provider_evidence_1",
        )
        wrapped = OneDriveMutationReceipt(
            connector_receipt=connector_receipt,
            capability=OneDriveMutationCapability.DELETE,
            approved_target_ref=target,
            result_resource=None,
            result_etag_sha256=None,
        )
        self.assertIsNone(wrapped.result_resource)
        with self.assertRaises(ContractError):
            OneDriveMutationReceipt(
                connector_receipt=connector_receipt,
                capability=OneDriveMutationCapability.DELETE,
                approved_target_ref=target,
                result_resource=None,
                result_etag_sha256=hashlib.sha256(b"etag").hexdigest(),
            )

    def test_permission_and_secret_nonclaims(self):
        self.assertTrue(MICROSOFT_GRAPH_REQUIRED)
        self.assertTrue(ONEDRIVE_SELECTED_RESOURCE_SCOPE_PREFERRED)
        self.assertTrue(ONEDRIVE_APP_FOLDER_PERSONAL_NARROW_MODE)
        self.assertFalse(ONEDRIVE_LEGACY_FILES_READWRITE_SELECTED_FOR_DIRECT_GRAPH)
        self.assertFalse(ONEDRIVE_WHOLE_TENANT_MODEL_VISIBILITY)
        self.assertFalse(ONEDRIVE_PATH_IS_AUTHORITY)
        self.assertFalse(ONEDRIVE_RAW_UPLOAD_SESSION_URL_IN_B54)
        self.assertFalse(ONEDRIVE_RAW_OAUTH_TOKEN_IN_B54)


if __name__ == "__main__":
    unittest.main()
