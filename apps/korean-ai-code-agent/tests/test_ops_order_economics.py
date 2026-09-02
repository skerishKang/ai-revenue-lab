from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import Money, PurchaseOrder, PurchaseOrderLine
from kagent.ops_customer_acceptance import SalesOrderProjection
from kagent.ops_order_economics import (
    ACCOUNTING_WRITE_FROM_ORDER_ECONOMICS_SUPPORTED,
    DUE_DATE_GUESSING_SUPPORTED,
    PAYMENT_EXECUTION_FROM_ORDER_ECONOMICS_SUPPORTED,
    TAX_CALCULATION_FROM_ORDER_ECONOMICS_SUPPORTED,
    CustomerPaymentTerms,
    build_sales_order_receivable,
    project_order_economics,
)


NOW = datetime(2026, 9, 3, 5, 0, tzinfo=timezone.utc)


def sales_order(*, sale_minor=2400, currency="KRW", supplier_quote_id="supplier_quote_1", supplier_quote_version=1):
    return SalesOrderProjection(
        sales_order_id="sales-order:1",
        workspace_id="ws_1",
        customer_id="customer_1",
        customer_quote_id="customer_quote_1",
        customer_quote_version=1,
        pricing_fingerprint="a" * 64,
        acceptance_decision_id="decision_1",
        accepted_at=NOW,
        currency=currency,
        sale_total=Money(sale_minor, currency),
        commercial_request_id="request_1",
        commercial_request_version=1,
        supplier_quote_id=supplier_quote_id,
        supplier_quote_version=supplier_quote_version,
        line_refs=("line_1",),
    )


def purchase_order(*, unit_minor=1000, currency="KRW", supplier_quote_id="supplier_quote_1", supplier_quote_version=1, workspace_id="ws_1"):
    return PurchaseOrder(
        po_id="po_1",
        workspace_id=workspace_id,
        supplier_id="supplier_1",
        supplier_quote_id=supplier_quote_id,
        supplier_quote_version=supplier_quote_version,
        version=1,
        lines=(PurchaseOrderLine("line_1", "모터", Decimal("2"), "EA", Money(unit_minor, currency)),),
    )


class OrderEconomicsTests(unittest.TestCase):
    def test_receivable_uses_explicit_due_days_and_exact_sales_order_amount(self):
        order = sales_order()
        handoff = build_sales_order_receivable(
            sales_order=order,
            payment_terms=CustomerPaymentTerms("terms:30d", 30),
        )
        self.assertEqual(handoff.amount, order.sale_total)
        self.assertEqual(handoff.expected_payment_date.isoformat(), "2026-10-03")
        rendered = handoff.safe_dict()
        self.assertTrue(rendered["advisory_projection"])
        self.assertFalse(rendered["accounting_authority"])
        self.assertFalse(rendered["tax_authority"])
        self.assertFalse(rendered["payment_authority"])
        self.assertFalse(rendered["invoice_created"])

    def test_payment_terms_are_explicit_and_bounded_no_due_date_guessing(self):
        for due_days in (-1, 3651, True, 1.5):
            with self.subTest(due_days=due_days):
                with self.assertRaises(ContractError):
                    CustomerPaymentTerms("terms:test", due_days)
        with self.assertRaises(ContractError):
            build_sales_order_receivable(sales_order=sales_order(), payment_terms=None)
        self.assertFalse(DUE_DATE_GUESSING_SUPPORTED)

    def test_order_economics_uses_exact_supplier_quote_lineage_and_same_currency(self):
        order = sales_order()
        economics = project_order_economics(sales_order=order, purchase_order=purchase_order())
        self.assertEqual(economics.sale_total.amount_minor, 2400)
        self.assertEqual(economics.purchase_total.amount_minor, 2000)
        self.assertEqual(economics.gross_profit.amount_minor, 400)
        self.assertEqual(economics.gross_margin_bps, 1666)
        self.assertFalse(economics.negative_gross_profit)

        with self.assertRaises(ContractError):
            project_order_economics(sales_order=order, purchase_order=purchase_order(supplier_quote_id="other_quote"))
        with self.assertRaises(ContractError):
            project_order_economics(sales_order=order, purchase_order=purchase_order(supplier_quote_version=2))
        with self.assertRaises(ContractError):
            project_order_economics(sales_order=order, purchase_order=purchase_order(workspace_id="ws_other"))
        with self.assertRaises(ContractError):
            project_order_economics(sales_order=order, purchase_order=purchase_order(currency="USD"))

    def test_negative_gross_profit_is_visible_not_hidden(self):
        economics = project_order_economics(
            sales_order=sales_order(sale_minor=1800),
            purchase_order=purchase_order(unit_minor=1000),
        )
        self.assertEqual(economics.gross_profit.amount_minor, -200)
        self.assertTrue(economics.negative_gross_profit)
        self.assertLess(economics.gross_margin_bps, 0)
        rendered = economics.safe_dict()
        self.assertTrue(rendered["negative_gross_profit"])
        self.assertFalse(rendered["hidden_model_recommendation"])

    def test_zero_sale_total_has_deterministic_zero_margin_basis_points(self):
        economics = project_order_economics(
            sales_order=sales_order(sale_minor=0),
            purchase_order=purchase_order(unit_minor=0),
        )
        self.assertEqual(economics.gross_margin_bps, 0)
        self.assertEqual(economics.gross_profit.amount_minor, 0)

    def test_sales_order_projection_retains_supplier_quote_lineage(self):
        rendered = sales_order(supplier_quote_id="quote_exact", supplier_quote_version=7).safe_dict()
        self.assertEqual(rendered["supplier_quote_id"], "quote_exact")
        self.assertEqual(rendered["supplier_quote_version"], 7)

    def test_order_economics_has_no_accounting_tax_or_payment_authority(self):
        economics = project_order_economics(sales_order=sales_order(), purchase_order=purchase_order())
        rendered = economics.safe_dict()
        self.assertFalse(rendered["accounting_authority"])
        self.assertFalse(rendered["tax_authority"])
        self.assertFalse(rendered["payment_authority"])
        self.assertTrue(rendered["advisory_only"])
        self.assertFalse(ACCOUNTING_WRITE_FROM_ORDER_ECONOMICS_SUPPORTED)
        self.assertFalse(TAX_CALCULATION_FROM_ORDER_ECONOMICS_SUPPORTED)
        self.assertFalse(PAYMENT_EXECUTION_FROM_ORDER_ECONOMICS_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
