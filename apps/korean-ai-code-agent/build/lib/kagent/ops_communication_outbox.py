from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .contracts import ContractError
from .ops_communications import (
    CommunicationConnectorPort,
    CommunicationDeliveryReceipt,
    CommunicationSendRequest,
)


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def communication_request_fingerprint(request: CommunicationSendRequest) -> str:
    if not isinstance(request, CommunicationSendRequest):
        raise ContractError("request must be CommunicationSendRequest")
    payload = {
        "request_id": request.request_id,
        "workspace_id": request.workspace_id,
        "channel": request.channel.value,
        "recipient_ref": request.recipient_ref,
        "subject_sha256": hashlib.sha256(request.subject.encode("utf-8")).hexdigest(),
        "body_sha256": hashlib.sha256(request.body.encode("utf-8")).hexdigest(),
        "target_kind": request.target_kind.value,
        "target_id": request.target_id,
        "target_version": request.target_version,
        "action_fingerprint": request.action_fingerprint,
        "approval_id": request.approval_id,
        "attachments": [
            {
                "attachment_id": item.attachment_id,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "mime_type": item.mime_type,
            }
            for item in request.attachments
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OutboxState(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True, slots=True)
class CommunicationOutboxRecord:
    outbox_id: str
    request_id: str
    workspace_id: str
    request_fingerprint: str
    state: OutboxState
    created_at: datetime
    attempted_at: datetime | None = None
    sent_at: datetime | None = None
    connector_id: str | None = None
    external_message_ref: str | None = None
    failure_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("outbox_id", "request_id", "workspace_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        digest = self.request_fingerprint.strip().lower() if isinstance(self.request_fingerprint, str) else ""
        if not _SHA256_RE.fullmatch(digest):
            raise ContractError("request_fingerprint must be SHA-256")
        object.__setattr__(self, "request_fingerprint", digest)
        if not isinstance(self.state, OutboxState):
            try:
                object.__setattr__(self, "state", OutboxState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid outbox state") from exc
        created = _aware(self.created_at, "created_at")
        object.__setattr__(self, "created_at", created)
        for field_name in ("attempted_at", "sent_at"):
            value = getattr(self, field_name)
            if value is not None:
                value = _aware(value, field_name)
                if value < created:
                    raise ContractError(f"{field_name} cannot precede created_at")
                object.__setattr__(self, field_name, value)
        for field_name in ("connector_id", "external_message_ref", "failure_ref"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _ref(value, field_name))
        if self.state is OutboxState.PENDING:
            if any(value is not None for value in (self.attempted_at, self.sent_at, self.connector_id, self.external_message_ref, self.failure_ref)):
                raise ContractError("pending outbox record cannot contain attempt/result metadata")
        elif self.state is OutboxState.SENT:
            if self.attempted_at is None or self.sent_at is None or self.connector_id is None or self.external_message_ref is None or self.failure_ref is not None:
                raise ContractError("sent outbox record requires correlated delivery metadata")
        elif self.state is OutboxState.RECONCILIATION_REQUIRED:
            if self.attempted_at is None or self.failure_ref is None or self.sent_at is not None:
                raise ContractError("reconciliation record requires attempted_at and failure_ref")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "outbox_id": self.outbox_id,
            "request_id": self.request_id,
            "workspace_id": self.workspace_id,
            "request_fingerprint": self.request_fingerprint,
            "state": self.state.value,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "attempted_at": self.attempted_at.isoformat().replace("+00:00", "Z") if self.attempted_at else None,
            "sent_at": self.sent_at.isoformat().replace("+00:00", "Z") if self.sent_at else None,
            "connector_id": self.connector_id,
            "external_message_ref": self.external_message_ref,
            "failure_ref": self.failure_ref,
            "raw_subject_or_body_stored": False,
            "automatic_retry_after_ambiguous_failure": False,
        }


class InMemoryCommunicationOutbox:
    def __init__(self) -> None:
        self._records: dict[str, CommunicationOutboxRecord] = {}

    def prepare(self, request: CommunicationSendRequest, *, now: datetime) -> CommunicationOutboxRecord:
        if not isinstance(request, CommunicationSendRequest):
            raise ContractError("request must be CommunicationSendRequest")
        fingerprint = communication_request_fingerprint(request)
        existing = self._records.get(request.request_id)
        if existing is not None:
            if existing.request_fingerprint != fingerprint or existing.workspace_id != request.workspace_id:
                raise ContractError("communication request ID replay conflicts with existing outbox record")
            return existing
        record = CommunicationOutboxRecord(
            outbox_id=f"outbox:{request.request_id}",
            request_id=request.request_id,
            workspace_id=request.workspace_id,
            request_fingerprint=fingerprint,
            state=OutboxState.PENDING,
            created_at=now,
        )
        self._records[request.request_id] = record
        return record

    def record(self, request_id: str) -> CommunicationOutboxRecord:
        request_id = _ref(request_id, "request_id")
        try:
            return self._records[request_id]
        except KeyError as exc:
            raise ContractError("communication outbox record not found") from exc

    def send_once(
        self,
        request: CommunicationSendRequest,
        *,
        connector: CommunicationConnectorPort,
        now: datetime,
    ) -> CommunicationOutboxRecord:
        record = self.prepare(request, now=now)
        if record.state is OutboxState.SENT:
            return record
        if record.state is OutboxState.RECONCILIATION_REQUIRED:
            raise ContractError("ambiguous communication delivery requires reconciliation before retry")
        attempted_at = _aware(now, "now")
        try:
            receipt = connector.send(request)
        except Exception as exc:
            failure_digest = hashlib.sha256(type(exc).__name__.encode("utf-8")).hexdigest()[:24]
            reconciled = CommunicationOutboxRecord(
                outbox_id=record.outbox_id,
                request_id=record.request_id,
                workspace_id=record.workspace_id,
                request_fingerprint=record.request_fingerprint,
                state=OutboxState.RECONCILIATION_REQUIRED,
                created_at=record.created_at,
                attempted_at=attempted_at,
                failure_ref=f"connector_failure:{failure_digest}",
            )
            self._records[request.request_id] = reconciled
            return reconciled
        if not isinstance(receipt, CommunicationDeliveryReceipt):
            raise ContractError("connector returned invalid delivery receipt")
        if receipt.request_id != request.request_id:
            raise ContractError("communication delivery receipt request correlation mismatch")
        if receipt.delivered_at < attempted_at:
            raise ContractError("delivery receipt predates send attempt")
        sent = CommunicationOutboxRecord(
            outbox_id=record.outbox_id,
            request_id=record.request_id,
            workspace_id=record.workspace_id,
            request_fingerprint=record.request_fingerprint,
            state=OutboxState.SENT,
            created_at=record.created_at,
            attempted_at=attempted_at,
            sent_at=receipt.delivered_at,
            connector_id=receipt.connector_id,
            external_message_ref=receipt.external_message_ref,
        )
        self._records[request.request_id] = sent
        return sent


AUTOMATIC_RETRY_AFTER_AMBIGUOUS_DELIVERY_SUPPORTED = False
