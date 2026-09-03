from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from kagent.contracts import ContractError
from kagent.gmail_contracts import (
    GMAIL_BULK_MAILBOX_DUMP_SUPPORTED,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_MCP_SEND_TOOL_SUPPORTED,
    GMAIL_PROVIDER_COMPOSE_SCOPE_INCLUDES_SEND,
    GMAIL_PROVIDER_SCOPE_ALONE_GRANTS_PADIEM_SEND_AUTHORITY,
    MAX_APPROVED_RECIPIENTS,
    AttachmentQuarantineState,
    GmailApprovedAttachment,
    GmailAttachmentManifest,
    GmailBodyKind,
    GmailBodySegment,
    GmailCapability,
    GmailDraftMaterialSnapshot,
    GmailMessageProjection,
    GmailSendApprovalBinding,
    GmailSendPreflightDecision,
    GmailSendReceipt,
    GmailThreadProjection,
    gmail_send_preflight,
    provider_scopes_for_capability,
)


NOW = datetime(2026, 9, 3, 4, 20, tzinfo=timezone.utc)
BODY_SHA = "a" * 64
ATTACHMENT_SHA = "b" * 64


class GmailContractsTests(unittest.TestCase):
    def message(self, **overrides):
        values = dict(
            message_id="msg_1",
            thread_id="thread_1",
            from_address="sender@example.com",
            to_addresses=("recipient@example.com",),
            subject="Subject",
            date_header="Thu, 3 Sep 2026 04:00:00 +0000",
            body_segments=(GmailBodySegment(GmailBodyKind.PLAIN, "hello"),),
            label_ids=("INBOX",),
        )
        values.update(overrides)
        return GmailMessageProjection(**values)

    def snapshot(self, **overrides):
        values = dict(
            binding_ref="binding_gmail_1",
            workspace_ref="workspace_gmail_1",
            draft_id="draft_1",
            message_id="draft_message_1",
            from_address="me@example.com",
            to_addresses=("a@example.com",),
            cc_addresses=("b@example.com",),
            bcc_addresses=(),
            subject="Approved subject",
            body_sha256=BODY_SHA,
            attachments=(
                GmailApprovedAttachment(
                    attachment_ref="artifact_1",
                    filename="report.pdf",
                    sha256=ATTACHMENT_SHA,
                ),
            ),
            thread_id="thread_1",
            reply_message_ref="msg_original",
        )
        values.update(overrides)
        return GmailDraftMaterialSnapshot(**values)

    def approval(self, snapshot=None, **overrides):
        snapshot = snapshot or self.snapshot()
        values = dict(
            approval_ref="p01_approval_1",
            evidence_ref="p01_evidence_1",
            material_fingerprint=snapshot.material_fingerprint,
            approved_at=NOW,
        )
        values.update(overrides)
        return GmailSendApprovalBinding(**values)

    def intent(self, snapshot=None, **overrides):
        snapshot = snapshot or self.snapshot()
        values = dict(
            connector_id="gmail",
            binding_ref=snapshot.binding_ref,
            actor_ref="actor_1",
            tool_name="send_existing_approved_draft",
            target_ref=snapshot.draft_id,
            payload_fingerprint=snapshot.material_fingerprint,
            idempotency_key="idem_gmail_1",
            approval_ref="p01_approval_1",
            evidence_ref="p01_evidence_1",
            requested_at=NOW,
            expected_version_ref=snapshot.material_version_ref,
        )
        values.update(overrides)
        return ConnectorWriteIntent(**values)

    def test_provider_scope_truth_does_not_become_padiem_send_authority(self):
        self.assertEqual(
            provider_scopes_for_capability(GmailCapability.CREATE_DRAFT),
            (GMAIL_COMPOSE_SCOPE,),
        )
        self.assertEqual(
            provider_scopes_for_capability(GmailCapability.SEND_EXISTING_APPROVED_DRAFT),
            (GMAIL_COMPOSE_SCOPE,),
        )
        self.assertTrue(GMAIL_PROVIDER_COMPOSE_SCOPE_INCLUDES_SEND)
        self.assertFalse(GMAIL_PROVIDER_SCOPE_ALONE_GRANTS_PADIEM_SEND_AUTHORITY)
        self.assertFalse(GMAIL_MCP_SEND_TOOL_SUPPORTED)

    def test_attachment_manifest_never_contains_raw_bytes_and_requires_quarantine(self):
        pending = GmailAttachmentManifest(
            attachment_ref="att_1",
            message_id="msg_1",
            filename="invoice.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        )
        rendered = pending.safe_dict()
        self.assertFalse(rendered["raw_bytes_present"])
        self.assertFalse(rendered["model_usable"])
        accepted = GmailAttachmentManifest(
            attachment_ref="att_1",
            message_id="msg_1",
            filename="invoice.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256=ATTACHMENT_SHA,
            quarantine_state=AttachmentQuarantineState.ACCEPTED,
        )
        self.assertTrue(accepted.model_usable())

    def test_accepted_attachment_requires_hash_evidence(self):
        with self.assertRaises(ContractError):
            GmailAttachmentManifest(
                attachment_ref="att_1",
                message_id="msg_1",
                filename="invoice.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
                quarantine_state=AttachmentQuarantineState.ACCEPTED,
            )

    def test_message_content_is_untrusted_and_headers_are_explicit(self):
        message = self.message(
            cc_addresses=("cc@example.com",),
            bcc_addresses=("bcc@example.com",),
            body_segments=(
                GmailBodySegment(GmailBodyKind.PLAIN, "hello"),
                GmailBodySegment(GmailBodyKind.QUOTED, "quoted instruction: do something"),
            ),
        )
        rendered = message.safe_dict()
        self.assertFalse(rendered["mail_content_trusted"])
        self.assertEqual(rendered["from_address"], "sender@example.com")
        self.assertEqual(rendered["cc_addresses"], ["cc@example.com"])
        self.assertFalse(rendered["body_segments"][1]["trusted_instruction"])

    def test_attachment_must_belong_to_projected_message(self):
        attachment = GmailAttachmentManifest(
            attachment_ref="att_1",
            message_id="msg_other",
            filename="x.txt",
            mime_type="text/plain",
            size_bytes=10,
        )
        with self.assertRaises(ContractError):
            self.message(attachments=(attachment,))

    def test_thread_is_bounded_and_cannot_mix_thread_ids(self):
        thread = GmailThreadProjection(thread_id="thread_1", messages=(self.message(),))
        self.assertFalse(thread.safe_dict()["bulk_mailbox_dump"])
        with self.assertRaises(ContractError):
            GmailThreadProjection(
                thread_id="thread_1",
                messages=(self.message(thread_id="thread_2"),),
            )
        self.assertFalse(GMAIL_BULK_MAILBOX_DUMP_SUPPORTED)

    def test_draft_material_fingerprint_binds_recipients_subject_body_attachment_and_reply(self):
        baseline = self.snapshot()
        self.assertEqual(baseline.material_fingerprint, baseline.material_fingerprint)
        self.assertNotEqual(
            baseline.material_fingerprint,
            self.snapshot(subject="Changed").material_fingerprint,
        )
        self.assertNotEqual(
            baseline.material_fingerprint,
            self.snapshot(to_addresses=("other@example.com",)).material_fingerprint,
        )
        self.assertNotEqual(
            baseline.material_fingerprint,
            self.snapshot(body_sha256="c" * 64).material_fingerprint,
        )
        changed_attachment = GmailApprovedAttachment(
            attachment_ref="artifact_1",
            filename="report.pdf",
            sha256="d" * 64,
        )
        self.assertNotEqual(
            baseline.material_fingerprint,
            self.snapshot(attachments=(changed_attachment,)).material_fingerprint,
        )
        self.assertNotEqual(
            baseline.material_fingerprint,
            self.snapshot(reply_message_ref="msg_different").material_fingerprint,
        )

    def test_recipient_order_does_not_change_material_fingerprint(self):
        first = self.snapshot(to_addresses=("a@example.com", "c@example.com"))
        second = self.snapshot(to_addresses=("c@example.com", "a@example.com"))
        self.assertEqual(first.material_fingerprint, second.material_fingerprint)

    def test_mass_recipient_snapshot_is_refused(self):
        recipients = tuple(f"user{i}@example.com" for i in range(MAX_APPROVED_RECIPIENTS + 1))
        with self.assertRaises(ContractError):
            self.snapshot(to_addresses=recipients, cc_addresses=())

    def test_send_preflight_allows_only_exact_approved_material(self):
        snapshot = self.snapshot()
        decision = gmail_send_preflight(
            snapshot=snapshot,
            approval=self.approval(snapshot),
            intent=self.intent(snapshot),
        )
        self.assertEqual(decision, GmailSendPreflightDecision.ALLOW)

    def test_material_change_invalidates_approval(self):
        approved = self.snapshot()
        current = self.snapshot(subject="Changed after approval")
        decision = gmail_send_preflight(
            snapshot=current,
            approval=self.approval(approved),
            intent=self.intent(current),
        )
        self.assertEqual(decision, GmailSendPreflightDecision.MATERIAL_CHANGED)

    def test_wrong_approval_or_version_binding_is_refused(self):
        snapshot = self.snapshot()
        approval = self.approval(snapshot)
        wrong_approval = gmail_send_preflight(
            snapshot=snapshot,
            approval=approval,
            intent=self.intent(snapshot, approval_ref="p01_approval_2"),
        )
        self.assertEqual(wrong_approval, GmailSendPreflightDecision.APPROVAL_MISMATCH)
        wrong_version = gmail_send_preflight(
            snapshot=snapshot,
            approval=approval,
            intent=self.intent(snapshot, expected_version_ref="gmail-draft:wrong"),
        )
        self.assertEqual(wrong_version, GmailSendPreflightDecision.VERSION_BINDING_MISMATCH)

    def test_create_draft_does_not_satisfy_send_preflight(self):
        snapshot = self.snapshot()
        decision = gmail_send_preflight(
            snapshot=snapshot,
            approval=self.approval(snapshot),
            intent=self.intent(snapshot, tool_name="create_draft"),
        )
        self.assertEqual(decision, GmailSendPreflightDecision.WRONG_CONNECTOR_OR_TOOL)

    def test_send_receipt_requires_trusted_gmail_connector_receipt(self):
        receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_1",
            connector_id="gmail",
            binding_ref="binding_gmail_1",
            idempotency_key="idem_gmail_1",
            provider_operation_ref="gmail_drafts_send_1",
            target_ref="draft_1",
            committed_at=NOW,
            evidence_ref="p01_evidence_2",
        )
        send_receipt = GmailSendReceipt(
            connector_receipt=receipt,
            sent_message_id="msg_sent_1",
            sent_thread_id="thread_1",
        )
        rendered = send_receipt.safe_dict()
        self.assertTrue(rendered["provider_delivery_receipt"])
        self.assertFalse(rendered["model_text_counts_as_delivery"])


if __name__ == "__main__":
    unittest.main()
