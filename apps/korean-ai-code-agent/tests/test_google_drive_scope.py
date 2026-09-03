from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from kagent.contracts import ContractError
from kagent.google_drive_scope import (
    DRIVE_ATOMIC_VERSION_CAS_SUPPORTED,
    DriveFileMetadata,
    DriveResourceProof,
    DriveScopeDecision,
    DriveScopeProjection,
    DriveShortcutDetails,
    DriveSpaceKind,
    DriveWritePostcheckDecision,
    DriveWritePrecondition,
    DriveWritePreflightDecision,
    authorize_drive_resource,
    authorize_drive_shortcut,
    drive_write_postcheck,
    drive_write_preflight,
    shared_drive_list_query,
    shared_drive_operation_query,
)


NOW = datetime(2026, 9, 3, 4, 10, tzinfo=timezone.utc)
DIGEST = "a" * 64


class GoogleDriveScopeTests(unittest.TestCase):
    def scope(self, **overrides):
        values = dict(
            binding_ref="binding_drive_1",
            allowed_file_ids=("file_exact",),
            allowed_folder_ids=("folder_allowed",),
            allowed_shared_drive_ids=("drive_allowed",),
        )
        values.update(overrides)
        return DriveScopeProjection(**values)

    def metadata(self, **overrides):
        values = dict(
            file_id="file_1",
            name="Report",
            mime_type="text/plain",
            version=10,
            parents=("folder_parent",),
            modified_time="2026-09-03T04:00:00Z",
        )
        values.update(overrides)
        return DriveFileMetadata(**values)

    def proof(self, metadata=None, **overrides):
        values = dict(
            binding_ref="binding_drive_1",
            metadata=metadata or self.metadata(),
            ancestor_folder_ids=("folder_allowed",),
        )
        values.update(overrides)
        return DriveResourceProof(**values)

    def intent(self, **overrides):
        values = dict(
            connector_id="google-drive",
            binding_ref="binding_drive_1",
            actor_ref="actor_1",
            tool_name="update_file",
            target_ref="file_1",
            payload_fingerprint=DIGEST,
            idempotency_key="idem_drive_1",
            approval_ref="p01_approval_1",
            evidence_ref="p01_evidence_1",
            requested_at=NOW,
            expected_version_ref="drive-version:10",
        )
        values.update(overrides)
        return ConnectorWriteIntent(**values)

    def precondition(self, **overrides):
        values = dict(
            file_id="file_1",
            expected_version=10,
            expected_modified_time="2026-09-03T04:00:00Z",
        )
        values.update(overrides)
        return DriveWritePrecondition(**values)

    def test_scope_requires_explicit_boundary(self):
        with self.assertRaises(ContractError):
            DriveScopeProjection(binding_ref="binding_drive_1")

    def test_exact_file_and_folder_ancestor_are_allowed(self):
        exact = self.proof(
            metadata=self.metadata(file_id="file_exact"),
            ancestor_folder_ids=(),
        )
        self.assertEqual(authorize_drive_resource(self.scope(), exact), DriveScopeDecision.ALLOW)
        descendant = self.proof(ancestor_folder_ids=("folder_allowed", "folder_child"))
        self.assertEqual(
            authorize_drive_resource(self.scope(), descendant),
            DriveScopeDecision.ALLOW,
        )

    def test_allowed_folder_itself_is_allowed(self):
        folder = self.proof(
            metadata=self.metadata(
                file_id="folder_allowed",
                mime_type="application/vnd.google-apps.folder",
            ),
            ancestor_folder_ids=(),
        )
        self.assertEqual(authorize_drive_resource(self.scope(), folder), DriveScopeDecision.ALLOW)

    def test_my_drive_root_is_never_implicit(self):
        proof = self.proof(ancestor_folder_ids=())
        narrow = DriveScopeProjection(
            binding_ref="binding_drive_1",
            allowed_file_ids=("other_file",),
        )
        self.assertEqual(authorize_drive_resource(narrow, proof), DriveScopeDecision.OUT_OF_SCOPE)
        broad = DriveScopeProjection(binding_ref="binding_drive_1", allow_my_drive_root=True)
        self.assertEqual(authorize_drive_resource(broad, proof), DriveScopeDecision.ALLOW)

    def test_exact_shared_drive_can_authorize_location(self):
        metadata = self.metadata(drive_id="drive_allowed")
        proof = self.proof(metadata=metadata, ancestor_folder_ids=())
        self.assertEqual(metadata.space_kind, DriveSpaceKind.SHARED_DRIVE)
        self.assertEqual(authorize_drive_resource(self.scope(), proof), DriveScopeDecision.ALLOW)

    def test_wrong_shared_drive_is_out_of_scope_without_exact_file_or_folder(self):
        narrow = DriveScopeProjection(
            binding_ref="binding_drive_1",
            allowed_shared_drive_ids=("drive_allowed",),
        )
        proof = self.proof(
            metadata=self.metadata(drive_id="drive_other"),
            ancestor_folder_ids=(),
        )
        self.assertEqual(authorize_drive_resource(narrow, proof), DriveScopeDecision.OUT_OF_SCOPE)

    def test_trashed_resource_is_refused_even_when_exactly_allowlisted(self):
        proof = self.proof(
            metadata=self.metadata(file_id="file_exact", trashed=True),
            ancestor_folder_ids=(),
        )
        self.assertEqual(authorize_drive_resource(self.scope(), proof), DriveScopeDecision.TRASHED)

    def test_shortcut_never_inherits_scope_to_target(self):
        shortcut = self.metadata(
            file_id="shortcut_1",
            mime_type="application/vnd.google-apps.shortcut",
            shortcut=DriveShortcutDetails(
                target_id="target_1",
                target_mime_type="text/plain",
                target_resource_key="rk_target_1",
            ),
        )
        scope = DriveScopeProjection(
            binding_ref="binding_drive_1",
            allowed_folder_ids=("folder_allowed",),
        )
        shortcut_proof = self.proof(metadata=shortcut, ancestor_folder_ids=("folder_allowed",))
        target_proof = self.proof(
            metadata=self.metadata(file_id="target_1"),
            ancestor_folder_ids=("different_folder",),
        )
        self.assertEqual(
            authorize_drive_resource(scope, shortcut_proof),
            DriveScopeDecision.SHORTCUT_TARGET_REQUIRED,
        )
        self.assertEqual(
            authorize_drive_shortcut(scope, shortcut_proof, target_proof),
            DriveScopeDecision.OUT_OF_SCOPE,
        )

    def test_shortcut_target_must_match_exact_target_id(self):
        shortcut = self.metadata(
            file_id="shortcut_1",
            mime_type="application/vnd.google-apps.shortcut",
            shortcut=DriveShortcutDetails(target_id="target_1"),
        )
        scope = DriveScopeProjection(
            binding_ref="binding_drive_1",
            allowed_file_ids=("shortcut_1", "target_1"),
        )
        shortcut_proof = self.proof(metadata=shortcut, ancestor_folder_ids=())
        wrong_target = self.proof(
            metadata=self.metadata(file_id="target_2"),
            ancestor_folder_ids=(),
        )
        self.assertEqual(
            authorize_drive_shortcut(scope, shortcut_proof, wrong_target),
            DriveScopeDecision.SHORTCUT_TARGET_MISMATCH,
        )

    def test_provider_metadata_preserves_version_drive_checksum_and_shortcut(self):
        metadata = DriveFileMetadata.from_provider(
            {
                "id": "shortcut_1",
                "name": "Shortcut",
                "mimeType": "application/vnd.google-apps.shortcut",
                "version": "42",
                "driveId": "drive_allowed",
                "parents": ["folder_allowed"],
                "modifiedTime": "2026-09-03T04:00:00Z",
                "resourceKey": "rk_shortcut_1",
                "shortcutDetails": {
                    "targetId": "target_1",
                    "targetMimeType": "text/plain",
                    "targetResourceKey": "rk_target_1",
                },
            }
        )
        self.assertEqual(metadata.version, 42)
        self.assertEqual(metadata.drive_id, "drive_allowed")
        self.assertEqual(metadata.shortcut.target_id, "target_1")
        self.assertFalse(metadata.safe_dict()["content_trusted"])

    def test_shared_drive_query_is_exact_and_never_all_drives(self):
        params = shared_drive_list_query(
            self.scope(),
            drive_id="drive_allowed",
            q="name contains 'Quarterly'",
        )
        self.assertEqual(params["corpora"], "drive")
        self.assertEqual(params["driveId"], "drive_allowed")
        self.assertEqual(params["includeItemsFromAllDrives"], "true")
        self.assertEqual(params["supportsAllDrives"], "true")
        self.assertNotEqual(params.get("corpora"), "allDrives")
        self.assertIn("trashed = false", params["q"])

    def test_shared_drive_query_refuses_unapproved_drive(self):
        with self.assertRaises(ContractError):
            shared_drive_list_query(self.scope(), drive_id="drive_other")

    def test_shared_drive_operation_query_supports_resource_key(self):
        params = shared_drive_operation_query(resource_key="rk_1")
        self.assertEqual(params, {"supportsAllDrives": "true", "resourceKey": "rk_1"})

    def test_write_precondition_matches_version_and_optional_metadata(self):
        precondition = DriveWritePrecondition(
            file_id="file_1",
            expected_version=10,
            expected_modified_time="2026-09-03T04:00:00Z",
            expected_md5_checksum="a" * 32,
        )
        matching = self.metadata(md5_checksum="a" * 32)
        changed = self.metadata(version=11, md5_checksum="a" * 32)
        self.assertTrue(precondition.matches(matching))
        self.assertFalse(precondition.matches(changed))
        self.assertEqual(precondition.version_ref, "drive-version:10")

    def test_write_preflight_reuses_p01_intent_and_refuses_stale(self):
        allowed = drive_write_preflight(
            scope=self.scope(),
            proof=self.proof(),
            intent=self.intent(),
            precondition=self.precondition(),
        )
        self.assertEqual(allowed, DriveWritePreflightDecision.ALLOW)
        stale = drive_write_preflight(
            scope=self.scope(),
            proof=self.proof(metadata=self.metadata(version=11)),
            intent=self.intent(),
            precondition=self.precondition(),
        )
        self.assertEqual(stale, DriveWritePreflightDecision.STALE)

    def test_write_preflight_requires_intent_expected_version_binding(self):
        decision = drive_write_preflight(
            scope=self.scope(),
            proof=self.proof(),
            intent=self.intent(expected_version_ref="drive-version:9"),
            precondition=self.precondition(),
        )
        self.assertEqual(decision, DriveWritePreflightDecision.INTENT_TARGET_MISMATCH)

    def test_write_postcheck_requires_advanced_exact_returned_version(self):
        receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_1",
            connector_id="google-drive",
            binding_ref="binding_drive_1",
            idempotency_key="idem_drive_1",
            provider_operation_ref="provider_op_1",
            target_ref="file_1",
            committed_at=NOW,
            evidence_ref="p01_evidence_2",
            version_ref="drive-version:11",
        )
        verified = drive_write_postcheck(
            intent=self.intent(),
            precondition=self.precondition(),
            receipt=receipt,
            returned_metadata=self.metadata(version=11),
        )
        self.assertEqual(verified, DriveWritePostcheckDecision.VERIFIED)
        not_advanced = drive_write_postcheck(
            intent=self.intent(),
            precondition=self.precondition(),
            receipt=receipt,
            returned_metadata=self.metadata(version=10),
        )
        self.assertEqual(not_advanced, DriveWritePostcheckDecision.VERSION_NOT_ADVANCED)

    def test_write_postcheck_requires_receipt_version_match(self):
        receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_1",
            connector_id="google-drive",
            binding_ref="binding_drive_1",
            idempotency_key="idem_drive_1",
            provider_operation_ref="provider_op_1",
            target_ref="file_1",
            committed_at=NOW,
            evidence_ref="p01_evidence_2",
            version_ref="drive-version:12",
        )
        decision = drive_write_postcheck(
            intent=self.intent(),
            precondition=self.precondition(),
            receipt=receipt,
            returned_metadata=self.metadata(version=11),
        )
        self.assertEqual(decision, DriveWritePostcheckDecision.VERSION_RECEIPT_MISMATCH)

    def test_atomic_cas_is_explicitly_not_claimed(self):
        self.assertFalse(DRIVE_ATOMIC_VERSION_CAS_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
