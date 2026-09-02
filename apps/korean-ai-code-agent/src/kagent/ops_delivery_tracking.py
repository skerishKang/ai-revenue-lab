from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any

from .contracts import ContractError
from .ops_contracts import BusinessObjectKind, DeliveryStatus, PurchaseOrder, PurchaseOrderStatus
from .ops_ledger import BusinessObjectEnvelope, InMemoryOpsLedger
from .security import redact_secrets


class DeliveryExceptionKind(str, Enum):
    NONE = "none"
    UNKNOWN_DATE = "unknown_date"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"
    AT_RISK = "at_risk"


_ALLOWED_TRANSITIONS = {
    DeliveryStatus.PLANNED: {DeliveryStatus.CONFIRMED, DeliveryStatus.AT_RISK, DeliveryStatus.CANCELLED},
    DeliveryStatus.CONFIRMED: {DeliveryStatus.CONFIRMED, DeliveryStatus.AT_RISK, DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED},
    DeliveryStatus.AT_RISK: {DeliveryStatus.CONFIRMED, DeliveryStatus.AT_RISK, DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED},
    DeliveryStatus.DELIVERED: set(),
    DeliveryStatus.CANCELLED: set(),
}


def _ref(value: str, field_name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise ContractError(f"{field_name} must be bounded and non-empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class DeliveryTrackingSnapshot:
    delivery_id: str
    workspace_id: str
    po_id: str
    po_version: int
    supplier_id: str
    version: int
    status: DeliveryStatus
    observed_at: datetime
    source_ref: str
    promised_date: date | None = None
    actual_delivery_date: date | None = None
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "delivery_id", _ref(self.delivery_id, "delivery_id", limit=128))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id", limit=128))
        object.__setattr__(self, "po_id", _ref(self.po_id, "po_id", limit=128))
        object.__setattr__(self, "supplier_id", _ref(self.supplier_id, "supplier_id", limit=128))
        object.__setattr__(self, "source_ref", _ref(self.source_ref, "source_ref"))
        if isinstance(self.po_version, bool) or not isinstance(self.po_version, int) or self.po_version < 1:
            raise ContractError("po_version must be positive")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ContractError("version must be positive")
        if not isinstance(self.status, DeliveryStatus):
            try:
                object.__setattr__(self, "status", DeliveryStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid delivery status") from exc
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if self.promised_date is not None and (not isinstance(self.promised_date, date) or isinstance(self.promised_date, datetime)):
            raise ContractError("promised_date must be a date or None")
        if self.actual_delivery_date is not None and (not isinstance(self.actual_delivery_date, date) or isinstance(self.actual_delivery_date, datetime)):
            raise ContractError("actual_delivery_date must be a date or None")
        if not isinstance(self.note, str) or len(self.note) > 2000:
            raise ContractError("note must be a bounded string")
        object.__setattr__(self, "note", self.note.strip())
        if self.status is DeliveryStatus.CONFIRMED and self.promised_date is None:
            raise ContractError("confirmed delivery requires promised_date")
        if self.status is DeliveryStatus.DELIVERED:
            if self.actual_delivery_date is None:
                raise ContractError("delivered status requires actual_delivery_date")
            if self.actual_delivery_date > self.observed_at.date():
                raise ContractError("actual_delivery_date cannot be later than observation date")
        elif self.actual_delivery_date is not None:
            raise ContractError("actual_delivery_date is only allowed for delivered status")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "workspace_id": self.workspace_id,
            "po_id": self.po_id,
            "po_version": self.po_version,
            "supplier_id": self.supplier_id,
            "version": self.version,
            "status": self.status.value,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "source_ref": self.source_ref,
            "promised_date": self.promised_date.isoformat() if self.promised_date else None,
            "actual_delivery_date": self.actual_delivery_date.isoformat() if self.actual_delivery_date else None,
            "note": redact_secrets(self.note),
        }


@dataclass(frozen=True, slots=True)
class DeliveryExceptionProjection:
    delivery_id: str
    delivery_version: int
    po_id: str
    po_version: int
    supplier_id: str
    kind: DeliveryExceptionKind
    as_of: date
    promised_date: date | None
    days_to_promised: int | None
    status: DeliveryStatus
    source_ref: str
    actionable: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "delivery_version": self.delivery_version,
            "po_id": self.po_id,
            "po_version": self.po_version,
            "supplier_id": self.supplier_id,
            "kind": self.kind.value,
            "as_of": self.as_of.isoformat(),
            "promised_date": self.promised_date.isoformat() if self.promised_date else None,
            "days_to_promised": self.days_to_promised,
            "status": self.status.value,
            "source_ref": self.source_ref,
            "actionable": self.actionable,
        }


@dataclass(frozen=True, slots=True)
class DeliveryFollowupDraft:
    delivery_id: str
    delivery_version: int
    supplier_id: str
    exception_kind: DeliveryExceptionKind
    message: str
    requires_approval: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.message, str) or not self.message.strip() or len(self.message) > 4000:
            raise ContractError("message must be bounded and non-empty")
        object.__setattr__(self, "message", self.message.strip())
        if self.requires_approval is not True:
            raise ContractError("delivery follow-up draft must require approval")


class DeliveryTrackingCoordinator:
    def __init__(self, ledger: InMemoryOpsLedger | None = None) -> None:
        self.ledger = ledger or InMemoryOpsLedger()

    def _po(self, snapshot: DeliveryTrackingSnapshot) -> PurchaseOrder:
        envelope = self.ledger.get_object(
            workspace_id=snapshot.workspace_id,
            kind=BusinessObjectKind.PURCHASE_ORDER,
            object_id=snapshot.po_id,
            version=snapshot.po_version,
        )
        if not isinstance(envelope.value, PurchaseOrder):
            raise ContractError("delivery target is not a PurchaseOrder")
        po = envelope.value
        if po.status is not PurchaseOrderStatus.ISSUED:
            raise ContractError("delivery tracking requires an issued purchase order")
        if po.supplier_id != snapshot.supplier_id:
            raise ContractError("delivery supplier does not match purchase order")
        return po

    def append(self, snapshot: DeliveryTrackingSnapshot) -> None:
        if not isinstance(snapshot, DeliveryTrackingSnapshot):
            raise ContractError("snapshot must be DeliveryTrackingSnapshot")
        self._po(snapshot)
        if snapshot.version > 1:
            previous = self.ledger.get_object(
                workspace_id=snapshot.workspace_id,
                kind=BusinessObjectKind.DELIVERY_COMMITMENT,
                object_id=snapshot.delivery_id,
                version=snapshot.version - 1,
            ).value
            if not isinstance(previous, DeliveryTrackingSnapshot):
                raise ContractError("previous delivery snapshot has unexpected type")
            if previous.po_id != snapshot.po_id or previous.po_version != snapshot.po_version or previous.supplier_id != snapshot.supplier_id:
                raise ContractError("delivery identity cannot move between purchase orders or suppliers")
            if snapshot.status not in _ALLOWED_TRANSITIONS[previous.status]:
                raise ContractError("invalid delivery status transition")
            if snapshot.observed_at < previous.observed_at:
                raise ContractError("delivery observations must be monotonic")
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.DELIVERY_COMMITMENT,
                object_id=snapshot.delivery_id,
                version=snapshot.version,
                workspace_id=snapshot.workspace_id,
                value=snapshot,
            )
        )

    def latest(self, *, workspace_id: str, delivery_id: str) -> DeliveryTrackingSnapshot:
        envelope = self.ledger.latest_object(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.DELIVERY_COMMITMENT,
            object_id=delivery_id,
        )
        if not isinstance(envelope.value, DeliveryTrackingSnapshot):
            raise ContractError("delivery object has unexpected type")
        return envelope.value


class DeliveryExceptionProjector:
    def __init__(self, *, due_soon_days: int = 3) -> None:
        if isinstance(due_soon_days, bool) or not isinstance(due_soon_days, int) or not 0 <= due_soon_days <= 90:
            raise ContractError("due_soon_days must be between 0 and 90")
        self.due_soon_days = due_soon_days

    def project(self, snapshot: DeliveryTrackingSnapshot, *, as_of: date) -> DeliveryExceptionProjection:
        if not isinstance(snapshot, DeliveryTrackingSnapshot):
            raise ContractError("snapshot must be DeliveryTrackingSnapshot")
        if not isinstance(as_of, date) or isinstance(as_of, datetime):
            raise ContractError("as_of must be a date")
        days: int | None = None
        if snapshot.status in {DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED}:
            kind = DeliveryExceptionKind.NONE
        elif snapshot.status is DeliveryStatus.AT_RISK:
            kind = DeliveryExceptionKind.AT_RISK
            if snapshot.promised_date is not None:
                days = (snapshot.promised_date - as_of).days
        elif snapshot.promised_date is None:
            kind = DeliveryExceptionKind.UNKNOWN_DATE
        else:
            days = (snapshot.promised_date - as_of).days
            if days < 0:
                kind = DeliveryExceptionKind.OVERDUE
            elif days <= self.due_soon_days:
                kind = DeliveryExceptionKind.DUE_SOON
            else:
                kind = DeliveryExceptionKind.NONE
        return DeliveryExceptionProjection(
            delivery_id=snapshot.delivery_id,
            delivery_version=snapshot.version,
            po_id=snapshot.po_id,
            po_version=snapshot.po_version,
            supplier_id=snapshot.supplier_id,
            kind=kind,
            as_of=as_of,
            promised_date=snapshot.promised_date,
            days_to_promised=days,
            status=snapshot.status,
            source_ref=snapshot.source_ref,
            actionable=kind is not DeliveryExceptionKind.NONE,
        )

    def draft_followup(self, projection: DeliveryExceptionProjection) -> DeliveryFollowupDraft:
        if not isinstance(projection, DeliveryExceptionProjection):
            raise ContractError("projection must be DeliveryExceptionProjection")
        if not projection.actionable:
            raise ContractError("no follow-up is needed for a non-actionable delivery")
        if projection.kind is DeliveryExceptionKind.UNKNOWN_DATE:
            message = "발주 건의 확정 납기일을 확인 부탁드립니다."
        elif projection.kind is DeliveryExceptionKind.OVERDUE:
            message = "약속된 납기일이 경과했습니다. 현재 출고·납품 예정일을 확인 부탁드립니다."
        elif projection.kind is DeliveryExceptionKind.AT_RISK:
            message = "납기 위험 상태가 확인되었습니다. 최신 예상 납기일과 지연 사유를 확인 부탁드립니다."
        else:
            message = "납기 예정일이 임박했습니다. 예정대로 납품 가능한지 확인 부탁드립니다."
        return DeliveryFollowupDraft(
            delivery_id=projection.delivery_id,
            delivery_version=projection.delivery_version,
            supplier_id=projection.supplier_id,
            exception_kind=projection.kind,
            message=message,
        )
