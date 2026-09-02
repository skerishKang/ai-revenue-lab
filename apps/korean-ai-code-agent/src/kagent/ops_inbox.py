from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

from .contracts import ContractError
from .ops_contracts import (
    AccountingHandoff,
    ApprovalAction,
    ApprovalDecision,
    ApprovalProjection,
    BusinessObjectKind,
    DeliveryCommitment,
    Money,
    NegotiationDraft,
    PurchaseOrder,
    QuoteComparison,
    SupplierQuoteRequest,
)
from .ops_ledger import InMemoryOpsLedger
from .security import redact_secrets


class InboxCardKind(str, Enum):
    RFQ_APPROVAL = "rfq_approval"
    SUPPLIER_SELECTION = "supplier_selection"
    NEGOTIATION_APPROVAL = "negotiation_approval"
    PURCHASE_ORDER_APPROVAL = "purchase_order_approval"
    ACCOUNTING_WRITE_APPROVAL = "accounting_write_approval"
    PAYMENT_APPROVAL = "payment_approval"
    GENERIC_APPROVAL = "generic_approval"


class InboxCardStatus(str, Enum):
    OPEN = "open"
    STALE = "stale"
    RESOLVED = "resolved"


class InboxPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_ACTION_CARD_KIND: dict[ApprovalAction, InboxCardKind] = {
    ApprovalAction.SEND_RFQ: InboxCardKind.RFQ_APPROVAL,
    ApprovalAction.SELECT_SUPPLIER: InboxCardKind.SUPPLIER_SELECTION,
    ApprovalAction.SEND_NEGOTIATION: InboxCardKind.NEGOTIATION_APPROVAL,
    ApprovalAction.ISSUE_PURCHASE_ORDER: InboxCardKind.PURCHASE_ORDER_APPROVAL,
    ApprovalAction.ACCOUNTING_WRITE: InboxCardKind.ACCOUNTING_WRITE_APPROVAL,
    ApprovalAction.PAYMENT: InboxCardKind.PAYMENT_APPROVAL,
}

_ACTION_PRIORITY: dict[ApprovalAction, InboxPriority] = {
    ApprovalAction.PAYMENT: InboxPriority.HIGH,
    ApprovalAction.ACCOUNTING_WRITE: InboxPriority.HIGH,
    ApprovalAction.ISSUE_PURCHASE_ORDER: InboxPriority.HIGH,
    ApprovalAction.SELECT_SUPPLIER: InboxPriority.MEDIUM,
    ApprovalAction.SEND_NEGOTIATION: InboxPriority.MEDIUM,
    ApprovalAction.SEND_RFQ: InboxPriority.LOW,
}


@dataclass(frozen=True, slots=True)
class ExecutiveInboxCard:
    card_id: str
    workspace_id: str
    kind: InboxCardKind
    status: InboxCardStatus
    priority: InboxPriority
    title: str
    summary: str
    approval_id: str
    action: ApprovalAction
    target_kind: BusinessObjectKind
    target_id: str
    target_version: int
    action_fingerprint: str
    supplier_ref: str | None = None
    amount: Money | None = None
    due_date: date | None = None
    evidence_ids: tuple[str, ...] = ()
    decision: ApprovalDecision = ApprovalDecision.PENDING

    def __post_init__(self) -> None:
        for name in ("card_id", "workspace_id", "approval_id", "target_id", "action_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"{name} is required")
            if len(value) > 256:
                raise ContractError(f"{name} exceeds 256 characters")
        if not isinstance(self.kind, InboxCardKind):
            raise ContractError("kind must be InboxCardKind")
        if not isinstance(self.status, InboxCardStatus):
            raise ContractError("status must be InboxCardStatus")
        if not isinstance(self.priority, InboxPriority):
            raise ContractError("priority must be InboxPriority")
        if not isinstance(self.action, ApprovalAction):
            raise ContractError("action must be ApprovalAction")
        if not isinstance(self.target_kind, BusinessObjectKind):
            raise ContractError("target_kind must be BusinessObjectKind")
        if not isinstance(self.decision, ApprovalDecision):
            raise ContractError("decision must be ApprovalDecision")
        if isinstance(self.target_version, bool) or not isinstance(self.target_version, int) or self.target_version < 1:
            raise ContractError("target_version must be a positive integer")
        for name in ("title", "summary"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"{name} is required")
            if len(value) > (300 if name == "title" else 2000):
                raise ContractError(f"{name} is too long")
        if self.supplier_ref is not None and (not isinstance(self.supplier_ref, str) or not self.supplier_ref.strip()):
            raise ContractError("supplier_ref must be a non-empty string or None")
        if self.amount is not None and not isinstance(self.amount, Money):
            raise ContractError("amount must be Money or None")
        if self.due_date is not None and not isinstance(self.due_date, date):
            raise ContractError("due_date must be date or None")
        if not isinstance(self.evidence_ids, tuple) or len(self.evidence_ids) > 20:
            raise ContractError("evidence_ids must be a tuple with at most 20 entries")
        if any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in self.evidence_ids):
            raise ContractError("evidence_ids contains an invalid identifier")

    @property
    def actionable(self) -> bool:
        return self.status is InboxCardStatus.OPEN and self.decision is ApprovalDecision.PENDING

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-inbox-card.v1",
            "card_id": self.card_id,
            "workspace_id": self.workspace_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "title": redact_secrets(self.title),
            "summary": redact_secrets(self.summary),
            "approval_id": self.approval_id,
            "action": self.action.value,
            "target_kind": self.target_kind.value,
            "target_id": self.target_id,
            "target_version": self.target_version,
            "action_fingerprint": self.action_fingerprint,
            "supplier_ref": self.supplier_ref,
            "amount": self.amount.safe_dict() if self.amount else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "evidence_ids": list(self.evidence_ids),
            "decision": self.decision.value,
            "actionable": self.actionable,
        }


class ExecutiveInboxProjector:
    """Build read-only owner/manager decision cards from product projections.

    The projector cannot approve, reject, resume, or execute anything. Approval
    verification and continuation remain in P01 and trusted application surfaces.
    """

    def __init__(self, ledger: InMemoryOpsLedger) -> None:
        if not isinstance(ledger, InMemoryOpsLedger):
            raise ContractError("ledger must be InMemoryOpsLedger")
        self.ledger = ledger

    def project(self, approval: ApprovalProjection) -> ExecutiveInboxCard:
        if not isinstance(approval, ApprovalProjection):
            raise ContractError("approval must be ApprovalProjection")
        exact = self.ledger.get_object(
            workspace_id=approval.workspace_id,
            kind=approval.target_kind,
            object_id=approval.target_id,
            version=approval.target_version,
        )
        latest = self.ledger.latest_object(
            workspace_id=approval.workspace_id,
            kind=approval.target_kind,
            object_id=approval.target_id,
        )

        if approval.decision is not ApprovalDecision.PENDING:
            status = InboxCardStatus.RESOLVED
        elif latest.version != approval.target_version:
            status = InboxCardStatus.STALE
        else:
            status = InboxCardStatus.OPEN

        title, summary, supplier_ref, amount, due_date = self._present(exact.value, approval)
        evidence = self.ledger.evidence_for_object(
            workspace_id=approval.workspace_id,
            kind=approval.target_kind,
            object_id=approval.target_id,
            version=approval.target_version,
        )
        evidence_ids = tuple(item.evidence_id for item in evidence[:20])

        return ExecutiveInboxCard(
            card_id=f"card_{approval.approval_id}",
            workspace_id=approval.workspace_id,
            kind=_ACTION_CARD_KIND.get(approval.action, InboxCardKind.GENERIC_APPROVAL),
            status=status,
            priority=_ACTION_PRIORITY.get(approval.action, InboxPriority.MEDIUM),
            title=title,
            summary=summary,
            approval_id=approval.approval_id,
            action=approval.action,
            target_kind=approval.target_kind,
            target_id=approval.target_id,
            target_version=approval.target_version,
            action_fingerprint=approval.action_fingerprint,
            supplier_ref=supplier_ref,
            amount=amount,
            due_date=due_date,
            evidence_ids=evidence_ids,
            decision=approval.decision,
        )

    def project_many(
        self,
        approvals: tuple[ApprovalProjection, ...],
        *,
        workspace_id: str,
    ) -> tuple[ExecutiveInboxCard, ...]:
        if not isinstance(approvals, tuple) or len(approvals) > 200:
            raise ContractError("approvals must be a tuple with at most 200 entries")
        cards: list[ExecutiveInboxCard] = []
        for approval in approvals:
            if not isinstance(approval, ApprovalProjection):
                raise ContractError("approvals must contain ApprovalProjection values")
            if approval.workspace_id != workspace_id:
                raise ContractError("cross-workspace approval cannot enter this inbox")
            cards.append(self.project(approval))
        rank = {
            InboxPriority.HIGH: 0,
            InboxPriority.MEDIUM: 1,
            InboxPriority.LOW: 2,
        }
        return tuple(sorted(cards, key=lambda card: (rank[card.priority], card.card_id)))

    @staticmethod
    def _present(
        value: object,
        approval: ApprovalProjection,
    ) -> tuple[str, str, str | None, Money | None, date | None]:
        if isinstance(value, SupplierQuoteRequest):
            return (
                "공급사 견적요청 전송 승인",
                f"공급사 {value.supplier_id}에 RFQ v{value.version} 전송 승인이 필요합니다.",
                value.supplier_id,
                None,
                None,
            )
        if isinstance(value, NegotiationDraft):
            return (
                "가격 협상 메시지 전송 승인",
                f"공급사 {value.supplier_id} 대상 협상안 v{value.version}을 검토하세요.",
                value.supplier_id,
                value.target_total,
                None,
            )
        if isinstance(value, PurchaseOrder):
            return (
                "발주서 발행 승인",
                f"공급사 {value.supplier_id} 발주서 v{value.version}, 총액 {value.total.amount_minor} {value.total.currency}.",
                value.supplier_id,
                value.total,
                value.requested_delivery_date,
            )
        if isinstance(value, QuoteComparison):
            selected = value.recommended_supplier_id or "미선택"
            return (
                "공급사 선택 검토",
                f"견적 비교 v{value.version}; 현재 추천 공급사: {selected}.",
                value.recommended_supplier_id,
                None,
                None,
            )
        if isinstance(value, AccountingHandoff):
            return (
                "회계 반영 승인",
                f"발주 {value.po_id} 관련 회계 handoff v{value.version}을 검토하세요.",
                None,
                value.obligation_amount,
                value.expected_payment_date,
            )
        if isinstance(value, DeliveryCommitment):
            return (
                "납기 관련 결정",
                f"발주 {value.po_id} 납기 상태 {value.status.value}.",
                None,
                None,
                value.promised_date,
            )
        return (
            "업무 승인 필요",
            f"{approval.target_kind.value} {approval.target_id} v{approval.target_version}에 대한 {approval.action.value} 결정을 검토하세요.",
            None,
            None,
            None,
        )
