from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import Money
from kagent.ops_order_economics import SalesOrderReceivableHandoff
from kagent.ops_receivables import (
    ACCOUNTING_WRITE_FROM_RECEIVABLE_SUPPORTED,
    AUTO_RECEIVABLE_REMINDER_SEND_SUPPORTED,
    MESSAGE_INFERRED_PAYMENT_SUPPORTED,
    PAYMENT_COLLECTION_SUPPORTED,
    ReceivableStatus,
    TrustedPaymentObservation,
    build_receivable_reminder,
    project_receivable,
)


NOW = datetime(2026, 9, 3, 7, 0, tzinfo=timezone.utc)


def handoff():
    return SalesOrderReceivableHandoff(
        handoff_id="receivable_1",
        workspace_id="ws_1",
        sales_order_id="sales_order_1",
        customer_id="customer_1",
        customer_quote_id="quote_1",
        customer_quote_version=1,
        payment_terms_ref="terms_30",
        amount=Money(10000, "KRW"),
        expected_payment_date=date(2026, 9, 10),
    )


def payment(amount, *, observation_id="payment_1", workspace_id="ws_1", currency="KRW"):
    return TrustedPaymentObservation(
        observation_id=observation_id,
        workspace_id=workspace_id,
        sales_order_id="sales_order_1",
        handoff_id="receivable_1",
        amount_paid=Money(amount, currency),
        observed_at=NOW,
        authority_ref="trusted:finance-connector",
        evidence_ref="evidence:payment-1",
    )


class ReceivableTests(unittest.TestCase):
    def test_open_due_soon_overdue_and_paid_are_deterministic(self):
        h = handoff()
        self.assertEqual(project_receivable(handoff=h, as_of=date(2026, 9, 1)).status, ReceivableStatus.OPEN)
        self.assertEqual(project_receivable(handoff=h, as_of=date(2026, 9, 8)).status, ReceivableStatus.DUE_SOON)
        overdue = project_receivable(handoff=h, as_of=date(2026, 9, 13))
        self.assertEqual(overdue.status, ReceivableStatus.OVERDUE)
        self.assertEqual(overdue.days_overdue, 3)
        self.assertEqual(project_receivable(handoff=h, as_of=date(2026, 9, 13), payments=(payment(10000),)).status, ReceivableStatus.PAID)

    def test_partial_payment_keeps_exact_remaining_amount(self):
        projection = project_receivable(handoff=handoff(), as_of=date(2026, 9, 13), payments=(payment(2500),))
        self.assertEqual(projection.status, ReceivableStatus.OVERDUE)
        self.assertEqual(projection.paid_amount, Money(2500, "KRW"))
        self.assertEqual(projection.remaining_amount, Money(7500, "KRW"))

    def test_cross_workspace_currency_duplicate_and_overpayment_fail_closed(self):
        h = handoff()
        with self.assertRaises(ContractError):
            project_receivable(handoff=h, as_of=date(2026, 9, 13), payments=(payment(1, workspace_id="ws_other"),))
        with self.assertRaises(ContractError):
            project_receivable(handoff=h, as_of=date(2026, 9, 13), payments=(payment(1, currency="USD"),))
        same = payment(1000)
        with self.assertRaises(ContractError):
            project_receivable(handoff=h, as_of=date(2026, 9, 13), payments=(same, same))
        with self.assertRaises(ContractError):
            project_receivable(handoff=h, as_of=date(2026, 9, 13), payments=(payment(10001),))

    def test_reminder_is_draft_only_for_due_or_overdue_amount(self):
        h = handoff()
        projection = project_receivable(handoff=h, as_of=date(2026, 9, 13), payments=(payment(2500),))
        reminder = build_receivable_reminder(handoff=h, projection=projection)
        self.assertEqual(reminder.remaining_amount, Money(7500, "KRW"))
        self.assertTrue(reminder.approval_required)
        self.assertFalse(reminder.safe_dict()["auto_send"])
        with self.assertRaises(ContractError):
            build_receivable_reminder(handoff=h, projection=project_receivable(handoff=h, as_of=date(2026, 9, 1)))

    def test_no_message_inference_auto_send_collection_or_accounting_write(self):
        self.assertFalse(MESSAGE_INFERRED_PAYMENT_SUPPORTED)
        self.assertFalse(AUTO_RECEIVABLE_REMINDER_SEND_SUPPORTED)
        self.assertFalse(PAYMENT_COLLECTION_SUPPORTED)
        self.assertFalse(ACCOUNTING_WRITE_FROM_RECEIVABLE_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
