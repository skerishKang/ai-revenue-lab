from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import CommercialRequest, LineItem, Money, PurchaseOrder, PurchaseOrderLine, SupplierQuote, SupplierQuoteLine, SupplierQuoteStatus
from kagent.ops_customer_quote import CustomerQuotePricingPolicy, build_customer_quote_draft
from kagent.ops_document_renderer import (
    ARBITRARY_DOCUMENT_TEMPLATE_SUPPORTED,
    DOCUMENT_RENDER_NETWORK_FETCH_SUPPORTED,
    DOCUMENT_RENDER_SCRIPT_EXECUTION_SUPPORTED,
    REAL_PDF_RENDERER_CONFIGURED,
    DeterministicHtmlBusinessDocumentRenderer,
)
from kagent.ops_documents import BusinessDocumentKind, CustomerQuoteDocumentManifest, InMemoryDocumentNumberRegistry, PurchaseOrderDocumentManifest


DAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc)


def customer_manifest():
    request = CommercialRequest(
        request_id="req_1",
        workspace_id="ws_1",
        customer_id="customer_1",
        version=1,
        title="<script>alert(1)</script> 견적",
        line_items=(LineItem("line_1", "<b>모터</b>", Decimal("2"), "EA"),),
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
    quote = build_customer_quote_draft(customer_quote_id="quote_1", request=request, supplier_quote=supplier, policy=CustomerQuotePricingPolicy("policy_1", 1000))
    assignment = InMemoryDocumentNumberRegistry().assign(workspace_id="ws_1", kind=BusinessDocumentKind.CUSTOMER_QUOTE, subject_id=quote.customer_quote_id, subject_version=quote.version, issue_date=DAY)
    return CustomerQuoteDocumentManifest.from_quote(assignment=assignment, quote=quote)


def po_manifest():
    po = PurchaseOrder(
        po_id="po_1",
        workspace_id="ws_1",
        supplier_id="supplier_1",
        supplier_quote_id="supplier_quote_1",
        supplier_quote_version=1,
        version=1,
        lines=(PurchaseOrderLine("line_1", "모터", Decimal("2"), "EA", Money(1000, "KRW")),),
    )
    assignment = InMemoryDocumentNumberRegistry().assign(workspace_id="ws_1", kind=BusinessDocumentKind.PURCHASE_ORDER, subject_id=po.po_id, subject_version=po.version, issue_date=DAY)
    return PurchaseOrderDocumentManifest.from_purchase_order(assignment=assignment, purchase_order=po)


class DocumentRendererTests(unittest.TestCase):
    def test_customer_quote_render_is_deterministic_and_html_escaped(self):
        renderer = DeterministicHtmlBusinessDocumentRenderer()
        first = renderer.render(customer_manifest())
        second = renderer.render(customer_manifest())
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.utf8_bytes, second.utf8_bytes)
        text = first.utf8_bytes.decode("utf-8")
        self.assertNotIn("<script>alert(1)</script>", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertIn("&lt;b&gt;모터&lt;/b&gt;", text)
        self.assertNotIn("cost_unit_price", text)
        self.assertNotIn("margin", text.lower())

    def test_purchase_order_render_does_not_gain_customer_sale_fields(self):
        rendered = DeterministicHtmlBusinessDocumentRenderer().render(po_manifest()).utf8_bytes.decode("utf-8")
        self.assertIn("Purchase Order", rendered)
        self.assertNotIn("customer_", rendered)
        self.assertNotIn("sale_total", rendered)

    def test_safe_projection_exposes_hash_size_not_body(self):
        artifact = DeterministicHtmlBusinessDocumentRenderer().render(customer_manifest())
        safe = artifact.safe_dict()
        self.assertEqual(len(safe["sha256"]), 64)
        self.assertGreater(safe["size_bytes"], 0)
        self.assertFalse(safe["body_exposed"])
        self.assertNotIn("utf8_bytes", safe)

    def test_renderer_rejects_untyped_input_and_has_no_active_code_or_network(self):
        with self.assertRaises(ContractError):
            DeterministicHtmlBusinessDocumentRenderer().render({"document_number": "fake"})
        self.assertFalse(ARBITRARY_DOCUMENT_TEMPLATE_SUPPORTED)
        self.assertFalse(DOCUMENT_RENDER_NETWORK_FETCH_SUPPORTED)
        self.assertFalse(DOCUMENT_RENDER_SCRIPT_EXECUTION_SUPPORTED)
        self.assertFalse(REAL_PDF_RENDERER_CONFIGURED)


if __name__ == "__main__":
    unittest.main()
