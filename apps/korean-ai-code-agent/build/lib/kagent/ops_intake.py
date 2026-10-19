from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Protocol

from .contracts import ContractError
from .ops_communications import AttachmentMetadata
from .ops_contracts import CommercialRequest, LineItem


class IntakeSourceKind(str, Enum):
    PDF = "pdf"
    XLSX = "xlsx"
    XLS = "xls"
    CSV = "csv"
    EMAIL_ATTACHMENT = "email_attachment"
    MANUAL = "manual"


class ExtractionOrigin(str, Enum):
    OCR = "ocr"
    MODEL = "model"
    RULE = "rule"
    MANUAL = "manual"


class FieldReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    UNKNOWN = "unknown"


def _ref(value: str, field_name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise ContractError(f"{field_name} must be a bounded non-empty reference")
    return value


def _bounded(value: str, field_name: str, *, limit: int = 2000, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not allow_empty and not value:
        raise ContractError(f"{field_name} is required")
    if len(value) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    return value


def _confidence(value: object) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ContractError("confidence must not use binary float")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ContractError("confidence must be decimal-compatible") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise ContractError("confidence must be between 0 and 1")
    return result


@dataclass(frozen=True, slots=True)
class IntakeSource:
    source_id: str
    workspace_id: str
    kind: IntakeSourceKind
    attachment: AttachmentMetadata | None = None
    manual_source_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _ref(self.source_id, "source_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        if not isinstance(self.kind, IntakeSourceKind):
            raise ContractError("kind must be IntakeSourceKind")
        if self.kind is IntakeSourceKind.MANUAL:
            if self.attachment is not None:
                raise ContractError("manual source cannot carry attachment metadata")
            if self.manual_source_ref is None:
                raise ContractError("manual source requires manual_source_ref")
            object.__setattr__(self, "manual_source_ref", _ref(self.manual_source_ref, "manual_source_ref"))
        else:
            if not isinstance(self.attachment, AttachmentMetadata):
                raise ContractError("document source requires attachment metadata")
            if self.manual_source_ref is not None:
                raise ContractError("document source cannot carry manual_source_ref")

    @property
    def immutable_content_ref(self) -> str:
        if self.attachment is not None:
            return f"sha256:{self.attachment.sha256}"
        assert self.manual_source_ref is not None
        return self.manual_source_ref


@dataclass(frozen=True, slots=True)
class ExtractedField:
    field_id: str
    raw_value: str | None
    confidence: Decimal
    origin: ExtractionOrigin
    source_locator: str
    review_status: FieldReviewStatus = FieldReviewStatus.UNREVIEWED
    corrected_value: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_id", _ref(self.field_id, "field_id", limit=96))
        if self.raw_value is not None:
            object.__setattr__(self, "raw_value", _bounded(self.raw_value, "raw_value", limit=4000, allow_empty=True))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if not isinstance(self.origin, ExtractionOrigin):
            raise ContractError("origin must be ExtractionOrigin")
        object.__setattr__(self, "source_locator", _ref(self.source_locator, "source_locator", limit=512))
        if not isinstance(self.review_status, FieldReviewStatus):
            raise ContractError("review_status must be FieldReviewStatus")
        if self.corrected_value is not None:
            object.__setattr__(self, "corrected_value", _bounded(self.corrected_value, "corrected_value", limit=4000, allow_empty=True))
        if self.review_status is FieldReviewStatus.CORRECTED and self.corrected_value is None:
            raise ContractError("corrected field requires corrected_value")
        if self.review_status is not FieldReviewStatus.CORRECTED and self.corrected_value is not None:
            raise ContractError("corrected_value is only allowed for corrected fields")
        if self.review_status is FieldReviewStatus.CONFIRMED and self.raw_value is None:
            raise ContractError("confirmed field requires raw_value")
        if self.review_status is FieldReviewStatus.UNKNOWN and self.corrected_value is not None:
            raise ContractError("unknown field cannot carry corrected_value")

    @property
    def resolved_value(self) -> str | None:
        if self.review_status is FieldReviewStatus.CORRECTED:
            return self.corrected_value
        if self.review_status is FieldReviewStatus.CONFIRMED:
            return self.raw_value
        return None

    @property
    def trusted_business_value(self) -> bool:
        return self.review_status in {FieldReviewStatus.CONFIRMED, FieldReviewStatus.CORRECTED}

    def safe_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "confidence": format(self.confidence, "f"),
            "origin": self.origin.value,
            "source_locator": self.source_locator,
            "review_status": self.review_status.value,
            "trusted_business_value": self.trusted_business_value,
            "has_raw_value": self.raw_value is not None,
            "has_correction": self.corrected_value is not None,
        }


@dataclass(frozen=True, slots=True)
class IntakeLineCandidate:
    line_candidate_id: str
    description: ExtractedField
    quantity: ExtractedField
    unit: ExtractedField

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_candidate_id", _ref(self.line_candidate_id, "line_candidate_id"))
        fields = (self.description, self.quantity, self.unit)
        if not all(isinstance(item, ExtractedField) for item in fields):
            raise ContractError("line fields must be ExtractedField values")

    @property
    def ready_for_promotion(self) -> bool:
        return all(item.trusted_business_value for item in (self.description, self.quantity, self.unit))


@dataclass(frozen=True, slots=True)
class CommercialRequestIntakeCandidate:
    candidate_id: str
    workspace_id: str
    source: IntakeSource
    version: int
    title: ExtractedField
    requested_delivery_date: ExtractedField | None
    line_candidates: tuple[IntakeLineCandidate, ...]
    trusted_customer_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _ref(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        if self.source.workspace_id != self.workspace_id:
            raise ContractError("source belongs to another workspace")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ContractError("version must be a positive integer")
        if not isinstance(self.title, ExtractedField):
            raise ContractError("title must be ExtractedField")
        if self.requested_delivery_date is not None and not isinstance(self.requested_delivery_date, ExtractedField):
            raise ContractError("requested_delivery_date must be ExtractedField")
        if not isinstance(self.line_candidates, tuple) or not self.line_candidates:
            raise ContractError("line_candidates must be a non-empty tuple")
        if not all(isinstance(item, IntakeLineCandidate) for item in self.line_candidates):
            raise ContractError("line_candidates must contain IntakeLineCandidate values")
        ids = [item.line_candidate_id for item in self.line_candidates]
        if len(ids) != len(set(ids)):
            raise ContractError("line candidate IDs must be unique")
        if self.trusted_customer_id is not None:
            object.__setattr__(self, "trusted_customer_id", _ref(self.trusted_customer_id, "trusted_customer_id"))

    @property
    def trusted_execution_input(self) -> bool:
        return False

    @property
    def unresolved_field_count(self) -> int:
        fields: list[ExtractedField] = [self.title]
        if self.requested_delivery_date is not None:
            fields.append(self.requested_delivery_date)
        for line in self.line_candidates:
            fields.extend((line.description, line.quantity, line.unit))
        return sum(1 for field in fields if not field.trusted_business_value)

    @property
    def ready_for_promotion(self) -> bool:
        if self.trusted_customer_id is None or not self.title.trusted_business_value:
            return False
        if self.requested_delivery_date is not None and not self.requested_delivery_date.trusted_business_value:
            return False
        return all(line.ready_for_promotion for line in self.line_candidates)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "workspace_id": self.workspace_id,
            "source_id": self.source.source_id,
            "source_kind": self.source.kind.value,
            "source_content_ref": self.source.immutable_content_ref,
            "version": self.version,
            "trusted_customer_bound": self.trusted_customer_id is not None,
            "unresolved_field_count": self.unresolved_field_count,
            "ready_for_promotion": self.ready_for_promotion,
            "trusted_execution_input": False,
        }


class DocumentExtractionPort(Protocol):
    def extract(self, source: IntakeSource) -> CommercialRequestIntakeCandidate:
        ...


class UnconfiguredDocumentExtractionPort:
    def extract(self, source: IntakeSource) -> CommercialRequestIntakeCandidate:
        raise ContractError("document extraction adapter is not configured")


def promote_candidate(candidate: CommercialRequestIntakeCandidate, *, request_id: str) -> CommercialRequest:
    if not isinstance(candidate, CommercialRequestIntakeCandidate):
        raise ContractError("candidate must be CommercialRequestIntakeCandidate")
    if not candidate.ready_for_promotion:
        raise ContractError("candidate contains unresolved or untrusted fields")
    assert candidate.trusted_customer_id is not None
    assert candidate.title.resolved_value is not None

    lines: list[LineItem] = []
    for line in candidate.line_candidates:
        description = line.description.resolved_value
        quantity = line.quantity.resolved_value
        unit = line.unit.resolved_value
        if description is None or quantity is None or unit is None:
            raise ContractError("line candidate is not fully resolved")
        lines.append(
            LineItem(
                line_id=line.line_candidate_id,
                description=description,
                quantity=quantity,
                unit=unit,
            )
        )

    delivery_date: date | None = None
    if candidate.requested_delivery_date is not None:
        resolved_date = candidate.requested_delivery_date.resolved_value
        if resolved_date is None:
            raise ContractError("delivery date is unresolved")
        try:
            delivery_date = date.fromisoformat(resolved_date)
        except ValueError as exc:
            raise ContractError("reviewed delivery date must use ISO YYYY-MM-DD") from exc

    return CommercialRequest(
        request_id=request_id,
        workspace_id=candidate.workspace_id,
        customer_id=candidate.trusted_customer_id,
        version=1,
        title=candidate.title.resolved_value,
        line_items=tuple(lines),
        requested_delivery_date=delivery_date,
    )
