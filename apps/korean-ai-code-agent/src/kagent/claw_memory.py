"""#2057 B54 ACT-0/ACT-1: Claw business memory contracts (MVP slice).

Workspace-scoped business memory for Claw: customers/suppliers (거래처),
items/SKUs/service types (품목), price/quote history (단가·견적 이력),
preferred delivery/contact method, unresolved requests, follow-up tasks,
alert inbox, and user-approved memory update proposals.

Boundary rules enforced by this module:

- Pasted or connector text is UNTRUSTED inbound input. Extraction produces
  candidates/proposals only — never durable trusted records.
- Durable memory updates require explicit user approval (approved, or an
  edited proposal approved with edits). Applying anything else fails closed.
- Durable records keep a source/evidence reference where possible.
- Raw inbound body is never part of a safe projection; the source ref may
  hold a review-only excerpt that is excluded from ``safe_dict`` output.
- No hidden model/provider output is stored as authority: model-derived
  values must arrive as candidates the user reviews.

This is a deterministic in-memory store only. No database, no connector
OAuth, no provider calls, no automatic outbound actions, no billing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets

CONTRACT_VERSION = "claw-memory.v1"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_MAX_RAW_EXCERPT_CHARS = 4_000
_MAX_TEXT_CHARS = 2_000


class ClawMemoryError(ContractError):
    """Fail-closed Claw business-memory contract error."""


def _safe_id(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ClawMemoryError(f"{name} must be a string")
    value = value.strip()
    if not _SAFE_ID_RE.fullmatch(value):
        raise ClawMemoryError(f"{name} has an invalid identifier shape")
    return value


def _text(value: str, name: str, *, limit: int = _MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise ClawMemoryError(f"{name} must be a string")
    value = value.strip()
    if not value:
        raise ClawMemoryError(f"{name} is required")
    if len(value) > limit:
        raise ClawMemoryError(f"{name} exceeds {limit} characters")
    if _CONTROL_RE.search(value):
        raise ClawMemoryError(f"{name} contains control characters")
    return value


def _optional_text(value: Any, name: str, *, limit: int = 512) -> str | None:
    if value is None:
        return None
    return _text(value, name, limit=limit)


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ClawMemoryError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _plain_date(value: date | None, name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ClawMemoryError(f"{name} must be a date")
    return value


def _enum_value(enum_type: type, value: Any) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ClawMemoryError(f"value must be one of: {allowed}") from exc


def _payload_dict(value: Any, name: str = "payload") -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ClawMemoryError(f"{name} must be a non-empty dict")
    for key in value:
        if not isinstance(key, str) or not key.strip():
            raise ClawMemoryError(f"{name} keys must be non-empty strings")
    return dict(value)


class ClawMemoryKind(str, Enum):
    PARTY = "party"
    ITEM = "item"
    PRICE = "price"


class ClawPartyRole(str, Enum):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"


class ClawItemKind(str, Enum):
    PRODUCT = "product"
    SERVICE = "service"


class ClawSourceOrigin(str, Enum):
    PASTE = "paste"
    CONNECTOR = "connector"
    USER_INPUT = "user_input"


class ClawProposalState(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SUPPRESSED = "suppressed"
    EDITED = "edited"
    REJECTED = "rejected"
    APPLIED = "applied"


class ClawTaskStatus(str, Enum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class ClawAlertKind(str, Enum):
    FOLLOWUP_DUE = "followup_due"
    PRICE_CHANGE = "price_change"
    UNRESOLVED_REQUEST = "unresolved_request"
    MEMORY_PROPOSAL = "memory_proposal"


class ClawAlertSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class ClawAlertStatus(str, Enum):
    ACTIVE = "active"
    DISMISSED = "dismissed"


def sha256_text(body: str) -> str:
    """Deterministic digest used to reference inbound text without storing it."""
    if not isinstance(body, str):
        raise ClawMemoryError("body must be a string")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ClawMemorySourceRef:
    """Evidence reference for a memory fact. Never authoritative by itself.

    ``raw_excerpt`` is optional and review-only: it is excluded from
    ``safe_dict`` output by default. The SHA-256 digest lets durable records
    point back to the exact inbound text without embedding the untrusted body.
    """

    source_id: str
    workspace_id: str
    origin: ClawSourceOrigin
    body_sha256: str
    created_at: datetime
    raw_excerpt: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        if not isinstance(self.origin, ClawSourceOrigin):
            raise ClawMemoryError("origin must be ClawSourceOrigin")
        if not isinstance(self.body_sha256, str) or not _SHA256_RE.fullmatch(self.body_sha256):
            raise ClawMemoryError("body_sha256 must be a lowercase sha-256 hex digest")
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))
        if self.raw_excerpt is not None:
            object.__setattr__(
                self, "raw_excerpt", _text(self.raw_excerpt, "raw_excerpt", limit=_MAX_RAW_EXCERPT_CHARS)
            )

    def safe_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION,
            "source_id": self.source_id,
            "workspace_id": self.workspace_id,
            "origin": self.origin.value,
            "body_sha256": self.body_sha256,
            "created_at": self.created_at.isoformat(),
        }
        if include_raw and self.raw_excerpt is not None:
            data["raw_excerpt"] = redact_secrets(self.raw_excerpt)
        return data


@dataclass(frozen=True, slots=True)
class ClawMemoryCandidate:
    """An untrusted extracted fact. It can never become durable memory directly."""

    candidate_id: str
    workspace_id: str
    kind: ClawMemoryKind
    payload: dict[str, Any]
    source: ClawMemorySourceRef
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _safe_id(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        if not isinstance(self.kind, ClawMemoryKind):
            raise ClawMemoryError("kind must be ClawMemoryKind")
        object.__setattr__(self, "payload", _payload_dict(self.payload))
        if not isinstance(self.source, ClawMemorySourceRef):
            raise ClawMemoryError("source must be a ClawMemorySourceRef")
        if self.source.workspace_id != self.workspace_id:
            raise ClawMemoryError("candidate workspace must match source workspace")
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "candidate_id": self.candidate_id,
            "workspace_id": self.workspace_id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
            "source": self.source.safe_dict(),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ClawMemoryProposal:
    """A user-reviewable memory update derived from a candidate."""

    proposal_id: str
    workspace_id: str
    kind: ClawMemoryKind
    payload: dict[str, Any]
    source: ClawMemorySourceRef
    candidate_id: str
    state: ClawProposalState = ClawProposalState.PENDING_REVIEW
    edited_payload: dict[str, Any] | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _safe_id(self.proposal_id, "proposal_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        if not isinstance(self.kind, ClawMemoryKind):
            raise ClawMemoryError("kind must be ClawMemoryKind")
        object.__setattr__(self, "payload", _payload_dict(self.payload))
        if not isinstance(self.source, ClawMemorySourceRef):
            raise ClawMemoryError("source must be a ClawMemorySourceRef")
        object.__setattr__(self, "candidate_id", _safe_id(self.candidate_id, "candidate_id"))
        if not isinstance(self.state, ClawProposalState):
            raise ClawMemoryError("state must be ClawProposalState")
        if self.edited_payload is not None:
            if self.state not in (ClawProposalState.EDITED, ClawProposalState.APPLIED):
                raise ClawMemoryError("edited_payload is only allowed on edited or applied proposals")
            object.__setattr__(self, "edited_payload", _payload_dict(self.edited_payload, "edited_payload"))
        if self.decided_by is not None:
            object.__setattr__(self, "decided_by", _text(self.decided_by, "decided_by", limit=128))
        if self.decided_at is not None:
            object.__setattr__(self, "decided_at", _aware_utc(self.decided_at, "decided_at"))

    @property
    def effective_payload(self) -> dict[str, Any]:
        if (
            self.edited_payload is not None
            and self.state in (ClawProposalState.EDITED, ClawProposalState.APPLIED)
        ):
            return dict(self.edited_payload)
        return dict(self.payload)

    @property
    def applicable(self) -> bool:
        return self.state in (ClawProposalState.APPROVED, ClawProposalState.EDITED)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "proposal_id": self.proposal_id,
            "workspace_id": self.workspace_id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
            "edited_payload": dict(self.edited_payload) if self.edited_payload else None,
            "effective_payload": self.effective_payload,
            "source": self.source.safe_dict(),
            "candidate_id": self.candidate_id,
            "state": self.state.value,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }


@dataclass(frozen=True, slots=True)
class ClawPartyMemory:
    """Durable customer/supplier (거래처) record. Requires a source ref."""

    memory_id: str
    workspace_id: str
    name: str
    role: ClawPartyRole
    source_id: str
    updated_at: datetime
    preferred_contact_method: str | None = None
    delivery_preference: str | None = None
    unresolved_request: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", _safe_id(self.memory_id, "memory_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "name", _text(self.name, "name", limit=256))
        if not isinstance(self.role, ClawPartyRole):
            raise ClawMemoryError("role must be ClawPartyRole")
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        object.__setattr__(self, "updated_at", _aware_utc(self.updated_at, "updated_at"))
        for opt in ("preferred_contact_method", "delivery_preference", "unresolved_request"):
            value = getattr(self, opt)
            if value is not None:
                object.__setattr__(self, opt, _text(value, opt, limit=256))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "memory_id": self.memory_id,
            "workspace_id": self.workspace_id,
            "kind": ClawMemoryKind.PARTY.value,
            "name": redact_secrets(self.name),
            "role": self.role.value,
            "preferred_contact_method": self.preferred_contact_method,
            "delivery_preference": self.delivery_preference,
            "unresolved_request": self.unresolved_request,
            "source_id": self.source_id,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ClawItemMemory:
    """Durable item/SKU/service-type (품목) record. Requires a source ref."""

    memory_id: str
    workspace_id: str
    item_name: str
    item_kind: ClawItemKind
    source_id: str
    updated_at: datetime
    sku: str | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", _safe_id(self.memory_id, "memory_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "item_name", _text(self.item_name, "item_name", limit=256))
        if not isinstance(self.item_kind, ClawItemKind):
            raise ClawMemoryError("item_kind must be ClawItemKind")
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        object.__setattr__(self, "updated_at", _aware_utc(self.updated_at, "updated_at"))
        for opt in ("sku", "unit"):
            value = getattr(self, opt)
            if value is not None:
                object.__setattr__(self, opt, _text(value, opt, limit=64))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "memory_id": self.memory_id,
            "workspace_id": self.workspace_id,
            "kind": ClawMemoryKind.ITEM.value,
            "item_name": redact_secrets(self.item_name),
            "item_kind": self.item_kind.value,
            "sku": self.sku,
            "unit": self.unit,
            "source_id": self.source_id,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ClawPriceMemory:
    """Durable price/quote-history (단가·견적 이력) record. Requires a source ref."""

    memory_id: str
    workspace_id: str
    item_memory_id: str
    unit_price: Decimal
    currency: str
    quoted_at: date
    source_id: str
    updated_at: datetime
    party_memory_id: str | None = None
    quote_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", _safe_id(self.memory_id, "memory_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "item_memory_id", _safe_id(self.item_memory_id, "item_memory_id"))
        if self.party_memory_id is not None:
            object.__setattr__(
                self, "party_memory_id", _safe_id(self.party_memory_id, "party_memory_id")
            )
        if isinstance(self.unit_price, bool) or isinstance(self.unit_price, float):
            raise ClawMemoryError("unit_price must not be bool or float")
        try:
            price = self.unit_price if isinstance(self.unit_price, Decimal) else Decimal(str(self.unit_price))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ClawMemoryError("unit_price must be a decimal-compatible value") from exc
        if not price.is_finite() or price <= 0 or price > Decimal("1000000000"):
            raise ClawMemoryError("unit_price must be finite, positive, and bounded")
        object.__setattr__(self, "unit_price", price)
        if not isinstance(self.currency, str) or not _CURRENCY_RE.fullmatch(self.currency.strip()):
            raise ClawMemoryError("currency must be a 3-letter uppercase code")
        object.__setattr__(self, "currency", self.currency.strip())
        if self.quoted_at is None:
            raise ClawMemoryError("quoted_at is required")
        object.__setattr__(self, "quoted_at", _plain_date(self.quoted_at, "quoted_at"))
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        object.__setattr__(self, "updated_at", _aware_utc(self.updated_at, "updated_at"))
        if self.quote_note is not None:
            object.__setattr__(self, "quote_note", _text(self.quote_note, "quote_note", limit=512))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "memory_id": self.memory_id,
            "workspace_id": self.workspace_id,
            "kind": ClawMemoryKind.PRICE.value,
            "item_memory_id": self.item_memory_id,
            "party_memory_id": self.party_memory_id,
            "unit_price": str(self.unit_price),
            "currency": self.currency,
            "quoted_at": self.quoted_at.isoformat(),
            "quote_note": redact_secrets(self.quote_note) if self.quote_note else None,
            "source_id": self.source_id,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ClawFollowupTask:
    """Follow-up task. Representable and reversible (done/cancelled can reopen)."""

    task_id: str
    workspace_id: str
    member_id: str
    title: str
    status: ClawTaskStatus
    created_at: datetime
    due_date: date | None = None
    source_id: str | None = None
    linked_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _safe_id(self.task_id, "task_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "member_id", _safe_id(self.member_id, "member_id"))
        object.__setattr__(self, "title", _text(self.title, "title", limit=256))
        if not isinstance(self.status, ClawTaskStatus):
            raise ClawMemoryError("status must be ClawTaskStatus")
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))
        object.__setattr__(self, "due_date", _plain_date(self.due_date, "due_date"))
        if self.source_id is not None:
            object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        if self.linked_ref is not None:
            object.__setattr__(self, "linked_ref", _safe_id(self.linked_ref, "linked_ref"))

    def with_status(self, status: ClawTaskStatus, *, at: datetime) -> "ClawFollowupTask":
        if not isinstance(status, ClawTaskStatus):
            raise ClawMemoryError("status must be ClawTaskStatus")
        _aware_utc(at, "at")
        return replace(self, status=status)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "member_id": self.member_id,
            "title": redact_secrets(self.title),
            "status": self.status.value,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "source_id": self.source_id,
            "linked_ref": self.linked_ref,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ClawAlert:
    """Alert-inbox entry. Workspace-scoped, member-filterable, dismiss reversible."""

    alert_id: str
    workspace_id: str
    kind: ClawAlertKind
    severity: ClawAlertSeverity
    title: str
    created_at: datetime
    status: ClawAlertStatus = ClawAlertStatus.ACTIVE
    visible_to_members: tuple[str, ...] = ()
    linked_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "alert_id", _safe_id(self.alert_id, "alert_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        if not isinstance(self.kind, ClawAlertKind):
            raise ClawMemoryError("kind must be ClawAlertKind")
        if not isinstance(self.severity, ClawAlertSeverity):
            raise ClawMemoryError("severity must be ClawAlertSeverity")
        object.__setattr__(self, "title", _text(self.title, "title", limit=256))
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))
        if not isinstance(self.status, ClawAlertStatus):
            raise ClawMemoryError("status must be ClawAlertStatus")
        for name in ("visible_to_members", "linked_refs"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise ClawMemoryError(f"{name} must be a tuple")
            if len(value) > 50:
                raise ClawMemoryError(f"{name} exceeds 50 entries")
            object.__setattr__(self, name, tuple(_safe_id(item, name) for item in value))

    @property
    def visible_to_all(self) -> bool:
        return not self.visible_to_members

    def is_visible_to(self, member_id: str | None) -> bool:
        if self.visible_to_all:
            return True
        if member_id is None:
            return False
        return _safe_id(member_id, "member_id") in self.visible_to_members

    def with_status(self, status: ClawAlertStatus, *, at: datetime) -> "ClawAlert":
        if not isinstance(status, ClawAlertStatus):
            raise ClawMemoryError("status must be ClawAlertStatus")
        _aware_utc(at, "at")
        return replace(self, status=status)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "alert_id": self.alert_id,
            "workspace_id": self.workspace_id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "title": redact_secrets(self.title),
            "status": self.status.value,
            "visible_to_all": self.visible_to_all,
            "visible_to_members": list(self.visible_to_members),
            "linked_refs": list(self.linked_refs),
            "created_at": self.created_at.isoformat(),
        }


def proposal_from_candidate(candidate: ClawMemoryCandidate, *, proposal_id: str) -> ClawMemoryProposal:
    """Wrap a candidate as a pending_review proposal. Never a durable record."""
    return ClawMemoryProposal(
        proposal_id=proposal_id,
        workspace_id=candidate.workspace_id,
        kind=candidate.kind,
        payload=dict(candidate.payload),
        source=candidate.source,
        candidate_id=candidate.candidate_id,
    )


def with_decision(
    proposal: ClawMemoryProposal,
    state: ClawProposalState,
    *,
    decided_by: str,
    decided_at: datetime,
    edited_payload: dict[str, Any] | None = None,
) -> ClawMemoryProposal:
    """Return a decided copy of a pending proposal. Fails closed on re-decision.

    Allowed decision targets: APPROVED, EDITED (approval with edits),
    SUPPRESSED, REJECTED. EDITED requires a non-empty ``edited_payload``; the
    original payload and source ref are preserved untouched.
    """
    if state not in (
        ClawProposalState.APPROVED,
        ClawProposalState.EDITED,
        ClawProposalState.SUPPRESSED,
        ClawProposalState.REJECTED,
    ):
        raise ClawMemoryError("decision state must be approved, edited, suppressed, or rejected")
    if proposal.state is not ClawProposalState.PENDING_REVIEW:
        raise ClawMemoryError("only pending_review proposals can be decided")
    if state is ClawProposalState.EDITED:
        if not isinstance(edited_payload, dict) or not edited_payload:
            raise ClawMemoryError("edited decisions require a non-empty edited_payload")
    elif edited_payload is not None:
        raise ClawMemoryError("edited_payload is only allowed for edited decisions")
    return ClawMemoryProposal(
        proposal_id=proposal.proposal_id,
        workspace_id=proposal.workspace_id,
        kind=proposal.kind,
        payload=proposal.payload,
        source=proposal.source,
        candidate_id=proposal.candidate_id,
        state=state,
        edited_payload=dict(edited_payload) if edited_payload else None,
        decided_by=decided_by,
        decided_at=decided_at,
    )


def durable_record_from_proposal(
    proposal: ClawMemoryProposal, *, memory_id: str, applied_at: datetime
) -> Any:
    """Materialize a durable record from an approved/edited proposal.

    Fails closed: a pending, rejected, suppressed, or already-applied proposal
    can never produce a durable record. The source ref is carried onto the
    record so the durable fact points back at its (untrusted) origin.
    """
    if not proposal.applicable:
        raise ClawMemoryError(
            "memory update requires a user-approved (or edited-approved) proposal; "
            f"proposal is {proposal.state.value}"
        )
    _safe_id(memory_id, "memory_id")
    applied_at = _aware_utc(applied_at, "applied_at")
    payload = proposal.effective_payload
    source_id = proposal.source.source_id
    if proposal.kind is ClawMemoryKind.PARTY:
        return ClawPartyMemory(
            memory_id=memory_id,
            workspace_id=proposal.workspace_id,
            name=_text(str(payload.get("name", "")), "name", limit=256),
            role=_enum_value(ClawPartyRole, payload.get("role")),
            source_id=source_id,
            updated_at=applied_at,
            preferred_contact_method=_optional_text(
                payload.get("preferred_contact_method"), "preferred_contact_method", limit=256
            ),
            delivery_preference=_optional_text(
                payload.get("delivery_preference"), "delivery_preference", limit=256
            ),
            unresolved_request=_optional_text(
                payload.get("unresolved_request"), "unresolved_request", limit=256
            ),
        )
    if proposal.kind is ClawMemoryKind.ITEM:
        return ClawItemMemory(
            memory_id=memory_id,
            workspace_id=proposal.workspace_id,
            item_name=_text(str(payload.get("item_name", "")), "item_name", limit=256),
            item_kind=_enum_value(ClawItemKind, payload.get("item_kind")),
            source_id=source_id,
            updated_at=applied_at,
            sku=_optional_text(payload.get("sku"), "sku", limit=64),
            unit=_optional_text(payload.get("unit"), "unit", limit=64),
        )
    if proposal.kind is ClawMemoryKind.PRICE:
        quoted_at = payload.get("quoted_at")
        if isinstance(quoted_at, str):
            quoted_at = date.fromisoformat(quoted_at)
        return ClawPriceMemory(
            memory_id=memory_id,
            workspace_id=proposal.workspace_id,
            item_memory_id=_safe_id(str(payload.get("item_memory_id", "")), "item_memory_id"),
            unit_price=payload.get("unit_price"),
            currency=str(payload.get("currency", "")),
            quoted_at=quoted_at,
            source_id=source_id,
            updated_at=applied_at,
            party_memory_id=(
                _safe_id(str(payload["party_memory_id"]), "party_memory_id")
                if payload.get("party_memory_id") is not None
                else None
            ),
            quote_note=_optional_text(payload.get("quote_note"), "quote_note", limit=512),
        )
    raise ClawMemoryError("unknown proposal kind")


class ClawMemoryStore:
    """Abstract workspace-scoped memory boundary (fake implementations only)."""

    def submit_candidate(self, candidate: ClawMemoryCandidate, *, proposal_id: str) -> ClawMemoryProposal:
        raise NotImplementedError

    def decide_proposal(self, proposal_id: str, state: ClawProposalState, *, workspace_id: str, decided_by: str, decided_at: datetime, edited_payload: dict[str, Any] | None = None) -> ClawMemoryProposal:
        raise NotImplementedError

    def apply_proposal(self, proposal_id: str, *, workspace_id: str, memory_id: str, applied_at: datetime) -> Any:
        raise NotImplementedError

    def add_task(self, task: ClawFollowupTask) -> ClawFollowupTask:
        raise NotImplementedError

    def set_task_status(self, task_id: str, status: ClawTaskStatus, *, workspace_id: str, at: datetime) -> ClawFollowupTask:
        raise NotImplementedError

    def add_alert(self, alert: ClawAlert) -> ClawAlert:
        raise NotImplementedError

    def set_alert_status(self, alert_id: str, status: ClawAlertStatus, *, workspace_id: str, at: datetime) -> ClawAlert:
        raise NotImplementedError

    def projection(self, workspace_id: str, *, member_id: str | None = None) -> dict[str, Any]:
        raise NotImplementedError


class InMemoryClawMemoryStore(ClawMemoryStore):
    """Deterministic in-memory repository for tests. No production persistence.

    Every read/write is workspace-scoped: identifiers from another workspace
    are invisible and cross-workspace access fails closed.
    """

    def __init__(self) -> None:
        self._proposals: dict[str, ClawMemoryProposal] = {}
        self._parties: dict[str, ClawPartyMemory] = {}
        self._items: dict[str, ClawItemMemory] = {}
        self._prices: dict[str, ClawPriceMemory] = {}
        self._tasks: dict[str, ClawFollowupTask] = {}
        self._alerts: dict[str, ClawAlert] = {}

    def submit_candidate(self, candidate: ClawMemoryCandidate, *, proposal_id: str) -> ClawMemoryProposal:
        if proposal_id in self._proposals:
            raise ClawMemoryError("proposal_id already exists")
        proposal = proposal_from_candidate(candidate, proposal_id=proposal_id)
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def decide_proposal(
        self,
        proposal_id: str,
        state: ClawProposalState,
        *,
        workspace_id: str,
        decided_by: str,
        decided_at: datetime,
        edited_payload: dict[str, Any] | None = None,
    ) -> ClawMemoryProposal:
        proposal = self._require(self._proposals, proposal_id, workspace_id, "proposal")
        updated = with_decision(
            proposal,
            _enum_value(ClawProposalState, state),
            decided_by=decided_by,
            decided_at=decided_at,
            edited_payload=edited_payload,
        )
        self._proposals[proposal_id] = updated
        return updated

    def apply_proposal(
        self, proposal_id: str, *, workspace_id: str, memory_id: str, applied_at: datetime
    ) -> Any:
        proposal = self._require(self._proposals, proposal_id, workspace_id, "proposal")
        record = durable_record_from_proposal(proposal, memory_id=memory_id, applied_at=applied_at)
        target = {
            ClawMemoryKind.PARTY: self._parties,
            ClawMemoryKind.ITEM: self._items,
            ClawMemoryKind.PRICE: self._prices,
        }[proposal.kind]
        if memory_id in target:
            raise ClawMemoryError("memory_id already exists")
        target[memory_id] = record
        self._proposals[proposal_id] = replace(proposal, state=ClawProposalState.APPLIED)
        return record

    def add_task(self, task: ClawFollowupTask) -> ClawFollowupTask:
        if task.task_id in self._tasks:
            raise ClawMemoryError("task_id already exists")
        self._tasks[task.task_id] = task
        return task

    def set_task_status(
        self, task_id: str, status: ClawTaskStatus, *, workspace_id: str, at: datetime
    ) -> ClawFollowupTask:
        task = self._require(self._tasks, task_id, workspace_id, "task")
        updated = task.with_status(_enum_value(ClawTaskStatus, status), at=at)
        self._tasks[task_id] = updated
        return updated

    def add_alert(self, alert: ClawAlert) -> ClawAlert:
        if alert.alert_id in self._alerts:
            raise ClawMemoryError("alert_id already exists")
        self._alerts[alert.alert_id] = alert
        return alert

    def set_alert_status(
        self, alert_id: str, status: ClawAlertStatus, *, workspace_id: str, at: datetime
    ) -> ClawAlert:
        alert = self._require(self._alerts, alert_id, workspace_id, "alert")
        updated = alert.with_status(_enum_value(ClawAlertStatus, status), at=at)
        self._alerts[alert_id] = updated
        return updated

    def list_parties(self, workspace_id: str) -> tuple[ClawPartyMemory, ...]:
        _safe_id(workspace_id, "workspace_id")
        return tuple(r for r in self._parties.values() if r.workspace_id == workspace_id)

    def list_items(self, workspace_id: str) -> tuple[ClawItemMemory, ...]:
        _safe_id(workspace_id, "workspace_id")
        return tuple(r for r in self._items.values() if r.workspace_id == workspace_id)

    def list_prices(self, workspace_id: str) -> tuple[ClawPriceMemory, ...]:
        _safe_id(workspace_id, "workspace_id")
        return tuple(r for r in self._prices.values() if r.workspace_id == workspace_id)

    def list_tasks(self, workspace_id: str) -> tuple[ClawFollowupTask, ...]:
        _safe_id(workspace_id, "workspace_id")
        return tuple(r for r in self._tasks.values() if r.workspace_id == workspace_id)

    def list_alerts(self, workspace_id: str, *, member_id: str | None = None) -> tuple[ClawAlert, ...]:
        _safe_id(workspace_id, "workspace_id")
        return tuple(
            alert
            for alert in self._alerts.values()
            if alert.workspace_id == workspace_id and alert.is_visible_to(member_id)
        )

    def projection(self, workspace_id: str, *, member_id: str | None = None) -> dict[str, Any]:
        """Safe workspace projection. Raw inbound bodies are never included."""
        return {
            "contract_version": CONTRACT_VERSION,
            "workspace_id": workspace_id,
            "parties": [record.safe_dict() for record in self.list_parties(workspace_id)],
            "items": [record.safe_dict() for record in self.list_items(workspace_id)],
            "prices": [record.safe_dict() for record in self.list_prices(workspace_id)],
            "tasks": [task.safe_dict() for task in self.list_tasks(workspace_id)],
            "alerts": [alert.safe_dict() for alert in self.list_alerts(workspace_id, member_id=member_id)],
            "proposals": [
                proposal.safe_dict()
                for proposal in self._proposals.values()
                if proposal.workspace_id == workspace_id
            ],
        }

    @staticmethod
    def _require(store: dict[str, Any], item_id: str, workspace_id: str, label: str) -> Any:
        _safe_id(workspace_id, "workspace_id")
        record = store.get(_safe_id(item_id, f"{label}_id"))
        if record is None or record.workspace_id != workspace_id:
            raise ClawMemoryError(f"{label} not found in workspace")
        return record
