from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_supplier_reminders import (
    AUTO_SUPPLIER_REMINDER_SEND_SUPPORTED,
    ReminderProjectionKind,
    RfqTrackingStatus,
    SupplierReminderPolicy,
    SupplierRfqReminderProjector,
    SupplierRfqTrackingSnapshot,
)


SENT = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def snapshot(**kwargs):
    values = dict(
        workspace_id="ws_1",
        rfq_id="rfq_1",
        rfq_version=2,
        supplier_id="supplier_1",
        status=RfqTrackingStatus.SENT,
        sent_at=SENT,
    )
    values.update(kwargs)
    return SupplierRfqTrackingSnapshot(**values)


class SupplierReminderTests(unittest.TestCase):
    def setUp(self):
        self.policy = SupplierReminderPolicy(
            first_delay_minutes=60,
            escalation_delay_minutes=180,
            minimum_spacing_minutes=60,
            max_reminders=2,
        )
        self.projector = SupplierRfqReminderProjector(self.policy)

    def test_not_due_before_first_delay(self):
        projected = self.projector.project(snapshot(), as_of=SENT + timedelta(minutes=59))
        self.assertEqual(projected.kind, ReminderProjectionKind.NOT_DUE)
        self.assertFalse(projected.requires_approval)

    def test_due_at_first_delay_and_draft_requires_approval(self):
        projected = self.projector.project(snapshot(), as_of=SENT + timedelta(minutes=60))
        self.assertEqual(projected.kind, ReminderProjectionKind.DUE)
        self.assertTrue(projected.requires_approval)
        draft = self.projector.draft(projected)
        self.assertTrue(draft.requires_approval)
        self.assertEqual(draft.rfq_version, 2)
        self.assertEqual(draft.supplier_id, "supplier_1")

    def test_response_or_closed_cancelled_status_resolves(self):
        responded = self.projector.project(snapshot(response_at=SENT + timedelta(minutes=30)), as_of=SENT + timedelta(hours=5))
        self.assertEqual(responded.kind, ReminderProjectionKind.RESOLVED)
        for status in (RfqTrackingStatus.CLOSED, RfqTrackingStatus.CANCELLED):
            with self.subTest(status=status):
                resolved = self.projector.project(snapshot(status=status), as_of=SENT + timedelta(hours=5))
                self.assertEqual(resolved.kind, ReminderProjectionKind.RESOLVED)

    def test_minimum_spacing_rate_limits_repeated_reminder(self):
        snap = snapshot(reminder_count=1, last_reminder_at=SENT + timedelta(minutes=90))
        early = self.projector.project(snap, as_of=SENT + timedelta(minutes=149))
        self.assertEqual(early.kind, ReminderProjectionKind.NOT_DUE)
        due = self.projector.project(snap, as_of=SENT + timedelta(minutes=150))
        self.assertIn(due.kind, {ReminderProjectionKind.DUE, ReminderProjectionKind.ESCALATE})

    def test_escalation_is_deterministic(self):
        projected = self.projector.project(snapshot(), as_of=SENT + timedelta(minutes=180))
        self.assertEqual(projected.kind, ReminderProjectionKind.ESCALATE)

    def test_max_reminders_stops_more_drafts(self):
        projected = self.projector.project(
            snapshot(reminder_count=2, last_reminder_at=SENT + timedelta(minutes=180)),
            as_of=SENT + timedelta(hours=10),
        )
        self.assertEqual(projected.kind, ReminderProjectionKind.MAXED_OUT)
        with self.assertRaises(ContractError):
            self.projector.draft(projected)

    def test_invalid_history_and_time_order_fail_closed(self):
        with self.assertRaises(ContractError):
            snapshot(reminder_count=1)
        with self.assertRaises(ContractError):
            snapshot(last_reminder_at=SENT)
        with self.assertRaises(ContractError):
            snapshot(response_at=SENT - timedelta(seconds=1))
        with self.assertRaises(ContractError):
            self.projector.project(snapshot(), as_of=SENT - timedelta(seconds=1))

    def test_policy_requires_escalation_after_first_due(self):
        with self.assertRaises(ContractError):
            SupplierReminderPolicy(first_delay_minutes=120, escalation_delay_minutes=60)

    def test_auto_send_is_explicitly_unsupported(self):
        self.assertFalse(AUTO_SUPPLIER_REMINDER_SEND_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
