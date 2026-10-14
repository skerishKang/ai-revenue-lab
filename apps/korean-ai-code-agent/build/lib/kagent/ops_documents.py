from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import re
from typing import Any, Protocol

from .contracts import ContractError
from .ops_contracts import Money, PurchaseOrder
from .ops_customer_quote import CustomerQuoteDraft


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_DOC_NUMBER_RE = re.compile(r"^(?:QT|PO)-\d{8}-\d{4}$")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _version(value: int, field_name: str = "version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{field_name} must be a positive integer")
    return value


class BusinessDocumentKind(str, Enum):
    CUSTOMER_QUOTE = "customer_quote"
    PURCHASE_ORDER = "purchase_order"


_PREFIX = {
    BusinessDocumentKind.CUSTOMER_QUOTE: "QT",
    BusinessDocumentKind.PURCHASE_ORDER: "PO",
}


@dataclass(frozen=True, slots=True)
class DocumentNumberAssignment:
    document_number: str
    workspace_id: str
    kind: BusinessDocumentKind
    subject_id: str
    subject_version: int
    issue_date: date
    sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.document_number, str) or not _DOC_NUMBER_RE.fullmatch(self.document_number):
            raise ContractError("document_number must use server-owned format")
        object.__setattr__(self, "workspace_id", _id(self.workspace_id, "workspace_id"))
        if not isinstance(self.kind, BusinessDocumentKind):
            try:
                object.__setattr__(self, "kind", BusinessDocumentKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid business document kind") from exc
        object.__setattr__(self, "subject_id", _id(self.subject_id, "subject_id"))
        object.__setattr__(self, "subject_version", _version(self.subject_version, "subject_version"))
        if not isinstance(self.issue_date, date):
            raise ContractError("issue_date must be date")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or not 1 <= self.sequence <= 9999:
            raise ContractError("document sequence must be between 1 and 9999")
        expected = f"{_PREFIX[self.kind]}-{self.issue_date.strftime('%Y%m%d')}-{self.sequence:04d}"
        if self.document_number != expected:
            raise ContractError("document number does not match kind/date/sequence")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "workspace_id": self.workspace_id,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "issue_date": self.issue_date.isoformat(),
            "sequence": self.sequence,
            "server_owned": True,
        }


class InMemoryDocumentNumberRegistry:
    def __init__(self) -> None:
        self._by_subject: dict[tuple[str, BusinessDocumentKind, str, int], DocumentNumberAssignment] = {}
        self._by_number: dict[tuple[str, str], DocumentNumberAssignment] = {}
        self._next: dict[tuple[str, BusinessDocumentKind, date], int] = {}

    def assign(
        self,
        *,
        workspace_id: str,
        kind: BusinessDocumentKind,
        subject_id: str,
        subject_version: int,
        issue_date: date,
    ) -> DocumentNumberAssignment:
        workspace_id = _id(workspace_id, "workspace_id")
        if not isinstance(kind, BusinessDocumentKind):
            try:
                kind = BusinessDocumentKind(kind)
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid business document kind") from exc
        subject_id = _id(subject_id, "subject_id")
        subject_version = _version(subject_version, "subject_version")
        if not isinstance(issue_date, date):
            raise ContractError("issue_date must be date")
        subject_key = (workspace_id, kind, subject_id, subject_version)
        existing = self._by_subject.get(subject_key)
        if existing is not None:
            if existing.issue_date != issue_date:
                raise ContractError("document number assignment date cannot change after allocation")
            return existing

        seq_key = (workspace_id, kind, issue_date)
        sequence = self._next.get(seq_key, 1)
        if sequence > 9999:
            raise ContractError("daily document number capacity exhausted")
        number = f"{_PREFIX[kind]}-{issue_date.strftime('%Y%m%d')}-{sequence:04d}"
        number_key = (workspace_id, number)
        if number_key in self._by_number:
            raise ContractError("document number collision")
        assignment = DocumentNumberAssignment(
            document_number=number,
            workspace_id=workspace_id,
            kind=kind,
            subject_id=subject_id,
            subject_version=subject_version,
            issue_date=issue_date,
            sequence=sequence,
        )
        self._by_subject[subject_key] = assignment
        self._by_number[number_key] = assignment
        self._next[seq_key] = sequence + 1
        return assignment

    def get_by_number(self, *, workspace_id: str, document_number: str) -> DocumentNumberAssignment:
        workspace_id = _id(workspace_id, "workspace_id")
        if not isinstance(document_number, str) or not _DOC_NUMBER_RE.fullmatch(document_number):
            raise ContractError("invalid document number")
        try:
            return self._by_number[(workspace_id, document_number)]
        except KeyError as exc:
            raise ContractError("document number not found") from exc


@dataclass(frozen=True, slots=True)
class CustomerQuoteDocumentManifest:
    document_number: str
    workspace_id: str
    customer_quote_id: str
    customer_quote_version: int
    customer_id: str
    issue_date: date
    title: str
    currency: str
    sale_total: Money
    pricing_fingerprint: str
    lines: tuple[dict[str, Any], ...]

    @classmethod
    def from_quote(
        cls,
        *,
        assignment: DocumentNumberAssignment,
        quote: CustomerQuoteDraft,
    ) -> "CustomerQuoteDocumentManifest":
        if not isinstance(assignment, DocumentNumberAssignment) or not isinstance(quote, CustomerQuoteDraft):
            raise ContractError("assignment and CustomerQuoteDraft are required")
        if assignment.kind is not BusinessDocumentKind.CUSTOMER_QUOTE:
            raise ContractError("customer quote requires customer-quote document number")
        if (
            assignment.workspace_id != quote.workspace_id
            or assignment.subject_id != quote.customer_quote_id
            or assignment.subject_version != quote.version
        ):
            raise ContractError("document number is not bound to this customer quote version")
        lines = tuple(
            {
                "line_id": line.line_id,
                "description": line.description,
                "quantity": format(line.quantity, "f"),
                "unit": line.unit,
                "sale_unit_price": line.sale_unit_price.safe_dict(),
                "sale_total": line.sale_total.safe_dict(),
            }
            for line in quote.lines
        )
        return cls(
            document_number=assignment.document_number,
            workspace_id=quote.workspace_id,
            customer_quote_id=quote.customer_quote_id,
            customer_quote_version=quote.version,
            customer_id=quote.customer_id,
            issue_date=assignment.issue_date,
            title=quote.title,
            currency=quote.currency,
            sale_total=quote.sale_total,
            pricing_fingerprint=quote.pricing_fingerprint,
            lines=lines,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-customer-quote-document.v1",
            "document_number": self.document_number,
            "workspace_id": self.workspace_id,
            "customer_quote_id": self.customer_quote_id,
            "customer_quote_version": self.customer_quote_version,
            "customer_id": self.customer_id,
            "issue_date": self.issue_date.isoformat(),
            "title": self.title,
            "currency": self.currency,
            "sale_total": self.sale_total.safe_dict(),
            "pricing_fingerprint": self.pricing_fingerprint,
            "lines": list(self.lines),
            "supplier_cost_exposed": False,
            "margin_exposed": False,
            "arbitrary_template_code": False,
        }


@dataclass(frozen=True, slots=True)
class PurchaseOrderDocumentManifest:
    document_number: str
    workspace_id: str
    po_id: str
    po_version: int
    supplier_id: str
    issue_date: date
    currency: str
    purchase_total: Money
    supplier_quote_id: str
    supplier_quote_version: int
    lines: tuple[dict[str, Any], ...]

    @classmethod
    def from_purchase_order(
        cls,
        *,
        assignment: DocumentNumberAssignment,
        purchase_order: PurchaseOrder,
    ) -> "PurchaseOrderDocumentManifest":
        if not isinstance(assignment, DocumentNumberAssignment) or not isinstance(purchase_order, PurchaseOrder):
            raise ContractError("assignment and PurchaseOrder are required")
        if assignment.kind is not BusinessDocumentKind.PURCHASE_ORDER:
            raise ContractError("purchase order requires PO document number")
        if (
            assignment.workspace_id != purchase_order.workspace_id
            or assignment.subject_id != purchase_order.po_id
            or assignment.subject_version != purchase_order.version
        ):
            raise ContractError("document number is not bound to this PO version")
        lines = tuple(
            {
                "line_id": line.line_id,
                "description": line.description,
                "quantity": format(line.quantity, "f"),
                "unit": line.unit,
                "unit_price": line.unit_price.safe_dict(),
                "total": line.total.safe_dict(),
            }
            for line in purchase_order.lines
        )
        total = purchase_order.total
        return cls(
            document_number=assignment.document_number,
            workspace_id=purchase_order.workspace_id,
            po_id=purchase_order.po_id,
            po_version=purchase_order.version,
            supplier_id=purchase_order.supplier_id,
            issue_date=assignment.issue_date,
            currency=total.currency,
            purchase_total=total,
            supplier_quote_id=purchase_order.supplier_quote_id,
            supplier_quote_version=purchase_order.supplier_quote_version,
            lines=lines,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-purchase-order-document.v1",
            "document_number": self.document_number,
            "workspace_id": self.workspace_id,
            "po_id": self.po_id,
            "po_version": self.po_version,
            "supplier_id": self.supplier_id,
            "issue_date": self.issue_date.isoformat(),
            "currency": self.currency,
            "purchase_total": self.purchase_total.safe_dict(),
            "supplier_quote_id": self.supplier_quote_id,
            "supplier_quote_version": self.supplier_quote_version,
            "lines": list(self.lines),
            "customer_sale_price_exposed": False,
            "customer_identity_exposed": False,
            "arbitrary_template_code": False,
        }


class BusinessDocumentRendererPort(Protocol):
    def render(self, manifest: CustomerQuoteDocumentManifest | PurchaseOrderDocumentManifest) -> str:
        ...


class UnconfiguredBusinessDocumentRenderer:
    def render(self, manifest: CustomerQuoteDocumentManifest | PurchaseOrderDocumentManifest) -> str:
        raise ContractError("business document renderer is not configured")


REAL_BUSINESS_DOCUMENT_RENDERER_CONFIGURED = False
MODEL_ASSIGNED_OFFICIAL_DOCUMENT_NUMBER_SUPPORTED = False
