from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from .contracts import ContractError
from .security import redact_secrets

MAX_MESSAGE_BODY_CHARS = 20_000
MAX_THREAD_MESSAGES = 8
MAX_THREAD_BODY_CHARS = 60_000
MAX_ATTACHMENTS_PER_MESSAGE = 10
MAX_ATTACHMENT_BYTES_FOR_QUARANTINE = 10 * 1024 * 1024
MAX_APPROVED_RECIPIENTS = 20
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _optional_ref(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _safe_ref(value, field_name)


def _bounded_text(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = redact_secrets(value.strip())
    if len(normalized) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _fingerprint(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value.strip().lower()


def _email_address(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 320
        or any(ord(char) < 32 for char in normalized)
        or normalized.count("@") != 1
    ):
        raise ContractError(f"{field_name} must be a bounded email address")
    local, domain = normalized.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise ContractError(f"{field_name} must be a bounded email address")
    return f"{local}@{domain.lower()}"


def _addresses(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_email_address(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{field_name} addresses must be unique")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _size(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field_name} must be a non-negative integer")
    if value > MAX_ATTACHMENT_BYTES_FOR_QUARANTINE:
        raise ContractError("attachment exceeds B54 quarantine ingress bound")
    return value


class GmailCapability(str, Enum):
    READ = "read"
    CREATE_DRAFT = "create_draft"
    SEND_EXISTING_APPROVED_DRAFT = "send_existing_approved_draft"
    LABEL_MUTATION = "label_mutation"


def provider_scopes_for_capability(capability: GmailCapability) -> tuple[str, ...]:
    if not isinstance(capability, GmailCapability):
        raise ContractError("capability must be GmailCapability")
    if capability is GmailCapability.READ:
        return (GMAIL_READONLY_SCOPE,)
    if capability is GmailCapability.CREATE_DRAFT:
        return (GMAIL_COMPOSE_SCOPE,)
    if capability is GmailCapability.SEND_EXISTING_APPROVED_DRAFT:
        # Gmail drafts.send accepts gmail.compose. Padiem still requires a separate
        # SEND capability + P01 approval because provider scope is broader than our authority.
        return (GMAIL_COMPOSE_SCOPE,)
    if capability is GmailCapability.LABEL_MUTATION:
        return ("https://www.googleapis.com/auth/gmail.modify",)
    raise ContractError("unsupported Gmail capability")


class GmailBodyKind(str, Enum):
    PLAIN = "plain"
    HTML_TEXT = "html_text"
    QUOTED = "quoted"
    FORWARDED = "forwarded"
    SIGNATURE = "signature"


@dataclass(frozen=True, slots=True)
class GmailBodySegment:
    kind: GmailBodyKind
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, GmailBodyKind):
            try:
                object.__setattr__(self, "kind", GmailBodyKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Gmail body kind") from exc
        object.__setattr__(self, "text", _bounded_text(self.text, "body text", MAX_MESSAGE_BODY_CHARS))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "text": self.text,
            "trusted_instruction": False,
        }


class AttachmentQuarantineState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class GmailAttachmentManifest:
    attachment_ref: str
    message_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str | None = None
    quarantine_state: AttachmentQuarantineState = AttachmentQuarantineState.PENDING
    quarantine_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_ref", _safe_ref(self.attachment_ref, "attachment_ref"))
        object.__setattr__(self, "message_id", _safe_ref(self.message_id, "message_id"))
        object.__setattr__(self, "filename", _bounded_text(self.filename, "filename", 512))
        object.__setattr__(self, "mime_type", _bounded_text(self.mime_type, "mime_type", 255))
        object.__setattr__(self, "size_bytes", _size(self.size_bytes, "size_bytes"))
        if self.sha256 is not None:
            object.__setattr__(self, "sha256", _fingerprint(self.sha256, "sha256"))
        if not isinstance(self.quarantine_state, AttachmentQuarantineState):
            try:
                object.__setattr__(
                    self,
                    "quarantine_state",
                    AttachmentQuarantineState(self.quarantine_state),
                )
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid attachment quarantine state") from exc
        object.__setattr__(
            self,
            "quarantine_evidence_ref",
            _optional_ref(self.quarantine_evidence_ref, "quarantine_evidence_ref"),
        )
        if self.quarantine_state is AttachmentQuarantineState.ACCEPTED:
            if self.sha256 is None or self.quarantine_evidence_ref is None:
                raise ContractError("accepted attachment requires SHA-256 and quarantine evidence")
        elif self.quarantine_evidence_ref is not None:
            raise ContractError("only accepted attachment may carry quarantine evidence")

    def model_usable(self) -> bool:
        return (
            self.quarantine_state is AttachmentQuarantineState.ACCEPTED
            and self.sha256 is not None
            and self.quarantine_evidence_ref is not None
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "attachment_ref": self.attachment_ref,
            "message_id": self.message_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "quarantine_state": self.quarantine_state.value,
            "quarantine_evidence_ref": self.quarantine_evidence_ref,
            "raw_bytes_present": False,
            "model_usable": self.model_usable(),
        }


@dataclass(frozen=True, slots=True)
class GmailMessageProjection:
    message_id: str
    thread_id: str
    from_address: str
    to_addresses: tuple[str, ...]
    subject: str
    date_header: str
    body_segments: tuple[GmailBodySegment, ...]
    label_ids: tuple[str, ...] = ()
    cc_addresses: tuple[str, ...] = ()
    bcc_addresses: tuple[str, ...] = ()
    attachments: tuple[GmailAttachmentManifest, ...] = ()
    internal_date_ref: str | None = None
    history_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", _safe_ref(self.message_id, "message_id"))
        object.__setattr__(self, "thread_id", _safe_ref(self.thread_id, "thread_id"))
        object.__setattr__(self, "from_address", _email_address(self.from_address, "from_address"))
        object.__setattr__(self, "to_addresses", _addresses(self.to_addresses, "to_address"))
        object.__setattr__(self, "cc_addresses", _addresses(self.cc_addresses, "cc_address"))
        object.__setattr__(self, "bcc_addresses", _addresses(self.bcc_addresses, "bcc_address"))
        object.__setattr__(self, "subject", _bounded_text(self.subject, "subject", 998))
        object.__setattr__(self, "date_header", _bounded_text(self.date_header, "date_header", 256))
        if not isinstance(self.body_segments, tuple) or any(
            not isinstance(segment, GmailBodySegment) for segment in self.body_segments
        ):
            raise ContractError("body_segments must contain GmailBodySegment values")
        total_chars = sum(len(segment.text) for segment in self.body_segments)
        if total_chars > MAX_MESSAGE_BODY_CHARS:
            raise ContractError("message body exceeds bounded context size")
        label_ids = tuple(_safe_ref(value, "label_id") for value in self.label_ids)
        if len(label_ids) != len(set(label_ids)):
            raise ContractError("label_ids must be unique")
        object.__setattr__(self, "label_ids", label_ids)
        if len(self.attachments) > MAX_ATTACHMENTS_PER_MESSAGE or any(
            not isinstance(item, GmailAttachmentManifest) for item in self.attachments
        ):
            raise ContractError("attachments exceed bounded manifest")
        if any(item.message_id != self.message_id for item in self.attachments):
            raise ContractError("attachment message_id must match message")
        object.__setattr__(self, "internal_date_ref", _optional_ref(self.internal_date_ref, "internal_date_ref"))
        object.__setattr__(self, "history_id", _optional_ref(self.history_id, "history_id"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "from_address": self.from_address,
            "to_addresses": list(self.to_addresses),
            "cc_addresses": list(self.cc_addresses),
            "bcc_addresses": list(self.bcc_addresses),
            "subject": self.subject,
            "date_header": self.date_header,
            "body_segments": [segment.safe_dict() for segment in self.body_segments],
            "label_ids": list(self.label_ids),
            "attachments": [item.safe_dict() for item in self.attachments],
            "internal_date_ref": self.internal_date_ref,
            "history_id": self.history_id,
            "mail_content_trusted": False,
        }


@dataclass(frozen=True, slots=True)
class GmailThreadProjection:
    thread_id: str
    messages: tuple[GmailMessageProjection, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "thread_id", _safe_ref(self.thread_id, "thread_id"))
        if not self.messages or len(self.messages) > MAX_THREAD_MESSAGES:
            raise ContractError("thread must contain between 1 and bounded maximum messages")
        if any(not isinstance(message, GmailMessageProjection) for message in self.messages):
            raise ContractError("messages must contain GmailMessageProjection values")
        if any(message.thread_id != self.thread_id for message in self.messages):
            raise ContractError("message thread_id must match thread")
        body_chars = sum(
            len(segment.text)
            for message in self.messages
            for segment in message.body_segments
        )
        if body_chars > MAX_THREAD_BODY_CHARS:
            raise ContractError("thread body exceeds bounded context size")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "messages": [message.safe_dict() for message in self.messages],
            "mail_content_trusted": False,
            "bulk_mailbox_dump": False,
        }


@dataclass(frozen=True, slots=True)
class GmailApprovedAttachment:
    attachment_ref: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    quarantine_evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_ref", _safe_ref(self.attachment_ref, "attachment_ref"))
        object.__setattr__(self, "filename", _bounded_text(self.filename, "filename", 512))
        object.__setattr__(self, "mime_type", _bounded_text(self.mime_type, "mime_type", 255))
        object.__setattr__(self, "size_bytes", _size(self.size_bytes, "size_bytes"))
        object.__setattr__(self, "sha256", _fingerprint(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "quarantine_evidence_ref",
            _safe_ref(self.quarantine_evidence_ref, "quarantine_evidence_ref"),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "attachment_ref": self.attachment_ref,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "quarantine_evidence_ref": self.quarantine_evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class GmailDraftMaterialSnapshot:
    binding_ref: str
    workspace_ref: str
    draft_id: str
    message_id: str
    from_address: str
    to_addresses: tuple[str, ...]
    subject: str
    body_sha256: str
    cc_addresses: tuple[str, ...] = ()
    bcc_addresses: tuple[str, ...] = ()
    attachments: tuple[GmailApprovedAttachment, ...] = ()
    thread_id: str | None = None
    reply_message_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "workspace_ref", "draft_id", "message_id"):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "from_address", _email_address(self.from_address, "from_address"))
        object.__setattr__(self, "to_addresses", _addresses(self.to_addresses, "to_address"))
        object.__setattr__(self, "cc_addresses", _addresses(self.cc_addresses, "cc_address"))
        object.__setattr__(self, "bcc_addresses", _addresses(self.bcc_addresses, "bcc_address"))
        recipient_count = len(self.to_addresses) + len(self.cc_addresses) + len(self.bcc_addresses)
        if recipient_count < 1 or recipient_count > MAX_APPROVED_RECIPIENTS:
            raise ContractError("approved Gmail send must have 1..20 recipients")
        object.__setattr__(self, "subject", _bounded_text(self.subject, "subject", 998))
        object.__setattr__(self, "body_sha256", _fingerprint(self.body_sha256, "body_sha256"))
        if any(not isinstance(item, GmailApprovedAttachment) for item in self.attachments):
            raise ContractError("attachments must contain GmailApprovedAttachment values")
        if len(self.attachments) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise ContractError("approved attachment count exceeds bound")
        refs = [item.attachment_ref for item in self.attachments]
        if len(refs) != len(set(refs)):
            raise ContractError("approved attachment refs must be unique")
        object.__setattr__(self, "thread_id", _optional_ref(self.thread_id, "thread_id"))
        object.__setattr__(self, "reply_message_ref", _optional_ref(self.reply_message_ref, "reply_message_ref"))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "draft_id": self.draft_id,
            "message_id": self.message_id,
            "from_address": self.from_address,
            "to_addresses": sorted(self.to_addresses),
            "cc_addresses": sorted(self.cc_addresses),
            "bcc_addresses": sorted(self.bcc_addresses),
            "subject": self.subject,
            "body_sha256": self.body_sha256,
            "attachments": sorted(
                (item.canonical_dict() for item in self.attachments),
                key=lambda item: (item["attachment_ref"], item["sha256"]),
            ),
            "thread_id": self.thread_id,
            "reply_message_ref": self.reply_message_ref,
        }

    @property
    def material_fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def material_version_ref(self) -> str:
        return f"gmail-draft:{self.material_fingerprint}"


@dataclass(frozen=True, slots=True)
class GmailSendApprovalBinding:
    approval_ref: str
    evidence_ref: str
    material_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _safe_ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(
            self,
            "material_fingerprint",
            _fingerprint(self.material_fingerprint, "material_fingerprint"),
        )
        object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at"))


class GmailSendPreflightDecision(str, Enum):
    ALLOW = "allow"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    DRAFT_TARGET_MISMATCH = "draft_target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    VERSION_BINDING_MISMATCH = "version_binding_mismatch"


def gmail_send_preflight(
    *,
    snapshot: GmailDraftMaterialSnapshot,
    approval: GmailSendApprovalBinding,
    intent: ConnectorWriteIntent,
) -> GmailSendPreflightDecision:
    if not isinstance(snapshot, GmailDraftMaterialSnapshot):
        raise ContractError("snapshot must be GmailDraftMaterialSnapshot")
    if not isinstance(approval, GmailSendApprovalBinding):
        raise ContractError("approval must be GmailSendApprovalBinding")
    if not isinstance(intent, ConnectorWriteIntent):
        raise ContractError("intent must be ConnectorWriteIntent")
    if intent.connector_id != "gmail" or intent.tool_name != GmailCapability.SEND_EXISTING_APPROVED_DRAFT.value:
        return GmailSendPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != snapshot.binding_ref or intent.target_ref != snapshot.draft_id:
        return GmailSendPreflightDecision.DRAFT_TARGET_MISMATCH
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return GmailSendPreflightDecision.APPROVAL_MISMATCH
    if snapshot.material_fingerprint != approval.material_fingerprint:
        return GmailSendPreflightDecision.MATERIAL_CHANGED
    if intent.payload_fingerprint != snapshot.material_fingerprint:
        return GmailSendPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != snapshot.material_version_ref:
        return GmailSendPreflightDecision.VERSION_BINDING_MISMATCH
    return GmailSendPreflightDecision.ALLOW


@dataclass(frozen=True, slots=True)
class GmailSendReceipt:
    connector_receipt: ConnectorWriteReceipt
    sent_message_id: str
    sent_thread_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.connector_receipt, ConnectorWriteReceipt):
            raise ContractError("connector_receipt must be ConnectorWriteReceipt")
        if self.connector_receipt.connector_id != "gmail":
            raise ContractError("Gmail send receipt requires gmail connector receipt")
        object.__setattr__(self, "sent_message_id", _safe_ref(self.sent_message_id, "sent_message_id"))
        object.__setattr__(self, "sent_thread_id", _safe_ref(self.sent_thread_id, "sent_thread_id"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_receipt": self.connector_receipt.safe_dict(),
            "sent_message_id": self.sent_message_id,
            "sent_thread_id": self.sent_thread_id,
            "provider_delivery_receipt": True,
            "model_text_counts_as_delivery": False,
        }


GMAIL_MCP_SEND_TOOL_SUPPORTED = False
GMAIL_MCP_CREATE_DRAFT_SUPPORTED = True
GMAIL_PROVIDER_COMPOSE_SCOPE_INCLUDES_SEND = True
GMAIL_PROVIDER_SCOPE_ALONE_GRANTS_PADIEM_SEND_AUTHORITY = False
GMAIL_SEND_REQUIRES_P01_APPROVAL = True
GMAIL_ATTACHMENT_QUARANTINE_REQUIRED = True
GMAIL_BULK_MAILBOX_DUMP_SUPPORTED = False
GMAIL_AUTONOMOUS_MASS_SEND_SUPPORTED = False
REAL_GMAIL_SEND_CONFIGURED = False
