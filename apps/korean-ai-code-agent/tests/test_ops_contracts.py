from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import (
    AccountingHandoff,
    ApprovalAction,
    ApprovalDecision,
    ApprovalProjection,
    ArtifactRef,
    BusinessObjectKind,
    CommercialRequest,
    CompanyWorkspace,
    EvidenceOrigin,
    LineItem,
    Money,
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    QuoteComparison,
    QuoteComparisonEntry,
    RecommendationKind,
    Supplier,
    SupplierQuote,
    SupplierQuoteLine,
    SupplierQuoteStatus,
    WorkflowEvidenceRecord,
)


NOW = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)


class OpsContractTests(unittest.TestCase):
    def test_money_rejects_floats_and_normalizes_currency(self):
        self.assertEqual(Money(1250000, "krw").currency, "KRW")
        with self.assertRaises(ContractError):
            Money(12.5, "KRW")  # type: ignore[arg-type]
        with self.assertRaises(ContractError):
            Money(True, "KRW")  # type: ignore[arg-type]
        with self.assertRaises(ContractError):
            Money(100, "WON")

    def test_quantity_rejects_binary_float_and_supports_decimal_text(self):
        line = LineItem(
            line_id="line_1",
            description="모터",
            quantity="2.50",
            unit="EA",
        )
        self.assertEqual(line.quantity, Decimal("2.5"))
        self.assertEqual(line.safe_dict()["quantity"], "2.5")
        with self.assertRaises(ContractError):
            LineItem(line_id="line_2", description="모터", quantity=1.1, unit="EA")

    def test_commercial_request_requires_tuple_unique_line_ids(self):
        line = LineItem("line_1", "모터", 2, "EA")
        request = CommercialRequest(
            request_id="req_1",
            workspace_id="ws_1",
            customer_id="customer_1",
            version=1,
            title="9월 구매 요청",
            line_items=(line,),
            requested_delivery_date=date(2026, 9, 30),
        )
        self.assertEqual(request.version, 1)
        with self.assertRaises(ContractError):
            CommercialRequest(
                request_id="req_2",
                workspace_id="ws_1",
                customer_id="customer_1",
                version=1,
                title="bad",
                line_items=[line],  # type: ignore[arg-type]
            )
        with self.assertRaises(ContractError):
            CommercialRequest(
                request_id="req_3",
                workspace_id="ws_1",
                customer_id="customer_1",
                version=1,
                title="bad",
                line_items=(line, line),
            )

    def test_supplier_quote_total_is_deterministic_minor_units(self):
        quote = SupplierQuote(
            quote_id="quote_1",
            workspace_id="ws_1",
            rfq_id="rfq_1",
            supplier_id="supplier_1",
            version=1,
            lines=(
                SupplierQuoteLine("line_1", 2, Money(1000)),
                SupplierQuoteLine("line_2", 3, Money(2500)),
            ),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=NOW,
        )
        self.assertEqual(quote.total, Money(9500, "KRW"))

    def test_fractional_minor_unit_total_fails_closed(self):
        line = SupplierQuoteLine("line_1", "1.5", Money(101))
        with self.assertRaises(ContractError):
            _ = line.total

    def test_supplier_quote_requires_single_currency(self):
        with self.assertRaises(ContractError):
            SupplierQuote(
                quote_id="quote_1",
                workspace_id="ws_1",
                rfq_id="rfq_1",
                supplier_id="supplier_1",
                version=1,
                lines=(
                    SupplierQuoteLine("line_1", 1, Money(1000, "KRW")),
                    SupplierQuoteLine("line_2", 1, Money(10, "USD")),
                ),
                status=SupplierQuoteStatus.RECEIVED,
                received_at=NOW,
            )

    def test_comparison_recommendation_must_reference_real_supplier(self):
        entry = QuoteComparisonEntry(
            supplier_id="supplier_1",
            quote_id="quote_1",
            quote_version=1,
            total=Money(100000),
            promised_delivery_date=date(2026, 9, 10),
            payment_terms_label="익월말",
        )
        comparison = QuoteComparison(
            comparison_id="cmp_1",
            workspace_id="ws_1",
            commercial_request_id="req_1",
            version=1,
            entries=(entry,),
            recommendation=RecommendationKind.BALANCED,
            recommended_supplier_id="supplier_1",
            recommendation_summary="가격과 결제조건 균형",
        )
        self.assertEqual(comparison.recommended_supplier_id, "supplier_1")
        with self.assertRaises(ContractError):
            QuoteComparison(
                comparison_id="cmp_2",
                workspace_id="ws_1",
                commercial_request_id="req_1",
                version=1,
                entries=(entry,),
                recommended_supplier_id="invented_supplier",
            )

    def test_purchase_order_total_preserves_quote_currency(self):
        po = PurchaseOrder(
            po_id="po_1",
            workspace_id="ws_1",
            supplier_id="supplier_1",
            supplier_quote_id="quote_1",
            supplier_quote_version=2,
            version=1,
            lines=(PurchaseOrderLine("line_1", "모터", 2, "EA", Money(1000)),),
            status=PurchaseOrderStatus.APPROVAL_REQUIRED,
            requested_delivery_date=date(2026, 9, 20),
            payment_terms=PaymentTerms("terms_30", "30일", due_days=30),
        )
        self.assertEqual(po.total, Money(2000, "KRW"))

    def test_approval_projection_binds_exact_action_and_version(self):
        approval = ApprovalProjection(
            approval_id="approval_1",
            workspace_id="ws_1",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_1",
            target_version=3,
            action_fingerprint="a" * 64,
        )
        self.assertFalse(approval.approved)
        self.assertEqual(approval.decision, ApprovalDecision.PENDING)
        with self.assertRaises(ContractError):
            ApprovalProjection(
                approval_id="approval_2",
                workspace_id="ws_1",
                action=ApprovalAction.ISSUE_PURCHASE_ORDER,
                target_kind=BusinessObjectKind.PURCHASE_ORDER,
                target_id="po_1",
                target_version=3,
                action_fingerprint="not-a-sha",
            )

    def test_decided_approval_requires_actor_and_time(self):
        with self.assertRaises(ContractError):
            ApprovalProjection(
                approval_id="approval_1",
                workspace_id="ws_1",
                action=ApprovalAction.SEND_RFQ,
                target_kind=BusinessObjectKind.SUPPLIER_RFQ,
                target_id="rfq_1",
                target_version=1,
                action_fingerprint="b" * 64,
                decision=ApprovalDecision.APPROVED,
            )
        decided = ApprovalProjection(
            approval_id="approval_1",
            workspace_id="ws_1",
            action=ApprovalAction.SEND_RFQ,
            target_kind=BusinessObjectKind.SUPPLIER_RFQ,
            target_id="rfq_1",
            target_version=1,
            action_fingerprint="b" * 64,
            decision=ApprovalDecision.APPROVED,
            actor_ref="user_1",
            decided_at=NOW,
        )
        self.assertTrue(decided.approved)

    def test_model_projection_cannot_be_authoritative_evidence(self):
        with self.assertRaises(ContractError):
            WorkflowEvidenceRecord(
                evidence_id="ev_1",
                workspace_id="ws_1",
                workflow_id="wf_1",
                object_kind=BusinessObjectKind.QUOTE_COMPARISON,
                object_id="cmp_1",
                object_version=1,
                origin=EvidenceOrigin.MODEL_PROJECTION,
                source_ref="model-output",
                summary="추천",
                recorded_at=NOW,
                authoritative=True,
            )

    def test_evidence_safe_projection_redacts_accidental_secrets(self):
        evidence = WorkflowEvidenceRecord(
            evidence_id="ev_2",
            workspace_id="ws_1",
            workflow_id="wf_1",
            object_kind=BusinessObjectKind.COMMERCIAL_REQUEST,
            object_id="req_1",
            object_version=1,
            origin=EvidenceOrigin.SOURCE_DOCUMENT,
            source_ref="token=verysecretvalue",
            summary="api_key=anothersecretvalue",
            recorded_at=NOW,
            authoritative=True,
            metadata=(("source", "password=hiddenvalue"),),
        )
        rendered = str(evidence.safe_dict())
        self.assertNotIn("verysecretvalue", rendered)
        self.assertNotIn("anothersecretvalue", rendered)
        self.assertNotIn("hiddenvalue", rendered)
        self.assertIn("REDACTED", rendered)

    def test_accounting_handoff_is_projection_not_payment_execution(self):
        handoff = AccountingHandoff(
            handoff_id="handoff_1",
            workspace_id="ws_1",
            po_id="po_1",
            po_version=1,
            version=1,
            obligation_amount=Money(1500000),
            expected_payment_date=date(2026, 10, 31),
            note="회계 시스템으로 넘길 예정 데이터",
        )
        self.assertEqual(handoff.obligation_amount.amount_minor, 1500000)
        self.assertFalse(hasattr(handoff, "bank_credential"))
        self.assertFalse(hasattr(handoff, "execute_payment"))

    def test_master_data_is_workspace_scoped(self):
        workspace = CompanyWorkspace("ws_1", "Pilot Company")
        supplier = Supplier(
            supplier_id="supplier_1",
            workspace_id=workspace.workspace_id,
            name="Supplier A",
            payment_terms=PaymentTerms("terms_1", "익월말", due_days=30),
        )
        self.assertEqual(supplier.workspace_id, "ws_1")
        self.assertTrue(supplier.active)

    def test_artifact_hash_is_validated(self):
        artifact = ArtifactRef(
            artifact_id="artifact_1",
            kind="pdf",
            display_name="견적서",
            content_sha256="c" * 64,
        )
        self.assertEqual(artifact.content_sha256, "c" * 64)
        with self.assertRaises(ContractError):
            ArtifactRef("artifact_2", "pdf", content_sha256="bad")


if __name__ == "__main__":
    unittest.main()
