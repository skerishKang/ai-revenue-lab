from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_comparison import (
    ComparisonMode,
    ComparisonWeights,
    SupplierComparisonEngine,
)
from kagent.ops_contracts import (
    Money,
    PaymentTerms,
    SupplierQuote,
    SupplierQuoteLine,
    SupplierQuoteStatus,
)


NOW = datetime(2026, 9, 2, 15, 30, tzinfo=timezone.utc)


def quote(
    quote_id: str,
    supplier_id: str,
    total_minor: int,
    *,
    delivery: date | None,
    due_days: int | None,
    prepaid: bool = False,
) -> SupplierQuote:
    terms = None if due_days is None else PaymentTerms(
        f"terms_{supplier_id}",
        f"{due_days} days",
        due_days=due_days,
        prepaid=prepaid,
    )
    return SupplierQuote(
        quote_id=quote_id,
        workspace_id="ws_1",
        rfq_id=f"rfq_{supplier_id}",
        supplier_id=supplier_id,
        version=1,
        lines=(SupplierQuoteLine("line_1", 1, Money(total_minor)),),
        status=SupplierQuoteStatus.RECEIVED,
        received_at=NOW,
        promised_delivery_date=delivery,
        payment_terms=terms,
    )


class SupplierComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SupplierComparisonEngine()
        self.a = quote(
            "quote_a",
            "supplier_a",
            100000,
            delivery=date(2026, 9, 12),
            due_days=30,
        )
        self.b = quote(
            "quote_b",
            "supplier_b",
            90000,
            delivery=date(2026, 9, 20),
            due_days=0,
            prepaid=True,
        )
        self.c = quote(
            "quote_c",
            "supplier_c",
            110000,
            delivery=date(2026, 9, 10),
            due_days=60,
        )

    def test_lowest_price_mode_selects_actual_lowest_quote(self):
        result = self.engine.evaluate((self.a, self.b, self.c), mode=ComparisonMode.LOWEST_PRICE)
        self.assertEqual(result.recommended_supplier_id, "supplier_b")
        self.assertEqual(result.scores[0].price_rank, 1)
        self.assertTrue(result.safe_dict()["advisory_only"])

    def test_fastest_delivery_mode_selects_earliest_known_date(self):
        result = self.engine.evaluate((self.a, self.b, self.c), mode=ComparisonMode.FASTEST_DELIVERY)
        self.assertEqual(result.recommended_supplier_id, "supplier_c")
        self.assertEqual(result.scores[0].delivery_rank, 1)

    def test_cashflow_mode_prefers_longer_nonprepaid_terms(self):
        result = self.engine.evaluate((self.a, self.b, self.c), mode=ComparisonMode.BEST_CASHFLOW_FIT)
        self.assertEqual(result.recommended_supplier_id, "supplier_c")
        self.assertEqual(result.scores[0].cashflow_rank, 1)

    def test_balanced_mode_is_reproducible_and_exposes_weights(self):
        first = self.engine.evaluate((self.a, self.b, self.c), mode=ComparisonMode.BALANCED)
        second = self.engine.evaluate((self.a, self.b, self.c), mode=ComparisonMode.BALANCED)
        self.assertEqual(first, second)
        self.assertEqual(first.weights, ComparisonWeights(50, 25, 25))
        self.assertEqual(first.safe_dict(), second.safe_dict())

    def test_custom_weights_must_sum_to_100(self):
        self.assertEqual(ComparisonWeights(70, 10, 20).price, 70)
        with self.assertRaises(ContractError):
            ComparisonWeights(50, 20, 20)
        with self.assertRaises(ContractError):
            ComparisonWeights(True, 0, 99)  # type: ignore[arg-type]

    def test_missing_delivery_and_terms_are_visible_and_penalized(self):
        unknown = quote(
            "quote_unknown",
            "supplier_unknown",
            80000,
            delivery=None,
            due_days=None,
        )
        delivery = self.engine.evaluate((unknown, self.a), mode=ComparisonMode.FASTEST_DELIVERY)
        self.assertEqual(delivery.recommended_supplier_id, "supplier_a")
        unknown_score = next(item for item in delivery.scores if item.supplier_id == "supplier_unknown")
        self.assertIn("promised_delivery_date", unknown_score.unknown_fields)
        self.assertIn("payment_terms", unknown_score.unknown_fields)
        self.assertIsNone(unknown_score.delivery_rank)
        self.assertIsNone(unknown_score.cashflow_rank)

    def test_cross_currency_quotes_cannot_be_compared(self):
        usd = SupplierQuote(
            quote_id="quote_usd",
            workspace_id="ws_1",
            rfq_id="rfq_usd",
            supplier_id="supplier_usd",
            version=1,
            lines=(SupplierQuoteLine("line_1", 1, Money(100, "USD")),),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=NOW,
        )
        with self.assertRaises(ContractError):
            self.engine.evaluate((self.a, usd))

    def test_duplicate_supplier_is_rejected(self):
        revised_id = SupplierQuote(
            quote_id="quote_a_other",
            workspace_id="ws_1",
            rfq_id="rfq_supplier_a",
            supplier_id="supplier_a",
            version=1,
            lines=(SupplierQuoteLine("line_1", 1, Money(95000)),),
            status=SupplierQuoteStatus.RECEIVED,
            received_at=NOW,
        )
        with self.assertRaises(ContractError):
            self.engine.evaluate((self.a, revised_id))

    def test_negotiation_target_uses_captured_competing_quote_not_invention(self):
        target = self.engine.negotiation_target_from_competing_quote(
            target_quote=self.a,
            competing_quotes=(self.b, self.c),
        )
        self.assertEqual(target.target_total, Money(90000))
        self.assertEqual(target.current_total, Money(100000))
        self.assertEqual(target.basis, "captured_competing_quote:quote_b:v1")

    def test_negotiation_target_cannot_use_same_supplier_only(self):
        with self.assertRaises(ContractError):
            self.engine.negotiation_target_from_competing_quote(
                target_quote=self.a,
                competing_quotes=(self.a,),
            )


if __name__ == "__main__":
    unittest.main()
