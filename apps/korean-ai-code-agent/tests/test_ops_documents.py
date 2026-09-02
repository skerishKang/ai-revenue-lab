from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import (
    CommercialRequest,
    LineItem,
    Money,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierQuote,
    SupplierQuoteLine,
    SupplierQuoteStatus,
)
from kagent.ops_customer_quote import CustomerQuotePricingPolicy, build_customer_quote_draft
from kagent.ops_documents import (
    MODEL_ASSIGNED_OFFICIAL_DOCUMENT_NUMBER_SUPPORTED,
    REAL_BUSINESS_DOCUMENT_RENDERER_CONFIGURED,
    BusinessDocumentKind,
    CustomerQuoteDocumentManifest,
    InMemoryDocumentNumberRegistry,
    PurchaseOrderDocumentManifest,
    UnconfiguredBusinessDocumentRenderer,
)


DAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def customer_quote(*, version=1):
    request = CommercialRequest(
        request_id="request_1",
        workspace_id="ws_1",
        customer_id="customer_1",
        version=1,
        title="모터 견적",
        line_items=(LineItem("line_1", "모터", Decimal("2"), "EA"),),
    )
    supplier = SupplierQuote(
        quote_id="supplier_quote_1",
        workspace_id="ws_1",
        rfq_id="rfq_1",
        supplier_id="supplier_1",
        version=1,
        lines=(SupplierQuoteLine("line_1", Decimal("2"), Money(1000, "KRW")),),
        status=SupplierQuoteStatus.RECEIVED,
        received_at=NOW,
    )
    return build_customer_quote_draft(
        customer_quote_id="customer_quote_1",
        request=request,
        supplier_quote=supplier,
        policy=CustomerQuotePricingPolicy("policy_1", 1000),
        version=version,
    )


def purchase_order(*, version=1):
    return PurchaseOrder(
        po_id="po_1",
        workspace_id="ws_1",
        supplier_id="supplier_1",
        supplier_quote_id="supplier_quote_1",
        supplier_quote_version=1,
        version=version,
        lines=(PurchaseOrderLine("line_1", "모터", Decimal("2"), "EA", Money(1000, "KRW")),),
    )


class OpsDocumentTests(unittest.TestCase):
    def test_number_assignment_is_server_owned_monotonic_and_exact_replay_idempotent(self):
        registry = InMemoryDocumentNumberRegistry()
        first = registry.assign(
            workspace_id="ws_1",
            kind=BusinessDocumentKind.CUSTOMER_QUOTE,
            subject_id="quote_1",
            subject_version=1,
            issue_date=DAY,
        )
        replay = registry.assign(
            workspace_id="ws_1",
            kind=BusinessDocumentKind.CUSTOMER_QUOTE,
            subject_id="quote_1",
            subject_version=1,
            issue_date=DAY,
        )
        second = registry.assign(
            workspace_id="ws_1",
            kind=BusinessDocumentKind.CUSTOMER_QUOTE,
            subject_id="quote_2",
            subject_version=1,
            issue_date=DAY,
        )
        self.assertEqual(first, replay)
        self.assertEqual(first.document_number, "QT-20260903-0001")
        self.assertEqual(second.document_number, "QT-20260903-0002")
        self.assertFalse(MODEL_ASSIGNED_OFFICIAL_DOCUMENT_NUMBER_SUPPORTED)

    def test_sequence_is_scoped_by_workspace_kind_and_date(self):
        registry = InMemoryDocumentNumberRegistry()
        quote = registry.assign(workspace_id="ws_1", kind=BusinessDocumentKind.CUSTOMER_QUOTE, subject_id="q1", subject_version=1, issue_date=DAY)
        po = registry.assign(workspace_id="ws_1", kind=BusinessDocumentKind.PURCHASE_ORDER, subject_id="p1", subject_version=1, issue_date=DAY)
        other_ws = registry.assign(workspace_id="ws_2", kind=BusinessDocumentKind.CUSTOMER_QUOTE, subject_id="q2", subject_version=1, issue_date=DAY)
        self.assertEqual(quote.document_number, "QT-20260903-0001")
        self.assertEqual(po.document_number, "PO-20260903-0001")
        self.assertEqual(other_ws.document_number, "QT-20260903-0001")

    def test_assignment_date_cannot_change_and_new_object_version_gets_new_number(self):
        registry = InMemoryDocumentNumberRegistry()
        v1 = registry.assign(workspace_id="ws_1", kind=BusinessDocumentKind.CUSTOMER_QUOTE, subject_id="q1", subject_version=1, issue_date=DAY)
        with self.assertRaises(ContractError):
            registry.assign(workspace_id="ws_1", kind=BusinessDocumentKind.CUSTOMER_QUOTE, subject_id="q1", subject_version=1, issue_date=date(2026, 9, 4))
        v2 = registry.assign(workspace_id="ws_1", kind=BusinessDocumentKind.CUSTOMER_QUOTE, subject_id="q1", subject_version=2, issue_date=DAY)
        self.assertNotEqual(v1.document_number, v2.document_number)

    def test_customer_quote_manifest_never_exposes_supplier_cost_or_margin(self):
        registry = InMemoryDocumentNumberRegistry()
        quote = customer_quote()
        assignment = registry.assign(
            workspace_id=quote.workspace_id,
            kind=BusinessDocumentKind.CUSTOMER_QUOTE,
            subject_id=quote.customer_quote_id,
            subject_version=quote.version,
            issue_date=DAY,
        )
        manifest = CustomerQuoteDocumentManifest.from_quote(assignment=assignment, quote=quote)
        rendered = manifest.safe_dict()
        self.assertFalse(rendered["supplier_cost_exposed"])
        self.assertFalse(rendered["margin_exposed"])
        self.assertNotIn("cost_unit_price", str(rendered))
        self.assertNotIn("margin_total", str(rendered))
        self.assertEqual(rendered["sale_total"], quote.sale_total.safe_dict())

    def test_po_manifest_never_exposes_customer_sale_price_or_identity(self):
        registry = InMemoryDocumentNumberRegistry()
        po = purchase_order()
        assignment = registry.assign(
            workspace_id=po.workspace_id,
            kind=BusinessDocumentKind.PURCHASE_ORDER,
            subject_id=po.po_id,
            subject_version=po.version,
            issue_date=DAY,
        )
        manifest = PurchaseOrderDocumentManifest.from_purchase_order(assignment=assignment, purchase_order=po)
        rendered = manifest.safe_dict()
        self.assertFalse(rendered["customer_sale_price_exposed"])
        self.assertFalse(rendered["customer_identity_exposed"])
        self.assertEqual(rendered["purchase_total"], po.total.safe_dict())

    def test_manifest_rejects_cross_kind_subject_and_version_binding(self):
        registry = InMemoryDocumentNumberRegistry()
        quote = customer_quote()
        po_assignment = registry.assign(workspace_id="ws_1", kind=BusinessDocumentKind.PURCHASE_ORDER, subject_id=quote.customer_quote_id, subject_version=1, issue_date=DAY)
        with self.assertRaises(ContractError):
            CustomerQuoteDocumentManifest.from_quote(assignment=po_assignment, quote=quote)
        wrong_subject = registry.assign(workspace_id="ws_1", kind=BusinessDocumentKind.CUSTOMER_QUOTE, subject_id="other_quote", subject_version=1, issue_date=DAY)
        with self.assertRaises(ContractError):
            CustomerQuoteDocumentManifest.from_quote(assignment=wrong_subject, quote=quote)

    def test_renderer_is_unconfigured_and_arbitrary_template_code_is_not_manifest_data(self):
        quote = customer_quote()
        registry = InMemoryDocumentNumberRegistry()
        assignment = registry.assign(workspace_id="ws_1", kind=BusinessDocumentKind.CUSTOMER_QUOTE, subject_id=quote.customer_quote_id, subject_version=quote.version, issue_date=DAY)
        manifest = CustomerQuoteDocumentManifest.from_quote(assignment=assignment, quote=quote)
        self.assertFalse(manifest.safe_dict()["arbitrary_template_code"])
        self.assertFalse(REAL_BUSINESS_DOCUMENT_RENDERER_CONFIGURED)
        with self.assertRaises(ContractError):
            UnconfiguredBusinessDocumentRenderer().render(manifest)


if __name__ == "__main__":
    unittest.main()
