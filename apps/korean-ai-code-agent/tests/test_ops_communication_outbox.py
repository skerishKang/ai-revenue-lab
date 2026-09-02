from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from kagent.contracts import ContractError
from kagent.ops_communication_outbox import (
    AUTOMATIC_RETRY_AFTER_AMBIGUOUS_DELIVERY_SUPPORTED,
    InMemoryCommunicationOutbox,
    OutboxState,
    communication_request_fingerprint,
)
from kagent.ops_communications import (
    AttachmentMetadata,
    CommunicationChannel,
    CommunicationSendRequest,
    DeterministicFakeCommunicationConnector,
)
from kagent.ops_contracts import BusinessObjectKind


NOW = datetime(2026, 9, 1, 23, 59, tzinfo=timezone.utc)
ACTION = hashlib.sha256(b"action").hexdigest()
ATTACHMENT_SHA = hashlib.sha256(b"attachment").hexdigest()


def request(**kwargs):
    values = dict(
        request_id="send_1",
        workspace_id="ws_1",
        channel=CommunicationChannel.EMAIL,
        recipient_ref="supplier_contact_1",
        subject="견적 요청",
        body="견적 회신 부탁드립니다.",
        target_kind=BusinessObjectKind.SUPPLIER_RFQ,
        target_id="rfq_1",
        target_version=2,
        action_fingerprint=ACTION,
        approval_id="approval_1",
        attachments=(),
    )
    values.update(kwargs)
    return CommunicationSendRequest(**values)


class CommunicationOutboxTests(unittest.TestCase):
    def test_fingerprint_changes_with_material_request_content(self):
        baseline = communication_request_fingerprint(request())
        self.assertNotEqual(baseline, communication_request_fingerprint(request(body="다른 본문")))
        self.assertNotEqual(baseline, communication_request_fingerprint(request(recipient_ref="supplier_contact_2")))
        self.assertNotEqual(baseline, communication_request_fingerprint(request(channel=CommunicationChannel.SMS)))

    def test_attachment_hash_participates_in_fingerprint(self):
        first = AttachmentMetadata("att_1", "quote.pdf", "application/pdf", 10, ATTACHMENT_SHA)
        second = AttachmentMetadata("att_1", "quote.pdf", "application/pdf", 10, hashlib.sha256(b"other").hexdigest())
        self.assertNotEqual(
            communication_request_fingerprint(request(attachments=(first,))),
            communication_request_fingerprint(request(attachments=(second,))),
        )

    def test_prepare_exact_replay_is_idempotent(self):
        outbox = InMemoryCommunicationOutbox()
        first = outbox.prepare(request(), now=NOW)
        second = outbox.prepare(request(), now=NOW)
        self.assertEqual(first, second)
        self.assertEqual(first.state, OutboxState.PENDING)

    def test_conflicting_request_id_replay_fails_closed(self):
        outbox = InMemoryCommunicationOutbox()
        outbox.prepare(request(), now=NOW)
        with self.assertRaises(ContractError):
            outbox.prepare(request(body="changed"), now=NOW)

    def test_successful_send_is_not_sent_twice_on_replay(self):
        outbox = InMemoryCommunicationOutbox()
        connector = DeterministicFakeCommunicationConnector()
        sent = outbox.send_once(request(), connector=connector, now=NOW)
        self.assertEqual(sent.state, OutboxState.SENT)
        self.assertEqual(len(connector.sent), 1)
        replay = outbox.send_once(request(), connector=connector, now=NOW)
        self.assertEqual(replay, sent)
        self.assertEqual(len(connector.sent), 1)
        rendered = replay.safe_dict()
        self.assertFalse(rendered["raw_subject_or_body_stored"])

    def test_ambiguous_connector_failure_requires_reconciliation_and_never_auto_retries(self):
        class AmbiguousConnector:
            def __init__(self):
                self.calls = 0

            def send(self, request):
                self.calls += 1
                raise RuntimeError("ambiguous")

        outbox = InMemoryCommunicationOutbox()
        connector = AmbiguousConnector()
        record = outbox.send_once(request(), connector=connector, now=NOW)
        self.assertEqual(record.state, OutboxState.RECONCILIATION_REQUIRED)
        self.assertEqual(connector.calls, 1)
        with self.assertRaises(ContractError):
            outbox.send_once(request(), connector=connector, now=NOW)
        self.assertEqual(connector.calls, 1)
        self.assertFalse(record.safe_dict()["automatic_retry_after_ambiguous_failure"])

    def test_receipt_request_mismatch_fails_closed(self):
        from kagent.ops_communications import CommunicationDeliveryReceipt

        class BadConnector:
            def send(self, request):
                return CommunicationDeliveryReceipt(
                    request_id="other_request",
                    connector_id="connector_1",
                    external_message_ref="message_1",
                    delivered_at=datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc),
                )

        outbox = InMemoryCommunicationOutbox()
        with self.assertRaises(ContractError):
            outbox.send_once(request(), connector=BadConnector(), now=NOW)

    def test_no_automatic_retry_authority_is_claimed(self):
        self.assertFalse(AUTOMATIC_RETRY_AFTER_AMBIGUOUS_DELIVERY_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
