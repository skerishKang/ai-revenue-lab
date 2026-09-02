from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalProjection,
    BusinessObjectKind,
    EvidenceOrigin,
    Money,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    QuoteComparison,
    QuoteComparisonEntry,
    WorkflowEvidenceRecord,
)
from kagent.ops_inbox import (
    ExecutiveInboxProjector,
    InboxCardKind,
    InboxCardStatus,
    InboxPriority,
)
from kagent.ops_ledger import BusinessObjectEnvelope, InMemoryOpsLedger


NOW = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)


class ExecutiveInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = InMemoryOpsLedger()
        self.projector = ExecutiveInboxProjector(self.ledger)
        self.po = PurchaseOrder(
            po_id="po_1",
            workspace_id="ws_1",
            supplier_id="supplier_a",
            supplier_quote_id="quote_a",
            supplier_quote_version=1,
            version=1,
            lines=(PurchaseOrderLine("line_1", "모터", 2, "EA", Money(150000)),),
            status=PurchaseOrderStatus.APPROVAL_REQUIRED,
            requested_delivery_date=date(2026, 9, 20),
        )
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id=self.po.po_id,
                version=self.po.version,
                workspace_id=self.po.workspace_id,
                value=self.po,
            )
        )
        self.pending = ApprovalProjection(
            approval_id="approval_po_1",
            workspace_id="ws_1",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_1",
            target_version=1,
            action_fingerprint="a" * 64,
        )
        self.ledger.add_approval_projection(self.pending)

    def test_po_card_surfaces_decision_fields_without_execution_authority(self):
        card = self.projector.project(self.pending)
        self.assertEqual(card.kind, InboxCardKind.PURCHASE_ORDER_APPROVAL)
        self.assertEqual(card.status, InboxCardStatus.OPEN)
        self.assertEqual(card.priority, InboxPriority.HIGH)
        self.assertTrue(card.actionable)
        self.assertEqual(card.supplier_ref, "supplier_a")
        self.assertEqual(card.amount, Money(300000))
        self.assertEqual(card.due_date, date(2026, 9, 20))
        self.assertFalse(hasattr(card, "approve"))
        self.assertFalse(hasattr(self.projector, "approve"))
        rendered = card.safe_dict()
        self.assertEqual(rendered["target_version"], 1)
        self.assertEqual(rendered["action_fingerprint"], "a" * 64)
        self.assertTrue(rendered["actionable"])

    def test_newer_object_version_makes_pending_card_stale(self):
        edited = PurchaseOrder(
            po_id="po_1",
            workspace_id="ws_1",
            supplier_id="supplier_a",
            supplier_quote_id="quote_a",
            supplier_quote_version=1,
            version=2,
            lines=(PurchaseOrderLine("line_1", "모터", 2, "EA", Money(149000)),),
            status=PurchaseOrderStatus.APPROVAL_REQUIRED,
            requested_delivery_date=date(2026, 9, 20),
        )
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id="po_1",
                version=2,
                workspace_id="ws_1",
                value=edited,
            )
        )
        card = self.projector.project(self.pending)
        self.assertEqual(card.status, InboxCardStatus.STALE)
        self.assertFalse(card.actionable)
        self.assertEqual(card.amount, Money(300000))  # exact approved target, not newer content

    def test_decided_approval_is_resolved_not_actionable(self):
        decided = ApprovalProjection(
            approval_id=self.pending.approval_id,
            workspace_id=self.pending.workspace_id,
            action=self.pending.action,
            target_kind=self.pending.target_kind,
            target_id=self.pending.target_id,
            target_version=self.pending.target_version,
            action_fingerprint=self.pending.action_fingerprint,
            decision=ApprovalDecision.APPROVED,
            actor_ref="owner_1",
            decided_at=NOW,
        )
        self.ledger.add_approval_projection(decided)
        card = self.projector.project(decided)
        self.assertEqual(card.status, InboxCardStatus.RESOLVED)
        self.assertFalse(card.actionable)
        self.assertEqual(card.decision, ApprovalDecision.APPROVED)

    def test_evidence_ids_are_bound_to_exact_target_version(self):
        evidence = WorkflowEvidenceRecord(
            evidence_id="ev_po_1",
            workspace_id="ws_1",
            workflow_id="wf_1",
            object_kind=BusinessObjectKind.PURCHASE_ORDER,
            object_id="po_1",
            object_version=1,
            origin=EvidenceOrigin.SOURCE_DOCUMENT,
            source_ref="artifact_po_1",
            summary="발주서 원본",
            recorded_at=NOW,
            authoritative=True,
        )
        self.ledger.add_evidence(evidence)
        card = self.projector.project(self.pending)
        self.assertEqual(card.evidence_ids, ("ev_po_1",))

    def test_supplier_selection_card_is_medium_priority(self):
        comparison = QuoteComparison(
            comparison_id="cmp_1",
            workspace_id="ws_1",
            commercial_request_id="req_1",
            version=1,
            entries=(
                QuoteComparisonEntry(
                    supplier_id="supplier_a",
                    quote_id="quote_a",
                    quote_version=1,
                    total=Money(300000),
                ),
            ),
            recommended_supplier_id="supplier_a",
        )
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.QUOTE_COMPARISON,
                object_id="cmp_1",
                version=1,
                workspace_id="ws_1",
                value=comparison,
            )
        )
        approval = ApprovalProjection(
            approval_id="approval_cmp_1",
            workspace_id="ws_1",
            action=ApprovalAction.SELECT_SUPPLIER,
            target_kind=BusinessObjectKind.QUOTE_COMPARISON,
            target_id="cmp_1",
            target_version=1,
            action_fingerprint="b" * 64,
        )
        self.ledger.add_approval_projection(approval)
        card = self.projector.project(approval)
        self.assertEqual(card.kind, InboxCardKind.SUPPLIER_SELECTION)
        self.assertEqual(card.priority, InboxPriority.MEDIUM)
        self.assertEqual(card.supplier_ref, "supplier_a")

    def test_project_many_rejects_cross_workspace_mixing(self):
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id="po_2",
                version=1,
                workspace_id="ws_2",
                value=PurchaseOrder(
                    po_id="po_2",
                    workspace_id="ws_2",
                    supplier_id="supplier_b",
                    supplier_quote_id="quote_b",
                    supplier_quote_version=1,
                    version=1,
                    lines=(PurchaseOrderLine("line_1", "케이블", 1, "EA", Money(1000)),),
                    status=PurchaseOrderStatus.APPROVAL_REQUIRED,
                ),
            )
        )
        other = ApprovalProjection(
            approval_id="approval_po_2",
            workspace_id="ws_2",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_2",
            target_version=1,
            action_fingerprint="c" * 64,
        )
        self.ledger.add_approval_projection(other)
        with self.assertRaises(ContractError):
            self.projector.project_many((self.pending, other), workspace_id="ws_1")

    def test_project_many_sorts_high_priority_before_medium(self):
        comparison = QuoteComparison(
            comparison_id="cmp_sort",
            workspace_id="ws_1",
            commercial_request_id="req_1",
            version=1,
            entries=(QuoteComparisonEntry("supplier_a", "quote_a", 1, Money(1000)),),
        )
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.QUOTE_COMPARISON,
                object_id="cmp_sort",
                version=1,
                workspace_id="ws_1",
                value=comparison,
            )
        )
        medium = ApprovalProjection(
            approval_id="approval_cmp_sort",
            workspace_id="ws_1",
            action=ApprovalAction.SELECT_SUPPLIER,
            target_kind=BusinessObjectKind.QUOTE_COMPARISON,
            target_id="cmp_sort",
            target_version=1,
            action_fingerprint="d" * 64,
        )
        self.ledger.add_approval_projection(medium)
        cards = self.projector.project_many((medium, self.pending), workspace_id="ws_1")
        self.assertEqual(cards[0].priority, InboxPriority.HIGH)
        self.assertEqual(cards[1].priority, InboxPriority.MEDIUM)


if __name__ == "__main__":
    unittest.main()
