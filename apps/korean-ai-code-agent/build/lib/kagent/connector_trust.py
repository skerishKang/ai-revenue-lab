from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets

_MAX_EVENT_BODY_CHARS = 20_000
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _refs(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_safe_ref(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{field_name} values must be unique")
    return normalized


def _fingerprint(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value.strip().lower()


def _non_negative_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field_name} must be a non-negative integer")
    return value


class ConnectorBindingState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class ConnectorBindingProjection:
    binding_ref: str
    connector_id: str
    actor_ref: str
    account_ref: str
    workspace_ref: str
    granted_scopes: tuple[str, ...]
    granted_capabilities: tuple[str, ...]
    issued_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    state: ConnectorBindingState = ConnectorBindingState.ACTIVE

    def __post_init__(self) -> None:
        for field_name in (
            "binding_ref",
            "connector_id",
            "actor_ref",
            "account_ref",
            "workspace_ref",
        ):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "granted_scopes", _refs(self.granted_scopes, "granted_scope"))
        object.__setattr__(
            self,
            "granted_capabilities",
            _refs(self.granted_capabilities, "granted_capability"),
        )
        issued = _aware(self.issued_at, "issued_at")
        updated = _aware(self.updated_at, "updated_at")
        if updated < issued:
            raise ContractError("updated_at cannot precede issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "updated_at", updated)
        if self.expires_at is not None:
            expires = _aware(self.expires_at, "expires_at")
            if expires <= issued:
                raise ContractError("expires_at must follow issued_at")
            object.__setattr__(self, "expires_at", expires)
        if self.revoked_at is not None:
            revoked = _aware(self.revoked_at, "revoked_at")
            if revoked < issued:
                raise ContractError("revoked_at cannot precede issued_at")
            object.__setattr__(self, "revoked_at", revoked)
        if not isinstance(self.state, ConnectorBindingState):
            try:
                object.__setattr__(self, "state", ConnectorBindingState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid connector binding state") from exc
        if self.state is ConnectorBindingState.REVOKED and self.revoked_at is None:
            raise ContractError("revoked binding requires revoked_at")
        if self.state is ConnectorBindingState.ACTIVE and self.revoked_at is not None:
            raise ContractError("active binding cannot carry revoked_at")

    def usable_at(self, now: datetime) -> bool:
        current = _aware(now, "now")
        if self.state is not ConnectorBindingState.ACTIVE:
            return False
        if self.expires_at is not None and current >= self.expires_at:
            return False
        return current >= self.issued_at

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-connector-binding.v1",
            "binding_ref": self.binding_ref,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "granted_scopes": list(self.granted_scopes),
            "granted_capabilities": list(self.granted_capabilities),
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z") if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat().replace("+00:00", "Z") if self.revoked_at else None,
            "state": self.state.value,
            "raw_access_token": False,
            "raw_refresh_token": False,
            "raw_client_secret": False,
            "raw_api_key": False,
            "raw_cookie": False,
        }


class ConnectorHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class ConnectorHealthProjection:
    binding_ref: str
    state: ConnectorHealthState
    observed_at: datetime
    freshness_seconds: int
    health_ref: str
    detail_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "health_ref", _safe_ref(self.health_ref, "health_ref"))
        if self.detail_ref is not None:
            object.__setattr__(self, "detail_ref", _safe_ref(self.detail_ref, "detail_ref"))
        if not isinstance(self.state, ConnectorHealthState):
            try:
                object.__setattr__(self, "state", ConnectorHealthState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid connector health state") from exc
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if (
            isinstance(self.freshness_seconds, bool)
            or not isinstance(self.freshness_seconds, int)
            or not 10 <= self.freshness_seconds <= 86_400
        ):
            raise ContractError("freshness_seconds must be between 10 and 86400")

    def fresh_at(self, now: datetime) -> bool:
        current = _aware(now, "now")
        age = current - self.observed_at
        return timedelta(0) <= age <= timedelta(seconds=self.freshness_seconds)

    def healthy_at(self, now: datetime, binding: ConnectorBindingProjection) -> bool:
        if not isinstance(binding, ConnectorBindingProjection):
            raise ContractError("binding must be ConnectorBindingProjection")
        return (
            self.binding_ref == binding.binding_ref
            and self.state is ConnectorHealthState.HEALTHY
            and self.fresh_at(now)
            and binding.usable_at(now)
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-connector-health.v1",
            "binding_ref": self.binding_ref,
            "state": self.state.value,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "freshness_seconds": self.freshness_seconds,
            "health_ref": self.health_ref,
            "detail_ref": self.detail_ref,
        }


class SignatureStatus(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    NOT_SUPPORTED = "not_supported"


class ReplayDisposition(str, Enum):
    NEW = "new"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ConnectorInboundEvent:
    event_ref: str
    connector_id: str
    binding_ref: str
    workspace_ref: str
    received_at: datetime
    body_text: str
    signature_required: bool
    signature_status: SignatureStatus
    signature_timestamp: datetime | None
    replay: ReplayDisposition
    signature_max_age_seconds: int = 300

    def __post_init__(self) -> None:
        for field_name in ("event_ref", "connector_id", "binding_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "received_at", _aware(self.received_at, "received_at"))
        if not isinstance(self.body_text, str):
            raise ContractError("event body_text must be a string")
        body = redact_secrets(self.body_text)
        if len(body) > _MAX_EVENT_BODY_CHARS:
            body = body[:_MAX_EVENT_BODY_CHARS]
        object.__setattr__(self, "body_text", body)
        if not isinstance(self.signature_required, bool):
            raise ContractError("signature_required must be boolean")
        if not isinstance(self.signature_status, SignatureStatus):
            try:
                object.__setattr__(self, "signature_status", SignatureStatus(self.signature_status))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid signature status") from exc
        if self.signature_timestamp is not None:
            object.__setattr__(
                self,
                "signature_timestamp",
                _aware(self.signature_timestamp, "signature_timestamp"),
            )
        if self.signature_required and self.signature_timestamp is None:
            raise ContractError("signature-required event needs signature_timestamp")
        if not isinstance(self.replay, ReplayDisposition):
            try:
                object.__setattr__(self, "replay", ReplayDisposition(self.replay))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid replay disposition") from exc
        if (
            isinstance(self.signature_max_age_seconds, bool)
            or not isinstance(self.signature_max_age_seconds, int)
            or not 30 <= self.signature_max_age_seconds <= 3_600
        ):
            raise ContractError("signature_max_age_seconds must be between 30 and 3600")

    def signature_fresh(self) -> bool:
        if not self.signature_required:
            return self.signature_status in {SignatureStatus.VERIFIED, SignatureStatus.NOT_SUPPORTED}
        if self.signature_status is not SignatureStatus.VERIFIED or self.signature_timestamp is None:
            return False
        age = self.received_at - self.signature_timestamp
        return timedelta(0) <= age <= timedelta(seconds=self.signature_max_age_seconds)

    def accepted(self) -> bool:
        return self.replay is ReplayDisposition.NEW and self.signature_fresh()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-connector-inbound-event.v1",
            "event_ref": self.event_ref,
            "connector_id": self.connector_id,
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "received_at": self.received_at.isoformat().replace("+00:00", "Z"),
            "body_text": self.body_text,
            "body_trusted": False,
            "signature_required": self.signature_required,
            "signature_status": self.signature_status.value,
            "signature_timestamp": (
                self.signature_timestamp.isoformat().replace("+00:00", "Z")
                if self.signature_timestamp
                else None
            ),
            "signature_max_age_seconds": self.signature_max_age_seconds,
            "replay": self.replay.value,
            "accepted": self.accepted(),
        }


class InMemoryEventReplayGuard:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str, str]] = set()

    def observe(self, *, connector_id: str, binding_ref: str, event_ref: str) -> ReplayDisposition:
        key = (
            _safe_ref(connector_id, "connector_id"),
            _safe_ref(binding_ref, "binding_ref"),
            _safe_ref(event_ref, "event_ref"),
        )
        if key in self._seen:
            return ReplayDisposition.DUPLICATE
        self._seen.add(key)
        return ReplayDisposition.NEW


@dataclass(frozen=True, slots=True)
class ConnectorWriteIntent:
    connector_id: str
    binding_ref: str
    actor_ref: str
    tool_name: str
    target_ref: str
    payload_fingerprint: str
    idempotency_key: str
    approval_ref: str
    evidence_ref: str
    requested_at: datetime
    expected_version_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "connector_id",
            "binding_ref",
            "actor_ref",
            "tool_name",
            "target_ref",
            "idempotency_key",
            "approval_ref",
            "evidence_ref",
        ):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "payload_fingerprint",
            _fingerprint(self.payload_fingerprint, "payload_fingerprint"),
        )
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if self.expected_version_ref is not None:
            object.__setattr__(
                self,
                "expected_version_ref",
                _safe_ref(self.expected_version_ref, "expected_version_ref"),
            )

    def stable_identity(self) -> tuple[str, ...]:
        return (
            self.connector_id,
            self.binding_ref,
            self.actor_ref,
            self.tool_name,
            self.target_ref,
            self.payload_fingerprint,
            self.approval_ref,
            self.evidence_ref,
            self.expected_version_ref or "",
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-connector-write-intent.v1",
            "connector_id": self.connector_id,
            "binding_ref": self.binding_ref,
            "actor_ref": self.actor_ref,
            "tool_name": self.tool_name,
            "target_ref": self.target_ref,
            "payload_fingerprint": self.payload_fingerprint,
            "idempotency_key": self.idempotency_key,
            "approval_ref": self.approval_ref,
            "evidence_ref": self.evidence_ref,
            "expected_version_ref": self.expected_version_ref,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "payload_text_present": False,
            "model_text_counts_as_success": False,
        }


class IdempotencyDisposition(str, Enum):
    NEW = "new"
    REPLAY_SAME = "replay_same"
    CONFLICT = "conflict"


class InMemoryWriteIdempotencyRegistry:
    def __init__(self) -> None:
        self._seen: dict[str, tuple[str, ...]] = {}

    def observe(self, intent: ConnectorWriteIntent) -> IdempotencyDisposition:
        if not isinstance(intent, ConnectorWriteIntent):
            raise ContractError("intent must be ConnectorWriteIntent")
        identity = intent.stable_identity()
        existing = self._seen.get(intent.idempotency_key)
        if existing is None:
            self._seen[intent.idempotency_key] = identity
            return IdempotencyDisposition.NEW
        if existing == identity:
            return IdempotencyDisposition.REPLAY_SAME
        return IdempotencyDisposition.CONFLICT


@dataclass(frozen=True, slots=True)
class ConnectorRateLimitProjection:
    observed_at: datetime
    remaining: int | None = None
    limit: int | None = None
    retry_after_seconds: int | None = None
    reset_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "remaining", _non_negative_int(self.remaining, "remaining"))
        object.__setattr__(self, "limit", _non_negative_int(self.limit, "limit"))
        object.__setattr__(
            self,
            "retry_after_seconds",
            _non_negative_int(self.retry_after_seconds, "retry_after_seconds"),
        )
        if self.limit is not None and self.remaining is not None and self.remaining > self.limit:
            raise ContractError("remaining cannot exceed limit")
        if self.reset_at is not None:
            object.__setattr__(self, "reset_at", _aware(self.reset_at, "reset_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "remaining": self.remaining,
            "limit": self.limit,
            "retry_after_seconds": self.retry_after_seconds,
            "reset_at": self.reset_at.isoformat().replace("+00:00", "Z") if self.reset_at else None,
        }


class ConnectorProviderErrorKind(str, Enum):
    AUTHORIZATION = "authorization"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ConnectorProviderError:
    kind: ConnectorProviderErrorKind
    error_ref: str
    retryable: bool
    rate_limit: ConnectorRateLimitProjection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ConnectorProviderErrorKind):
            try:
                object.__setattr__(self, "kind", ConnectorProviderErrorKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid provider error kind") from exc
        object.__setattr__(self, "error_ref", _safe_ref(self.error_ref, "error_ref"))
        if not isinstance(self.retryable, bool):
            raise ContractError("retryable must be boolean")
        if self.rate_limit is not None and not isinstance(self.rate_limit, ConnectorRateLimitProjection):
            raise ContractError("rate_limit must be ConnectorRateLimitProjection")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "error_ref": self.error_ref,
            "retryable": self.retryable,
            "rate_limit": self.rate_limit.safe_dict() if self.rate_limit else None,
            "raw_provider_error": False,
        }


@dataclass(frozen=True, slots=True)
class ConnectorWriteReceipt:
    receipt_ref: str
    connector_id: str
    binding_ref: str
    idempotency_key: str
    provider_operation_ref: str
    target_ref: str
    committed_at: datetime
    evidence_ref: str
    version_ref: str | None = None
    rate_limit: ConnectorRateLimitProjection | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_ref",
            "connector_id",
            "binding_ref",
            "idempotency_key",
            "provider_operation_ref",
            "target_ref",
            "evidence_ref",
        ):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "committed_at", _aware(self.committed_at, "committed_at"))
        if self.version_ref is not None:
            object.__setattr__(self, "version_ref", _safe_ref(self.version_ref, "version_ref"))
        if self.rate_limit is not None and not isinstance(self.rate_limit, ConnectorRateLimitProjection):
            raise ContractError("rate_limit must be ConnectorRateLimitProjection")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-connector-write-receipt.v1",
            "receipt_ref": self.receipt_ref,
            "connector_id": self.connector_id,
            "binding_ref": self.binding_ref,
            "idempotency_key": self.idempotency_key,
            "provider_operation_ref": self.provider_operation_ref,
            "target_ref": self.target_ref,
            "committed_at": self.committed_at.isoformat().replace("+00:00", "Z"),
            "evidence_ref": self.evidence_ref,
            "version_ref": self.version_ref,
            "rate_limit": self.rate_limit.safe_dict() if self.rate_limit else None,
            "trusted_receipt": True,
            "model_text_counts_as_success": False,
        }


TRUSTED_CONNECTOR_BINDING_REQUIRED = True
RAW_CONNECTOR_SECRET_IN_B54 = False
FAKE_CONNECTOR_COUNTS_AS_LIVE = False
MODEL_TEXT_COUNTS_AS_EXTERNAL_WRITE_SUCCESS = False
