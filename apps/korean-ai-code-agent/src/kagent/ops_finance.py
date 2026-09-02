from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

from .contracts import ContractError
from .ops_contracts import AccountingHandoff, Money


class CashFlowEntryKind(str, Enum):
    RECEIVABLE = "receivable"
    PAYABLE = "payable"


@dataclass(frozen=True, slots=True)
class CashFlowEntry:
    entry_id: str
    workspace_id: str
    kind: CashFlowEntryKind
    amount: Money
    due_date: date
    source_kind: str
    source_id: str
    source_version: int
    confirmed: bool = True
    note: str = ""

    def __post_init__(self) -> None:
        for field_name in ("entry_id", "workspace_id", "source_kind", "source_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
                raise ContractError(f"{field_name} must be a bounded non-empty string")
            object.__setattr__(self, field_name, value.strip())
        if not isinstance(self.kind, CashFlowEntryKind):
            try:
                object.__setattr__(self, "kind", CashFlowEntryKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid cash-flow entry kind") from exc
        if not isinstance(self.amount, Money):
            raise ContractError("amount must be Money")
        if self.amount.amount_minor <= 0:
            raise ContractError("cash-flow entry amount must be positive")
        if not isinstance(self.due_date, date):
            raise ContractError("due_date must be date")
        if isinstance(self.source_version, bool) or not isinstance(self.source_version, int) or self.source_version < 1:
            raise ContractError("source_version must be a positive integer")
        if not isinstance(self.confirmed, bool):
            raise ContractError("confirmed must be boolean")
        if not isinstance(self.note, str) or len(self.note) > 1000:
            raise ContractError("note must be a string with at most 1000 characters")

    @property
    def signed_minor(self) -> int:
        return self.amount.amount_minor if self.kind is CashFlowEntryKind.RECEIVABLE else -self.amount.amount_minor


@dataclass(frozen=True, slots=True)
class CashFlowPoint:
    on_date: date
    balance: Money
    entry_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.on_date, date):
            raise ContractError("on_date must be date")
        if not isinstance(self.balance, Money):
            raise ContractError("balance must be Money")
        if not isinstance(self.entry_ids, tuple) or len(self.entry_ids) > 500:
            raise ContractError("entry_ids must be a bounded tuple")


@dataclass(frozen=True, slots=True)
class CashFlowProjection:
    workspace_id: str
    start_date: date
    end_date: date
    opening_balance: Money
    closing_balance: Money
    minimum_balance: Money
    first_shortage_date: date | None
    timeline: tuple[CashFlowPoint, ...]
    included_entry_ids: tuple[str, ...]
    unconfirmed_entry_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, str) or not self.workspace_id.strip():
            raise ContractError("workspace_id is required")
        if not isinstance(self.start_date, date) or not isinstance(self.end_date, date):
            raise ContractError("projection dates must be dates")
        if self.end_date < self.start_date:
            raise ContractError("end_date must be on or after start_date")
        for field_name in ("opening_balance", "closing_balance", "minimum_balance"):
            if not isinstance(getattr(self, field_name), Money):
                raise ContractError(f"{field_name} must be Money")
        currencies = {
            self.opening_balance.currency,
            self.closing_balance.currency,
            self.minimum_balance.currency,
            *(point.balance.currency for point in self.timeline),
        }
        if len(currencies) != 1:
            raise ContractError("projection currencies must match")
        if self.first_shortage_date is not None and not isinstance(self.first_shortage_date, date):
            raise ContractError("first_shortage_date must be date or None")
        if not isinstance(self.timeline, tuple) or len(self.timeline) > 3660:
            raise ContractError("timeline must be a bounded tuple")
        if not isinstance(self.included_entry_ids, tuple) or len(self.included_entry_ids) > 5000:
            raise ContractError("included_entry_ids must be a bounded tuple")
        if not isinstance(self.unconfirmed_entry_ids, tuple) or len(self.unconfirmed_entry_ids) > 5000:
            raise ContractError("unconfirmed_entry_ids must be a bounded tuple")

    @property
    def has_projected_shortage(self) -> bool:
        return self.first_shortage_date is not None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-cashflow.v1",
            "workspace_id": self.workspace_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "opening_balance": self.opening_balance.safe_dict(),
            "closing_balance": self.closing_balance.safe_dict(),
            "minimum_balance": self.minimum_balance.safe_dict(),
            "first_shortage_date": self.first_shortage_date.isoformat() if self.first_shortage_date else None,
            "timeline": [
                {
                    "on_date": point.on_date.isoformat(),
                    "balance": point.balance.safe_dict(),
                    "entry_ids": list(point.entry_ids),
                }
                for point in self.timeline
            ],
            "included_entry_ids": list(self.included_entry_ids),
            "unconfirmed_entry_ids": list(self.unconfirmed_entry_ids),
            "advisory_only": True,
            "payment_execution": False,
        }


@dataclass(frozen=True, slots=True)
class CashTimingRecommendation:
    code: str
    severity: str
    summary: str
    shortage_date: date | None
    evidence_entry_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.code not in {"NO_GAP", "PROJECTED_GAP", "UNCONFIRMED_DATA"}:
            raise ContractError("invalid recommendation code")
        if self.severity not in {"info", "warning", "high"}:
            raise ContractError("invalid recommendation severity")
        if not isinstance(self.summary, str) or not self.summary.strip() or len(self.summary) > 1000:
            raise ContractError("summary must be a bounded non-empty string")
        if self.shortage_date is not None and not isinstance(self.shortage_date, date):
            raise ContractError("shortage_date must be date or None")
        if not isinstance(self.evidence_entry_ids, tuple) or len(self.evidence_entry_ids) > 100:
            raise ContractError("evidence_entry_ids must be a bounded tuple")


class CashFlowProjectionEngine:
    """Pure cash timing projection. No ledger mutation, bank access or payment execution."""

    def project(
        self,
        *,
        workspace_id: str,
        opening_balance: Money,
        start_date: date,
        end_date: date,
        entries: tuple[CashFlowEntry, ...],
    ) -> CashFlowProjection:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise ContractError("workspace_id is required")
        if not isinstance(opening_balance, Money):
            raise ContractError("opening_balance must be Money")
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise ContractError("start_date and end_date must be dates")
        if end_date < start_date:
            raise ContractError("end_date must be on or after start_date")
        if not isinstance(entries, tuple) or len(entries) > 5000:
            raise ContractError("entries must be a tuple with at most 5000 entries")
        if not all(isinstance(entry, CashFlowEntry) for entry in entries):
            raise ContractError("entries must contain CashFlowEntry values")
        if any(entry.workspace_id != workspace_id for entry in entries):
            raise ContractError("cross-workspace cash-flow entries are not allowed")
        if any(entry.amount.currency != opening_balance.currency for entry in entries):
            raise ContractError("cash-flow currencies must match opening balance")
        if len({entry.entry_id for entry in entries}) != len(entries):
            raise ContractError("cash-flow entry IDs must be unique")

        included = tuple(entry for entry in entries if start_date <= entry.due_date <= end_date)
        by_date: dict[date, list[CashFlowEntry]] = {}
        for entry in included:
            by_date.setdefault(entry.due_date, []).append(entry)

        current = opening_balance.amount_minor
        minimum = current
        first_shortage: date | None = start_date if current < 0 else None
        timeline: list[CashFlowPoint] = []

        for on_date in sorted(by_date):
            day_entries = sorted(by_date[on_date], key=lambda item: item.entry_id)
            current += sum(entry.signed_minor for entry in day_entries)
            minimum = min(minimum, current)
            if current < 0 and first_shortage is None:
                first_shortage = on_date
            timeline.append(
                CashFlowPoint(
                    on_date=on_date,
                    balance=Money(current, opening_balance.currency),
                    entry_ids=tuple(entry.entry_id for entry in day_entries),
                )
            )

        return CashFlowProjection(
            workspace_id=workspace_id,
            start_date=start_date,
            end_date=end_date,
            opening_balance=opening_balance,
            closing_balance=Money(current, opening_balance.currency),
            minimum_balance=Money(minimum, opening_balance.currency),
            first_shortage_date=first_shortage,
            timeline=tuple(timeline),
            included_entry_ids=tuple(entry.entry_id for entry in included),
            unconfirmed_entry_ids=tuple(entry.entry_id for entry in included if not entry.confirmed),
        )

    def recommend(self, projection: CashFlowProjection) -> tuple[CashTimingRecommendation, ...]:
        if not isinstance(projection, CashFlowProjection):
            raise ContractError("projection must be CashFlowProjection")
        recommendations: list[CashTimingRecommendation] = []
        if projection.has_projected_shortage:
            recommendations.append(
                CashTimingRecommendation(
                    code="PROJECTED_GAP",
                    severity="high",
                    summary=(
                        f"Projected balance falls below zero on {projection.first_shortage_date.isoformat()}; "
                        "review payment timing, receivable timing, or commercial terms before committing."
                    ),
                    shortage_date=projection.first_shortage_date,
                    evidence_entry_ids=projection.included_entry_ids,
                )
            )
        else:
            recommendations.append(
                CashTimingRecommendation(
                    code="NO_GAP",
                    severity="info",
                    summary="No negative cash balance is projected within the selected window from the supplied entries.",
                    shortage_date=None,
                    evidence_entry_ids=projection.included_entry_ids,
                )
            )
        if projection.unconfirmed_entry_ids:
            recommendations.append(
                CashTimingRecommendation(
                    code="UNCONFIRMED_DATA",
                    severity="warning",
                    summary="Projection includes unconfirmed cash-flow entries; verify them before relying on timing recommendations.",
                    shortage_date=projection.first_shortage_date,
                    evidence_entry_ids=projection.unconfirmed_entry_ids,
                )
            )
        return tuple(recommendations)

    def payable_from_accounting_handoff(self, handoff: AccountingHandoff) -> CashFlowEntry:
        if not isinstance(handoff, AccountingHandoff):
            raise ContractError("handoff must be AccountingHandoff")
        if handoff.expected_payment_date is None:
            raise ContractError("accounting handoff needs expected_payment_date for cash projection")
        if handoff.obligation_amount.amount_minor <= 0:
            raise ContractError("accounting obligation must be positive for payable projection")
        return CashFlowEntry(
            entry_id=f"payable_{handoff.handoff_id}_v{handoff.version}",
            workspace_id=handoff.workspace_id,
            kind=CashFlowEntryKind.PAYABLE,
            amount=handoff.obligation_amount,
            due_date=handoff.expected_payment_date,
            source_kind="accounting_handoff",
            source_id=handoff.handoff_id,
            source_version=handoff.version,
            confirmed=True,
            note="Projected payable from approved product handoff; external accounting system remains authoritative.",
        )
