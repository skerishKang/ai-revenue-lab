from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import Money
from kagent.ops_supplier_history import (
    AUTOMATIC_SUPPLIER_SELECTION_SUPPORTED,
    OPAQUE_SUPPLIER_COMPOSITE_SCORE_SUPPORTED,
    SupplierDeliveryObservation,
    SupplierPerformanceLedger,
    SupplierPriceObservation,
    SupplierResponseObservation,
)


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class SupplierHistoryTests(unittest.TestCase):
    def test_response_history_uses_exact_duration_and_sample_count(self):
        ledger = SupplierPerformanceLedger()
        ledger.add_response(
            SupplierResponseObservation(
                observation_id="resp_1",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                rfq_id="rfq_1",
                sent_at=NOW,
                received_at=NOW + timedelta(minutes=30),
                evidence_ref="evidence:resp_1",
            )
        )
        ledger.add_response(
            SupplierResponseObservation(
                observation_id="resp_2",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                rfq_id="rfq_2",
                sent_at=NOW,
                received_at=NOW + timedelta(minutes=90),
                evidence_ref="evidence:resp_2",
            )
        )
        summary = ledger.summarize(workspace_id="ws_1", supplier_id="supplier_1")
        self.assertEqual(summary.response_sample_count, 2)
        self.assertEqual(summary.average_response_minutes, Decimal("60"))
        self.assertEqual(summary.evidence_refs[:2], ("evidence:resp_1", "evidence:resp_2"))

    def test_response_received_before_sent_and_unbounded_interval_fail_closed(self):
        with self.assertRaises(ContractError):
            SupplierResponseObservation(
                observation_id="resp_bad",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                rfq_id="rfq_1",
                sent_at=NOW,
                received_at=NOW - timedelta(seconds=1),
                evidence_ref="evidence:bad",
            )
        with self.assertRaises(ContractError):
            SupplierResponseObservation(
                observation_id="resp_long",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                rfq_id="rfq_1",
                sent_at=NOW,
                received_at=NOW + timedelta(days=366),
                evidence_ref="evidence:long",
            )

    def test_delivery_history_exposes_on_time_rate_and_days_late(self):
        ledger = SupplierPerformanceLedger()
        ledger.add_delivery(
            SupplierDeliveryObservation(
                observation_id="delivery_1",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                po_id="po_1",
                promised_date=date(2026, 9, 10),
                actual_delivery_date=date(2026, 9, 9),
                evidence_ref="evidence:delivery_1",
            )
        )
        ledger.add_delivery(
            SupplierDeliveryObservation(
                observation_id="delivery_2",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                po_id="po_2",
                promised_date=date(2026, 9, 10),
                actual_delivery_date=date(2026, 9, 14),
                evidence_ref="evidence:delivery_2",
            )
        )
        summary = ledger.summarize(workspace_id="ws_1", supplier_id="supplier_1")
        self.assertEqual(summary.delivery_sample_count, 2)
        self.assertEqual(summary.on_time_delivery_count, 1)
        self.assertEqual(summary.on_time_rate_percent, Decimal("50"))
        self.assertEqual(summary.average_days_late, Decimal("2"))

    def test_price_history_is_separated_by_item_and_currency(self):
        ledger = SupplierPerformanceLedger()
        ledger.add_price(
            SupplierPriceObservation(
                observation_id="price_krw_1",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                item_key="item_motor",
                quote_id="quote_1",
                captured_at=NOW,
                unit_price=Money(1000, "KRW"),
                evidence_ref="evidence:price_krw_1",
            )
        )
        ledger.add_price(
            SupplierPriceObservation(
                observation_id="price_krw_2",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                item_key="item_motor",
                quote_id="quote_2",
                captured_at=NOW + timedelta(days=1),
                unit_price=Money(900, "KRW"),
                evidence_ref="evidence:price_krw_2",
            )
        )
        ledger.add_price(
            SupplierPriceObservation(
                observation_id="price_usd_1",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                item_key="item_motor",
                quote_id="quote_3",
                captured_at=NOW + timedelta(days=2),
                unit_price=Money(8, "USD"),
                evidence_ref="evidence:price_usd_1",
            )
        )
        summary = ledger.summarize(workspace_id="ws_1", supplier_id="supplier_1")
        self.assertEqual(len(summary.price_series), 2)
        krw = next(item for item in summary.price_series if item.currency == "KRW")
        usd = next(item for item in summary.price_series if item.currency == "USD")
        self.assertEqual(krw.sample_count, 2)
        self.assertEqual(krw.minimum_unit_price_minor, 900)
        self.assertEqual(krw.maximum_unit_price_minor, 1000)
        self.assertEqual(krw.latest_unit_price_minor, 900)
        self.assertEqual(usd.sample_count, 1)
        self.assertEqual(usd.latest_unit_price_minor, 8)

    def test_negative_supplier_unit_price_is_rejected_even_if_generic_money_allows_it(self):
        with self.assertRaisesRegex(ContractError, "negative"):
            SupplierPriceObservation(
                observation_id="price_negative",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                item_key="item_motor",
                quote_id="quote_negative",
                captured_at=NOW,
                unit_price=Money(-1, "KRW"),
                evidence_ref="evidence:price_negative",
            )

    def test_unknown_history_remains_unknown_instead_of_inventing_score(self):
        summary = SupplierPerformanceLedger().summarize(
            workspace_id="ws_empty",
            supplier_id="supplier_empty",
        )
        self.assertEqual(summary.response_sample_count, 0)
        self.assertIsNone(summary.average_response_minutes)
        self.assertEqual(summary.delivery_sample_count, 0)
        self.assertIsNone(summary.on_time_rate_percent)
        self.assertIsNone(summary.average_days_late)
        self.assertEqual(summary.price_series, ())
        rendered = summary.safe_dict()
        self.assertIsNone(rendered["opaque_composite_score"])
        self.assertFalse(rendered["automatic_supplier_selection"])

    def test_workspace_and_supplier_scope_do_not_mix(self):
        ledger = SupplierPerformanceLedger()
        ledger.add_response(
            SupplierResponseObservation(
                observation_id="resp_ws1",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                rfq_id="rfq_1",
                sent_at=NOW,
                received_at=NOW + timedelta(minutes=10),
                evidence_ref="evidence:ws1",
            )
        )
        ledger.add_response(
            SupplierResponseObservation(
                observation_id="resp_ws2",
                workspace_id="ws_2",
                supplier_id="supplier_1",
                rfq_id="rfq_2",
                sent_at=NOW,
                received_at=NOW + timedelta(minutes=100),
                evidence_ref="evidence:ws2",
            )
        )
        summary = ledger.summarize(workspace_id="ws_1", supplier_id="supplier_1")
        self.assertEqual(summary.response_sample_count, 1)
        self.assertEqual(summary.average_response_minutes, Decimal("10"))
        self.assertNotIn("evidence:ws2", summary.evidence_refs)

    def test_observation_ids_are_globally_unique_across_history_kinds(self):
        ledger = SupplierPerformanceLedger()
        ledger.add_response(
            SupplierResponseObservation(
                observation_id="same_id",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                rfq_id="rfq_1",
                sent_at=NOW,
                received_at=NOW,
                evidence_ref="evidence:resp",
            )
        )
        with self.assertRaises(ContractError):
            ledger.add_delivery(
                SupplierDeliveryObservation(
                    observation_id="same_id",
                    workspace_id="ws_1",
                    supplier_id="supplier_1",
                    po_id="po_1",
                    promised_date=date(2026, 9, 10),
                    actual_delivery_date=date(2026, 9, 10),
                    evidence_ref="evidence:delivery",
                )
            )

    def test_credential_like_evidence_reference_is_rejected(self):
        credential_like = "token" + "=" + "fixturevalue"
        with self.assertRaises(ContractError):
            SupplierResponseObservation(
                observation_id="resp_secret",
                workspace_id="ws_1",
                supplier_id="supplier_1",
                rfq_id="rfq_1",
                sent_at=NOW,
                received_at=NOW,
                evidence_ref=credential_like,
            )

    def test_no_opaque_score_or_automatic_supplier_selection_authority(self):
        self.assertFalse(OPAQUE_SUPPLIER_COMPOSITE_SCORE_SUPPORTED)
        self.assertFalse(AUTOMATIC_SUPPLIER_SELECTION_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
