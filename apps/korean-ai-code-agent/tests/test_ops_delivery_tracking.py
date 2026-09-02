from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import (
    BusinessObjectKind,
    Money,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    DeliveryStatus,
)
from kagent.ops_delivery_tracking import (
    DeliveryExceptionKind,
    DeliveryExceptionProjector,
    DeliveryTrackingCoordinator,
    DeliveryTrackingSnapshot,
)
from kagent.ops_ledger import BusinessObjectEnvelope, InMemoryOpsLedger


NOW = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)


class DeliveryTrackingTests(unittest.TestCase):
    def ledger_with_po(self, *, status=PurchaseOrderStatus.ISSUED, supplier_id="supplier_1"):
        ledger = InMemoryOpsLedger()
        po = PurchaseOrder(
            po_id="po_1",
            workspace_id="ws_1",
            supplier_id=supplier_id,
            supplier_quote_id="quote_1",
            supplier_quote_version=1,
            version=1,
            lines=(PurchaseOrderLine("line_1", "모터", 2, "EA", Money(1000)),),
            status=status,
            requested_delivery_date=date(2026, 9, 10),
        )
        ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id=po.po_id,
                version=po.version,
                workspace_id=po.workspace_id,
                value=po,
            )
        )
        return ledger

    def snapshot(self, *, version=1, status=DeliveryStatus.PLANNED, promised_date=None, actual=None, observed_at=NOW, supplier_id="supplier_1"):
        return DeliveryTrackingSnapshot(
            delivery_id="delivery_1",
            workspace_id="ws_1",
            po_id="po_1",
            po_version=1,
            supplier_id=supplier_id,
            version=version,
            status=status,
            observed_at=observed_at,
            source_ref=f"evidence:delivery:{version}",
            promised_date=promised_date,
            actual_delivery_date=actual,
        )

    def test_tracking_requires_issued_purchase_order_and_matching_supplier(self):
        with self.assertRaises(ContractError):
            DeliveryTrackingCoordinator(self.ledger_with_po(status=PurchaseOrderStatus.APPROVAL_REQUIRED)).append(self.snapshot())
        with self.assertRaises(ContractError):
            DeliveryTrackingCoordinator(self.ledger_with_po()).append(self.snapshot(supplier_id="supplier_2"))

    def test_unknown_promised_date_is_explicit_not_guessed(self):
        snapshot = self.snapshot()
        projection = DeliveryExceptionProjector().project(snapshot, as_of=date(2026, 9, 2))
        self.assertEqual(projection.kind, DeliveryExceptionKind.UNKNOWN_DATE)
        self.assertIsNone(projection.promised_date)
        self.assertIsNone(projection.days_to_promised)
        self.assertTrue(projection.actionable)

    def test_confirmed_delivery_requires_promised_date(self):
        with self.assertRaises(ContractError):
            self.snapshot(status=DeliveryStatus.CONFIRMED)

    def test_due_soon_and_overdue_are_deterministic(self):
        projector = DeliveryExceptionProjector(due_soon_days=3)
        due = self.snapshot(status=DeliveryStatus.CONFIRMED, promised_date=date(2026, 9, 5))
        overdue = self.snapshot(status=DeliveryStatus.CONFIRMED, promised_date=date(2026, 9, 1))
        self.assertEqual(projector.project(due, as_of=date(2026, 9, 2)).kind, DeliveryExceptionKind.DUE_SOON)
        overdue_projection = projector.project(overdue, as_of=date(2026, 9, 2))
        self.assertEqual(overdue_projection.kind, DeliveryExceptionKind.OVERDUE)
        self.assertEqual(overdue_projection.days_to_promised, -1)

    def test_at_risk_status_wins_even_before_promised_date(self):
        snapshot = self.snapshot(status=DeliveryStatus.AT_RISK, promised_date=date(2026, 9, 20))
        projection = DeliveryExceptionProjector().project(snapshot, as_of=date(2026, 9, 2))
        self.assertEqual(projection.kind, DeliveryExceptionKind.AT_RISK)
        self.assertEqual(projection.days_to_promised, 18)

    def test_delivered_and_cancelled_are_not_actionable(self):
        delivered = self.snapshot(
            status=DeliveryStatus.DELIVERED,
            promised_date=date(2026, 9, 1),
            actual=date(2026, 9, 2),
        )
        cancelled = self.snapshot(status=DeliveryStatus.CANCELLED, promised_date=date(2026, 9, 1))
        projector = DeliveryExceptionProjector()
        self.assertFalse(projector.project(delivered, as_of=date(2026, 9, 3)).actionable)
        self.assertFalse(projector.project(cancelled, as_of=date(2026, 9, 3)).actionable)

    def test_actual_delivery_date_only_allowed_for_delivered_and_not_future(self):
        with self.assertRaises(ContractError):
            self.snapshot(status=DeliveryStatus.CONFIRMED, promised_date=date(2026, 9, 5), actual=date(2026, 9, 2))
        with self.assertRaises(ContractError):
            self.snapshot(
                status=DeliveryStatus.DELIVERED,
                promised_date=date(2026, 9, 5),
                actual=date(2026, 9, 3),
            )

    def test_versioned_transition_is_contiguous_and_identity_stable(self):
        ledger = self.ledger_with_po()
        coordinator = DeliveryTrackingCoordinator(ledger)
        coordinator.append(self.snapshot(version=1))
        coordinator.append(
            self.snapshot(
                version=2,
                status=DeliveryStatus.CONFIRMED,
                promised_date=date(2026, 9, 10),
                observed_at=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
            )
        )
        latest = coordinator.latest(workspace_id="ws_1", delivery_id="delivery_1")
        self.assertEqual(latest.version, 2)
        with self.assertRaises(ContractError):
            coordinator.append(
                DeliveryTrackingSnapshot(
                    delivery_id="delivery_1",
                    workspace_id="ws_1",
                    po_id="po_1",
                    po_version=1,
                    supplier_id="supplier_2",
                    version=3,
                    status=DeliveryStatus.AT_RISK,
                    observed_at=datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc),
                    source_ref="evidence:bad",
                )
            )

    def test_terminal_delivery_cannot_resurrect(self):
        ledger = self.ledger_with_po()
        coordinator = DeliveryTrackingCoordinator(ledger)
        coordinator.append(self.snapshot(version=1))
        coordinator.append(
            self.snapshot(
                version=2,
                status=DeliveryStatus.DELIVERED,
                promised_date=date(2026, 9, 2),
                actual=date(2026, 9, 2),
            )
        )
        with self.assertRaisesRegex(ContractError, "transition"):
            coordinator.append(
                self.snapshot(
                    version=3,
                    status=DeliveryStatus.AT_RISK,
                    promised_date=date(2026, 9, 3),
                    observed_at=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
                )
            )

    def test_followup_is_draft_only_and_requires_approval(self):
        projector = DeliveryExceptionProjector()
        projection = projector.project(self.snapshot(), as_of=date(2026, 9, 2))
        draft = projector.draft_followup(projection)
        self.assertTrue(draft.requires_approval)
        self.assertEqual(draft.supplier_id, "supplier_1")
        with self.assertRaises(ContractError):
            projector.draft_followup(
                projector.project(
                    self.snapshot(status=DeliveryStatus.CONFIRMED, promised_date=date(2026, 10, 1)),
                    as_of=date(2026, 9, 2),
                )
            )


if __name__ == "__main__":
    unittest.main()
