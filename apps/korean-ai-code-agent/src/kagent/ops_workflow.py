from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Callable, Protocol

from .contracts import ContractError
from .ops_contracts import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalProjection,
    ArtifactRef,
    BusinessObjectKind,
    CommercialRequest,
    EvidenceOrigin,
    NegotiationDraft,
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    QuoteComparison,
    QuoteComparisonEntry,
    RecommendationKind,
    RfqStatus,
    Supplier,
    SupplierQuote,
    SupplierQuoteRequest,
    SupplierQuoteStatus,
    WorkflowEvidenceRecord,
)
from .ops_ledger import BusinessObjectEnvelope, InMemoryOpsLedger


class OpsWorkflowError(ContractError):
    pass


@dataclass(frozen=True, slots=True)
class OutboundActionResult:
    action_id: str
    channel: str
    external_ref: str
    completed_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("action_id", "channel", "external_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
                raise OpsWorkflowError(f"{field_name} must be a bounded non-empty string")
            object.__setattr__(self, field_name, value.strip())
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise OpsWorkflowError("completed_at must be timezone-aware")
        object.__setattr__(self, "completed_at", self.completed_at.astimezone(timezone.utc))


class OpsOutboundPort(Protocol):
    def send_rfq(self, rfq: SupplierQuoteRequest) -> OutboundActionResult:
        ...

    def send_negotiation(self, draft: NegotiationDraft) -> OutboundActionResult:
        ...

    def send_purchase_order(self, purchase_order: PurchaseOrder) -> OutboundActionResult:
        ...


class UnconfiguredOpsOutboundPort:
    def send_rfq(self, rfq: SupplierQuoteRequest) -> OutboundActionResult:
        raise OpsWorkflowError("Claw Ops outbound connector is not configured")

    def send_negotiation(self, draft: NegotiationDraft) -> OutboundActionResult:
        raise OpsWorkflowError("Claw Ops outbound connector is not configured")

    def send_purchase_order(self, purchase_order: PurchaseOrder) -> OutboundActionResult:
        raise OpsWorkflowError("Claw Ops outbound connector is not configured")


class DeterministicFakeOpsOutboundPort:
    """Network-free fake for contract tests only."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.sent: list[tuple[str, str, int]] = []

    @staticmethod
    def _ref(prefix: str, object_id: str, version: int) -> str:
        digest = hashlib.sha256(f"{prefix}:{object_id}:{version}".encode("utf-8")).hexdigest()[:20]
        return f"fake-{prefix}-{digest}"

    def send_rfq(self, rfq: SupplierQuoteRequest) -> OutboundActionResult:
        self.sent.append(("rfq", rfq.rfq_id, rfq.version))
        return OutboundActionResult(
            action_id=f"send-rfq-{rfq.rfq_id}-v{rfq.version}",
            channel="fake",
            external_ref=self._ref("rfq", rfq.rfq_id, rfq.version),
            completed_at=self._clock(),
        )

    def send_negotiation(self, draft: NegotiationDraft) -> OutboundActionResult:
        self.sent.append(("negotiation", draft.negotiation_id, draft.version))
        return OutboundActionResult(
            action_id=f"send-negotiation-{draft.negotiation_id}-v{draft.version}",
            channel="fake",
            external_ref=self._ref("negotiation", draft.negotiation_id, draft.version),
            completed_at=self._clock(),
        )

    def send_purchase_order(self, purchase_order: PurchaseOrder) -> OutboundActionResult:
        self.sent.append(("po", purchase_order.po_id, purchase_order.version))
        return OutboundActionResult(
            action_id=f"send-po-{purchase_order.po_id}-v{purchase_order.version}",
            channel="fake",
            external_ref=self._ref("po", purchase_order.po_id, purchase_order.version),
            completed_at=self._clock(),
        )


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def rfq_action_fingerprint(rfq: SupplierQuoteRequest) -> str:
    return _fingerprint(
        {
            "action": ApprovalAction.SEND_RFQ.value,
            "rfq_id": rfq.rfq_id,
            "version": rfq.version,
            "workspace_id": rfq.workspace_id,
            "commercial_request_id": rfq.commercial_request_id,
            "commercial_request_version": rfq.commercial_request_version,
            "supplier_id": rfq.supplier_id,
            "line_items": [item.safe_dict() for item in rfq.line_items],
            "message": rfq.message,
        }
    )


def negotiation_action_fingerprint(draft: NegotiationDraft) -> str:
    return _fingerprint(
        {
            "action": ApprovalAction.SEND_NEGOTIATION.value,
            "negotiation_id": draft.negotiation_id,
            "version": draft.version,
            "workspace_id": draft.workspace_id,
            "supplier_id": draft.supplier_id,
            "quote_id": draft.quote_id,
            "quote_version": draft.quote_version,
            "message": draft.message,
            "target_total": draft.target_total.safe_dict() if draft.target_total else None,
        }
    )


def purchase_order_action_fingerprint(purchase_order: PurchaseOrder) -> str:
    return _fingerprint(
        {
            "action": ApprovalAction.ISSUE_PURCHASE_ORDER.value,
            "po_id": purchase_order.po_id,
            "version": purchase_order.version,
            "workspace_id": purchase_order.workspace_id,
            "supplier_id": purchase_order.supplier_id,
            "supplier_quote_id": purchase_order.supplier_quote_id,
            "supplier_quote_version": purchase_order.supplier_quote_version,
            "lines": [
                {
                    "line_id": line.line_id,
                    "description": line.description,
                    "quantity": format(line.quantity, "f"),
                    "unit": line.unit,
                    "unit_price": line.unit_price.safe_dict(),
                }
                for line in purchase_order.lines
            ],
            "requested_delivery_date": (
                purchase_order.requested_delivery_date.isoformat()
                if purchase_order.requested_delivery_date
                else None
            ),
            "payment_terms": (
                {
                    "terms_id": purchase_order.payment_terms.terms_id,
                    "label": purchase_order.payment_terms.label,
                    "due_days": purchase_order.payment_terms.due_days,
                    "prepaid": purchase_order.payment_terms.prepaid,
                }
                if purchase_order.payment_terms
                else None
            ),
        }
    )


class QuoteToOrderCoordinator:
    """Product-owned Quote-to-Order workflow coordinator.

    Generic Agent/Tool/Approval semantics remain P01-owned. This coordinator only
    manages Claw Ops business records, exact-version approval projections and an
    injected outbound connector.
    """

    def __init__(
        self,
        *,
        ledger: InMemoryOpsLedger | None = None,
        outbound: OpsOutboundPort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.ledger = ledger or InMemoryOpsLedger()
        self.outbound = outbound or UnconfiguredOpsOutboundPort()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise OpsWorkflowError("clock must return timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def _append(
        self,
        *,
        kind: BusinessObjectKind,
        object_id: str,
        version: int,
        workspace_id: str,
        value: object,
    ) -> None:
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=kind,
                object_id=object_id,
                version=version,
                workspace_id=workspace_id,
                value=value,
            )
        )

    def _latest_value(
        self,
        *,
        workspace_id: str,
        kind: BusinessObjectKind,
        object_id: str,
        expected_type: type,
    ) -> object:
        value = self.ledger.latest_object(
            workspace_id=workspace_id,
            kind=kind,
            object_id=object_id,
        ).value
        if not isinstance(value, expected_type):
            raise OpsWorkflowError("ledger object has unexpected type")
        return value

    def register_request(self, request: CommercialRequest) -> CommercialRequest:
        self._append(
            kind=BusinessObjectKind.COMMERCIAL_REQUEST,
            object_id=request.request_id,
            version=request.version,
            workspace_id=request.workspace_id,
            value=request,
        )
        return request

    def draft_supplier_rfq(
        self,
        *,
        request: CommercialRequest,
        supplier: Supplier,
        rfq_id: str,
        message: str = "",
    ) -> SupplierQuoteRequest:
        latest = self._latest_value(
            workspace_id=request.workspace_id,
            kind=BusinessObjectKind.COMMERCIAL_REQUEST,
            object_id=request.request_id,
            expected_type=CommercialRequest,
        )
        assert isinstance(latest, CommercialRequest)
        if latest.version != request.version:
            raise OpsWorkflowError("cannot draft RFQ from a stale commercial request")
        if supplier.workspace_id != request.workspace_id:
            raise OpsWorkflowError("supplier belongs to another workspace")
        if not supplier.active:
            raise OpsWorkflowError("inactive supplier cannot receive an RFQ")

        rfq = SupplierQuoteRequest(
            rfq_id=rfq_id,
            workspace_id=request.workspace_id,
            commercial_request_id=request.request_id,
            commercial_request_version=request.version,
            supplier_id=supplier.supplier_id,
            version=1,
            line_items=request.line_items,
            status=RfqStatus.APPROVAL_REQUIRED,
            message=message,
        )
        self._append(
            kind=BusinessObjectKind.SUPPLIER_RFQ,
            object_id=rfq.rfq_id,
            version=rfq.version,
            workspace_id=rfq.workspace_id,
            value=rfq,
        )
        return rfq

    def project_rfq_approval(self, *, rfq: SupplierQuoteRequest, approval_id: str) -> ApprovalProjection:
        approval = ApprovalProjection(
            approval_id=approval_id,
            workspace_id=rfq.workspace_id,
            action=ApprovalAction.SEND_RFQ,
            target_kind=BusinessObjectKind.SUPPLIER_RFQ,
            target_id=rfq.rfq_id,
            target_version=rfq.version,
            action_fingerprint=rfq_action_fingerprint(rfq),
        )
        self.ledger.add_approval_projection(approval)
        return approval

    def record_approval_projection(self, approval: ApprovalProjection) -> ApprovalProjection:
        """Record a trusted projection of an approval decision made by P01/owner UI."""
        self.ledger.add_approval_projection(approval)
        return approval

    def send_rfq(self, *, workspace_id: str, rfq_id: str, approval_id: str) -> SupplierQuoteRequest:
        rfq = self._latest_value(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.SUPPLIER_RFQ,
            object_id=rfq_id,
            expected_type=SupplierQuoteRequest,
        )
        assert isinstance(rfq, SupplierQuoteRequest)
        if rfq.status is not RfqStatus.APPROVAL_REQUIRED:
            raise OpsWorkflowError("RFQ is not waiting for outbound approval")
        self.ledger.require_approved_action(
            approval_id=approval_id,
            workspace_id=workspace_id,
            action=ApprovalAction.SEND_RFQ,
            target_kind=BusinessObjectKind.SUPPLIER_RFQ,
            target_id=rfq.rfq_id,
            target_version=rfq.version,
            action_fingerprint=rfq_action_fingerprint(rfq),
        )
        result = self.outbound.send_rfq(rfq)
        sent = SupplierQuoteRequest(
            rfq_id=rfq.rfq_id,
            workspace_id=rfq.workspace_id,
            commercial_request_id=rfq.commercial_request_id,
            commercial_request_version=rfq.commercial_request_version,
            supplier_id=rfq.supplier_id,
            version=rfq.version + 1,
            line_items=rfq.line_items,
            status=RfqStatus.SENT,
            message=rfq.message,
        )
        self._append(
            kind=BusinessObjectKind.SUPPLIER_RFQ,
            object_id=sent.rfq_id,
            version=sent.version,
            workspace_id=sent.workspace_id,
            value=sent,
        )
        self.ledger.add_evidence(
            WorkflowEvidenceRecord(
                evidence_id=self._evidence_id("rfq", sent.rfq_id, sent.version, result.external_ref),
                workspace_id=sent.workspace_id,
                workflow_id=sent.commercial_request_id,
                object_kind=BusinessObjectKind.SUPPLIER_RFQ,
                object_id=sent.rfq_id,
                object_version=sent.version,
                origin=EvidenceOrigin.CONNECTOR_RESULT,
                source_ref=result.external_ref,
                summary=f"RFQ delivered through {result.channel}",
                recorded_at=result.completed_at,
                authoritative=True,
                metadata=(("action_id", result.action_id), ("channel", result.channel)),
            )
        )
        return sent

    def capture_supplier_quote(self, quote: SupplierQuote) -> SupplierQuote:
        rfq = self._latest_value(
            workspace_id=quote.workspace_id,
            kind=BusinessObjectKind.SUPPLIER_RFQ,
            object_id=quote.rfq_id,
            expected_type=SupplierQuoteRequest,
        )
        assert isinstance(rfq, SupplierQuoteRequest)
        if rfq.status is not RfqStatus.SENT:
            raise OpsWorkflowError("supplier quote cannot be attached to an unsent RFQ")
        if rfq.supplier_id != quote.supplier_id:
            raise OpsWorkflowError("supplier quote does not match the RFQ supplier")
        if {item.line_id for item in rfq.line_items} != {line.line_id for line in quote.lines}:
            raise OpsWorkflowError("supplier quote line set must match the RFQ line set")
        self._append(
            kind=BusinessObjectKind.SUPPLIER_QUOTE,
            object_id=quote.quote_id,
            version=quote.version,
            workspace_id=quote.workspace_id,
            value=quote,
        )
        return quote

    def build_comparison(
        self,
        *,
        workspace_id: str,
        commercial_request_id: str,
        comparison_id: str,
        quote_ids: tuple[str, ...],
    ) -> QuoteComparison:
        if not isinstance(quote_ids, tuple) or not quote_ids:
            raise OpsWorkflowError("quote_ids must be a non-empty tuple")
        entries: list[QuoteComparisonEntry] = []
        for quote_id in quote_ids:
            quote = self._latest_value(
                workspace_id=workspace_id,
                kind=BusinessObjectKind.SUPPLIER_QUOTE,
                object_id=quote_id,
                expected_type=SupplierQuote,
            )
            assert isinstance(quote, SupplierQuote)
            if quote.status not in {SupplierQuoteStatus.RECEIVED, SupplierQuoteStatus.REVISED}:
                raise OpsWorkflowError("comparison may only use active received/revised supplier quotes")
            rfq = self._latest_value(
                workspace_id=workspace_id,
                kind=BusinessObjectKind.SUPPLIER_RFQ,
                object_id=quote.rfq_id,
                expected_type=SupplierQuoteRequest,
            )
            assert isinstance(rfq, SupplierQuoteRequest)
            if rfq.commercial_request_id != commercial_request_id:
                raise OpsWorkflowError("quote belongs to a different commercial request")
            entries.append(
                QuoteComparisonEntry(
                    supplier_id=quote.supplier_id,
                    quote_id=quote.quote_id,
                    quote_version=quote.version,
                    total=quote.total,
                    promised_delivery_date=quote.promised_delivery_date,
                    payment_terms_label=quote.payment_terms.label if quote.payment_terms else "",
                )
            )
        lowest = min(entries, key=lambda item: (item.total.amount_minor, item.supplier_id))
        comparison = QuoteComparison(
            comparison_id=comparison_id,
            workspace_id=workspace_id,
            commercial_request_id=commercial_request_id,
            version=1,
            entries=tuple(entries),
            recommendation=RecommendationKind.LOWEST_PRICE,
            recommended_supplier_id=lowest.supplier_id,
            recommendation_summary="Deterministic lowest-price projection from captured supplier quotes.",
        )
        self._append(
            kind=BusinessObjectKind.QUOTE_COMPARISON,
            object_id=comparison.comparison_id,
            version=comparison.version,
            workspace_id=workspace_id,
            value=comparison,
        )
        return comparison

    def draft_negotiation(
        self,
        *,
        workspace_id: str,
        negotiation_id: str,
        quote_id: str,
        message: str,
        target_total=None,
    ) -> NegotiationDraft:
        quote = self._latest_value(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.SUPPLIER_QUOTE,
            object_id=quote_id,
            expected_type=SupplierQuote,
        )
        assert isinstance(quote, SupplierQuote)
        draft = NegotiationDraft(
            negotiation_id=negotiation_id,
            workspace_id=workspace_id,
            supplier_id=quote.supplier_id,
            quote_id=quote.quote_id,
            quote_version=quote.version,
            version=1,
            message=message,
            target_total=target_total,
        )
        self._append(
            kind=BusinessObjectKind.NEGOTIATION_DRAFT,
            object_id=draft.negotiation_id,
            version=draft.version,
            workspace_id=workspace_id,
            value=draft,
        )
        return draft

    def project_negotiation_approval(
        self,
        *,
        draft: NegotiationDraft,
        approval_id: str,
    ) -> ApprovalProjection:
        approval = ApprovalProjection(
            approval_id=approval_id,
            workspace_id=draft.workspace_id,
            action=ApprovalAction.SEND_NEGOTIATION,
            target_kind=BusinessObjectKind.NEGOTIATION_DRAFT,
            target_id=draft.negotiation_id,
            target_version=draft.version,
            action_fingerprint=negotiation_action_fingerprint(draft),
        )
        self.ledger.add_approval_projection(approval)
        return approval

    def send_negotiation(
        self,
        *,
        workspace_id: str,
        negotiation_id: str,
        approval_id: str,
    ) -> OutboundActionResult:
        draft = self._latest_value(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.NEGOTIATION_DRAFT,
            object_id=negotiation_id,
            expected_type=NegotiationDraft,
        )
        assert isinstance(draft, NegotiationDraft)
        self.ledger.require_approved_action(
            approval_id=approval_id,
            workspace_id=workspace_id,
            action=ApprovalAction.SEND_NEGOTIATION,
            target_kind=BusinessObjectKind.NEGOTIATION_DRAFT,
            target_id=draft.negotiation_id,
            target_version=draft.version,
            action_fingerprint=negotiation_action_fingerprint(draft),
        )
        return self.outbound.send_negotiation(draft)

    def draft_purchase_order(
        self,
        *,
        workspace_id: str,
        commercial_request_id: str,
        quote_id: str,
        po_id: str,
        payment_terms: PaymentTerms | None = None,
    ) -> PurchaseOrder:
        request = self._latest_value(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.COMMERCIAL_REQUEST,
            object_id=commercial_request_id,
            expected_type=CommercialRequest,
        )
        quote = self._latest_value(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.SUPPLIER_QUOTE,
            object_id=quote_id,
            expected_type=SupplierQuote,
        )
        assert isinstance(request, CommercialRequest)
        assert isinstance(quote, SupplierQuote)
        rfq = self._latest_value(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.SUPPLIER_RFQ,
            object_id=quote.rfq_id,
            expected_type=SupplierQuoteRequest,
        )
        assert isinstance(rfq, SupplierQuoteRequest)
        if rfq.commercial_request_id != request.request_id:
            raise OpsWorkflowError("selected quote belongs to another commercial request")
        requested_lines = {line.line_id: line for line in request.line_items}
        if set(requested_lines) != {line.line_id for line in quote.lines}:
            raise OpsWorkflowError("selected quote does not cover the current request line set")
        po_lines = tuple(
            PurchaseOrderLine(
                line_id=quote_line.line_id,
                description=requested_lines[quote_line.line_id].description,
                quantity=quote_line.quantity,
                unit=requested_lines[quote_line.line_id].unit,
                unit_price=quote_line.unit_price,
            )
            for quote_line in quote.lines
        )
        po = PurchaseOrder(
            po_id=po_id,
            workspace_id=workspace_id,
            supplier_id=quote.supplier_id,
            supplier_quote_id=quote.quote_id,
            supplier_quote_version=quote.version,
            version=1,
            lines=po_lines,
            status=PurchaseOrderStatus.APPROVAL_REQUIRED,
            requested_delivery_date=quote.promised_delivery_date or request.requested_delivery_date,
            payment_terms=payment_terms or quote.payment_terms,
        )
        self._append(
            kind=BusinessObjectKind.PURCHASE_ORDER,
            object_id=po.po_id,
            version=po.version,
            workspace_id=workspace_id,
            value=po,
        )
        return po

    def project_purchase_order_approval(
        self,
        *,
        purchase_order: PurchaseOrder,
        approval_id: str,
    ) -> ApprovalProjection:
        approval = ApprovalProjection(
            approval_id=approval_id,
            workspace_id=purchase_order.workspace_id,
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id=purchase_order.po_id,
            target_version=purchase_order.version,
            action_fingerprint=purchase_order_action_fingerprint(purchase_order),
        )
        self.ledger.add_approval_projection(approval)
        return approval

    def issue_purchase_order(
        self,
        *,
        workspace_id: str,
        po_id: str,
        approval_id: str,
    ) -> PurchaseOrder:
        po = self._latest_value(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.PURCHASE_ORDER,
            object_id=po_id,
            expected_type=PurchaseOrder,
        )
        assert isinstance(po, PurchaseOrder)
        if po.status is not PurchaseOrderStatus.APPROVAL_REQUIRED:
            raise OpsWorkflowError("purchase order is not waiting for issue approval")
        self.ledger.require_approved_action(
            approval_id=approval_id,
            workspace_id=workspace_id,
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id=po.po_id,
            target_version=po.version,
            action_fingerprint=purchase_order_action_fingerprint(po),
        )
        result = self.outbound.send_purchase_order(po)
        issued = PurchaseOrder(
            po_id=po.po_id,
            workspace_id=po.workspace_id,
            supplier_id=po.supplier_id,
            supplier_quote_id=po.supplier_quote_id,
            supplier_quote_version=po.supplier_quote_version,
            version=po.version + 1,
            lines=po.lines,
            status=PurchaseOrderStatus.ISSUED,
            requested_delivery_date=po.requested_delivery_date,
            payment_terms=po.payment_terms,
            document_artifact=po.document_artifact,
        )
        self._append(
            kind=BusinessObjectKind.PURCHASE_ORDER,
            object_id=issued.po_id,
            version=issued.version,
            workspace_id=workspace_id,
            value=issued,
        )
        self.ledger.add_evidence(
            WorkflowEvidenceRecord(
                evidence_id=self._evidence_id("po", issued.po_id, issued.version, result.external_ref),
                workspace_id=workspace_id,
                workflow_id=po.supplier_quote_id,
                object_kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id=issued.po_id,
                object_version=issued.version,
                origin=EvidenceOrigin.CONNECTOR_RESULT,
                source_ref=result.external_ref,
                summary=f"Purchase order delivered through {result.channel}",
                recorded_at=result.completed_at,
                authoritative=True,
                metadata=(("action_id", result.action_id), ("channel", result.channel)),
            )
        )
        return issued

    @staticmethod
    def approved_projection(pending: ApprovalProjection, *, actor_ref: str, decided_at: datetime) -> ApprovalProjection:
        """Test/helper projection only; does not validate a real P01 approval token."""
        if pending.decision is not ApprovalDecision.PENDING:
            raise OpsWorkflowError("only a pending approval can be projected as approved")
        return ApprovalProjection(
            approval_id=pending.approval_id,
            workspace_id=pending.workspace_id,
            action=pending.action,
            target_kind=pending.target_kind,
            target_id=pending.target_id,
            target_version=pending.target_version,
            action_fingerprint=pending.action_fingerprint,
            decision=ApprovalDecision.APPROVED,
            actor_ref=actor_ref,
            decided_at=decided_at,
        )

    @staticmethod
    def _evidence_id(prefix: str, object_id: str, version: int, external_ref: str) -> str:
        digest = hashlib.sha256(
            f"{prefix}:{object_id}:{version}:{external_ref}".encode("utf-8")
        ).hexdigest()[:24]
        return f"ev_{digest}"
