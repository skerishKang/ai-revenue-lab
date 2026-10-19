from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class RfqTrackingStatus(str, Enum):
    SENT = "sent"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ReminderProjectionKind(str, Enum):
    NOT_DUE = "not_due"
    DUE = "due"
    ESCALATE = "escalate"
    RESOLVED = "resolved"
    MAXED_OUT = "maxed_out"


@dataclass(frozen=True, slots=True)
class SupplierReminderPolicy:
    first_delay_minutes: int = 24 * 60
    escalation_delay_minutes: int = 48 * 60
    minimum_spacing_minutes: int = 12 * 60
    max_reminders: int = 3

    def __post_init__(self) -> None:
        for name, value, low, high in (
            ("first_delay_minutes", self.first_delay_minutes, 1, 30 * 24 * 60),
            ("escalation_delay_minutes", self.escalation_delay_minutes, 1, 60 * 24 * 60),
            ("minimum_spacing_minutes", self.minimum_spacing_minutes, 1, 30 * 24 * 60),
            ("max_reminders", self.max_reminders, 1, 10),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ContractError(f"{name} outside supported bounds")
        if self.escalation_delay_minutes < self.first_delay_minutes:
            raise ContractError("escalation delay cannot precede first reminder")


@dataclass(frozen=True, slots=True)
class SupplierRfqTrackingSnapshot:
    workspace_id: str
    rfq_id: str
    rfq_version: int
    supplier_id: str
    status: RfqTrackingStatus
    sent_at: datetime
    response_at: datetime | None = None
    reminder_count: int = 0
    last_reminder_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("workspace_id", "rfq_id", "supplier_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if isinstance(self.rfq_version, bool) or not isinstance(self.rfq_version, int) or self.rfq_version < 1:
            raise ContractError("rfq_version must be positive")
        if not isinstance(self.status, RfqTrackingStatus):
            try:
                object.__setattr__(self, "status", RfqTrackingStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid RFQ tracking status") from exc
        sent = _aware(self.sent_at, "sent_at")
        response = _aware(self.response_at, "response_at")
        last = _aware(self.last_reminder_at, "last_reminder_at")
        assert sent is not None
        if response is not None and response < sent:
            raise ContractError("response_at cannot precede sent_at")
        if last is not None and last < sent:
            raise ContractError("last_reminder_at cannot precede sent_at")
        if isinstance(self.reminder_count, bool) or not isinstance(self.reminder_count, int) or not 0 <= self.reminder_count <= 100:
            raise ContractError("reminder_count must be bounded")
        if self.reminder_count == 0 and last is not None:
            raise ContractError("last_reminder_at requires prior reminder")
        if self.reminder_count > 0 and last is None:
            raise ContractError("prior reminder count requires last_reminder_at")
        object.__setattr__(self, "sent_at", sent)
        object.__setattr__(self, "response_at", response)
        object.__setattr__(self, "last_reminder_at", last)


@dataclass(frozen=True, slots=True)
class SupplierReminderProjection:
    workspace_id: str
    rfq_id: str
    rfq_version: int
    supplier_id: str
    kind: ReminderProjectionKind
    due_at: datetime | None
    reminder_number: int | None
    requires_approval: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "rfq_id": self.rfq_id,
            "rfq_version": self.rfq_version,
            "supplier_id": self.supplier_id,
            "kind": self.kind.value,
            "due_at": self.due_at.isoformat().replace("+00:00", "Z") if self.due_at else None,
            "reminder_number": self.reminder_number,
            "requires_approval": self.requires_approval,
            "auto_send": False,
        }


@dataclass(frozen=True, slots=True)
class SupplierReminderDraft:
    workspace_id: str
    rfq_id: str
    rfq_version: int
    supplier_id: str
    reminder_number: int
    subject: str
    body: str
    requires_approval: bool = True


class SupplierRfqReminderProjector:
    def __init__(self, policy: SupplierReminderPolicy | None = None) -> None:
        self.policy = policy or SupplierReminderPolicy()

    def project(self, snapshot: SupplierRfqTrackingSnapshot, *, as_of: datetime) -> SupplierReminderProjection:
        if not isinstance(snapshot, SupplierRfqTrackingSnapshot):
            raise ContractError("snapshot must be SupplierRfqTrackingSnapshot")
        now = _aware(as_of, "as_of")
        assert now is not None
        if now < snapshot.sent_at:
            raise ContractError("as_of cannot precede RFQ sent time")
        if snapshot.status in {RfqTrackingStatus.CLOSED, RfqTrackingStatus.CANCELLED} or snapshot.response_at is not None:
            return SupplierReminderProjection(snapshot.workspace_id, snapshot.rfq_id, snapshot.rfq_version, snapshot.supplier_id, ReminderProjectionKind.RESOLVED, None, None, False)
        if snapshot.reminder_count >= self.policy.max_reminders:
            return SupplierReminderProjection(snapshot.workspace_id, snapshot.rfq_id, snapshot.rfq_version, snapshot.supplier_id, ReminderProjectionKind.MAXED_OUT, None, None, False)

        first_due = snapshot.sent_at + timedelta(minutes=self.policy.first_delay_minutes)
        escalation_due = snapshot.sent_at + timedelta(minutes=self.policy.escalation_delay_minutes)
        spacing_due = (
            snapshot.last_reminder_at + timedelta(minutes=self.policy.minimum_spacing_minutes)
            if snapshot.last_reminder_at is not None
            else first_due
        )
        due_at = max(first_due, spacing_due)
        if now < due_at:
            return SupplierReminderProjection(snapshot.workspace_id, snapshot.rfq_id, snapshot.rfq_version, snapshot.supplier_id, ReminderProjectionKind.NOT_DUE, due_at, snapshot.reminder_count + 1, False)
        kind = ReminderProjectionKind.ESCALATE if now >= escalation_due else ReminderProjectionKind.DUE
        return SupplierReminderProjection(snapshot.workspace_id, snapshot.rfq_id, snapshot.rfq_version, snapshot.supplier_id, kind, due_at, snapshot.reminder_count + 1, True)

    def draft(self, projection: SupplierReminderProjection) -> SupplierReminderDraft:
        if not isinstance(projection, SupplierReminderProjection):
            raise ContractError("projection must be SupplierReminderProjection")
        if projection.kind not in {ReminderProjectionKind.DUE, ReminderProjectionKind.ESCALATE} or not projection.requires_approval:
            raise ContractError("only actionable reminder projections can create drafts")
        assert projection.reminder_number is not None
        subject = "견적 회신 일정 확인 요청"
        body = (
            "이전에 전달드린 견적 요청 건의 검토 및 회신 가능 일정을 확인 부탁드립니다."
            if projection.kind is ReminderProjectionKind.DUE
            else "견적 요청 건의 회신이 지연되고 있어 가능 여부와 예상 회신 시점을 확인 부탁드립니다."
        )
        return SupplierReminderDraft(
            workspace_id=projection.workspace_id,
            rfq_id=projection.rfq_id,
            rfq_version=projection.rfq_version,
            supplier_id=projection.supplier_id,
            reminder_number=projection.reminder_number,
            subject=subject,
            body=body,
        )


AUTO_SUPPLIER_REMINDER_SEND_SUPPORTED = False
