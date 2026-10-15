from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _sha(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be lowercase SHA-256")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class ProductCommandKind(str, Enum):
    START_CLOUD_RUN = "start_cloud_run"
    CREATE_RFQ_DRAFT = "create_rfq_draft"
    REQUEST_APPROVAL = "request_approval"
    SUBMIT_APPROVED_COMMUNICATION = "submit_approved_communication"
    CREATE_DRAFT_PR = "create_draft_pr"
    CANCEL_RUN = "cancel_run"


class ProductCommandStatus(str, Enum):
    RECEIVED = "received"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS = {
    ProductCommandStatus.RECEIVED: {ProductCommandStatus.DISPATCHED, ProductCommandStatus.FAILED},
    ProductCommandStatus.DISPATCHED: {ProductCommandStatus.COMPLETED, ProductCommandStatus.FAILED},
    ProductCommandStatus.COMPLETED: set(),
    ProductCommandStatus.FAILED: set(),
}


@dataclass(frozen=True, slots=True)
class ProductCommandEnvelope:
    command_id: str
    idempotency_key: str
    trusted_session_ref: str
    workspace_id: str
    kind: ProductCommandKind
    subject_ref: str
    subject_version: int
    payload_sha256: str
    requested_at: datetime

    def __post_init__(self) -> None:
        for name in ("command_id", "idempotency_key", "trusted_session_ref", "workspace_id", "subject_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if not isinstance(self.kind, ProductCommandKind):
            try:
                object.__setattr__(self, "kind", ProductCommandKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid product command kind") from exc
        if isinstance(self.subject_version, bool) or not isinstance(self.subject_version, int) or self.subject_version < 1:
            raise ContractError("subject_version must be positive")
        object.__setattr__(self, "payload_sha256", _sha(self.payload_sha256, "payload_sha256"))
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))

    @property
    def fingerprint(self) -> str:
        payload = {
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "trusted_session_ref": self.trusted_session_ref,
            "workspace_id": self.workspace_id,
            "kind": self.kind.value,
            "subject_ref": self.subject_ref,
            "subject_version": self.subject_version,
            "payload_sha256": self.payload_sha256,
            "requested_at": self.requested_at.isoformat(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "trusted_session_ref": self.trusted_session_ref,
            "workspace_id": self.workspace_id,
            "kind": self.kind.value,
            "subject_ref": self.subject_ref,
            "subject_version": self.subject_version,
            "payload_sha256": self.payload_sha256,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "command_fingerprint": self.fingerprint,
            "raw_payload": False,
            "authorization_granted": False,
            "approval_minted": False,
        }


@dataclass(frozen=True, slots=True)
class ProductCommandRecord:
    envelope: ProductCommandEnvelope
    status: ProductCommandStatus
    updated_at: datetime
    result_ref: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, ProductCommandEnvelope):
            raise ContractError("envelope must be ProductCommandEnvelope")
        if not isinstance(self.status, ProductCommandStatus):
            raise ContractError("status must be ProductCommandStatus")
        object.__setattr__(self, "updated_at", _aware(self.updated_at, "updated_at"))
        if self.updated_at < self.envelope.requested_at:
            raise ContractError("command update cannot predate request")
        if self.result_ref is not None:
            object.__setattr__(self, "result_ref", _ref(self.result_ref, "result_ref"))
        if self.failure_code is not None:
            object.__setattr__(self, "failure_code", _ref(self.failure_code, "failure_code"))
        if self.status is ProductCommandStatus.COMPLETED and self.result_ref is None:
            raise ContractError("completed command requires result_ref")
        if self.status is ProductCommandStatus.FAILED and self.failure_code is None:
            raise ContractError("failed command requires failure_code")


class InMemoryProductCommandJournal:
    def __init__(self) -> None:
        self._by_command: dict[str, ProductCommandRecord] = {}
        self._by_idempotency: dict[tuple[str, str], str] = {}

    def receive(self, envelope: ProductCommandEnvelope) -> ProductCommandRecord:
        if not isinstance(envelope, ProductCommandEnvelope):
            raise ContractError("envelope must be ProductCommandEnvelope")
        existing = self._by_command.get(envelope.command_id)
        if existing is not None:
            if existing.envelope.fingerprint != envelope.fingerprint:
                raise ContractError("conflicting command_id replay")
            return existing
        key = (envelope.workspace_id, envelope.idempotency_key)
        prior_id = self._by_idempotency.get(key)
        if prior_id is not None:
            prior = self._by_command[prior_id]
            if prior.envelope.fingerprint != envelope.fingerprint:
                raise ContractError("idempotency key already belongs to different command fingerprint")
            return prior
        record = ProductCommandRecord(envelope=envelope, status=ProductCommandStatus.RECEIVED, updated_at=envelope.requested_at)
        self._by_command[envelope.command_id] = record
        self._by_idempotency[key] = envelope.command_id
        return record

    def transition(self, command_id: str, *, status: ProductCommandStatus, updated_at: datetime, result_ref: str | None = None, failure_code: str | None = None) -> ProductCommandRecord:
        command_id = _ref(command_id, "command_id")
        try:
            current = self._by_command[command_id]
        except KeyError as exc:
            raise ContractError("unknown product command") from exc
        if not isinstance(status, ProductCommandStatus):
            raise ContractError("status must be ProductCommandStatus")
        if status not in _ALLOWED_TRANSITIONS[current.status]:
            raise ContractError("illegal or terminal product command transition")
        record = ProductCommandRecord(
            envelope=current.envelope,
            status=status,
            updated_at=updated_at,
            result_ref=result_ref,
            failure_code=failure_code,
        )
        self._by_command[command_id] = record
        return record


RAW_COMMAND_PAYLOAD_SUPPORTED = False
COMMAND_ENVELOPE_AUTHORIZATION_SUPPORTED = False
COMMAND_ENVELOPE_APPROVAL_MINTING_SUPPORTED = False
REAL_API_SERVER_CONFIGURED = False
