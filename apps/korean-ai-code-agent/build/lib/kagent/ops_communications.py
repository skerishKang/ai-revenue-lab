from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Protocol

from .contracts import ContractError
from .ops_contracts import BusinessObjectKind
from .security import redact_secrets


class CommunicationChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    BUSINESS_MESSAGING = "business_messaging"
    KAKAO_BUSINESS = "kakao_business"


class AttachmentDisposition(str, Enum):
    ACCEPTED = "accepted"
    REJECTED_TYPE = "rejected_type"
    REJECTED_SIZE = "rejected_size"


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "text/csv",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > 512 or not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} has invalid reference syntax")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain a raw credential")
    return value


def _bounded_text(value: str, field_name: str, *, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not allow_empty and not value:
        raise ContractError(f"{field_name} is required")
    if len(value) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class AttachmentMetadata:
    attachment_id: str
    file_name: str
    mime_type: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_id", _ref(self.attachment_id, "attachment_id"))
        object.__setattr__(self, "file_name", _bounded_text(self.file_name, "file_name", limit=255))
        object.__setattr__(self, "mime_type", _bounded_text(self.mime_type.lower(), "mime_type", limit=160))
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ContractError("size_bytes must be a non-negative integer")
        digest = self.sha256.strip().lower() if isinstance(self.sha256, str) else ""
        if not _SHA256_RE.fullmatch(digest):
            raise ContractError("sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True, slots=True)
class AttachmentPolicy:
    max_file_bytes: int = 10 * 1024 * 1024
    max_attachments: int = 10
    allowed_mime_types: frozenset[str] = _ALLOWED_MIME_TYPES

    def __post_init__(self) -> None:
        if isinstance(self.max_file_bytes, bool) or not isinstance(self.max_file_bytes, int) or not 1 <= self.max_file_bytes <= 100 * 1024 * 1024:
            raise ContractError("max_file_bytes must be between 1 byte and 100 MiB")
        if isinstance(self.max_attachments, bool) or not isinstance(self.max_attachments, int) or not 0 <= self.max_attachments <= 100:
            raise ContractError("max_attachments must be between 0 and 100")
        if not isinstance(self.allowed_mime_types, frozenset) or not self.allowed_mime_types:
            raise ContractError("allowed_mime_types must be a non-empty frozenset")

    def disposition(self, attachment: AttachmentMetadata) -> AttachmentDisposition:
        if not isinstance(attachment, AttachmentMetadata):
            raise ContractError("attachment must be AttachmentMetadata")
        if attachment.size_bytes > self.max_file_bytes:
            return AttachmentDisposition.REJECTED_SIZE
        if attachment.mime_type not in self.allowed_mime_types:
            return AttachmentDisposition.REJECTED_TYPE
        return AttachmentDisposition.ACCEPTED

    def require_accepted(self, attachments: tuple[AttachmentMetadata, ...]) -> None:
        if not isinstance(attachments, tuple) or len(attachments) > self.max_attachments:
            raise ContractError("attachment count exceeds policy")
        if len({item.attachment_id for item in attachments}) != len(attachments):
            raise ContractError("attachment IDs must be unique")
        for attachment in attachments:
            disposition = self.disposition(attachment)
            if disposition is not AttachmentDisposition.ACCEPTED:
                raise ContractError(f"attachment {attachment.attachment_id} rejected: {disposition.value}")


@dataclass(frozen=True, slots=True)
class CommunicationSendRequest:
    request_id: str
    workspace_id: str
    channel: CommunicationChannel
    recipient_ref: str
    subject: str
    body: str
    target_kind: BusinessObjectKind
    target_id: str
    target_version: int
    action_fingerprint: str
    approval_id: str
    attachments: tuple[AttachmentMetadata, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _ref(self.request_id, "request_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        if not isinstance(self.channel, CommunicationChannel):
            try:
                object.__setattr__(self, "channel", CommunicationChannel(self.channel))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid communication channel") from exc
        object.__setattr__(self, "recipient_ref", _ref(self.recipient_ref, "recipient_ref"))
        object.__setattr__(self, "subject", _bounded_text(self.subject, "subject", limit=500, allow_empty=True))
        object.__setattr__(self, "body", _bounded_text(self.body, "body", limit=20000))
        if not isinstance(self.target_kind, BusinessObjectKind):
            raise ContractError("target_kind must be BusinessObjectKind")
        object.__setattr__(self, "target_id", _ref(self.target_id, "target_id"))
        if isinstance(self.target_version, bool) or not isinstance(self.target_version, int) or self.target_version < 1:
            raise ContractError("target_version must be a positive integer")
        fingerprint = self.action_fingerprint.strip().lower() if isinstance(self.action_fingerprint, str) else ""
        if not _SHA256_RE.fullmatch(fingerprint):
            raise ContractError("action_fingerprint must be a SHA-256 digest")
        object.__setattr__(self, "action_fingerprint", fingerprint)
        object.__setattr__(self, "approval_id", _ref(self.approval_id, "approval_id"))
        if not isinstance(self.attachments, tuple) or len(self.attachments) > 100:
            raise ContractError("attachments must be a bounded tuple")
        if not all(isinstance(item, AttachmentMetadata) for item in self.attachments):
            raise ContractError("attachments must contain AttachmentMetadata values")

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workspace_id": self.workspace_id,
            "channel": self.channel.value,
            "recipient_ref": self.recipient_ref,
            "target_kind": self.target_kind.value,
            "target_id": self.target_id,
            "target_version": self.target_version,
            "action_fingerprint": self.action_fingerprint,
            "approval_id": self.approval_id,
            "attachment_ids": [item.attachment_id for item in self.attachments],
            "body_sha256": hashlib.sha256(self.body.encode("utf-8")).hexdigest(),
            "body_length": len(self.body),
        }


@dataclass(frozen=True, slots=True)
class CommunicationDeliveryReceipt:
    request_id: str
    connector_id: str
    external_message_ref: str
    delivered_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _ref(self.request_id, "request_id"))
        object.__setattr__(self, "connector_id", _ref(self.connector_id, "connector_id"))
        object.__setattr__(self, "external_message_ref", _ref(self.external_message_ref, "external_message_ref"))
        object.__setattr__(self, "delivered_at", _aware(self.delivered_at, "delivered_at"))


@dataclass(frozen=True, slots=True)
class InboundCommunication:
    inbound_id: str
    workspace_id: str
    channel: CommunicationChannel
    sender_ref: str
    thread_ref: str
    received_at: datetime
    body: str
    attachments: tuple[AttachmentMetadata, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "inbound_id", _ref(self.inbound_id, "inbound_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        if not isinstance(self.channel, CommunicationChannel):
            try:
                object.__setattr__(self, "channel", CommunicationChannel(self.channel))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid communication channel") from exc
        object.__setattr__(self, "sender_ref", _ref(self.sender_ref, "sender_ref"))
        object.__setattr__(self, "thread_ref", _ref(self.thread_ref, "thread_ref"))
        object.__setattr__(self, "received_at", _aware(self.received_at, "received_at"))
        object.__setattr__(self, "body", _bounded_text(self.body, "body", limit=50000, allow_empty=True))
        if not isinstance(self.attachments, tuple) or len(self.attachments) > 100:
            raise ContractError("attachments must be a bounded tuple")
        if not all(isinstance(item, AttachmentMetadata) for item in self.attachments):
            raise ContractError("attachments must contain AttachmentMetadata values")

    @property
    def trusted_execution_input(self) -> bool:
        return False

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "inbound_id": self.inbound_id,
            "workspace_id": self.workspace_id,
            "channel": self.channel.value,
            "sender_ref": self.sender_ref,
            "thread_ref": self.thread_ref,
            "received_at": self.received_at.isoformat().replace("+00:00", "Z"),
            "body_sha256": hashlib.sha256(self.body.encode("utf-8")).hexdigest(),
            "body_length": len(self.body),
            "attachment_ids": [item.attachment_id for item in self.attachments],
            "trusted_execution_input": False,
        }


class CommunicationConnectorPort(Protocol):
    def send(self, request: CommunicationSendRequest) -> CommunicationDeliveryReceipt:
        ...


class UnconfiguredCommunicationConnector:
    def send(self, request: CommunicationSendRequest) -> CommunicationDeliveryReceipt:
        raise ContractError("business communication connector is not configured")


class DeterministicFakeCommunicationConnector:
    def __init__(self, *, connector_id: str = "fake_connector") -> None:
        self.connector_id = _ref(connector_id, "connector_id")
        self.sent: list[CommunicationSendRequest] = []

    def send(self, request: CommunicationSendRequest) -> CommunicationDeliveryReceipt:
        if not isinstance(request, CommunicationSendRequest):
            raise ContractError("request must be CommunicationSendRequest")
        self.sent.append(request)
        digest = hashlib.sha256(f"{request.request_id}:{request.action_fingerprint}".encode("utf-8")).hexdigest()[:24]
        return CommunicationDeliveryReceipt(
            request_id=request.request_id,
            connector_id=self.connector_id,
            external_message_ref=f"fake_message:{digest}",
            delivered_at=datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc),
        )


PERSONAL_MESSENGER_SCRAPING_SUPPORTED = False
