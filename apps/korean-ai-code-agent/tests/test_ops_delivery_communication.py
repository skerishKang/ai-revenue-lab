from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from kagent.contracts import ContractError
from kagent.ops_communications import CommunicationChannel, DeterministicFakeCommunicationConnector
from kagent.ops_contracts import (
    BusinessObjectKind,
    DeliveryStatus,
    Money,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
)
from kagent.ops_delivery_communication import (
    REAL_DELIVERY_FOLLOWUP_SEND_CONFIGURED,
    DeliveryFollowupApprovalBinding,
    DeliveryFollowupCommunicationBridge,
)
from kagent.ops_delivery_tracking import (
    DeliveryExceptionProjector,
    DeliveryTrackingCoordinator,
    DeliveryTrackingSnapshot,
)
from kagent.ops_ledger import BusinessObjectEnvelope, InMemoryOpsLedger


NOW = datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc)


class DeliveryCommunicationBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        ledger = InMemoryOpsLedger()
        po = PurchaseOrder(
            po_id="po_1",
            workspace_id="ws_1",
            supplier_id="supplier_1",
            supplier_quote_id="quote_1",
            supplier_quote_version=1,
            version=1,
            lines=(PurchaseOrderLine("line_1", "모터", 2, "EA", Money(1000)),),
            status=PurchaseOrderStatus.ISSUED,
            requested_delivery_date=date(2026, 9, 10),
        )
        ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id=po.po_id,
                version=po.version,
                workspace_id=po.workspace_id,
                value=po,
            )
        )
        self.ledger = ledger
        self.coordinator = DeliveryTrackingCoordinator(ledger)
        self.snapshot = DeliveryTrackingSnapshot(
            delivery_id="delivery_1",
            workspace_id="ws_1",
            po_id="po_1",
            po_version=1,
            supplier_id="supplier_1",
            version=1,
            status=DeliveryStatus.CONFIRMED,
            observed_at=NOW,
            source_ref="evidence:delivery:1",
            promised_date=date(2026, 9, 1),
        )
        self.coordinator.append(self.snapshot)
        projector = DeliveryExceptionProjector()
        self.projection = projector.project(self.snapshot, as_of=date(2026, 9, 3))
        self.draft = projector.draft_followup(self.projection)
        self.binding = DeliveryFollowupApprovalBinding.bind(
            binding_id="binding_1",
            pause_id="pause_1",
            workspace_id="ws_1",
            projection=self.projection,
            draft=self.draft,
            recipient_ref="supplier-contact:1",
            channel=CommunicationChannel.EMAIL,
        )

    def decision(self, *, outcome: ApprovalOutcome = ApprovalOutcome.APPROVED, pause_id: str = "pause_1") -> VerifiedApprovalDecision:
        return VerifiedApprovalDecision(
            decision_id="decision_1",
            pause_id=pause_id,
            outcome=outcome,
            authority_ref="trusted_control_plane",
            evidence_ref="approval_evidence_1",
            decided_at=NOW,
        )

    def test_binding_contains_hashes_not_raw_message_body(self):
        rendered = self.binding.safe_dict()
        self.assertEqual(rendered["approval_authority"], "p01_verified_decision")
        self.assertNotIn(self.draft.message, str(rendered))
        self.assertEqual(len(rendered["message_sha256"]), 64)
        self.assertEqual(len(rendered["action_fingerprint"]), 64)

    def test_approved_decision_builds_exact_delivery_communication_request(self):
        request = DeliveryFollowupCommunicationBridge(self.coordinator).build_send_request(
            request_id="comm_1",
            projection=self.projection,
            draft=self.draft,
            binding=self.binding,
            decision=self.decision(),
        )
        self.assertEqual(request.workspace_id, "ws_1")
        self.assertEqual(request.channel, CommunicationChannel.EMAIL)
        self.assertEqual(request.recipient_ref, "supplier-contact:1")
        self.assertEqual(request.target_kind, BusinessObjectKind.DELIVERY_COMMITMENT)
        self.assertEqual(request.target_id, "delivery_1")
        self.assertEqual(request.target_version, 1)
        self.assertEqual(request.approval_id, "decision_1")
        self.assertEqual(request.action_fingerprint, self.binding.action_fingerprint)
        self.assertEqual(request.body, self.draft.message)

    def test_denied_or_wrong_pause_decision_fails_closed(self):
        bridge = DeliveryFollowupCommunicationBridge(self.coordinator)
        with self.assertRaises(ContractError):
            bridge.build_send_request(
                request_id="comm_denied",
                projection=self.projection,
                draft=self.draft,
                binding=self.binding,
                decision=self.decision(outcome=ApprovalOutcome.DENIED),
            )
        with self.assertRaises(ContractError):
            bridge.build_send_request(
                request_id="comm_wrong_pause",
                projection=self.projection,
                draft=self.draft,
                binding=self.binding,
                decision=self.decision(pause_id="pause_other"),
            )

    def test_changed_message_requires_new_approval_binding(self):
        changed = type(self.draft)(
            delivery_id=self.draft.delivery_id,
            delivery_version=self.draft.delivery_version,
            supplier_id=self.draft.supplier_id,
            exception_kind=self.draft.exception_kind,
            message=self.draft.message + " 오늘 중 회신 부탁드립니다.",
        )
        with self.assertRaisesRegex(ContractError, "message changed"):
            DeliveryFollowupCommunicationBridge(self.coordinator).build_send_request(
                request_id="comm_changed",
                projection=self.projection,
                draft=changed,
                binding=self.binding,
                decision=self.decision(),
            )

    def test_changed_recipient_or_channel_changes_fingerprint(self):
        other_recipient = DeliveryFollowupApprovalBinding.bind(
            binding_id="binding_recipient",
            pause_id="pause_1",
            workspace_id="ws_1",
            projection=self.projection,
            draft=self.draft,
            recipient_ref="supplier-contact:2",
            channel=CommunicationChannel.EMAIL,
        )
        other_channel = DeliveryFollowupApprovalBinding.bind(
            binding_id="binding_channel",
            pause_id="pause_1",
            workspace_id="ws_1",
            projection=self.projection,
            draft=self.draft,
            recipient_ref="supplier-contact:1",
            channel=CommunicationChannel.SMS,
        )
        self.assertNotEqual(other_recipient.action_fingerprint, self.binding.action_fingerprint)
        self.assertNotEqual(other_channel.action_fingerprint, self.binding.action_fingerprint)

    def test_newer_delivery_version_makes_prior_approval_stale(self):
        self.coordinator.append(
            DeliveryTrackingSnapshot(
                delivery_id="delivery_1",
                workspace_id="ws_1",
                po_id="po_1",
                po_version=1,
                supplier_id="supplier_1",
                version=2,
                status=DeliveryStatus.AT_RISK,
                observed_at=datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc),
                source_ref="evidence:delivery:2",
                promised_date=date(2026, 9, 5),
            )
        )
        with self.assertRaisesRegex(ContractError, "stale"):
            DeliveryFollowupCommunicationBridge(self.coordinator).build_send_request(
                request_id="comm_stale",
                projection=self.projection,
                draft=self.draft,
                binding=self.binding,
                decision=self.decision(),
            )

    def test_default_connector_fails_closed_and_fake_connector_is_deterministic(self):
        request = DeliveryFollowupCommunicationBridge(self.coordinator).build_send_request(
            request_id="comm_1",
            projection=self.projection,
            draft=self.draft,
            binding=self.binding,
            decision=self.decision(),
        )
        with self.assertRaises(ContractError):
            DeliveryFollowupCommunicationBridge(self.coordinator).send_approved(request)
        fake = DeterministicFakeCommunicationConnector()
        receipt = DeliveryFollowupCommunicationBridge(self.coordinator, fake).send_approved(request)
        self.assertEqual(receipt.request_id, request.request_id)
        self.assertEqual(len(fake.sent), 1)
        self.assertFalse(REAL_DELIVERY_FOLLOWUP_SEND_CONFIGURED)

    def test_connector_receipt_becomes_version_bound_evidence(self):
        fake = DeterministicFakeCommunicationConnector()
        bridge = DeliveryFollowupCommunicationBridge(self.coordinator, fake)
        request = bridge.build_send_request(
            request_id="comm_evidence",
            projection=self.projection,
            draft=self.draft,
            binding=self.binding,
            decision=self.decision(),
        )
        receipt = bridge.send_approved(request)
        evidence = bridge.receipt_evidence(
            evidence_id="evidence_followup_1",
            workflow_id="workflow_1",
            request=request,
            receipt=receipt,
            recorded_at=NOW,
        )
        self.assertEqual(evidence.object_kind, BusinessObjectKind.DELIVERY_COMMITMENT)
        self.assertEqual(evidence.object_id, "delivery_1")
        self.assertEqual(evidence.object_version, 1)
        self.ledger.add_evidence(evidence)
        found = self.ledger.evidence_for_object(
            workspace_id="ws_1",
            kind=BusinessObjectKind.DELIVERY_COMMITMENT,
            object_id="delivery_1",
            version=1,
        )
        self.assertEqual(found, (evidence,))


if __name__ == "__main__":
    unittest.main()
