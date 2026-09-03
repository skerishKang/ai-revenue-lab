from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import unittest

from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt, ReplayDisposition
from kagent.contracts import ContractError
from kagent.telegram_contracts import (
    MAX_TELEGRAM_FILE_BYTES,
    TELEGRAM_CALLBACK_DATA_IS_APPROVAL_AUTHORITY,
    TELEGRAM_PERSONAL_MTPROTO_SESSION_SUPPORTED,
    TELEGRAM_RAW_BOT_TOKEN_IN_B54,
    TELEGRAM_WEBHOOK_AND_GETUPDATES_SIMULTANEOUS,
    TELEGRAM_WEBHOOK_SECRET_IS_HMAC_SIGNATURE,
    TelegramApprovalDecision,
    TelegramBotScope,
    TelegramCallbackChallenge,
    TelegramChatKind,
    TelegramFileManifest,
    TelegramFileQuarantineState,
    TelegramInboundUpdate,
    TelegramIngressConfig,
    TelegramIngressMode,
    TelegramOutboundApproval,
    TelegramOutboundCapability,
    TelegramOutboundMaterial,
    TelegramOutboundPreflightDecision,
    TelegramOutboundReceipt,
    TelegramPairedChat,
    TelegramWebhookProof,
    telegram_outbound_preflight,
)

NOW = datetime(2026, 9, 3, 5, 10, tzinfo=timezone.utc)
DIGEST = hashlib.sha256(b"payload").hexdigest()


class TelegramContractTests(unittest.TestCase):
    def scope(self) -> TelegramBotScope:
        return TelegramBotScope(
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            telegram_bot_user_ref="telegram_bot_1",
            paired_chats=(
                TelegramPairedChat(
                    chat_ref="chat_1",
                    telegram_chat_id_ref="tg_chat_1001",
                    kind=TelegramChatKind.PRIVATE,
                    allowed_sender_refs=("actor_1",),
                    privileged_intake_allowed=False,
                ),
            ),
        )

    def webhook(self) -> TelegramIngressConfig:
        return TelegramIngressConfig(
            mode=TelegramIngressMode.WEBHOOK,
            allowed_update_types=("message", "callback_query"),
            webhook_secret_binding_ref="telegram_webhook_secret_1",
        )

    def proof(self, secret_ref: str = "telegram_webhook_secret_1") -> TelegramWebhookProof:
        return TelegramWebhookProof(
            proof_ref="proof_1",
            secret_binding_ref=secret_ref,
            secret_header_verified=True,
            verified_at=NOW,
        )

    def test_private_chat_pairing_requires_exact_sender(self):
        scope = self.scope()
        self.assertTrue(
            scope.authorizes_inbound(
                binding_ref="binding_telegram_1",
                workspace_ref="workspace_1",
                bot_ref="bot_1",
                chat_ref="chat_1",
                sender_ref="actor_1",
            )
        )
        self.assertFalse(
            scope.authorizes_inbound(
                binding_ref="binding_telegram_1",
                workspace_ref="workspace_1",
                bot_ref="bot_1",
                chat_ref="chat_1",
                sender_ref="actor_2",
            )
        )
        with self.assertRaises(ContractError):
            TelegramPairedChat(
                chat_ref="bad_private",
                telegram_chat_id_ref="tg_bad",
                kind=TelegramChatKind.PRIVATE,
                allowed_sender_refs=(),
            )

    def test_webhook_proof_must_match_exact_secret_binding(self):
        update = TelegramInboundUpdate(
            update_id=42,
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            chat_ref="chat_1",
            sender_ref="actor_1",
            update_type="message",
            text="hello",
            replay=ReplayDisposition.NEW,
            webhook_proof=self.proof(),
            message_ref="message_1",
        )
        self.assertTrue(update.accepted_by(scope=self.scope(), ingress=self.webhook()))

        wrong = TelegramInboundUpdate(
            update_id=43,
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            chat_ref="chat_1",
            sender_ref="actor_1",
            update_type="message",
            text="hello",
            replay=ReplayDisposition.NEW,
            webhook_proof=self.proof("telegram_webhook_secret_other"),
            message_ref="message_2",
        )
        self.assertFalse(wrong.accepted_by(scope=self.scope(), ingress=self.webhook()))

    def test_duplicate_update_and_unapproved_type_fail_closed(self):
        duplicate = TelegramInboundUpdate(
            update_id=44,
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            chat_ref="chat_1",
            sender_ref="actor_1",
            update_type="message",
            text="hello",
            replay=ReplayDisposition.DUPLICATE,
            webhook_proof=self.proof(),
        )
        self.assertFalse(duplicate.accepted_by(scope=self.scope(), ingress=self.webhook()))

        edited = TelegramInboundUpdate(
            update_id=45,
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            chat_ref="chat_1",
            sender_ref="actor_1",
            update_type="edited_message",
            text="hello",
            replay=ReplayDisposition.NEW,
            webhook_proof=self.proof(),
        )
        self.assertFalse(edited.accepted_by(scope=self.scope(), ingress=self.webhook()))

    def test_getupdates_and_webhook_proof_are_mutually_exclusive(self):
        ingress = TelegramIngressConfig(
            mode=TelegramIngressMode.GET_UPDATES,
            allowed_update_types=("message",),
        )
        update = TelegramInboundUpdate(
            update_id=46,
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            chat_ref="chat_1",
            sender_ref="actor_1",
            update_type="message",
            text="hello",
            replay=ReplayDisposition.NEW,
            webhook_proof=self.proof(),
        )
        self.assertFalse(update.accepted_by(scope=self.scope(), ingress=ingress))
        self.assertFalse(TELEGRAM_WEBHOOK_AND_GETUPDATES_SIMULTANEOUS)

    def test_file_requires_quarantine_evidence_and_product_bound(self):
        accepted = TelegramFileManifest(
            file_ref="file_1",
            file_unique_ref="unique_1",
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            quarantine_state=TelegramFileQuarantineState.ACCEPTED,
            sha256=DIGEST,
            quarantine_evidence_ref="quarantine_1",
        )
        self.assertTrue(accepted.model_usable())
        with self.assertRaises(ContractError):
            TelegramFileManifest(
                file_ref="file_2",
                file_unique_ref="unique_2",
                filename="report.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
                quarantine_state=TelegramFileQuarantineState.ACCEPTED,
                sha256=DIGEST,
            )
        with self.assertRaises(ContractError):
            TelegramFileManifest(
                file_ref="file_3",
                file_unique_ref="unique_3",
                filename="too-large.bin",
                mime_type="application/octet-stream",
                size_bytes=MAX_TELEGRAM_FILE_BYTES + 1,
            )

    def test_callback_challenge_is_opaque_expiring_and_single_use(self):
        challenge = TelegramCallbackChallenge(
            challenge_ref="opaque_challenge_1",
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            chat_ref="chat_1",
            sender_ref="actor_1",
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            decision=TelegramApprovalDecision.APPROVE,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )
        self.assertTrue(
            challenge.matches_callback(
                callback_data="opaque_challenge_1",
                binding_ref="binding_telegram_1",
                workspace_ref="workspace_1",
                bot_ref="bot_1",
                chat_ref="chat_1",
                sender_ref="actor_1",
                now=NOW + timedelta(minutes=1),
            )
        )
        consumed = challenge.consume(NOW + timedelta(minutes=1))
        self.assertFalse(consumed.usable_at(NOW + timedelta(minutes=2)))
        with self.assertRaises(ContractError):
            consumed.consume(NOW + timedelta(minutes=2))
        self.assertFalse(TELEGRAM_CALLBACK_DATA_IS_APPROVAL_AUTHORITY)

    def test_outbound_permission_does_not_depend_on_privileged_inbound_flag(self):
        material = TelegramOutboundMaterial(
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            capability=TelegramOutboundCapability.SEND_MESSAGE,
            chat_ref="chat_1",
            text_sha256=DIGEST,
        )
        approval = TelegramOutboundApproval(
            approval_ref="approval_send_1",
            evidence_ref="evidence_send_1",
            material_fingerprint=material.material_fingerprint,
            approved_at=NOW,
        )
        intent = ConnectorWriteIntent(
            connector_id="telegram",
            binding_ref="binding_telegram_1",
            actor_ref="actor_1",
            tool_name="telegram.send_message",
            target_ref=material.target_ref,
            payload_fingerprint=material.material_fingerprint,
            idempotency_key="telegram_send_1",
            approval_ref="approval_send_1",
            evidence_ref="evidence_send_1",
            requested_at=NOW,
            expected_version_ref=material.version_ref,
        )
        self.assertEqual(
            telegram_outbound_preflight(
                scope=self.scope(),
                material=material,
                approval=approval,
                intent=intent,
                actor_ref="actor_1",
            ),
            TelegramOutboundPreflightDecision.ALLOW,
        )

    def test_material_change_invalidates_approval(self):
        original = TelegramOutboundMaterial(
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            capability=TelegramOutboundCapability.SEND_MESSAGE,
            chat_ref="chat_1",
            text_sha256=DIGEST,
        )
        changed = TelegramOutboundMaterial(
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            capability=TelegramOutboundCapability.SEND_MESSAGE,
            chat_ref="chat_1",
            text_sha256=hashlib.sha256(b"changed").hexdigest(),
        )
        approval = TelegramOutboundApproval(
            approval_ref="approval_send_1",
            evidence_ref="evidence_send_1",
            material_fingerprint=original.material_fingerprint,
            approved_at=NOW,
        )
        intent = ConnectorWriteIntent(
            connector_id="telegram",
            binding_ref="binding_telegram_1",
            actor_ref="actor_1",
            tool_name="telegram.send_message",
            target_ref=changed.target_ref,
            payload_fingerprint=changed.material_fingerprint,
            idempotency_key="telegram_send_2",
            approval_ref="approval_send_1",
            evidence_ref="evidence_send_1",
            requested_at=NOW,
            expected_version_ref=changed.version_ref,
        )
        self.assertEqual(
            telegram_outbound_preflight(
                scope=self.scope(), material=changed, approval=approval, intent=intent, actor_ref="actor_1"
            ),
            TelegramOutboundPreflightDecision.MATERIAL_CHANGED,
        )

    def test_receipt_requires_exact_approved_target(self):
        connector_receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_1",
            connector_id="telegram",
            binding_ref="binding_telegram_1",
            idempotency_key="telegram_send_1",
            provider_operation_ref="telegram_message_99",
            target_ref="telegram:workspace_1:bot:bot_1:chat:chat_1:new-message",
            committed_at=NOW,
            evidence_ref="provider_evidence_1",
        )
        receipt = TelegramOutboundReceipt(
            connector_receipt=connector_receipt,
            capability=TelegramOutboundCapability.SEND_MESSAGE,
            approved_target_ref="telegram:workspace_1:bot:bot_1:chat:chat_1:new-message",
            result_message_ref="telegram_message_99",
        )
        self.assertEqual(receipt.result_message_ref, "telegram_message_99")
        with self.assertRaises(ContractError):
            TelegramOutboundReceipt(
                connector_receipt=connector_receipt,
                capability=TelegramOutboundCapability.SEND_MESSAGE,
                approved_target_ref="telegram:workspace_1:bot:bot_1:chat:chat_1:other",
                result_message_ref="telegram_message_99",
            )

    def test_nonclaims_remain_false(self):
        self.assertFalse(TELEGRAM_PERSONAL_MTPROTO_SESSION_SUPPORTED)
        self.assertFalse(TELEGRAM_WEBHOOK_SECRET_IS_HMAC_SIGNATURE)
        self.assertFalse(TELEGRAM_RAW_BOT_TOKEN_IN_B54)


if __name__ == "__main__":
    unittest.main()
