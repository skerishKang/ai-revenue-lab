from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import (
    CommercialRequest,
    LineItem,
    Money,
    SupplierQuote,
    SupplierQuoteLine,
    SupplierQuoteStatus,
)
from kagent.ops_customer_quote import (
    AUTO_CUSTOMER_QUOTE_SEND_SUPPORTED,
    FX_CONVERSION_SUPPORTED,
    MODEL_DRIVEN_HIDDEN_PRICING_SUPPORTED,
    CustomerQuotePricingPolicy,
    build_customer_quote_draft,
)


NOW = datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc)


def commercial_request(**kwargs):
    values = dict(
        request_id="request_1",
        workspace_id="ws_1",
        customer_id="customer_1",
        version=3,
        title="모터 공급 견적",
        line_items=(
            LineItem("line_1", "모터", Decimal("3"), "EA"),
            LineItem("line_2", "케이블", Decimal("2"), "EA"),
        ),
    )
    values.update(kwargs)
    return CommercialRequest(**values)


def supplier_quote(**kwargs):
    values = dict(
        quote_id="quote_1",
        workspace_id="ws_1",
        rfq_id="rfq_1",
        supplier_id="supplier_1",
        version=2,
        lines=(
            SupplierQuoteLine("line_1", Decimal("3"), Money(333, "KRW")),
            SupplierQuoteLine("line_2", Decimal("2"), Money(500, "KRW")),
        ),
        status=SupplierQuoteStatus.RECEIVED,
        received_at=NOW,
    )
    values.update(kwargs)
    return SupplierQuote(**values)


class CustomerQuoteTests(unittest.TestCase):
    def test_deterministic_markup_uses_ceil_minor_unit_rounding(self):
        draft = build_customer_quote_draft(
            customer_quote_id="customer_quote_1",
            request=commercial_request(),
            supplier_quote=supplier_quote(),
            policy=CustomerQuotePricingPolicy("pricing_1", 1000),
        )
        first = draft.lines[0]
        self.assertEqual(first.cost_unit_price.amount_minor, 333)
        self.assertEqual(first.sale_unit_price.amount_minor, 367)
        self.assertEqual(first.cost_total.amount_minor, 999)
        self.assertEqual(first.sale_total.amount_minor, 1101)
        self.assertEqual(first.margin_total.amount_minor, 102)
        self.assertTrue(draft.approval_required)
        self.assertEqual(draft.safe_dict()["rounding_rule"], "ceil_to_minor_unit_after_markup")

    def test_zero_markup_preserves_cost(self):
        draft = build_customer_quote_draft(
            customer_quote_id="cq",
            request=commercial_request(),
            supplier_quote=supplier_quote(),
            policy=CustomerQuotePricingPolicy("pricing_zero", 0),
        )
        self.assertEqual(draft.cost_total, draft.sale_total)
        self.assertEqual(draft.gross_margin_bps, 0)

    def test_cross_workspace_line_set_quantity_and_rejected_quote_fail_closed(self):
        with self.assertRaises(ContractError):
            build_customer_quote_draft(
                customer_quote_id="cq",
                request=commercial_request(),
                supplier_quote=supplier_quote(workspace_id="ws_2"),
                policy=CustomerQuotePricingPolicy("p", 1000),
            )
        with self.assertRaises(ContractError):
            build_customer_quote_draft(
                customer_quote_id="cq",
                request=commercial_request(),
                supplier_quote=supplier_quote(lines=(SupplierQuoteLine("line_1", 3, Money(333)),)),
                policy=CustomerQuotePricingPolicy("p", 1000),
            )
        with self.assertRaises(ContractError):
            build_customer_quote_draft(
                customer_quote_id="cq",
                request=commercial_request(),
                supplier_quote=supplier_quote(lines=(SupplierQuoteLine("line_1", 4, Money(333)), SupplierQuoteLine("line_2", 2, Money(500)))),
                policy=CustomerQuotePricingPolicy("p", 1000),
            )
        with self.assertRaises(ContractError):
            build_customer_quote_draft(
                customer_quote_id="cq",
                request=commercial_request(),
                supplier_quote=supplier_quote(status=SupplierQuoteStatus.REJECTED),
                policy=CustomerQuotePricingPolicy("p", 1000),
            )

    def test_negative_supplier_cost_is_rejected(self):
        quote = supplier_quote(lines=(
            SupplierQuoteLine("line_1", 3, Money(-1)),
            SupplierQuoteLine("line_2", 2, Money(500)),
        ))
        with self.assertRaises(ContractError):
            build_customer_quote_draft(
                customer_quote_id="cq",
                request=commercial_request(),
                supplier_quote=quote,
                policy=CustomerQuotePricingPolicy("p", 1000),
            )

    def test_pricing_policy_is_integer_basis_points_and_bounded(self):
        with self.assertRaises(ContractError):
            CustomerQuotePricingPolicy("p", 10.5)  # type: ignore[arg-type]
        with self.assertRaises(ContractError):
            CustomerQuotePricingPolicy("p", 50_001)
        policy = CustomerQuotePricingPolicy("p", 50_000)
        self.assertEqual(policy.markup_bps, 50_000)

    def test_pricing_fingerprint_changes_with_policy_cost_and_source_version(self):
        base = build_customer_quote_draft(
            customer_quote_id="cq",
            request=commercial_request(),
            supplier_quote=supplier_quote(),
            policy=CustomerQuotePricingPolicy("p1", 1000),
        )
        changed_policy = build_customer_quote_draft(
            customer_quote_id="cq",
            request=commercial_request(),
            supplier_quote=supplier_quote(),
            policy=CustomerQuotePricingPolicy("p2", 1100),
        )
        changed_cost = build_customer_quote_draft(
            customer_quote_id="cq",
            request=commercial_request(),
            supplier_quote=supplier_quote(lines=(SupplierQuoteLine("line_1", 3, Money(334)), SupplierQuoteLine("line_2", 2, Money(500)))),
            policy=CustomerQuotePricingPolicy("p1", 1000),
        )
        changed_version = build_customer_quote_draft(
            customer_quote_id="cq",
            request=commercial_request(version=4),
            supplier_quote=supplier_quote(),
            policy=CustomerQuotePricingPolicy("p1", 1000),
        )
        self.assertNotEqual(base.pricing_fingerprint, changed_policy.pricing_fingerprint)
        self.assertNotEqual(base.pricing_fingerprint, changed_cost.pricing_fingerprint)
        self.assertNotEqual(base.pricing_fingerprint, changed_version.pricing_fingerprint)

    def test_customer_quote_is_draft_only_no_hidden_model_or_fx_or_auto_send(self):
        draft = build_customer_quote_draft(
            customer_quote_id="cq",
            request=commercial_request(),
            supplier_quote=supplier_quote(),
            policy=CustomerQuotePricingPolicy("p", 1000),
        )
        rendered = draft.safe_dict()
        self.assertTrue(rendered["approval_required"])
        self.assertFalse(rendered["auto_send"])
        self.assertFalse(rendered["hidden_model_pricing"])
        self.assertFalse(AUTO_CUSTOMER_QUOTE_SEND_SUPPORTED)
        self.assertFalse(MODEL_DRIVEN_HIDDEN_PRICING_SUPPORTED)
        self.assertFalse(FX_CONVERSION_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
