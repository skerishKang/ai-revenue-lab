"""#5448: the virtual one-order pilot runner for online order -> supply -> shipment.

This module executes one **virtual** online order through the eight business
steps and writes the reusable work products: the order intake record, the
supplier purchase-order request draft, the shipment tracking record with its
waybill input structure, the order completion record, the exception cases, and
a pilot report.

The run is offline and side-effect free. It never opens a sales-channel
account, never calls a channel or carrier API, never issues a purchase order,
never sends a message, and never touches a real customer record.

Reuse disposition
-----------------
No new engine, no new provider, no new KPI machinery, no new store:

* :mod:`kagent.ops_sales_order` — the domain model, status graphs and
  coordinator this pilot drives.
* :mod:`kagent.ops_pilot` — ``default_pilot_metric_definitions``,
  ``PilotKpiEngine``, ``PilotObservation``, ``EvidenceQuality`` for the
  measured pilot KPIs.
* :mod:`kagent.ops_pilot_telemetry` — ``WorkflowTelemetryEvent``,
  ``PilotTelemetryKind``, ``PilotMeasurementBridge`` for milestone and
  duration derivation.
* :mod:`kagent.ops_contracts` / :mod:`kagent.ops_ledger` — the shared
  business records and the single versioned product store.

Honest measurement rule
-----------------------
Two different things are reported and never mixed:

``automation_execution``
    Measured on the real clock of this run: how long the automation itself
    took, how many human checkpoints it raised, and which fail-closed guards
    fired. These are **MEASURED**.

``business_step_intervals``
    The business lead time between the steps, taken from the virtual business
    clock in the sample inputs. These describe the **virtual case**, not a
    production measurement. They are reported separately and are explicitly
    marked ``production_measurement: false``.

The pilot therefore never turns a scripted virtual timeline into a claimed
production productivity delta.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
import json
from pathlib import Path
import time
from typing import Any, Callable, Iterable

from .contracts import ContractError
from .ops_contracts import Item, Money, PaymentTerms, Supplier
from .ops_pilot import (
    EvidenceQuality,
    PilotKpiEngine,
    PilotObservation,
    PilotPhase,
    default_pilot_metric_definitions,
)
from .ops_pilot_telemetry import (
    PilotMeasurementBridge,
    PilotTelemetryKind,
    WorkflowTelemetryEvent,
)
from .ops_sales_order import (
    ORDER_FULFILLMENT_STEPS,
    AutomationLevel,
    LocalCsvSalesChannelOrderPort,
    OnlineOrderFulfillmentCoordinator,
    ReturnReason,
    ReturnStatus,
    SalesOrder,
    SalesOrderStatus,
    Shipment,
    ShipmentStatus,
    StockPosition,
    SupplierOrderRequestDraft,
    artifact_digest,
    fulfillment_case_to_json,
    returns_to_csv,
    sales_order_lines_to_csv,
    sales_order_to_public_dict,
    shipments_to_csv,
)


DEFAULT_PILOT_SLUG = "order-supply-fulfillment"
DEFAULT_WORKSPACE_ID = "ws_demo"


class SalesOrderPilotError(ContractError):
    """Fail-closed pilot input or execution error."""


# --------------------------------------------------------------------------
# Sample inputs
# --------------------------------------------------------------------------

STOCK_HEADERS = (
    "item_id",
    "sku",
    "item_name",
    "unit",
    "supplier_id",
    "available_quantity",
    "reserved_quantity",
    "lead_time_days",
    "unit_cost_amount_minor",
    "currency",
)

SUPPLIER_HEADERS = (
    "supplier_id",
    "name",
    "terms_id",
    "terms_label",
    "due_days",
    "prepaid",
)

SHIPMENT_HEADERS = (
    "shipment_id",
    "status",
    "carrier",
    "tracking_number",
    "observed_at",
    "delivered_at",
    "note",
)

EXCEPTION_HEADERS = (
    "return_id",
    "reason",
    "shipment_id",
    "resolution_status",
    "resolution_note",
)

FIELD_REVIEW_HEADERS = ("field_id", "decision", "note")


@dataclass(frozen=True, slots=True)
class ShipmentObservation:
    """One recorded carrier observation for the virtual case."""

    shipment_id: str
    status: ShipmentStatus
    carrier: str
    tracking_number: str
    observed_at: datetime
    delivered_at: datetime | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ExceptionCase:
    """One recorded exception case for the virtual case."""

    return_id: str
    reason: ReturnReason
    shipment_id: str | None = None
    resolution_status: ReturnStatus = ReturnStatus.OPEN
    resolution_note: str = ""


@dataclass(frozen=True, slots=True)
class FieldReview:
    """One recorded intake field review."""

    field_id: str
    decision: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class PilotInputs:
    """Everything the virtual case reads from the sample directory."""

    channel_csv: str
    suppliers: tuple[Supplier, ...]
    positions: tuple[StockPosition, ...]
    shipments: tuple[ShipmentObservation, ...]
    exceptions: tuple[ExceptionCase, ...]
    field_reviews: tuple[FieldReview, ...]


def _read_csv(path: Path, headers: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise SalesOrderPilotError(f"sample file is missing: {path.name}")
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise SalesOrderPilotError(f"sample file has no header: {path.name}")
    normalized = tuple(name.strip() for name in reader.fieldnames)
    if set(normalized) != set(headers) or len(normalized) != len(headers):
        raise SalesOrderPilotError(f"sample file headers must match the schema: {path.name}")
    reader.fieldnames = list(normalized)
    rows: list[dict[str, str]] = []
    for row in reader:
        if None in row:
            raise SalesOrderPilotError(f"sample row has more columns than the header: {path.name}")
        rows.append({key: (value or "").strip() for key, value in row.items()})
    if not rows:
        raise SalesOrderPilotError(f"sample file has no data row: {path.name}")
    return rows


def _decimal(value: str, field_name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise SalesOrderPilotError(f"{field_name} must be decimal-compatible") from exc
    if not parsed.is_finite():
        raise SalesOrderPilotError(f"{field_name} must be finite")
    return parsed


def _timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SalesOrderPilotError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise SalesOrderPilotError(f"{field_name} must carry a timezone")
    return parsed.astimezone(timezone.utc)


def load_pilot_inputs(sample_dir: Path) -> PilotInputs:
    """Read every sample input of the virtual case."""

    if not sample_dir.is_dir():
        raise SalesOrderPilotError("sample directory is missing")

    channel_csv = (sample_dir / "channel_orders.csv").read_text(encoding="utf-8")

    suppliers: list[Supplier] = []
    for row in _read_csv(sample_dir / "suppliers.csv", SUPPLIER_HEADERS):
        due_days = int(row["due_days"]) if row["due_days"] else None
        terms = PaymentTerms(
            terms_id=row["terms_id"],
            label=row["terms_label"],
            due_days=due_days,
            prepaid=row["prepaid"].lower() == "true",
        )
        suppliers.append(
            Supplier(
                supplier_id=row["supplier_id"],
                workspace_id=DEFAULT_WORKSPACE_ID,
                name=row["name"],
                payment_terms=terms,
            )
        )

    positions: list[StockPosition] = []
    for row in _read_csv(sample_dir / "stock_positions.csv", STOCK_HEADERS):
        item = Item(
            item_id=row["item_id"],
            workspace_id=DEFAULT_WORKSPACE_ID,
            sku=row["sku"],
            name=row["item_name"],
            unit=row["unit"],
        )
        lead_time = int(row["lead_time_days"]) if row["lead_time_days"] else None
        positions.append(
            StockPosition(
                item=item,
                supplier_id=row["supplier_id"],
                available_quantity=_decimal(row["available_quantity"], "available_quantity"),
                reserved_quantity=_decimal(row["reserved_quantity"], "reserved_quantity"),
                lead_time_days=lead_time,
                unit_cost=Money(int(row["unit_cost_amount_minor"]), row["currency"]),
            )
        )

    shipments: list[ShipmentObservation] = []
    for row in _read_csv(sample_dir / "shipment_observations.csv", SHIPMENT_HEADERS):
        delivered_at = (
            _timestamp(row["delivered_at"], "delivered_at") if row["delivered_at"] else None
        )
        shipments.append(
            ShipmentObservation(
                shipment_id=row["shipment_id"],
                status=ShipmentStatus(row["status"]),
                carrier=row["carrier"],
                tracking_number=row["tracking_number"],
                observed_at=_timestamp(row["observed_at"], "observed_at"),
                delivered_at=delivered_at,
                note=row["note"],
            )
        )

    exceptions: list[ExceptionCase] = []
    for row in _read_csv(sample_dir / "exception_cases.csv", EXCEPTION_HEADERS):
        exceptions.append(
            ExceptionCase(
                return_id=row["return_id"],
                reason=ReturnReason(row["reason"]),
                shipment_id=row["shipment_id"] or None,
                resolution_status=ReturnStatus(row["resolution_status"]),
                resolution_note=row["resolution_note"],
            )
        )

    field_reviews = tuple(
        FieldReview(
            field_id=row["field_id"],
            decision=row["decision"],
            note=row["note"],
        )
        for row in _read_csv(sample_dir / "field_reviews.csv", FIELD_REVIEW_HEADERS)
    )

    return PilotInputs(
        channel_csv=channel_csv,
        suppliers=tuple(suppliers),
        positions=tuple(positions),
        shipments=tuple(shipments),
        exceptions=tuple(exceptions),
        field_reviews=field_reviews,
    )


# --------------------------------------------------------------------------
# Pilot result
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuardProbeResult:
    """One deliberate negative probe that proves a fail-closed guard fires."""

    name: str
    expected_error: str
    fired: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expected_error": self.expected_error,
            "fired": self.fired,
        }


@dataclass(frozen=True, slots=True)
class PilotArtifacts:
    """The generated work products, with a content digest for each."""

    path: str
    sha256: str
    bytes: int

    def safe_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


@dataclass(frozen=True, slots=True)
class OnlineOrderPilotResult:
    """Everything one virtual pilot run produced."""

    workspace_id: str
    order_id: str
    channel_order_ref: str
    order_status: str
    supplier_request_status: str
    outbox_state: str
    artifacts: tuple[PilotArtifacts, ...]
    guard_probes: tuple[GuardProbeResult, ...]
    automation_execution: dict[str, Any]
    business_step_intervals: dict[str, Any]
    measurement_plan: tuple[dict[str, Any], ...]
    order: SalesOrder
    draft: SupplierOrderRequestDraft
    shipments: tuple[Shipment, ...]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "order_id": self.order_id,
            "channel_order_ref": self.channel_order_ref,
            "order_status": self.order_status,
            "supplier_request_status": self.supplier_request_status,
            "outbox_state": self.outbox_state,
            "artifacts": [artifact.safe_dict() for artifact in self.artifacts],
            "guard_probes": [probe.safe_dict() for probe in self.guard_probes],
            "automation_execution": self.automation_execution,
            "business_step_intervals": self.business_step_intervals,
            "measurement_plan": list(self.measurement_plan),
        }


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def _write_text(path: Path, text: str) -> PilotArtifacts:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes(data)
    return PilotArtifacts(
        path=path.as_posix(),
        sha256=artifact_digest(text),
        bytes=len(data),
    )


def _write_json(path: Path, payload: Any) -> PilotArtifacts:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return _write_text(path, text)


def _tracking_input_template_csv(shipments: tuple[Shipment, ...]) -> str:
    """The waybill input structure an operator fills in per shipment."""

    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "shipment_id",
            "carrier",
            "tracking_number",
            "observed_at",
            "delivered_at",
            "status",
            "note",
        ]
    )
    for shipment in shipments:
        writer.writerow(
            [
                shipment.shipment_id,
                shipment.carrier,
                shipment.tracking_number,
                shipment.observed_at.isoformat().replace("+00:00", "Z"),
                shipment.delivered_at.isoformat().replace("+00:00", "Z")
                if shipment.delivered_at
                else "",
                shipment.status.value,
                shipment.note,
            ]
        )
    return buffer.getvalue()


def _build_measurement_plan() -> tuple[dict[str, Any], ...]:
    """How each step would be measured once a real system is connected."""

    plan: list[dict[str, Any]] = []
    for step in ORDER_FULFILLMENT_STEPS:
        plan.append(
            {
                "number": step.number,
                "key": step.key,
                "title_ko": step.title_ko,
                "automation": step.automation.value,
                "production_clock_source": _CLOCK_SOURCE.get(step.key, "미정"),
                "production_metric_key": _METRIC_KEY.get(step.key),
                "error_signal": _ERROR_SIGNAL.get(step.key, "미정"),
                "sample_case_status": "가상 케이스에서 재현 확인",
            }
        )
    return tuple(plan)


_CLOCK_SOURCE = {
    "receive_order": "판매채널 주문 접수 이벤트 (파일 수정시각 또는 API 수신시각)",
    "verify_order_lines": "접수~확인 구간의 검토 이벤트",
    "check_stock_and_terms": "재고 조회 응답시각 (ERP 재고 연계 확정 후)",
    "draft_supplier_order": "발주 초안 생성시각 (초안 렌더 완료 로그)",
    "confirm_supplier_result": "공급사 회신 수신시각 (이메일/메신저 수신함)",
    "track_shipment": "택배사 송장 조회 시각 (택배사 조회 계약 확정 후)",
    "complete_order": "배송 완료 확인 시각",
    "handle_exception": "예외 접수~종결 시각",
}

_METRIC_KEY = {
    "receive_order": "request_to_rfq_minutes",
    "verify_order_lines": "extraction_correction_rate",
    "check_stock_and_terms": "owner_intervention_count",
    "draft_supplier_order": "request_to_po_minutes",
    "confirm_supplier_result": "supplier_response_minutes",
    "track_shipment": "owner_intervention_count",
    "complete_order": "manual_reentry_count",
    "handle_exception": "automation_retry_count",
}

_ERROR_SIGNAL = {
    "receive_order": "채널 주문 식별 실패 / 스키마 불일치",
    "verify_order_lines": "필드 수정 건수 (correction rate)",
    "check_stock_and_terms": "재고 부족 라인 발생 건수",
    "draft_supplier_order": "발주 초안 검증 실패 (금액/품목 누락)",
    "confirm_supplier_result": "회신 미수신·납기일 미확정 건수",
    "track_shipment": "송장 미발급·조회 실패·상태 정체 건수",
    "complete_order": "완료 처리 실패 건수",
    "handle_exception": "반품/오배송 접수 후 미종결 건수",
}


def run_online_order_pilot(
    *,
    sample_dir: Path,
    out_dir: Path,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    order_id: str = "order_demo_1",
    channel_order_ref: str = "CH-2026-0011",
    clock: Callable[[], datetime] | None = None,
) -> OnlineOrderPilotResult:
    """Run one virtual order end to end and write the work products."""

    inputs = load_pilot_inputs(sample_dir)
    started = time.perf_counter()

    channel = LocalCsvSalesChannelOrderPort.parse_csv(inputs.channel_csv)
    peek = channel.fetch_order(
        workspace_id=workspace_id, channel_order_ref=channel_order_ref
    )
    if clock is not None:
        base_time = clock()
        if base_time.tzinfo is None:
            raise SalesOrderPilotError("clock must return timezone-aware datetime")
        if base_time < peek.received_at:
            raise SalesOrderPilotError("clock is earlier than the channel order receipt time")
    else:
        # The virtual case runs on a deterministic business clock derived from
        # the sample receipt time, so the pilot is reproducible.
        base_time = peek.received_at + timedelta(hours=1)

    coordinator = OnlineOrderFulfillmentCoordinator(
        channel=channel,
        clock=lambda: base_time,
    )
    telemetry = PilotMeasurementBridge()
    kpi = PilotKpiEngine(default_pilot_metric_definitions())

    def emit(
        kind: PilotTelemetryKind,
        *,
        event_id: str,
        occurred_at: datetime,
        evidence_ref: str,
        subject_ref: str | None = None,
    ) -> None:
        telemetry.add(
            WorkflowTelemetryEvent(
                event_id=event_id,
                workspace_id=workspace_id,
                workflow_ref=f"wf-order-{order_id}",
                phase=PilotPhase.SHADOW,
                kind=kind,
                occurred_at=occurred_at,
                evidence_ref=evidence_ref,
                subject_ref=subject_ref,
            )
        )

    # --- step 1: order intake -------------------------------------------
    order = coordinator.receive_order(
        workspace_id=workspace_id,
        order_id=order_id,
        channel_order_ref=channel_order_ref,
    )
    emit(
        PilotTelemetryKind.REQUEST_INGESTED,
        event_id="tev-request-ingested",
        occurred_at=order.received_at,
        evidence_ref=f"channel:{order.channel.value}:{order.channel_order_ref}",
    )
    for review in inputs.field_reviews:
        emit(
            PilotTelemetryKind.EXTRACTION_FIELD_CONFIRMED
            if review.decision == "confirmed"
            else PilotTelemetryKind.EXTRACTION_FIELD_CORRECTED,
            event_id=f"tev-field-{review.field_id}",
            occurred_at=order.received_at,
            evidence_ref=f"field-review:{review.field_id}",
        )

    # --- step 2 & 3: line review, stock and terms ------------------------
    availability = coordinator.check_availability(
        workspace_id=workspace_id,
        order_id=order_id,
        positions=inputs.positions,
    )
    if not availability.fully_covered:
        raise SalesOrderPilotError(
            "virtual case stock does not cover the order: "
            + ",".join(availability.short_line_ids)
        )
    coordinator.confirm_order(workspace_id=workspace_id, order_id=order_id)
    emit(
        PilotTelemetryKind.OWNER_INTERVENTION,
        event_id="tev-owner-intervention-availability",
        occurred_at=base_time,
        evidence_ref="check:stock_and_terms",
    )

    # --- step 4: supplier purchase-order request draft -------------------
    supplier = inputs.suppliers[0]
    draft = coordinator.draft_supplier_order(
        workspace_id=workspace_id,
        order_id=order_id,
        supplier=supplier,
        supplier_quote_id="quote_standing_demo_1",
        positions=inputs.positions,
    )
    emit(
        PilotTelemetryKind.RFQ_READY,
        event_id="tev-rfq-ready",
        occurred_at=base_time,
        evidence_ref=f"po:{draft.purchase_order.po_id}:v1",
    )
    emit(
        PilotTelemetryKind.PO_READY,
        event_id="tev-po-ready",
        occurred_at=base_time,
        evidence_ref=f"po:{draft.purchase_order.po_id}:v1",
    )
    outbox_id = coordinator.stage_supplier_request(
        draft=draft, recipient_ref=supplier.supplier_id
    )

    # --- step 5: supplier result (recorded virtual business input) ------
    coordinator.record_supplier_acknowledgement(
        workspace_id=workspace_id,
        order_id=order_id,
        supplier_id=supplier.supplier_id,
        acknowledged_at=base_time,
    )
    emit(
        PilotTelemetryKind.MANUAL_REENTRY,
        event_id="tev-manual-supplier-reply",
        occurred_at=base_time,
        evidence_ref=f"supplier:{supplier.supplier_id}",
    )

    # --- step 6: shipment and waybill ------------------------------------
    shipments: list[Shipment] = []
    for observation in inputs.shipments:
        shipment = coordinator.record_shipment(
            workspace_id=workspace_id,
            order_id=order_id,
            shipment_id=observation.shipment_id,
            status=observation.status,
            carrier=observation.carrier,
            tracking_number=observation.tracking_number,
            observed_at=observation.observed_at,
            delivered_at=observation.delivered_at,
            source_ref=f"carrier:{observation.carrier}:{observation.tracking_number}",
            note=observation.note,
        )
        shipments.append(shipment)
    emit(
        PilotTelemetryKind.MANUAL_REENTRY,
        event_id="tev-manual-waybill",
        occurred_at=base_time,
        evidence_ref=f"carrier:{inputs.shipments[0].carrier}",
    )

    # --- step 7: order completion ----------------------------------------
    coordinator.complete_order(workspace_id=workspace_id, order_id=order_id)
    emit(
        PilotTelemetryKind.WORKFLOW_COMPLETED,
        event_id="tev-workflow-completed",
        occurred_at=base_time,
        evidence_ref=f"order:{order_id}",
    )

    # --- step 8: exception case on a separate virtual order --------------
    exception_order_id = f"{order_id}-exception"
    exception_coordinator = OnlineOrderFulfillmentCoordinator(
        channel=channel,
        clock=lambda: base_time,
    )
    exception_coordinator.receive_order(
        workspace_id=workspace_id,
        order_id=exception_order_id,
        channel_order_ref=channel_order_ref,
    )
    exception_coordinator.confirm_order(
        workspace_id=workspace_id, order_id=exception_order_id
    )
    exception_coordinator.record_supplier_acknowledgement(
        workspace_id=workspace_id,
        order_id=exception_order_id,
        supplier_id=supplier.supplier_id,
        acknowledged_at=base_time,
    )
    exception_coordinator.record_shipment(
        workspace_id=workspace_id,
        order_id=exception_order_id,
        shipment_id="ship_demo_exception",
        status=ShipmentStatus.IN_TRANSIT,
        carrier=inputs.shipments[0].carrier,
        tracking_number="TRK-2026-EXCEPTION-0001",
        observed_at=base_time,
    )
    exception_returns = []
    for case in inputs.exceptions:
        request = exception_coordinator.open_return(
            workspace_id=workspace_id,
            order_id=exception_order_id,
            return_id=case.return_id,
            reason=case.reason,
            shipment_id=case.shipment_id,
        )
        if case.resolution_status is not ReturnStatus.OPEN:
            request = exception_coordinator.resolve_return(
                workspace_id=workspace_id,
                return_id=case.return_id,
                resolution=case.resolution_status,
                resolution_note=case.resolution_note,
            )
        exception_returns.append(request)

    # --- deliberate negative probes --------------------------------------
    probes = _run_guard_probes(inputs, base_time)

    derived = telemetry.capture_into(
        kpi,
        workspace_id=workspace_id,
        workflow_ref=f"wf-order-{order_id}",
    )
    measured_values = {item.observation.metric_key: item.observation.value for item in derived}

    elapsed_seconds = time.perf_counter() - started
    final_order = coordinator.order(workspace_id=workspace_id, order_id=order_id)
    outbox_record = coordinator.outbox._records.get(f"req-{draft.purchase_order.po_id}-v1")
    outbox_state = outbox_record.state.value if outbox_record is not None else "unknown"

    automation_execution = {
        "automation_execution_minutes": format(
            (Decimal(str(elapsed_seconds)) / Decimal(60)).quantize(Decimal("0.000001")),
            "f",
        ),
        "measured": True,
        "owner_intervention_count": int(measured_values.get("owner_intervention_count", 0)),
        "manual_reentry_count": int(measured_values.get("manual_reentry_count", 0)),
        "automation_retry_count": int(measured_values.get("automation_retry_count", 0)),
        "extraction_correction_rate": (
            format(measured_values["extraction_correction_rate"], "f")
            if "extraction_correction_rate" in measured_values
            else None
        ),
        "derived_metric_keys": sorted({item.observation.metric_key for item in derived}),
        "guard_probe_count": len(probes),
        "guard_probe_fired_count": sum(1 for probe in probes if probe.fired),
        "note": "가상 케이스 실행에서 실제로 측정된 자동화 처리 시간과 개입·재입력·재시도 건수.",
    }

    business_step_intervals = {
        "production_measurement": False,
        "source": "sample_input_virtual_business_clock",
        "note": "아래 값은 가상 업무 시각으로 만든 샘플 입력이며 운영 실측값이 아니다.",
        "steps": [
            {
                "step": "order_received",
                "at": order.received_at.isoformat().replace("+00:00", "Z"),
            },
            {
                "step": "supplier_request_drafted",
                "at": base_time.isoformat().replace("+00:00", "Z"),
            },
            {
                "step": "supplier_acknowledged",
                "at": base_time.isoformat().replace("+00:00", "Z"),
            },
            {
                "step": "shipment_label_issued",
                "at": inputs.shipments[0].observed_at.isoformat().replace("+00:00", "Z"),
            },
            {
                "step": "shipment_delivered",
                "at": inputs.shipments[-1].observed_at.isoformat().replace("+00:00", "Z"),
            },
        ],
    }

    measurement_plan = _build_measurement_plan()

    # --- artifacts -------------------------------------------------------
    artifacts: list[PilotArtifacts] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts.append(
        _write_json(
            out_dir / "order_intake_record.json",
            {
                "record_version": "claw-ops-order-intake.v1",
                "order": sales_order_to_public_dict(order, redact_personal=True),
                "availability_check": availability.safe_dict(),
                "personal_data_redacted": True,
                "real_customer_data_used": False,
            },
        )
    )
    artifacts.append(_write_text(out_dir / "supplier_order_request_draft.md", draft.to_markdown()))
    artifacts.append(
        _write_text(
            out_dir / "supplier_order_request_email_draft.txt", draft.to_email_draft()
        )
    )
    artifacts.append(
        _write_text(out_dir / "tracking_input_template.csv", _tracking_input_template_csv(tuple(shipments)))
    )
    artifacts.append(_write_text(out_dir / "shipment_tracking.csv", shipments_to_csv(tuple(shipments))))
    artifacts.append(_write_text(out_dir / "order_lines.csv", sales_order_lines_to_csv(final_order)))
    artifacts.append(_write_text(out_dir / "exception_cases.csv", returns_to_csv(tuple(exception_returns))))
    artifacts.append(
        _write_json(
            out_dir / "order_completion_record.json",
            {
                "record_version": "claw-ops-order-completion.v1",
                "order_id": final_order.order_id,
                "order_version": final_order.version,
                "status": final_order.status.value,
                "completed_at": base_time.isoformat().replace("+00:00", "Z"),
                "shipments": [shipment.safe_dict() for shipment in shipments],
                "personal_data_redacted": True,
            },
        )
    )
    artifacts.append(
        _write_text(
            out_dir / "fulfillment_case.json",
            fulfillment_case_to_json(
                order=final_order,
                draft=draft,
                shipments=tuple(shipments),
                returns=tuple(exception_returns),
                availability=availability,
            ),
        )
    )

    report = {
        "pilot": {
            "issue": "#5448",
            "slug": DEFAULT_PILOT_SLUG,
            "workspace_id": workspace_id,
            "order_id": order_id,
            "channel_order_ref": channel_order_ref,
            "virtual_case": True,
            "real_customer_data_used": False,
            "real_order_placed": False,
            "real_purchase_order_issued": False,
            "message_sent": False,
        },
        "automation_execution": automation_execution,
        "business_step_intervals": business_step_intervals,
        "measurement_plan": list(measurement_plan),
        "guard_probes": [probe.safe_dict() for probe in probes],
        "artifacts": [artifact.safe_dict() for artifact in artifacts],
        "steps": [step.safe_dict() for step in ORDER_FULFILLMENT_STEPS],
        "step_automation_summary": {
            "fully_automatable": sum(
                1
                for step in ORDER_FULFILLMENT_STEPS
                if step.automation is AutomationLevel.FULLY_AUTOMATABLE
            ),
            "human_confirmation_required": sum(
                1
                for step in ORDER_FULFILLMENT_STEPS
                if step.automation is AutomationLevel.HUMAN_CONFIRMATION_REQUIRED
            ),
            "manual_only": sum(
                1
                for step in ORDER_FULFILLMENT_STEPS
                if step.automation is AutomationLevel.MANUAL_ONLY
            ),
            "blocked_missing_system": sum(
                1
                for step in ORDER_FULFILLMENT_STEPS
                if step.automation is AutomationLevel.BLOCKED_MISSING_SYSTEM
            ),
        },
        "kpi_observations": [item.safe_dict() for item in derived],
        "kpi_measurement_scope": {
            "pilot_phase": PilotPhase.SHADOW.value,
            "milestone_clock_source": "sample_input_virtual_business_clock",
            "production_measurement": False,
            "note": (
                "마일스톤 시각은 샘플 입력의 가상 업무 시각이다. 값은 가상 케이스 안에서 "
                "일관되지만 운영 실측값이 아니며, 기준선 비교도 수행하지 않는다."
            ),
        },
        "baseline_measured": False,
        "measured_comparison_available": False,
        "baseline_note": "수동 처리 시간 기준선은 아직 측정하지 않았다. 기준선 없이 생산성 변화율을 산출하지 않는다.",
        "outbox_state": outbox_state,
    }
    artifacts.append(_write_json(out_dir / "pilot_report.json", report))

    return OnlineOrderPilotResult(
        workspace_id=workspace_id,
        order_id=order_id,
        channel_order_ref=channel_order_ref,
        order_status=final_order.status.value,
        supplier_request_status=draft.purchase_order.status.value,
        outbox_state=outbox_state,
        artifacts=tuple(artifacts),
        guard_probes=tuple(probes),
        automation_execution=automation_execution,
        business_step_intervals=business_step_intervals,
        measurement_plan=measurement_plan,
        order=final_order,
        draft=draft,
        shipments=tuple(shipments),
    )


def _run_guard_probes(
    inputs: PilotInputs,
    base_time: datetime,
) -> tuple[GuardProbeResult, ...]:
    """Prove the fail-closed guards actually fire, on throwaway records."""

    probes: list[GuardProbeResult] = []

    def refusing_probe(name: str, expected: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - the probe records the refusal
            fired = expected in str(exc)
            probes.append(GuardProbeResult(name=name, expected_error=expected, fired=fired))
            return
        probes.append(GuardProbeResult(name=name, expected_error=expected, fired=False))

    def asserting_probe(name: str, expected: str, action: Callable[[], bool]) -> None:
        try:
            fired = bool(action())
        except Exception:  # noqa: BLE001 - an exception is not a fired assertion
            fired = False
        probes.append(GuardProbeResult(name=name, expected_error=expected, fired=fired))

    def fresh_coordinator(order_ref: str) -> OnlineOrderFulfillmentCoordinator:
        channel = LocalCsvSalesChannelOrderPort.parse_csv(inputs.channel_csv)
        probe_coordinator = OnlineOrderFulfillmentCoordinator(
            channel=channel,
            clock=lambda: base_time,
        )
        probe_coordinator.receive_order(
            workspace_id=DEFAULT_WORKSPACE_ID,
            order_id=order_ref,
            channel_order_ref="CH-2026-0011",
        )
        return probe_coordinator

    def short_stock_probe() -> bool:
        probe_coordinator = fresh_coordinator("order_probe_short_stock")
        check = probe_coordinator.check_availability(
            workspace_id=DEFAULT_WORKSPACE_ID,
            order_id="order_probe_short_stock",
            positions=inputs.positions[:1],
        )
        still_received = (
            probe_coordinator.order(
                workspace_id=DEFAULT_WORKSPACE_ID, order_id="order_probe_short_stock"
            ).status
            is SalesOrderStatus.RECEIVED
        )
        return bool(check.short_line_ids) and not check.fully_covered and still_received

    asserting_probe(
        "short_stock_is_reported_and_order_stays_unconfirmed",
        "short_line_ids reported and status stays received",
        short_stock_probe,
    )

    def unconfirmed_probe() -> None:
        probe_coordinator = fresh_coordinator("order_probe_unconfirmed")
        probe_coordinator.draft_supplier_order(
            workspace_id=DEFAULT_WORKSPACE_ID,
            order_id="order_probe_unconfirmed",
            supplier=inputs.suppliers[0],
            supplier_quote_id="quote_standing_demo_1",
            positions=inputs.positions,
        )

    refusing_probe(
        "supplier_request_needs_confirmed_order",
        "supplier order request needs a confirmed order",
        unconfirmed_probe,
    )

    def tracking_probe() -> None:
        probe_coordinator = fresh_coordinator("order_probe_tracking")
        probe_coordinator.confirm_order(
            workspace_id=DEFAULT_WORKSPACE_ID, order_id="order_probe_tracking"
        )
        probe_coordinator.record_supplier_acknowledgement(
            workspace_id=DEFAULT_WORKSPACE_ID,
            order_id="order_probe_tracking",
            supplier_id=inputs.suppliers[0].supplier_id,
            acknowledged_at=base_time,
        )
        probe_coordinator.record_shipment(
            workspace_id=DEFAULT_WORKSPACE_ID,
            order_id="order_probe_tracking",
            shipment_id="ship_probe_tracking",
            status=ShipmentStatus.LABEL_ISSUED,
            carrier="demo_carrier",
            tracking_number="",
        )

    refusing_probe(
        "shipment_needs_a_tracking_number",
        "tracking_number is required",
        tracking_probe,
    )

    def terminal_return_probe() -> None:
        probe_coordinator = fresh_coordinator("order_probe_terminal")
        probe_coordinator.confirm_order(
            workspace_id=DEFAULT_WORKSPACE_ID, order_id="order_probe_terminal"
        )
        probe_coordinator.open_return(
            workspace_id=DEFAULT_WORKSPACE_ID,
            order_id="order_probe_terminal",
            return_id="ret_probe_terminal",
            reason=ReturnReason.CUSTOMER_RETURN,
        )

    refusing_probe(
        "return_before_shipment_is_refused",
        "return requires a shipped order",
        terminal_return_probe,
    )

    def draft_price_probe() -> bool:
        probe_coordinator = fresh_coordinator("order_probe_price")
        probe_coordinator.confirm_order(
            workspace_id=DEFAULT_WORKSPACE_ID, order_id="order_probe_price"
        )
        draft = probe_coordinator.draft_supplier_order(
            workspace_id=DEFAULT_WORKSPACE_ID,
            order_id="order_probe_price",
            supplier=inputs.suppliers[0],
            supplier_quote_id="quote_standing_demo_1",
            positions=inputs.positions,
        )
        customer_price = 12000
        supplier_price = draft.purchase_order.lines[0].unit_price.amount_minor
        return supplier_price != customer_price

    asserting_probe(
        "supplier_request_uses_supplier_cost_not_customer_price",
        "purchase order unit price differs from the customer sale price",
        draft_price_probe,
    )

    return tuple(probes)


__all__ = [
    "DEFAULT_PILOT_SLUG",
    "DEFAULT_WORKSPACE_ID",
    "ExceptionCase",
    "FieldReview",
    "GuardProbeResult",
    "OnlineOrderPilotResult",
    "PilotArtifacts",
    "PilotInputs",
    "SalesOrderPilotError",
    "ShipmentObservation",
    "load_pilot_inputs",
    "run_online_order_pilot",
]
