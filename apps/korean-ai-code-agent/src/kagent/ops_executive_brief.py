from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .ops_finance import CashTimingRecommendation
from .ops_inbox import ExecutiveInboxCard, InboxCardStatus, InboxPriority
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _text(value: str, field_name: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise ContractError(f"{field_name} must be bounded non-empty text")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


class BriefPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class BriefItemKind(str, Enum):
    APPROVAL = "approval"
    CASHFLOW = "cashflow"
    OPERATIONAL_ALERT = "operational_alert"


@dataclass(frozen=True, slots=True)
class OperationalAlert:
    alert_id: str
    workspace_id: str
    source_kind: str
    source_ref: str
    priority: BriefPriority
    title: str
    summary: str
    due_date: date | None = None
    actionable: bool = True

    def __post_init__(self) -> None:
        for field_name in ("alert_id", "workspace_id", "source_kind", "source_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.priority, BriefPriority):
            try:
                object.__setattr__(self, "priority", BriefPriority(self.priority))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid operational alert priority") from exc
        object.__setattr__(self, "title", _text(self.title, "title", limit=300))
        object.__setattr__(self, "summary", _text(self.summary, "summary", limit=1500))
        if self.due_date is not None and not isinstance(self.due_date, date):
            raise ContractError("due_date must be date or None")
        if not isinstance(self.actionable, bool):
            raise ContractError("actionable must be boolean")


@dataclass(frozen=True, slots=True)
class ExecutiveBriefItem:
    item_id: str
    workspace_id: str
    kind: BriefItemKind
    priority: BriefPriority
    title: str
    summary: str
    source_ref: str
    actionable: bool
    due_date: date | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("item_id", "workspace_id", "source_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.kind, BriefItemKind):
            raise ContractError("kind must be BriefItemKind")
        if not isinstance(self.priority, BriefPriority):
            raise ContractError("priority must be BriefPriority")
        object.__setattr__(self, "title", _text(self.title, "title", limit=300))
        object.__setattr__(self, "summary", _text(self.summary, "summary", limit=1500))
        if not isinstance(self.actionable, bool):
            raise ContractError("actionable must be boolean")
        if self.due_date is not None and not isinstance(self.due_date, date):
            raise ContractError("due_date must be date or None")
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > 100:
            raise ContractError("evidence_refs must be a bounded tuple")
        for ref in self.evidence_refs:
            _ref(ref, "evidence_ref")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "workspace_id": self.workspace_id,
            "kind": self.kind.value,
            "priority": self.priority.value,
            "title": self.title,
            "summary": self.summary,
            "source_ref": self.source_ref,
            "actionable": self.actionable,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "evidence_refs": list(self.evidence_refs),
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class DailyExecutiveBrief:
    workspace_id: str
    on_date: date
    items: tuple[ExecutiveBriefItem, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        if not isinstance(self.on_date, date):
            raise ContractError("on_date must be date")
        if not isinstance(self.items, tuple) or len(self.items) > 500:
            raise ContractError("items must be a bounded tuple")
        if any(not isinstance(item, ExecutiveBriefItem) for item in self.items):
            raise ContractError("items must contain ExecutiveBriefItem values")
        if any(item.workspace_id != self.workspace_id for item in self.items):
            raise ContractError("brief cannot mix workspaces")
        refs = [item.source_ref for item in self.items]
        if len(refs) != len(set(refs)):
            raise ContractError("brief source references must be unique")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-daily-executive-brief.v1",
            "workspace_id": self.workspace_id,
            "on_date": self.on_date.isoformat(),
            "items": [item.safe_dict() for item in self.items],
            "read_only": True,
            "hidden_model_ranking": False,
            "approval_execution_authority": False,
            "payment_execution_authority": False,
        }


_PRIORITY_RANK = {
    BriefPriority.CRITICAL: 0,
    BriefPriority.HIGH: 1,
    BriefPriority.MEDIUM: 2,
    BriefPriority.LOW: 3,
    BriefPriority.INFO: 4,
}

_INBOX_PRIORITY = {
    InboxPriority.HIGH: BriefPriority.HIGH,
    InboxPriority.MEDIUM: BriefPriority.MEDIUM,
    InboxPriority.LOW: BriefPriority.LOW,
}

_FINANCE_PRIORITY = {
    "high": BriefPriority.CRITICAL,
    "warning": BriefPriority.HIGH,
    "info": BriefPriority.INFO,
}


class DailyExecutiveBriefProjector:
    def from_inbox_card(self, card: ExecutiveInboxCard) -> ExecutiveBriefItem:
        if not isinstance(card, ExecutiveInboxCard):
            raise ContractError("card must be ExecutiveInboxCard")
        return ExecutiveBriefItem(
            item_id=f"brief:{card.card_id}",
            workspace_id=card.workspace_id,
            kind=BriefItemKind.APPROVAL,
            priority=_INBOX_PRIORITY[card.priority],
            title=card.title,
            summary=card.summary,
            source_ref=f"approval:{card.approval_id}",
            actionable=card.actionable,
            due_date=card.due_date,
            evidence_refs=card.evidence_ids,
        )

    def from_cash_recommendation(
        self,
        recommendation: CashTimingRecommendation,
        *,
        workspace_id: str,
        source_ref: str,
    ) -> ExecutiveBriefItem:
        if not isinstance(recommendation, CashTimingRecommendation):
            raise ContractError("recommendation must be CashTimingRecommendation")
        workspace_id = _ref(workspace_id, "workspace_id")
        source_ref = _ref(source_ref, "source_ref")
        return ExecutiveBriefItem(
            item_id=f"brief:{source_ref}",
            workspace_id=workspace_id,
            kind=BriefItemKind.CASHFLOW,
            priority=_FINANCE_PRIORITY[recommendation.severity],
            title={
                "PROJECTED_GAP": "예상 자금 부족 검토",
                "UNCONFIRMED_DATA": "현금흐름 미확정 데이터 확인",
                "NO_GAP": "현금흐름 전망",
            }[recommendation.code],
            summary=recommendation.summary,
            source_ref=source_ref,
            actionable=recommendation.code != "NO_GAP",
            due_date=recommendation.shortage_date,
            evidence_refs=recommendation.evidence_entry_ids,
        )

    def from_operational_alert(self, alert: OperationalAlert) -> ExecutiveBriefItem:
        if not isinstance(alert, OperationalAlert):
            raise ContractError("alert must be OperationalAlert")
        return ExecutiveBriefItem(
            item_id=f"brief:{alert.alert_id}",
            workspace_id=alert.workspace_id,
            kind=BriefItemKind.OPERATIONAL_ALERT,
            priority=alert.priority,
            title=alert.title,
            summary=alert.summary,
            source_ref=alert.source_ref,
            actionable=alert.actionable,
            due_date=alert.due_date,
        )

    def build(
        self,
        *,
        workspace_id: str,
        on_date: date,
        inbox_cards: tuple[ExecutiveInboxCard, ...] = (),
        cash_recommendations: tuple[tuple[CashTimingRecommendation, str], ...] = (),
        operational_alerts: tuple[OperationalAlert, ...] = (),
        include_resolved_approvals: bool = False,
    ) -> DailyExecutiveBrief:
        workspace_id = _ref(workspace_id, "workspace_id")
        if not isinstance(on_date, date):
            raise ContractError("on_date must be date")
        for value, name, maximum in (
            (inbox_cards, "inbox_cards", 200),
            (cash_recommendations, "cash_recommendations", 100),
            (operational_alerts, "operational_alerts", 200),
        ):
            if not isinstance(value, tuple) or len(value) > maximum:
                raise ContractError(f"{name} must be a bounded tuple")

        items: list[ExecutiveBriefItem] = []
        for card in inbox_cards:
            if not isinstance(card, ExecutiveInboxCard) or card.workspace_id != workspace_id:
                raise ContractError("inbox card workspace mismatch")
            if card.status is InboxCardStatus.RESOLVED and not include_resolved_approvals:
                continue
            items.append(self.from_inbox_card(card))
        for entry in cash_recommendations:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise ContractError("cash recommendation entry must be (recommendation, source_ref)")
            recommendation, source_ref = entry
            items.append(self.from_cash_recommendation(recommendation, workspace_id=workspace_id, source_ref=source_ref))
        for alert in operational_alerts:
            if not isinstance(alert, OperationalAlert) or alert.workspace_id != workspace_id:
                raise ContractError("operational alert workspace mismatch")
            items.append(self.from_operational_alert(alert))

        items.sort(key=lambda item: (_PRIORITY_RANK[item.priority], item.due_date or date.max, item.item_id))
        return DailyExecutiveBrief(workspace_id=workspace_id, on_date=on_date, items=tuple(items))


EXECUTIVE_BRIEF_EXECUTION_AUTHORITY = False
HIDDEN_MODEL_PRIORITY_SUPPORTED = False
