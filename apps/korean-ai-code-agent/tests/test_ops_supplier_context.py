from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_comparison import ComparisonMode, SupplierComparisonEngine
from kagent.ops_contracts import Money, SupplierQuote, SupplierQuoteLine, SupplierQuoteStatus
from kagent.ops_supplier_context import (
    SUPPLIER_HISTORY_AUTHORIZES_SELECTION,
    SUPPLIER_HISTORY_CHANGES_COMPARISON_SCORE,
    SupplierHistoryContextProjector,
)
from kagent.ops_supplier_history import (
    SupplierDeliveryObservation,
    SupplierPerformanceLedger,
    SupplierResponseObservation,
)


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def quote(quote_id: str, supplier_id: str, total_minor: int) -> SupplierQuote:
    return SupplierQuote(
        quote_id=quote_id,
        workspace_id="ws_1",
        rfq_id=f"rfq_{supplier_id}",
        supplier_id=supplier_id,
        version=1,
        lines=(SupplierQuoteLine("line_1", 1, Money(total_minor)),),
        status=SupplierQuoteStatus.RECEIVED,
        received_at=NOW,
        promised_delivery_date=date(2026, 9, 10),
    )


class SupplierHistoryContextTests(unittest.TestCase):
    def analysis(self):
        return SupplierComparisonEngine().evaluate(
            (
                quote("quote_a", "supplier_a", 100000),
                quote("quote_b", "supplier_b", 90000),
            ),
            mode=ComparisonMode.LOWEST_PRICE,
        )

    def history(self, supplier_id="supplier_a", *, workspace_id="ws_1"):
        ledger = SupplierPerformanceLedger()
        ledger.add_response(
            SupplierResponseObservation(
                observation_id=f"resp_{supplier_id}",
                workspace_id=workspace_id,
                supplier_id=supplier_id,
                rfq_id=f"rfq_{supplier_id}",
                sent_at=NOW,
                received_at=NOW + timedelta(minutes=20),
                evidence_ref=f"evidence:resp:{supplier_id}",
            )
        )
        ledger.add_delivery(
            SupplierDeliveryObservation(
                observation_id=f"delivery_{supplier_id}",
                workspace_id=workspace_id,
                supplier_id=supplier_id,
                po_id=f"po_{supplier_id}",
                promised_date=date(2026, 9, 10),
                actual_delivery_date=date(2026, 9, 11),
                evidence_ref=f"evidence:delivery:{supplier_id}",
            )
        )
        return ledger.summarize(workspace_id=workspace_id, supplier_id=supplier_id)

    def test_history_is_attached_without_changing_existing_winner_or_scores(self):
        analysis = self.analysis()
        before = analysis.safe_dict()
        projection = SupplierHistoryContextProjector().project(
            analysis,
            workspace_id="ws_1",
            histories=(self.history("supplier_a"),),
        )
        self.assertEqual(projection.analysis.safe_dict(), before)
        self.assertEqual(projection.analysis.recommended_supplier_id, "supplier_b")
        self.assertFalse(projection.history_influenced_recommendation)
        self.assertEqual(
            [item.supplier_id for item in projection.history_contexts],
            [item.supplier_id for item in analysis.scores],
        )

    def test_missing_supplier_history_is_explicit_unknown_context(self):
        projection = SupplierHistoryContextProjector().project(
            self.analysis(),
            workspace_id="ws_1",
            histories=(self.history("supplier_a"),),
        )
        missing = next(item for item in projection.history_contexts if item.supplier_id == "supplier_b")
        self.assertFalse(missing.history_available)
        self.assertEqual(missing.response_sample_count, 0)
        self.assertIsNone(missing.average_response_minutes)
        self.assertIsNone(missing.on_time_rate_percent)
        self.assertEqual(missing.evidence_refs, ())

    def test_available_history_exposes_samples_not_opaque_score(self):
        projection = SupplierHistoryContextProjector().project(
            self.analysis(),
            workspace_id="ws_1",
            histories=(self.history("supplier_a"),),
        )
        context = next(item for item in projection.history_contexts if item.supplier_id == "supplier_a")
        self.assertTrue(context.history_available)
        self.assertEqual(context.response_sample_count, 1)
        self.assertEqual(context.average_response_minutes, "20")
        self.assertEqual(context.delivery_sample_count, 1)
        self.assertEqual(context.on_time_rate_percent, "0")
        self.assertEqual(context.average_days_late, "1")
        rendered = projection.safe_dict()
        self.assertFalse(rendered["history_influenced_recommendation"])
        self.assertEqual(rendered["recommended_supplier_id_unchanged"], "supplier_b")

    def test_cross_workspace_history_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "another workspace"):
            SupplierHistoryContextProjector().project(
                self.analysis(),
                workspace_id="ws_1",
                histories=(self.history("supplier_a", workspace_id="ws_2"),),
            )

    def test_unrelated_supplier_history_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "unrelated"):
            SupplierHistoryContextProjector().project(
                self.analysis(),
                workspace_id="ws_1",
                histories=(self.history("supplier_other"),),
            )

    def test_duplicate_history_summary_is_rejected(self):
        history = self.history("supplier_a")
        with self.assertRaisesRegex(ContractError, "duplicate"):
            SupplierHistoryContextProjector().project(
                self.analysis(),
                workspace_id="ws_1",
                histories=(history, history),
            )

    def test_history_does_not_authorize_selection(self):
        self.assertFalse(SUPPLIER_HISTORY_CHANGES_COMPARISON_SCORE)
        self.assertFalse(SUPPLIER_HISTORY_AUTHORIZES_SELECTION)


if __name__ == "__main__":
    unittest.main()
