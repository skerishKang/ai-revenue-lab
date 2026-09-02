from __future__ import annotations

from datetime import date
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import AccountingHandoff, Money
from kagent.ops_finance import (
    CashFlowEntry,
    CashFlowEntryKind,
    CashFlowProjectionEngine,
)


class CashFlowProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = CashFlowProjectionEngine()

    def test_projection_detects_first_cash_shortage_and_closing_balance(self):
        entries = (
            CashFlowEntry(
                entry_id="pay_1",
                workspace_id="ws_1",
                kind=CashFlowEntryKind.PAYABLE,
                amount=Money(800000),
                due_date=date(2026, 9, 10),
                source_kind="po",
                source_id="po_1",
                source_version=1,
            ),
            CashFlowEntry(
                entry_id="recv_1",
                workspace_id="ws_1",
                kind=CashFlowEntryKind.RECEIVABLE,
                amount=Money(500000),
                due_date=date(2026, 9, 15),
                source_kind="invoice",
                source_id="inv_1",
                source_version=1,
            ),
        )
        projection = self.engine.project(
            workspace_id="ws_1",
            opening_balance=Money(600000),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            entries=entries,
        )
        self.assertEqual(projection.first_shortage_date, date(2026, 9, 10))
        self.assertEqual(projection.minimum_balance, Money(-200000))
        self.assertEqual(projection.closing_balance, Money(300000))
        self.assertTrue(projection.has_projected_shortage)
        self.assertEqual(len(projection.timeline), 2)
        rendered = projection.safe_dict()
        self.assertTrue(rendered["advisory_only"])
        self.assertFalse(rendered["payment_execution"])

    def test_recommendation_surfaces_gap_and_unconfirmed_data(self):
        entries = (
            CashFlowEntry(
                entry_id="pay_unconfirmed",
                workspace_id="ws_1",
                kind=CashFlowEntryKind.PAYABLE,
                amount=Money(700000),
                due_date=date(2026, 9, 5),
                source_kind="planned_po",
                source_id="po_plan",
                source_version=1,
                confirmed=False,
            ),
        )
        projection = self.engine.project(
            workspace_id="ws_1",
            opening_balance=Money(500000),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            entries=entries,
        )
        codes = [item.code for item in self.engine.recommend(projection)]
        self.assertEqual(codes, ["PROJECTED_GAP", "UNCONFIRMED_DATA"])

    def test_no_gap_is_reported_when_balance_stays_nonnegative(self):
        projection = self.engine.project(
            workspace_id="ws_1",
            opening_balance=Money(1000000),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            entries=(
                CashFlowEntry(
                    entry_id="pay_1",
                    workspace_id="ws_1",
                    kind=CashFlowEntryKind.PAYABLE,
                    amount=Money(100000),
                    due_date=date(2026, 9, 5),
                    source_kind="po",
                    source_id="po_1",
                    source_version=1,
                ),
            ),
        )
        recommendations = self.engine.recommend(projection)
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0].code, "NO_GAP")
        self.assertFalse(projection.has_projected_shortage)

    def test_entries_outside_window_do_not_change_projection(self):
        projection = self.engine.project(
            workspace_id="ws_1",
            opening_balance=Money(1000),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            entries=(
                CashFlowEntry(
                    entry_id="october",
                    workspace_id="ws_1",
                    kind=CashFlowEntryKind.PAYABLE,
                    amount=Money(9999),
                    due_date=date(2026, 10, 1),
                    source_kind="po",
                    source_id="po_2",
                    source_version=1,
                ),
            ),
        )
        self.assertEqual(projection.closing_balance, Money(1000))
        self.assertEqual(projection.included_entry_ids, ())

    def test_cross_workspace_and_cross_currency_entries_fail_closed(self):
        with self.assertRaises(ContractError):
            self.engine.project(
                workspace_id="ws_1",
                opening_balance=Money(1000, "KRW"),
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 30),
                entries=(
                    CashFlowEntry(
                        entry_id="other",
                        workspace_id="ws_2",
                        kind=CashFlowEntryKind.PAYABLE,
                        amount=Money(100, "KRW"),
                        due_date=date(2026, 9, 2),
                        source_kind="po",
                        source_id="po_other",
                        source_version=1,
                    ),
                ),
            )
        with self.assertRaises(ContractError):
            self.engine.project(
                workspace_id="ws_1",
                opening_balance=Money(1000, "KRW"),
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 30),
                entries=(
                    CashFlowEntry(
                        entry_id="usd",
                        workspace_id="ws_1",
                        kind=CashFlowEntryKind.PAYABLE,
                        amount=Money(100, "USD"),
                        due_date=date(2026, 9, 2),
                        source_kind="po",
                        source_id="po_usd",
                        source_version=1,
                    ),
                ),
            )

    def test_duplicate_entry_ids_fail_closed(self):
        entry = CashFlowEntry(
            entry_id="dup",
            workspace_id="ws_1",
            kind=CashFlowEntryKind.PAYABLE,
            amount=Money(100),
            due_date=date(2026, 9, 2),
            source_kind="po",
            source_id="po_1",
            source_version=1,
        )
        with self.assertRaises(ContractError):
            self.engine.project(
                workspace_id="ws_1",
                opening_balance=Money(1000),
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 30),
                entries=(entry, entry),
            )

    def test_accounting_handoff_can_project_payable_without_payment_authority(self):
        handoff = AccountingHandoff(
            handoff_id="handoff_1",
            workspace_id="ws_1",
            po_id="po_1",
            po_version=2,
            version=1,
            obligation_amount=Money(1500000),
            expected_payment_date=date(2026, 10, 31),
        )
        payable = self.engine.payable_from_accounting_handoff(handoff)
        self.assertEqual(payable.kind, CashFlowEntryKind.PAYABLE)
        self.assertEqual(payable.amount, Money(1500000))
        self.assertEqual(payable.due_date, date(2026, 10, 31))
        self.assertFalse(hasattr(payable, "execute_payment"))
        self.assertFalse(hasattr(self.engine, "execute_payment"))

    def test_handoff_without_expected_payment_date_is_not_guessed(self):
        handoff = AccountingHandoff(
            handoff_id="handoff_1",
            workspace_id="ws_1",
            po_id="po_1",
            po_version=2,
            version=1,
            obligation_amount=Money(1500000),
            expected_payment_date=None,
        )
        with self.assertRaises(ContractError):
            self.engine.payable_from_accounting_handoff(handoff)


if __name__ == "__main__":
    unittest.main()
