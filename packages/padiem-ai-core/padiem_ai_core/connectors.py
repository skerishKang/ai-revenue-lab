"""Gmail read-only connector projection for P01 Core (WO-10 PR-A, #2010 Gmail leg).

Ported from the Claw-side reviewed implementation
(``apps/korean-ai-code-agent/src/kagent/gmail_connector.py`` and
``gmail_contracts.py``) into the Core connector/tool registry contract.
This module is a projection of already-reviewed logic, not a new design.

Core owns no HTTP, OAuth, credentials, or attachment byte reads. The host
application supplies a trusted :class:`GmailReadPort` implementation; Core
only shapes bounded, untrusted-mail JSON projections from provider responses.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import re
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr
from enum import Enum
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import quote

from .connector_registry import ConnectorDescriptor
from .contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from .tool_runtime import MAX_TOOL_OUTPUT_BYTES, ToolHandler, ToolRuntime


class GmailContractError(ValueError):
    """Safe Gmail projection contract failure (kagent ContractError port)."""


GMAIL_CONNECTOR_ID = "connector:google:gmail@1"

# Provider OAuth scope (trusted port boundary only; never a Core identifier).
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

# Core ToolSpec auth_scope token. contracts._IDENTIFIER_RE rejects "/" so the
# provider URL cannot be a ToolSpec scope; the port still receives the exact
# provider scope above as required_scopes.
GMAIL_READONLY_AUTH_SCOPE = "gmail.readonly"

GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1"

# Bounds ported verbatim from kagent gmail_contracts.py:15-19 and
# gmail_connector.py:37-45.
MAX_MESSAGE_BODY_CHARS = 20_000
MAX_THREAD_MESSAGES = 8
MAX_THREAD_BODY_CHARS = 60_000
MAX_ATTACHMENTS_PER_MESSAGE = 10
REQUEST_TIMEOUT_SECONDS = 30
SEARCH_RESULT_LIMIT = 10
MESSAGE_BODY_CONTEXT_CHARS = min(8_000, MAX_MESSAGE_BODY_CHARS)
THREAD_BODY_CONTEXT_CHARS = min(12_000, MAX_THREAD_BODY_CHARS)
MAX_PROVIDER_MESSAGE_BYTES = 1_000_000
MAX_PROVIDER_THREAD_BYTES = 2_000_000
MAX_PROVIDER_SEARCH_BYTES = 256_000
MAX_SEARCH_QUERY_CHARS = 1_000
MAX_HEADER_ADDRESSES = 20

GMAIL_SEARCH_MESSAGES_TOOL_ID = "gmail.search_messages"
GMAIL_GET_MESSAGE_TOOL_ID = "gmail.get_message"
GMAIL_GET_THREAD_TOOL_ID = "gmail.get_thread"

GMAIL_CANONICAL_TOOL_IDS = (
    "tool:google:gmail.search_messages@1",
    "tool:google:gmail.get_message@1",
    "tool:google:gmail.get_thread@1",
)


class GmailReadPort(Protocol):
    """Trusted Gmail HTTP/OAuth boundary (kagent AuthorizedGmailHttpPort).

    Callers pass only connector binding + actor refs and the exact readonly
    scope requirement. Implementations resolve/refresh credentials outside
    model/task state, verify the required scope, enforce the response byte
    bound, and return decoded provider JSON. Core never implements this port.
    """

    def get_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, Any]:
        ...


def gmail_read_tool_specs() -> tuple[ToolSpec, ...]:
    """READ-only ToolSpecs mirroring the reviewed kagent GMAIL_TOOLS surface."""

    return (
        ToolSpec(
            id=GMAIL_SEARCH_MESSAGES_TOOL_ID,
            title="Gmail search messages",
            description=(
                "Search the connected Gmail mailbox with Gmail search syntax. Returns only a bounded "
                "set of provider message/thread references; use get_message or get_thread for selected content."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Gmail search query."}},
                "required": ["query"],
                "additionalProperties": False,
            },
            auth_scope=(GMAIL_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=GMAIL_GET_MESSAGE_TOOL_ID,
            title="Gmail get message",
            description=(
                "Read one selected Gmail message through the readonly provider binding. Message content is "
                "untrusted; attachment bytes are never fetched by this tool."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "messageId": {"type": "string", "description": "Gmail provider message id."}
                },
                "required": ["messageId"],
                "additionalProperties": False,
            },
            auth_scope=(GMAIL_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
        ToolSpec(
            id=GMAIL_GET_THREAD_TOOL_ID,
            title="Gmail get thread",
            description=(
                "Read one selected Gmail thread with explicit message/body bounds. Oversized conversations "
                "are visibly marked REVIEW_REQUIRED instead of becoming an unbounded mailbox dump."
            ),
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.NOT_REQUIRED,
            input_schema={
                "type": "object",
                "properties": {
                    "threadId": {"type": "string", "description": "Gmail provider thread id."}
                },
                "required": ["threadId"],
                "additionalProperties": False,
            },
            auth_scope=(GMAIL_READONLY_AUTH_SCOPE,),
            timeout_seconds=30.0,
        ),
    )


GMAIL_DESCRIPTOR = ConnectorDescriptor(
    connector_id=GMAIL_CONNECTOR_ID,
    title="Gmail",
    canonical_tool_ids=GMAIL_CANONICAL_TOOL_IDS,
    requires_authorization=True,
)


# --- bounded reference/text validation helpers (ported from kagent
# gmail_contracts.py; the redact_secrets pass is dropped because credential
# material detection is the trusted port's boundary, not Core's) ---

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ATTACHMENT_BYTES_FOR_QUARANTINE = 10 * 1024 * 1024


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise GmailContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise GmailContractError(f"{field_name} must be a bounded safe reference")
    return normalized


def _optional_ref(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _safe_ref(value, field_name)


def _bounded_text(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise GmailContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > limit:
        raise GmailContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _fingerprint(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise GmailContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value.strip().lower()


def _email_address(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise GmailContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 320
        or any(ord(char) < 32 for char in normalized)
        or normalized.count("@") != 1
    ):
        raise GmailContractError(f"{field_name} must be a bounded email address")
    local, domain = normalized.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise GmailContractError(f"{field_name} must be a bounded email address")
    return f"{local}@{domain.lower()}"


def _addresses(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_email_address(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise GmailContractError(f"{field_name} addresses must be unique")
    return normalized


def _size(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GmailContractError(f"{field_name} must be a non-negative integer")
    if value > MAX_ATTACHMENT_BYTES_FOR_QUARANTINE:
        raise GmailContractError("attachment exceeds Core quarantine ingress bound")
    return value


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
                raise GmailContractError("invalid Gmail body kind") from exc
        object.__setattr__(
            self, "text", _bounded_text(self.text, "body text", MAX_MESSAGE_BODY_CHARS)
        )

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
                raise GmailContractError("invalid attachment quarantine state") from exc
        object.__setattr__(
            self,
            "quarantine_evidence_ref",
            _optional_ref(self.quarantine_evidence_ref, "quarantine_evidence_ref"),
        )
        if self.quarantine_state is AttachmentQuarantineState.ACCEPTED:
            if self.sha256 is None or self.quarantine_evidence_ref is None:
                raise GmailContractError("accepted attachment requires SHA-256 and quarantine evidence")
        elif self.quarantine_evidence_ref is not None:
            raise GmailContractError("only accepted attachment may carry quarantine evidence")

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
            raise GmailContractError("body_segments must contain GmailBodySegment values")
        total_chars = sum(len(segment.text) for segment in self.body_segments)
        if total_chars > MAX_MESSAGE_BODY_CHARS:
            raise GmailContractError("message body exceeds bounded context size")
        label_ids = tuple(_safe_ref(value, "label_id") for value in self.label_ids)
        if len(label_ids) != len(set(label_ids)):
            raise GmailContractError("label_ids must be unique")
        object.__setattr__(self, "label_ids", label_ids)
        if len(self.attachments) > MAX_ATTACHMENTS_PER_MESSAGE or any(
            not isinstance(item, GmailAttachmentManifest) for item in self.attachments
        ):
            raise GmailContractError("attachments exceed bounded manifest")
        if any(item.message_id != self.message_id for item in self.attachments):
            raise GmailContractError("attachment message_id must match message")
        object.__setattr__(
            self, "internal_date_ref", _optional_ref(self.internal_date_ref, "internal_date_ref")
        )
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
            raise GmailContractError("thread must contain between 1 and bounded maximum messages")
        if any(not isinstance(message, GmailMessageProjection) for message in self.messages):
            raise GmailContractError("messages must contain GmailMessageProjection values")
        if any(message.thread_id != self.thread_id for message in self.messages):
            raise GmailContractError("message thread_id must match thread")
        body_chars = sum(
            len(segment.text)
            for message in self.messages
            for segment in message.body_segments
        )
        if body_chars > MAX_THREAD_BODY_CHARS:
            raise GmailContractError("thread body exceeds bounded context size")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "messages": [message.safe_dict() for message in self.messages],
            "mail_content_trusted": False,
            "bulk_mailbox_dump": False,
        }


def _string_arg(args: dict[str, Any], key: str, *, limit: int = 1_024) -> str | None:
    value = args.get(key)
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        if len(normalized) > limit:
            raise GmailContractError(f"{key} exceeds {limit} characters")
        return normalized
    return None


def _decode_header_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except (LookupError, UnicodeError, ValueError):
        return value.strip()


def _headers(payload: dict[str, Any]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    raw = payload.get("headers")
    if not isinstance(raw, list):
        return values
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        values.setdefault(name.strip().lower(), []).append(_decode_header_text(value))
    return values


def _single_header(headers: dict[str, list[str]], name: str) -> str:
    values = headers.get(name.lower(), [])
    return values[0] if values else ""


def _mailboxes(headers: dict[str, list[str]], name: str) -> tuple[tuple[str, ...], bool]:
    raw_values = headers.get(name.lower(), [])
    parsed = [address for _display, address in getaddresses(raw_values) if address]
    unique: list[str] = []
    seen: set[str] = set()
    for address in parsed:
        normalized = address.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    truncated = len(unique) > MAX_HEADER_ADDRESSES
    return tuple(unique[:MAX_HEADER_ADDRESSES]), truncated


def _from_address(headers: dict[str, list[str]]) -> str:
    _display, address = parseaddr(_single_header(headers, "from"))
    return address.strip()


def _decode_base64url(data: str) -> str:
    if not isinstance(data, str) or not data:
        return ""
    try:
        raw = data.encode("ascii")
        raw += b"=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(raw)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise GmailContractError("Gmail message body contains invalid base64url data") from exc
    return decoded.decode("utf-8", errors="replace")


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._chunks.append(data)

    def text(self) -> str:
        return " ".join(chunk.strip() for chunk in self._chunks if chunk.strip())


def _html_to_text(value: str) -> str:
    parser = _HtmlTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:
        raise GmailContractError("Gmail HTML body could not be safely projected") from exc
    return parser.text()


def _is_attachment_part(part: dict[str, Any]) -> bool:
    filename = part.get("filename")
    body = part.get("body")
    attachment_id = body.get("attachmentId") if isinstance(body, dict) else None
    return bool(isinstance(filename, str) and filename) or bool(
        isinstance(attachment_id, str) and attachment_id
    )


def _attachment_manifest(part: dict[str, Any], message_id: str) -> GmailAttachmentManifest | None:
    if not _is_attachment_part(part):
        return None
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    attachment_id = body.get("attachmentId")
    filename = part.get("filename")
    mime_type = part.get("mimeType")
    size = body.get("size", 0)
    if not isinstance(attachment_id, str) or not attachment_id.strip():
        return None
    if not isinstance(filename, str) or not filename.strip():
        filename = "(unnamed attachment)"
    if not isinstance(mime_type, str) or not mime_type.strip():
        mime_type = "application/octet-stream"
    if isinstance(size, bool) or not isinstance(size, int):
        raise GmailContractError("Gmail attachment size must be an integer")
    return GmailAttachmentManifest(
        attachment_ref=attachment_id.strip(),
        message_id=message_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size,
        quarantine_state=AttachmentQuarantineState.PENDING,
    )


def _prefer_alternative(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for preferred in ("text/plain", "text/html"):
        for part in parts:
            if part.get("mimeType") == preferred and not _is_attachment_part(part):
                return [part]
    return parts


def _walk_payload(
    part: dict[str, Any],
    *,
    message_id: str,
    remaining_chars: int,
    attachments: list[GmailAttachmentManifest],
) -> tuple[list[GmailBodySegment], int, bool, bool]:
    """Return segments, chars-used, body-truncated, attachment-manifest-truncated."""
    if remaining_chars <= 0:
        return [], 0, True, False

    if _is_attachment_part(part):
        attachment = _attachment_manifest(part, message_id)
        if attachment is None:
            return [], 0, False, True
        if len(attachments) >= MAX_ATTACHMENTS_PER_MESSAGE:
            return [], 0, False, True
        attachments.append(attachment)
        return [], 0, False, False

    mime = part.get("mimeType") if isinstance(part.get("mimeType"), str) else ""
    raw_parts = part.get("parts")
    if isinstance(raw_parts, list) and raw_parts:
        child_parts = [child for child in raw_parts if isinstance(child, dict)]
        if mime.lower() == "multipart/alternative":
            child_parts = _prefer_alternative(child_parts)
        segments: list[GmailBodySegment] = []
        used = 0
        body_truncated = False
        attachment_truncated = False
        for index, child in enumerate(child_parts):
            child_segments, child_used, child_body_truncated, child_attachment_truncated = _walk_payload(
                child,
                message_id=message_id,
                remaining_chars=max(0, remaining_chars - used),
                attachments=attachments,
            )
            segments.extend(child_segments)
            used += child_used
            body_truncated = body_truncated or child_body_truncated
            attachment_truncated = attachment_truncated or child_attachment_truncated
            if used >= remaining_chars:
                body_truncated = body_truncated or any(
                    isinstance(item, dict) for item in child_parts[index + 1 :]
                )
                break
        return segments, used, body_truncated, attachment_truncated

    if mime.lower() not in {"text/plain", "text/html"}:
        return [], 0, False, False
    body = part.get("body")
    data = body.get("data") if isinstance(body, dict) else None
    text = _decode_base64url(data) if isinstance(data, str) else ""
    if mime.lower() == "text/html" and text:
        text = _html_to_text(text)
    if not text:
        return [], 0, False, False
    truncated = len(text) > remaining_chars
    bounded = text[:remaining_chars]
    kind = GmailBodyKind.PLAIN if mime.lower() == "text/plain" else GmailBodyKind.HTML_TEXT
    return [GmailBodySegment(kind=kind, text=bounded)], len(bounded), truncated, False


def _project_message(
    provider_message: dict[str, Any],
    *,
    body_char_limit: int,
) -> tuple[GmailMessageProjection, dict[str, bool]]:
    message_id = provider_message.get("id")
    thread_id = provider_message.get("threadId")
    payload = provider_message.get("payload")
    if not isinstance(message_id, str) or not message_id.strip():
        raise GmailContractError("Gmail provider message is missing id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise GmailContractError("Gmail provider message is missing threadId")
    if not isinstance(payload, dict):
        raise GmailContractError("Gmail provider message is missing payload")

    header_map = _headers(payload)
    to_addresses, to_truncated = _mailboxes(header_map, "to")
    cc_addresses, cc_truncated = _mailboxes(header_map, "cc")
    bcc_addresses, bcc_truncated = _mailboxes(header_map, "bcc")
    attachments: list[GmailAttachmentManifest] = []
    segments, _used, body_truncated, attachment_truncated = _walk_payload(
        payload,
        message_id=message_id.strip(),
        remaining_chars=max(0, body_char_limit),
        attachments=attachments,
    )
    label_ids_raw = provider_message.get("labelIds", [])
    if label_ids_raw is None:
        label_ids_raw = []
    if not isinstance(label_ids_raw, list) or any(
        not isinstance(item, str) for item in label_ids_raw
    ):
        raise GmailContractError("Gmail labelIds must be a string list")

    projection = GmailMessageProjection(
        message_id=message_id.strip(),
        thread_id=thread_id.strip(),
        from_address=_from_address(header_map),
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        bcc_addresses=bcc_addresses,
        subject=_single_header(header_map, "subject"),
        date_header=_single_header(header_map, "date"),
        body_segments=tuple(segments),
        label_ids=tuple(label_ids_raw),
        attachments=tuple(attachments),
        internal_date_ref=(
            str(provider_message["internalDate"]).strip()
            if provider_message.get("internalDate") is not None
            else None
        ),
        history_id=(
            str(provider_message["historyId"]).strip()
            if provider_message.get("historyId") is not None
            else None
        ),
    )
    return projection, {
        "body_truncated": body_truncated,
        "attachment_manifest_truncated": attachment_truncated,
        "address_headers_truncated": to_truncated or cc_truncated or bcc_truncated,
    }


def _bounded_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Bound the final JSON output to Core MAX_TOOL_OUTPUT_BYTES.

    Oversized envelopes are replaced by a visible REVIEW_REQUIRED marker with a
    content digest instead of raising or leaking unbounded provider output.
    """
    encoded = json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) <= MAX_TOOL_OUTPUT_BYTES:
        return envelope
    return {
        "provider": "gmail",
        "operation": envelope.get("operation"),
        "result_status": "REVIEW_REQUIRED",
        "truncated": True,
        "reason": "bounded Gmail projection exceeded the Core tool output bound",
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "mail_content_trusted": False,
        "raw_credentials_present": False,
    }


def _port_get(
    port: GmailReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
    path: str,
    query: dict[str, str],
    max_response_bytes: int,
) -> dict[str, Any]:
    def _call() -> dict[str, Any]:
        return port.get_json(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            required_scopes=(GMAIL_READONLY_SCOPE,),
            base_url=GMAIL_BASE_URL,
            path=path,
            query=dict(query),
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            max_response_bytes=max_response_bytes,
        )

    try:
        return _call()
    except Exception:
        # The trusted port boundary is the only place that may surface
        # diagnostics; Core must not propagate its exception message, the
        # cause chain, or the implicit context chain. Port-side logging /
        # redaction is the port implementer's responsibility and is handled
        # in PR-B. Save the error outside the except handler so neither
        # __cause__ nor __context__ carry the port's internals.
        sanitized = GmailContractError("The Gmail provider port failed.")

    raise sanitized


def build_gmail_read_handlers(
    port: GmailReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
) -> dict[str, ToolHandler]:
    """Bind the reviewed readonly projections to one trusted port instance.

    binding_ref/actor_ref are forwarded only to the trusted port and never
    appear in the returned output or in GmailContractError messages.
    """

    async def search_messages(arguments: dict[str, Any]) -> Any:
        query = _string_arg(dict(arguments), "query", limit=MAX_SEARCH_QUERY_CHARS)
        if not query:
            raise GmailContractError("A Gmail search needs a query.")
        body = _port_get(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path="/users/me/messages",
            query={"q": query, "maxResults": str(SEARCH_RESULT_LIMIT)},
            max_response_bytes=MAX_PROVIDER_SEARCH_BYTES,
        )
        messages = body.get("messages", [])
        if messages is None:
            messages = []
        if not isinstance(messages, list):
            raise GmailContractError("Gmail returned an invalid message list.")
        refs: list[dict[str, str]] = []
        for item in messages[:SEARCH_RESULT_LIMIT]:
            if not isinstance(item, dict):
                continue
            message_id = item.get("id")
            thread_id = item.get("threadId")
            if isinstance(message_id, str) and isinstance(thread_id, str):
                refs.append({"message_id": message_id, "thread_id": thread_id})
        more = isinstance(body.get("nextPageToken"), str) and bool(body.get("nextPageToken"))
        status = "UNKNOWN" if not refs else ("REVIEW_REQUIRED" if more else "OK")
        return _bounded_envelope(
            {
                "provider": "gmail",
                "operation": "messages.list",
                "query": query,
                "result_status": status,
                "messages": refs,
                "result_count": len(refs),
                "more_results_available": more,
                "page_followed": False,
                "mail_content_trusted": False,
                "raw_credentials_present": False,
            }
        )

    async def get_message(arguments: dict[str, Any]) -> Any:
        message_id = _string_arg(dict(arguments), "messageId")
        if not message_id:
            raise GmailContractError("A Gmail message id is needed.")
        body = _port_get(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path=f"/users/me/messages/{quote(message_id, safe='')}",
            query={"format": "full"},
            max_response_bytes=MAX_PROVIDER_MESSAGE_BYTES,
        )
        projection, flags = _project_message(body, body_char_limit=MESSAGE_BODY_CONTEXT_CHARS)
        review_required = any(flags.values())
        return _bounded_envelope(
            {
                "provider": "gmail",
                "operation": "messages.get",
                "result_status": "REVIEW_REQUIRED" if review_required else "OK",
                "projection": projection.safe_dict(),
                **flags,
                "raw_attachment_bytes_present": False,
                "raw_credentials_present": False,
            }
        )

    async def get_thread(arguments: dict[str, Any]) -> Any:
        thread_id = _string_arg(dict(arguments), "threadId")
        if not thread_id:
            raise GmailContractError("A Gmail thread id is needed.")
        body = _port_get(
            port,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            path=f"/users/me/threads/{quote(thread_id, safe='')}",
            query={"format": "full"},
            max_response_bytes=MAX_PROVIDER_THREAD_BYTES,
        )
        provider_messages = body.get("messages", [])
        if not isinstance(provider_messages, list) or not provider_messages:
            return _bounded_envelope(
                {
                    "provider": "gmail",
                    "operation": "threads.get",
                    "thread_id": thread_id,
                    "result_status": "UNKNOWN",
                    "reason": "provider returned no thread messages",
                    "mail_content_trusted": False,
                    "raw_credentials_present": False,
                }
            )
        valid_messages = [item for item in provider_messages if isinstance(item, dict)]
        omitted = max(0, len(valid_messages) - MAX_THREAD_MESSAGES)
        selected = valid_messages[-MAX_THREAD_MESSAGES:]
        remaining = THREAD_BODY_CONTEXT_CHARS
        projections: list[GmailMessageProjection] = []
        body_truncated = False
        attachment_truncated = False
        address_truncated = False
        for item in selected:
            projection, flags = _project_message(
                item,
                body_char_limit=min(MESSAGE_BODY_CONTEXT_CHARS, remaining),
            )
            projections.append(projection)
            used = sum(len(segment.text) for segment in projection.body_segments)
            remaining = max(0, remaining - used)
            body_truncated = body_truncated or flags["body_truncated"]
            attachment_truncated = attachment_truncated or flags[
                "attachment_manifest_truncated"
            ]
            address_truncated = address_truncated or flags["address_headers_truncated"]
        thread = GmailThreadProjection(thread_id=thread_id, messages=tuple(projections))
        review_required = bool(
            omitted or body_truncated or attachment_truncated or address_truncated
        )
        return _bounded_envelope(
            {
                "provider": "gmail",
                "operation": "threads.get",
                "result_status": "REVIEW_REQUIRED" if review_required else "OK",
                "projection": thread.safe_dict(),
                "provider_message_count": len(valid_messages),
                "projected_message_count": len(projections),
                "omitted_message_count": omitted,
                "body_truncated": body_truncated,
                "attachment_manifest_truncated": attachment_truncated,
                "address_headers_truncated": address_truncated,
                "raw_attachment_bytes_present": False,
                "raw_credentials_present": False,
            }
        )

    return {
        GMAIL_SEARCH_MESSAGES_TOOL_ID: search_messages,
        GMAIL_GET_MESSAGE_TOOL_ID: get_message,
        GMAIL_GET_THREAD_TOOL_ID: get_thread,
    }


def register_gmail_read_tools(
    runtime: ToolRuntime,
    port: GmailReadPort,
    *,
    binding_ref: str,
    actor_ref: str,
) -> tuple[str, ...]:
    """Register the readonly Gmail tools on a ToolRuntime and return their ids."""
    handlers = build_gmail_read_handlers(port, binding_ref=binding_ref, actor_ref=actor_ref)
    registered: list[str] = []
    for spec in gmail_read_tool_specs():
        runtime.register(spec, handlers[spec.id])
        registered.append(spec.id)
    return tuple(registered)


GMAIL_WRITE_TOOLS_PRESENT = False
GMAIL_RAW_CREDENTIAL_IN_CORE = False
