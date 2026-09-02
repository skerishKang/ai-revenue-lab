from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import (
    ApprovalDecision,
    ApprovalProjection,
    BusinessObjectKind,
    CommercialRequest,
    LineItem,
    Money,
    PaymentTerms,
    PurchaseOrderStatus,
    Supplier,
    SupplierQuote,
    SupplierQuoteLine,
    SupplierQuoteStatus,
)
from kagent.ops_workflow import (
    DeterministicFakeOpsOutboundPort,
    OpsWorkflowError,
    QuoteToOrderCoordinator,
    UnconfiguredOpsOutboundPort,
    purchase_order_action_fingerprint,
    rfq_action_fingerprint,
)


NOW = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)


def approved(pending: ApprovalProjection) -> ApprovalProjection:
    return ApprovalProjection(
        approval_id=pending.approval_id,
        workspace_id=pending.workspace_id,
        action=pending.action,
        target_kind=pending.target_kind,
        target_id=pending.target_id,
        target_version=pending.target_version,
        action_fingerprint=pending.action_fingerprint,
        decision=ApprovalDecision.APPROVED,
        actor_ref="owner_1",
        decided_at=NOW,
    )


class QuoteToOrderWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.outbound = DeterministicFakeOpsOutboundPort(clock=lambda: NOW)
        self.coordinator = QuoteToOrderCoordinator(outbound=self.outbound, clock=lambda: NOW)
        self.request = CommercialRequest(
            request_id="req_1",
            workspace_id="ws_1",
            customer_id="customer_1",
            version=1,
            title="모터 구매 요청",
            line_items=(
                LineItem("line_1", "모터", 2, "EA"),
                LineItem("line_2", "케이블", 10, "EA"),
            ),
            requested_delivery_date=date(2026, 9, 30),
        )
        self.coordinator.register_request(self.request)
        self.supplier_a = Supplier(
            supplier_id="supplier_a",
            workspace_id="ws_1",
            name="Supplier A",
            payment_terms=PaymentTerms("terms_a", "익월말", due_days=30),
        )
        self.supplier_b = Supplier(
            supplier_id="supplier_b",
            workspace_id="ws_1",
            name="Supplier B",
            payment_terms=PaymentTerms("terms_b", "선결제", due_days=0, prepaid=True),
        )

    def _send_rfq(self, supplier: Supplier, rfq_id: str):
        rfq = self.coordinator.draft_supplier_rfq(
            request=self.request,
            supplier=supplier,
            rfq_id=rfq_id,
            message="견적 부탁드립니다.",
        )
        pending = self.coordinator.project_rfq_approval(
            rfq=rfq,
            approval_id=f"approval_{rfq_id}",
        )
        self.coordinator.record_approval_projection(approved(pending))
        return self.coordinator.send_rfq(
            workspace_id="ws_1",
            rfq_id=rfq_id,
            approval_id=pending.approval_id,
        )

    def test_rfq_draft_requires_trusted_active_same_workspace_supplier(self):
        with self.assertRaises(OpsWorkflowError):
            self.coordinator.draft_supplier_rfq(
                request=self.request,
                supplier=Supplier("supplier_x", "ws_2", "Other tenant"),
                rfq_id="rfq_x",
            )
        with self.assertRaises(OpsWorkflowError):
            self.coordinator.draft_supplier_rfq(
                request=self.request,
                supplier=Supplier("supplier_y", "ws_1", "Inactive", active=False),
                rfq_id="rfq_y",
            )

    def test_rfq_cannot_send_without_approved_exact_action(self):
        rfq = self.coordinator.draft_supplier_rfq(
            request=self.request,
            supplier=self.supplier_a,
            rfq_id="rfq_1",
        )
        pending = self.coordinator.project_rfq_approval(rfq=rfq, approval_id="approval_1")
        with self.assertRaises(ContractError):
            self.coordinator.send_rfq(
                workspace_id="ws_1",
                rfq_id="rfq_1",
                approval_id=pending.approval_id,
            )
        self.assertEqual(self.outbound.sent, [])

    def test_default_outbound_port_fails_closed_even_after_approval(self):
        coordinator = QuoteToOrderCoordinator(outbound=UnconfiguredOpsOutboundPort(), clock=lambda: NOW)
        coordinator.register_request(self.request)
        rfq = coordinator.draft_supplier_rfq(
            request=self.request,
            supplier=self.supplier_a,
            rfq_id="rfq_closed",
        )
        pending = coordinator.project_rfq_approval(rfq=rfq, approval_id="approval_closed")
        coordinator.record_approval_projection(approved(pending))
        with self.assertRaisesRegex(OpsWorkflowError, "not configured"):
            coordinator.send_rfq(
                workspace_id="ws_1",
                rfq_id=rfq.rfq_id,
                approval_id=pending.approval_id,
            )

    def test_rfq_send_creates_new_version_and_connector_evidence(self):
        sent = self._send_rfq(self.supplier_a, "rfq_1")
        self.assertEqual(sent.version, 2)
        self.assertEqual(sent.status.value, "sent")
        evidence = self.coordinator.ledger.evidence_for_object(
            workspace_id="ws_1",
            kind=BusinessObjectKind.SUPPLIER_RFQ,
            object_id=sent.rfq_id,
            version=sent.version,
        )
        self.assertEqual(len(evidence), 1)
        self.assertTrue(evidence[0].authoritative)
        self.assertEqual(evidence[0].origin.value, "connector_result")

    def test_quote_capture_requires_matching_sent_rfq_and_line_set(self):
        self._send_rfq(self.supplier_a, "rfq_1")
        quote = SupplierQuote(
            quote_id="quote_a",
            workspace_id="ws_1",
            rfq_id="rfq_1",
            supplier_id="supplier_a",
            version=1,
            lines=(
                SupplierQuoteLine("line_1", 2, Money(1000)),
                SupplierQuoteLine("line_2", 10, Money(100)),
            ),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=NOW,
            promised_delivery_date=date(2026, 9, 20),
            payment_terms=self.supplier_a.payment_terms,
        )
        self.assertEqual(self.coordinator.capture_supplier_quote(quote), quote)
        with self.assertRaises(OpsWorkflowError):
            self.coordinator.capture_supplier_quote(
                SupplierQuote(
                    quote_id="quote_bad",
                    workspace_id="ws_1",
                    rfq_id="rfq_1",
                    supplier_id="supplier_a",
                    version=1,
                    lines=(SupplierQuoteLine("line_1", 2, Money(1000)),),
                    status=SupplierQuoteStatus.RECEIVED,
                    received_at=NOW,
                )
            )

    def test_comparison_uses_captured_quotes_and_deterministic_lowest_price(self):
        self._send_rfq(self.supplier_a, "rfq_a")
        self._send_rfq(self.supplier_b, "rfq_b")
        quote_a = SupplierQuote(
            quote_id="quote_a",
            workspace_id="ws_1",
            rfq_id="rfq_a",
            supplier_id="supplier_a",
            version=1,
            lines=(
                SupplierQuoteLine("line_1", 2, Money(1000)),
                SupplierQuoteLine("line_2", 10, Money(100)),
            ),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=NOW,
            payment_terms=self.supplier_a.payment_terms,
        )
        quote_b = SupplierQuote(
            quote_id="quote_b",
            workspace_id="ws_1",
            rfq_id="rfq_b",
            supplier_id="supplier_b",
            version=1,
            lines=(
                SupplierQuoteLine("line_1", 2, Money(900)),
                SupplierQuoteLine("line_2", 10, Money(90)),
            ),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=NOW,
            payment_terms=self.supplier_b.payment_terms,
        )
        self.coordinator.capture_supplier_quote(quote_a)
        self.coordinator.capture_supplier_quote(quote_b)
        comparison = self.coordinator.build_comparison(
            workspace_id="ws_1",
            commercial_request_id="req_1",
            comparison_id="cmp_1",
            quote_ids=("quote_a", "quote_b"),
        )
        self.assertEqual(comparison.recommended_supplier_id, "supplier_b")
        self.assertEqual(comparison.recommendation.value, "lowest_price")
        self.assertEqual(len(comparison.entries), 2)

    def test_end_to_end_quote_to_approved_po_with_network_free_fake(self):
        self._send_rfq(self.supplier_a, "rfq_1")
        quote = SupplierQuote(
            quote_id="quote_a",
            workspace_id="ws_1",
            rfq_id="rfq_1",
            supplier_id="supplier_a",
            version=1,
            lines=(
                SupplierQuoteLine("line_1", 2, Money(1000)),
                SupplierQuoteLine("line_2", 10, Money(100)),
            ),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=NOW,
            promised_delivery_date=date(2026, 9, 20),
            payment_terms=self.supplier_a.payment_terms,
        )
        self.coordinator.capture_supplier_quote(quote)
        po = self.coordinator.draft_purchase_order(
            workspace_id="ws_1",
            commercial_request_id="req_1",
            quote_id="quote_a",
            po_id="po_1",
        )
        self.assertEqual(po.status, PurchaseOrderStatus.APPROVAL_REQUIRED)
        self.assertEqual(po.total, quote.total)
        pending = self.coordinator.project_purchase_order_approval(
            purchase_order=po,
            approval_id="approval_po_1",
        )
        self.coordinator.record_approval_projection(approved(pending))
        issued = self.coordinator.issue_purchase_order(
            workspace_id="ws_1",
            po_id="po_1",
            approval_id=pending.approval_id,
        )
        self.assertEqual(issued.status, PurchaseOrderStatus.ISSUED)
        self.assertEqual(issued.version, 2)
        self.assertEqual(self.outbound.sent[-1][0], "po")

    def test_action_fingerprint_changes_when_material_data_changes(self):
        rfq = self.coordinator.draft_supplier_rfq(
            request=self.request,
            supplier=self.supplier_a,
            rfq_id="rfq_1",
            message="원본",
        )
        changed = rfq.__class__(
            rfq_id=rfq.rfq_id,
            workspace_id=rfq.workspace_id,
            commercial_request_id=rfq.commercial_request_id,
            commercial_request_version=rfq.commercial_request_version,
            supplier_id=rfq.supplier_id,
            version=rfq.version,
            line_items=rfq.line_items,
            status=rfq.status,
            message="변경",
        )
        self.assertNotEqual(rfq_action_fingerprint(rfq), rfq_action_fingerprint(changed))

    def test_po_fingerprint_changes_with_price(self):
        self._send_rfq(self.supplier_a, "rfq_1")
        quote = SupplierQuote(
            quote_id="quote_a",
            workspace_id="ws_1",
            rfq_id="rfq_1",
            supplier_id="supplier_a",
            version=1,
            lines=(
                SupplierQuoteLine("line_1", 2, Money(1000)),
                SupplierQuoteLine("line_2", 10, Money(100)),
            ),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=NOW,
        )
        self.coordinator.capture_supplier_quote(quote)
        po = self.coordinator.draft_purchase_order(
            workspace_id="ws_1",
            commercial_request_id="req_1",
            quote_id="quote_a",
            po_id="po_1",
        )
        changed = po.__class__(
            po_id=po.po_id,
            workspace_id=po.workspace_id,
            supplier_id=po.supplier_id,
            supplier_quote_id=po.supplier_quote_id,
            supplier_quote_version=po.supplier_quote_version,
            version=po.version,
            lines=(
                po.lines[0].__class__(
                    po.lines[0].line_id,
                    po.lines[0].description,
                    po.lines[0].quantity,
                    po.lines[0].unit,
                    Money(po.lines[0].unit_price.amount_minor + 1),
                ),
                po.lines[1],
            ),
            status=po.status,
            requested_delivery_date=po.requested_delivery_date,
            payment_terms=po.payment_terms,
        )
        self.assertNotEqual(
            purchase_order_action_fingerprint(po),
            purchase_order_action_fingerprint(changed),
        )


if __name__ == "__main__":
    unittest.main()
