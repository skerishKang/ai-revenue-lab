from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
MAX_PRODUCT_USER_ID_CHARS = 256
MAX_CANONICAL_SUBJECT_ID_CHARS = 256
MAX_IDEMPOTENCY_KEY_CHARS = 256
MAX_ROUTE_LABEL_CHARS = 256


class ControlPlaneContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("control-plane error code must be a safe identifier")
        self.code = code
        self.safe_message = message


class IdentityLinkState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class SubjectType(str, Enum):
    ANONYMOUS = "anonymous"
    USER = "user"
    ACCOUNT = "account"


class UsageOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BillingDisposition(str, Enum):
    BILLABLE = "billable"
    NON_BILLABLE = "non_billable"


class CostEvidenceSource(str, Enum):
    CONFIGURED_ESTIMATE = "configured_estimate"
    UPSTREAM_REPORTED = "upstream_reported"
    MEASURED = "measured"


class RouteEvidenceStatus(str, Enum):
    OBSERVED = "observed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_identifier",
            f"{name} must be a non-empty safe identifier",
        )
    return value


def _opaque_id(name: str, value: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ControlPlaneContractError(
            "invalid_identifier",
            f"{name} must be a string",
        )
    normalized = value.strip()
    if not normalized or len(normalized) > limit or any(
        ord(char) < 32 or ord(char) == 127 for char in normalized
    ):
        raise ControlPlaneContractError(
            "invalid_identifier",
            f"{name} must be a bounded non-empty opaque identifier",
        )
    return normalized


def _aware_datetime(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_timestamp",
            f"{name} must be timezone-aware",
        )
    return value


def _optional_non_negative_int(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlPlaneContractError(
            "invalid_usage_value",
            f"{name} must be a non-negative integer or None",
        )
    return value


@dataclass(frozen=True, slots=True)
class ProductIdentityLink:
    """Non-destructive link from a product-owned user row to a canonical subject.

    `product_user_id` remains the product's existing stable identifier. Creating this
    contract does not authorize rewriting product persistence foreign keys.
    """

    product_id: str
    product_user_id: str
    canonical_subject_id: str
    state: IdentityLinkState = IdentityLinkState.ACTIVE

    def __post_init__(self) -> None:
        object.__setattr__(self, "product_id", _safe_identifier("product_id", self.product_id))
        object.__setattr__(
            self,
            "product_user_id",
            _opaque_id(
                "product_user_id",
                self.product_user_id,
                limit=MAX_PRODUCT_USER_ID_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "canonical_subject_id",
            _opaque_id(
                "canonical_subject_id",
                self.canonical_subject_id,
                limit=MAX_CANONICAL_SUBJECT_ID_CHARS,
            ),
        )
        if not isinstance(self.state, IdentityLinkState):
            raise ControlPlaneContractError(
                "invalid_identity_link",
                "state must be IdentityLinkState",
            )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "product_id": self.product_id,
            "product_user_id": self.product_user_id,
            "canonical_subject_id": self.canonical_subject_id,
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class CanonicalSubjectRef:
    subject_type: SubjectType
    subject_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject_type, SubjectType):
            raise ControlPlaneContractError(
                "invalid_subject",
                "subject_type must be SubjectType",
            )
        object.__setattr__(
            self,
            "subject_id",
            _opaque_id(
                "subject_id",
                self.subject_id,
                limit=MAX_CANONICAL_SUBJECT_ID_CHARS,
            ),
        )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "subject_type": self.subject_type.value,
            "subject_id": self.subject_id,
        }


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            object.__setattr__(
                self,
                name,
                _optional_non_negative_int(name, getattr(self, name)),
            )

    @property
    def is_unknown(self) -> bool:
        return (
            self.input_tokens is None
            and self.output_tokens is None
            and self.total_tokens is None
        )

    def to_public_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class MonetaryCostEvidence:
    amount: Decimal
    currency: str
    source: CostEvidenceSource

    def __post_init__(self) -> None:
        try:
            amount = Decimal(self.amount)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ControlPlaneContractError(
                "invalid_cost_evidence",
                "amount must be a finite non-negative decimal",
            ) from exc
        if not amount.is_finite() or amount < 0:
            raise ControlPlaneContractError(
                "invalid_cost_evidence",
                "amount must be a finite non-negative decimal",
            )
        object.__setattr__(self, "amount", amount)

        if not isinstance(self.currency, str) or not _CURRENCY_RE.fullmatch(self.currency):
            raise ControlPlaneContractError(
                "invalid_cost_evidence",
                "currency must be an uppercase ISO-style three-letter code",
            )
        if not isinstance(self.source, CostEvidenceSource):
            raise ControlPlaneContractError(
                "invalid_cost_evidence",
                "source must be CostEvidenceSource",
            )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "amount": format(self.amount, "f"),
            "currency": self.currency,
            "source": self.source.value,
        }


@dataclass(frozen=True, slots=True)
class RouteEvidence:
    status: RouteEvidenceStatus
    selected_provider: str | None = None
    selected_model: str | None = None
    selected_upstream_model: str | None = None
    selected_route_id: str | None = None
    attempt_count: int | None = None
    fallback_used: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RouteEvidenceStatus):
            raise ControlPlaneContractError(
                "invalid_route_evidence",
                "status must be RouteEvidenceStatus",
            )

        for name in (
            "selected_provider",
            "selected_model",
            "selected_upstream_model",
            "selected_route_id",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _opaque_id(name, value, limit=MAX_ROUTE_LABEL_CHARS),
                )

        if self.attempt_count is not None and (
            isinstance(self.attempt_count, bool)
            or not isinstance(self.attempt_count, int)
            or self.attempt_count < 1
        ):
            raise ControlPlaneContractError(
                "invalid_route_evidence",
                "attempt_count must be a positive integer or None",
            )
        if self.fallback_used is not None and not isinstance(self.fallback_used, bool):
            raise ControlPlaneContractError(
                "invalid_route_evidence",
                "fallback_used must be bool or None",
            )

        has_observed_value = any(
            value is not None
            for value in (
                self.selected_provider,
                self.selected_model,
                self.selected_upstream_model,
                self.selected_route_id,
                self.attempt_count,
                self.fallback_used,
            )
        )
        if self.status is RouteEvidenceStatus.UNKNOWN and has_observed_value:
            raise ControlPlaneContractError(
                "invalid_route_evidence",
                "UNKNOWN route evidence cannot carry observed route values",
            )

    def to_public_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "status": self.status.value,
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "selected_upstream_model": self.selected_upstream_model,
            "selected_route_id": self.selected_route_id,
            "attempt_count": self.attempt_count,
            "fallback_used": self.fallback_used,
        }


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """One authoritative server-side event per accepted billing semantic.

    The contract intentionally has no prompt/response/secret/arbitrary-metadata field.
    Callers must create events from trusted server execution evidence, not browser
    submitted token/cost values.
    """

    event_id: str
    idempotency_key: str
    billing_semantic_id: str
    product_id: str
    subject: CanonicalSubjectRef
    execution_id: str
    outcome: UsageOutcome
    billing_disposition: BillingDisposition
    occurred_at: datetime
    tokens: TokenUsage = TokenUsage()
    route: RouteEvidence = RouteEvidence(status=RouteEvidenceStatus.UNKNOWN)
    cost: MonetaryCostEvidence | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _safe_identifier("event_id", self.event_id))
        object.__setattr__(
            self,
            "idempotency_key",
            _opaque_id(
                "idempotency_key",
                self.idempotency_key,
                limit=MAX_IDEMPOTENCY_KEY_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "billing_semantic_id",
            _safe_identifier("billing_semantic_id", self.billing_semantic_id),
        )
        object.__setattr__(self, "product_id", _safe_identifier("product_id", self.product_id))
        object.__setattr__(self, "execution_id", _safe_identifier("execution_id", self.execution_id))

        if not isinstance(self.subject, CanonicalSubjectRef):
            raise ControlPlaneContractError(
                "invalid_usage_event",
                "subject must be CanonicalSubjectRef",
            )
        if not isinstance(self.outcome, UsageOutcome):
            raise ControlPlaneContractError(
                "invalid_usage_event",
                "outcome must be UsageOutcome",
            )
        if not isinstance(self.billing_disposition, BillingDisposition):
            raise ControlPlaneContractError(
                "invalid_usage_event",
                "billing_disposition must be BillingDisposition",
            )
        object.__setattr__(self, "occurred_at", _aware_datetime("occurred_at", self.occurred_at))
        if not isinstance(self.tokens, TokenUsage):
            raise ControlPlaneContractError(
                "invalid_usage_event",
                "tokens must be TokenUsage",
            )
        if not isinstance(self.route, RouteEvidence):
            raise ControlPlaneContractError(
                "invalid_usage_event",
                "route must be RouteEvidence",
            )
        if self.cost is not None and not isinstance(self.cost, MonetaryCostEvidence):
            raise ControlPlaneContractError(
                "invalid_usage_event",
                "cost must be MonetaryCostEvidence or None",
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "billing_semantic_id": self.billing_semantic_id,
            "product_id": self.product_id,
            "subject": self.subject.to_public_dict(),
            "execution_id": self.execution_id,
            "outcome": self.outcome.value,
            "billing_disposition": self.billing_disposition.value,
            "occurred_at": self.occurred_at.isoformat(),
            "tokens": self.tokens.to_public_dict(),
            "route": self.route.to_public_dict(),
            "cost": self.cost.to_public_dict() if self.cost is not None else None,
        }


def validate_usage_event_batch(events: Sequence[UsageEvent]) -> tuple[UsageEvent, ...]:
    if isinstance(events, (str, bytes)):
        raise ControlPlaneContractError(
            "invalid_usage_batch",
            "events must be a sequence of UsageEvent values",
        )
    items = tuple(events)
    if any(not isinstance(item, UsageEvent) for item in items):
        raise ControlPlaneContractError(
            "invalid_usage_batch",
            "events must contain only UsageEvent values",
        )

    unique_fields = (
        ("event_id", tuple(item.event_id for item in items)),
        ("idempotency_key", tuple(item.idempotency_key for item in items)),
        ("billing_semantic_id", tuple(item.billing_semantic_id for item in items)),
    )
    for name, values in unique_fields:
        if len(values) != len(set(values)):
            raise ControlPlaneContractError(
                "duplicate_usage_event",
                f"duplicate {name} is not allowed in one authoritative usage batch",
            )
    return items
