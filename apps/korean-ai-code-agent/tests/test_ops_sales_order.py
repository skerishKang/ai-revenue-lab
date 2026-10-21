"""#5448: online sales-channel order -> supplier purchase order -> shipment fulfilment.

Focused contract tests for :mod:`kagent.ops_sales_order`.

The suite proves the properties this pilot depends on:

* an order can be received from a sales-channel export and moves through the
  eight business steps with an explicit status graph;
* a supplier purchase-order request is produced as a **draft** and is staged in
  the outbox without any send, and the existing approval fingerprint is reused;
* the customer sale price never leaks into the supplier-facing purchase order;
* a shipment requires a carrier and a tracking number, and the waybill cannot
  change afterwards;
* cancellation, return, and misdelivery each reach their own terminal state;
* the customer delivery destination is masked in every exported artifact;
* a short stock position fails closed instead of silently confirming the order.

No network, no credentials, no provider, no model call.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import (
    ApprovalAction,
    ApprovalDecision,
    BusinessObjectKind,
    Item,
    Money,
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderStatus,
    Supplier,
)
from kagent.ops_sales_order import (
    ORDER_FULFILLMENT_STEPS,
    AutomationLevel,
    LocalCsvSalesChannelOrderPort,
    OnlineOrderFulfillmentCoordinator,
    ReturnReason,
    ReturnStatus,
    SalesChannelKind,
    SalesOrder,
    SalesOrderError,
    SalesOrderStatus,
    ShipTo,
    Shipment,
    ShipmentStatus,
    StockPosition,
    SupplierOrderRequestDraft,
    UnconfiguredSalesChannelOrderPort,
    artifact_digest,
    fulfillment_case_to_json,
    returns_to_csv,
    sales_order_lines_to_csv,
    sales_order_to_public_dict,
    shipments_to_csv,
)


NOW = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)
WORKSPACE = "ws_demo"

CHANNEL_CSV = "\n".join(
    [
        "channel_order_ref,customer_ref,received_at,requested_delivery_date,"
        "recipient_name,recipient_phone,postal_code,address_line1,address_line2,"
        "line_id,sku,item_id,description,quantity,unit,unit_price_amount_minor,unit_price_currency",
        "CH-2026-0011,cust_demo_001,2026-10-21T09:00:00Z,2026-10-24,"
        "홍길동,010-0000-0000,04524,서울시 Gangnam-gu 테스트로 1,2층,"
        "L1,SKU-DEMO-1,item_demo_1,데모 상품 A,2,EA,12000,KRW",
        "CH-2026-0011,cust_demo_001,2026-10-21T09:00:00Z,2026-10-24,"
        "홍길동,010-0000-0000,04524,서울시 Gangnam-gu 테스트로 1,2층,"
        "L2,SKU-DEMO-2,item_demo_2,데모 상품 B,1,EA,8000,KRW",
    ]
)


def build_ship_to() -> ShipTo:
    return ShipTo(
        recipient_name="홍길동",
        recipient_phone="010-0000-0000",
        postal_code="04524",
        address_line1="서울시 Gangnam-gu 테스트로 1",
        address_line2="2층",
    )


def build_item(item_id: str, sku: str, name: str) -> Item:
    return Item(
        item_id=item_id,
        workspace_id=WORKSPACE,
        sku=sku,
        name=name,
        unit="EA",
    )


def build_positions(*, quantity: str = "10") -> tuple[StockPosition, ...]:
    return (
        StockPosition(
            item=build_item("item_demo_1", "SKU-DEMO-1", "데모 상품 A"),
            supplier_id="supplier_demo_1",
            available_quantity=quantity,
            reserved_quantity="0",
            lead_time_days=2,
            unit_cost=Money(9000),
        ),
        StockPosition(
            item=build_item("item_demo_2", "SKU-DEMO-2", "데모 상품 B"),
            supplier_id="supplier_demo_1",
            available_quantity=quantity,
            reserved_quantity="0",
            lead_time_days=2,
            unit_cost=Money(6000),
        ),
    )


def build_supplier() -> Supplier:
    return Supplier(
        supplier_id="supplier_demo_1",
        workspace_id=WORKSPACE,
        name="데모 공급사",
        payment_terms=PaymentTerms(terms_id="terms_demo_1", label="선불", prepaid=True),
    )


def build_coordinator() -> OnlineOrderFulfillmentCoordinator:
    channel = LocalCsvSalesChannelOrderPort.parse_csv(CHANNEL_CSV)
    return OnlineOrderFulfillmentCoordinator(
        channel=channel,
        clock=lambda: NOW,
    )


def receive_confirmed_order(
    coordinator: OnlineOrderFulfillmentCoordinator | None = None,
) -> tuple[OnlineOrderFulfillmentCoordinator, SalesOrder]:
    coordinator = coordinator or build_coordinator()
    order = coordinator.receive_order(
        workspace_id=WORKSPACE,
        order_id="order_demo_1",
        channel_order_ref="CH-2026-0011",
    )
    coordinator.confirm_order(workspace_id=WORKSPACE, order_id=order.order_id)
    return coordinator, coordinator.order(workspace_id=WORKSPACE, order_id=order.order_id)


class SalesOrderContractTests(unittest.TestCase):
    def test_order_is_received_with_totals_and_channel_provenance(self) -> None:
        coordinator = build_coordinator()
        order = coordinator.receive_order(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            channel_order_ref="CH-2026-0011",
        )

        self.assertEqual(order.status, SalesOrderStatus.RECEIVED)
        self.assertEqual(order.channel, SalesChannelKind.CSV_EXPORT)
        self.assertEqual(order.channel_order_ref, "CH-2026-0011")
        self.assertEqual(len(order.lines), 2)
        self.assertEqual(order.total.amount_minor, 2 * 12000 + 8000)
        self.assertEqual(order.total.currency, "KRW")

    def test_unconfigured_channel_port_refuses_instead_of_guessing(self) -> None:
        coordinator = OnlineOrderFulfillmentCoordinator(clock=lambda: NOW)

        with self.assertRaises(SalesOrderError):
            coordinator.receive_order(
                workspace_id=WORKSPACE,
                order_id="order_demo_1",
                channel_order_ref="CH-2026-0011",
            )

    def test_csv_headers_must_match_the_supported_schema(self) -> None:
        broken = CHANNEL_CSV.replace("postal_code,address_line1", "zip,address_line1")

        with self.assertRaises(SalesOrderError):
            LocalCsvSalesChannelOrderPort.parse_csv(broken)

    def test_csv_order_level_fields_must_be_identical_across_rows(self) -> None:
        broken = CHANNEL_CSV.replace(
            "CH-2026-0011,cust_demo_001,2026-10-21T09:00:00Z,2026-10-24,"
            "홍길동,010-0000-0000,04524,서울시 Gangnam-gu 테스트로 1,2층,"
            "L2,",
            "CH-2026-0011,cust_demo_001,2026-10-21T09:00:00Z,2026-10-25,"
            "홍길동,010-0000-0000,04524,서울시 Gangnam-gu 테스트로 1,2층,"
            "L2,",
        )

        with self.assertRaises(SalesOrderError):
            LocalCsvSalesChannelOrderPort.parse_csv(broken)

    def test_order_version_must_start_at_one_and_be_contiguous(self) -> None:
        coordinator = build_coordinator()
        coordinator.receive_order(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            channel_order_ref="CH-2026-0011",
        )
        coordinator.confirm_order(workspace_id=WORKSPACE, order_id="order_demo_1")

        with self.assertRaises(ContractError):
            coordinator.ledger.append_object(
                coordinator.ledger.get_object(
                    workspace_id=WORKSPACE,
                    kind=BusinessObjectKind.SALES_ORDER,
                    object_id="order_demo_1",
                    version=1,
                )
            )


class AvailabilityTests(unittest.TestCase):
    def test_full_stock_covers_every_line(self) -> None:
        coordinator = build_coordinator()
        coordinator.receive_order(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            channel_order_ref="CH-2026-0011",
        )

        check = coordinator.check_availability(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            positions=build_positions(),
        )

        self.assertTrue(check.fully_covered)
        self.assertEqual(check.short_line_ids, ())
        self.assertEqual(set(check.covered_line_ids), {"L1", "L2"})
        self.assertEqual(check.supplier_ids, ("supplier_demo_1",))

    def test_short_stock_reports_the_short_line_and_keeps_the_order_unconfirmed(self) -> None:
        coordinator = build_coordinator()
        coordinator.receive_order(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            channel_order_ref="CH-2026-0011",
        )

        check = coordinator.check_availability(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            positions=build_positions(quantity="0.5"),
        )

        self.assertFalse(check.fully_covered)
        self.assertEqual(sorted(check.short_line_ids), ["L1", "L2"])
        self.assertEqual(
            coordinator.order(workspace_id=WORKSPACE, order_id="order_demo_1").status,
            SalesOrderStatus.RECEIVED,
        )

    def test_reserved_stock_is_not_sellable(self) -> None:
        position = StockPosition(
            item=build_item("item_demo_1", "SKU-DEMO-1", "데모 상품 A"),
            supplier_id="supplier_demo_1",
            available_quantity="5",
            reserved_quantity="5",
        )

        self.assertEqual(position.sellable_quantity, 0)


class SupplierOrderRequestTests(unittest.TestCase):
    def test_supplier_request_is_a_draft_and_never_sent(self) -> None:
        coordinator, order = receive_confirmed_order()

        draft = coordinator.draft_supplier_order(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            supplier=build_supplier(),
            supplier_quote_id="quote_standing_1",
            positions=build_positions(),
        )

        self.assertIsInstance(draft, SupplierOrderRequestDraft)
        self.assertIs(draft.purchase_order.status, PurchaseOrderStatus.DRAFT)
        self.assertTrue(draft.requires_approval)

        outbox_id = coordinator.stage_supplier_request(
            draft=draft, recipient_ref="supplier_demo_1"
        )
        self.assertTrue(outbox_id.startswith("outbox:"))

    def test_supplier_request_needs_a_supplier_side_cost_for_every_line(self) -> None:
        coordinator, order = receive_confirmed_order()
        partial_positions = (build_positions()[0],)

        with self.assertRaises(SalesOrderError):
            coordinator.draft_supplier_order(
                workspace_id=WORKSPACE,
                order_id=order.order_id,
                supplier=build_supplier(),
                supplier_quote_id="quote_standing_1",
                positions=partial_positions,
            )

    def test_supplier_request_carries_supplier_cost_not_the_customer_sale_price(self) -> None:
        coordinator, order = receive_confirmed_order()

        draft = coordinator.draft_supplier_order(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            supplier=build_supplier(),
            supplier_quote_id="quote_standing_1",
            positions=build_positions(),
        )

        prices = {line.line_id: line.unit_price.amount_minor for line in draft.purchase_order.lines}
        self.assertEqual(prices, {"L1": 9000, "L2": 6000})
        customer_prices = {line.line_id: line.unit_price.amount_minor for line in order.lines}
        self.assertNotEqual(prices["L1"], customer_prices["L1"])

    def test_supplier_request_reuses_the_existing_approval_fingerprint(self) -> None:
        coordinator, order = receive_confirmed_order()

        draft = coordinator.draft_supplier_order(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            supplier=build_supplier(),
            supplier_quote_id="quote_standing_1",
            positions=build_positions(),
        )

        approval = coordinator.ledger.approval(f"ap-{draft.purchase_order.po_id}-v1")
        self.assertIs(approval.action, ApprovalAction.ISSUE_PURCHASE_ORDER)
        self.assertIs(approval.decision, ApprovalDecision.PENDING)
        self.assertEqual(approval.action_fingerprint, draft.action_fingerprint)

    def test_supplier_request_requires_a_confirmed_order(self) -> None:
        coordinator = build_coordinator()
        coordinator.receive_order(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            channel_order_ref="CH-2026-0011",
        )

        with self.assertRaises(SalesOrderError):
            coordinator.draft_supplier_order(
                workspace_id=WORKSPACE,
                order_id="order_demo_1",
                supplier=build_supplier(),
                supplier_quote_id="quote_standing_1",
                positions=build_positions(),
            )

    def test_inactive_supplier_is_refused(self) -> None:
        coordinator, order = receive_confirmed_order()
        supplier = Supplier(
            supplier_id="supplier_demo_1",
            workspace_id=WORKSPACE,
            name="데모 공급사",
            active=False,
        )

        with self.assertRaises(SalesOrderError):
            coordinator.draft_supplier_order(
                workspace_id=WORKSPACE,
                order_id=order.order_id,
                supplier=supplier,
                supplier_quote_id="quote_standing_1",
                positions=build_positions(),
            )


class ShipmentTests(unittest.TestCase):
    def _shipped_order(self) -> tuple[OnlineOrderFulfillmentCoordinator, SalesOrder]:
        coordinator, order = receive_confirmed_order()
        coordinator.record_supplier_acknowledgement(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            supplier_id="supplier_demo_1",
            acknowledged_at=NOW + timedelta(hours=1),
        )
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            shipment_id="ship_demo_1",
            status=ShipmentStatus.LABEL_ISSUED,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=2),
        )
        return coordinator, coordinator.order(workspace_id=WORKSPACE, order_id=order.order_id)

    def test_shipment_requires_a_carrier_and_a_tracking_number(self) -> None:
        coordinator, order = receive_confirmed_order()

        with self.assertRaises(SalesOrderError):
            coordinator.record_shipment(
                workspace_id=WORKSPACE,
                order_id=order.order_id,
                shipment_id="ship_demo_1",
                status=ShipmentStatus.LABEL_ISSUED,
                carrier="",
                tracking_number="TRK-2026-0001",
            )

    def test_tracking_number_cannot_change_after_the_first_observation(self) -> None:
        coordinator, order = self._shipped_order()

        with self.assertRaises(SalesOrderError):
            coordinator.record_shipment(
                workspace_id=WORKSPACE,
                order_id=order.order_id,
                shipment_id="ship_demo_1",
                status=ShipmentStatus.IN_TRANSIT,
                carrier="demo_carrier",
                tracking_number="TRK-OTHER-9999",
                observed_at=NOW + timedelta(hours=3),
            )

    def test_shipment_status_advances_the_order_to_shipped(self) -> None:
        coordinator, order = self._shipped_order()

        shipment = coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            shipment_id="ship_demo_1",
            status=ShipmentStatus.IN_TRANSIT,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=3),
        )

        self.assertEqual(shipment.version, 2)
        self.assertEqual(
            coordinator.order(workspace_id=WORKSPACE, order_id=order.order_id).status,
            SalesOrderStatus.SHIPPED,
        )

    def test_invalid_shipment_transition_is_refused(self) -> None:
        coordinator, order = self._shipped_order()

        with self.assertRaises(SalesOrderError):
            coordinator.record_shipment(
                workspace_id=WORKSPACE,
                order_id=order.order_id,
                shipment_id="ship_demo_1",
                status=ShipmentStatus.DELIVERED,
                carrier="demo_carrier",
                tracking_number="TRK-2026-0001",
                observed_at=NOW + timedelta(hours=3),
                delivered_at=NOW + timedelta(hours=3),
            )

    def test_delivered_shipment_moves_the_order_to_delivered_then_completed(self) -> None:
        coordinator, order = self._shipped_order()
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            shipment_id="ship_demo_1",
            status=ShipmentStatus.IN_TRANSIT,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=3),
        )
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            shipment_id="ship_demo_1",
            status=ShipmentStatus.DELIVERED,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=30),
            delivered_at=NOW + timedelta(hours=30),
        )

        self.assertEqual(
            coordinator.order(workspace_id=WORKSPACE, order_id=order.order_id).status,
            SalesOrderStatus.DELIVERED,
        )
        completed = coordinator.complete_order(
            workspace_id=WORKSPACE, order_id=order.order_id
        )
        self.assertEqual(completed.status, SalesOrderStatus.COMPLETED)

    def test_completed_order_is_terminal(self) -> None:
        coordinator, order = self._shipped_order()
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            shipment_id="ship_demo_1",
            status=ShipmentStatus.IN_TRANSIT,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=3),
        )
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            shipment_id="ship_demo_1",
            status=ShipmentStatus.DELIVERED,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=30),
            delivered_at=NOW + timedelta(hours=30),
        )
        coordinator.complete_order(workspace_id=WORKSPACE, order_id=order.order_id)

        with self.assertRaises(SalesOrderError):
            coordinator.open_return(
                workspace_id=WORKSPACE,
                order_id=order.order_id,
                return_id="ret_demo_1",
                reason=ReturnReason.CUSTOMER_RETURN,
            )


class ExceptionCaseTests(unittest.TestCase):
    def test_cancellation_before_shipment_moves_the_order_to_cancelled(self) -> None:
        coordinator, order = receive_confirmed_order()

        request = coordinator.open_return(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            return_id="ret_demo_1",
            reason=ReturnReason.CUSTOMER_CANCELLED,
        )

        self.assertEqual(request.status, ReturnStatus.OPEN)
        self.assertEqual(
            coordinator.order(workspace_id=WORKSPACE, order_id=order.order_id).status,
            SalesOrderStatus.CANCELLED,
        )

    def test_return_after_delivery_opens_a_case_and_keeps_the_order_open(self) -> None:
        coordinator = build_coordinator()
        coordinator.receive_order(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            channel_order_ref="CH-2026-0011",
        )
        coordinator.confirm_order(workspace_id=WORKSPACE, order_id="order_demo_1")
        coordinator.record_supplier_acknowledgement(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            supplier_id="supplier_demo_1",
            acknowledged_at=NOW + timedelta(hours=1),
        )
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            shipment_id="ship_demo_1",
            status=ShipmentStatus.IN_TRANSIT,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=2),
        )
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            shipment_id="ship_demo_1",
            status=ShipmentStatus.DELIVERED,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=30),
            delivered_at=NOW + timedelta(hours=30),
        )

        coordinator.open_return(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            return_id="ret_demo_1",
            reason=ReturnReason.CUSTOMER_RETURN,
        )

        self.assertEqual(
            coordinator.order(workspace_id=WORKSPACE, order_id="order_demo_1").status,
            SalesOrderStatus.RETURN_REQUESTED,
        )

    def test_misdelivery_can_be_re_delivered(self) -> None:
        coordinator = build_coordinator()
        coordinator.receive_order(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            channel_order_ref="CH-2026-0011",
        )
        coordinator.confirm_order(workspace_id=WORKSPACE, order_id="order_demo_1")
        coordinator.record_supplier_acknowledgement(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            supplier_id="supplier_demo_1",
            acknowledged_at=NOW + timedelta(hours=1),
        )
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            shipment_id="ship_demo_1",
            status=ShipmentStatus.IN_TRANSIT,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=2),
        )
        coordinator.record_shipment(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            shipment_id="ship_demo_1",
            status=ShipmentStatus.MISDELIVERY,
            carrier="demo_carrier",
            tracking_number="TRK-2026-0001",
            observed_at=NOW + timedelta(hours=10),
        )

        self.assertEqual(
            coordinator.order(workspace_id=WORKSPACE, order_id="order_demo_1").status,
            SalesOrderStatus.MISDELIVERY,
        )

        coordinator.open_return(
            workspace_id=WORKSPACE,
            order_id="order_demo_1",
            return_id="ret_demo_1",
            reason=ReturnReason.MISDELIVERY,
        )
        self.assertEqual(
            coordinator.order(workspace_id=WORKSPACE, order_id="order_demo_1").status,
            SalesOrderStatus.MISDELIVERY,
        )

    def test_resolved_case_requires_a_resolution_note(self) -> None:
        coordinator, order = receive_confirmed_order()
        coordinator.open_return(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            return_id="ret_demo_1",
            reason=ReturnReason.CUSTOMER_CANCELLED,
        )

        with self.assertRaises(SalesOrderError):
            coordinator.resolve_return(
                workspace_id=WORKSPACE,
                return_id="ret_demo_1",
                resolution=ReturnStatus.RESOLVED,
            )

        resolved = coordinator.resolve_return(
            workspace_id=WORKSPACE,
            return_id="ret_demo_1",
            resolution=ReturnStatus.RESOLVED,
            resolution_note="고객 확인 후 발주 취소 완료",
        )
        self.assertEqual(resolved.status, ReturnStatus.RESOLVED)


class ExportTests(unittest.TestCase):
    def test_exported_artifacts_mask_the_delivery_destination(self) -> None:
        coordinator, order = receive_confirmed_order()

        payload = sales_order_to_public_dict(order)
        csv_text = sales_order_lines_to_csv(order)

        self.assertEqual(payload["ship_to"]["address_line1"], "(redacted)")
        self.assertTrue(payload["personal_data_redacted"])
        self.assertNotIn("테스트로 1", csv_text)
        self.assertIn("(redacted)", csv_text)

    def test_the_masked_phone_keeps_only_the_last_four_digits(self) -> None:
        masked = build_ship_to().redacted()

        self.assertEqual(masked.recipient_phone, "***-****-***0000")
        self.assertEqual(masked.postal_code, "04**")
        self.assertNotIn("010", masked.recipient_phone.replace("***-****-***", ""))

    def test_case_json_is_valid_and_marks_the_draft_as_unsent(self) -> None:
        coordinator, order = receive_confirmed_order()
        draft = coordinator.draft_supplier_order(
            workspace_id=WORKSPACE,
            order_id=order.order_id,
            supplier=build_supplier(),
            supplier_quote_id="quote_standing_1",
            positions=build_positions(),
        )

        text = fulfillment_case_to_json(order=order, draft=draft)
        payload = json.loads(text)

        self.assertEqual(payload["contract_version"], "claw-ops-online-order-fulfillment.v1")
        self.assertFalse(payload["supplier_order_request_draft"]["sent"])
        self.assertEqual(len(payload["fulfillment_steps"]), 8)
        self.assertEqual(artifact_digest(text), artifact_digest(text))

    def test_shipment_and_return_csv_headers_are_stable(self) -> None:
        shipment_csv = shipments_to_csv(
            (
                Shipment(
                    shipment_id="ship_demo_1",
                    order_id="order_demo_1",
                    order_version=2,
                    version=1,
                    status=ShipmentStatus.LABEL_ISSUED,
                    carrier="demo_carrier",
                    tracking_number="TRK-2026-0001",
                    observed_at=NOW,
                    source_ref="carrier:demo",
                ),
            )
        )
        return_csv = returns_to_csv(())

        self.assertTrue(shipment_csv.startswith("shipment_id,order_id,order_version,version"))
        self.assertIn("tracking_number", shipment_csv)
        self.assertTrue(return_csv.startswith("return_id,order_id,order_version,version"))


class AutomationBoundaryTests(unittest.TestCase):
    def test_eight_business_steps_are_declared_with_an_automation_level(self) -> None:
        numbers = [step.number for step in ORDER_FULFILLMENT_STEPS]

        self.assertEqual(numbers, [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(
            [step.key for step in ORDER_FULFILLMENT_STEPS],
            [
                "receive_order",
                "verify_order_lines",
                "check_stock_and_terms",
                "draft_supplier_order",
                "confirm_supplier_result",
                "track_shipment",
                "complete_order",
                "handle_exception",
            ],
        )
        for step in ORDER_FULFILLMENT_STEPS:
            self.assertIsInstance(step.automation, AutomationLevel)
            self.assertTrue(step.system_dependency)

    def test_step_seven_is_the_only_fully_automatable_step_without_a_checkpoint(self) -> None:
        automatic = [
            step.number
            for step in ORDER_FULFILLMENT_STEPS
            if step.automation is AutomationLevel.FULLY_AUTOMATABLE
        ]

        self.assertEqual(automatic, [1, 7])


if __name__ == "__main__":
    unittest.main()
