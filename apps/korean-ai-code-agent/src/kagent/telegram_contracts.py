from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt, ReplayDisposition
from .contracts import ContractError
from .security import redact_secrets

MAX_TELEGRAM_CHATS = 128
MAX_TELEGRAM_SENDERS_PER_CHAT = 128
MAX_TELEGRAM_MESSAGE_CHARS = 20_000
MAX_TELEGRAM_FILE_BYTES = 10 * 1024 * 1024
MAX_TELEGRAM_FILES_PER_UPDATE = 8
MAX_TELEGRAM_FILES_PER_SEND = 1
TELEGRAM_PROVIDER_CLOUD_DOWNLOAD_LIMIT_BYTES = 20 * 1024 * 1024
TELEGRAM_PROVIDER_CLOUD_SEND_DOCUMENT_LIMIT_BYTES = 50 * 1024 * 1024

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CALLBACK_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_UPDATE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


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
    return None if value is None else _safe_ref(value, field_name)


def _bounded_text(value: str, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    normalized = redact_secrets(value.strip())
    if len(normalized) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    return normalized


def _fingerprint(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value.strip().lower()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _bounded_nonnegative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field_name} must be a non-negative integer")
    return value


def _normalize_update_type(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("Telegram update type must be text")
    normalized = value.strip().lower()
    if not _UPDATE_TYPE_RE.fullmatch(normalized):
        raise ContractError("Telegram update type must be a bounded Bot API field name")
    return normalized


def _challenge_ref(value: str) -> str:
    if not isinstance(value, str) or not _CALLBACK_CHALLENGE_RE.fullmatch(value):
        raise ContractError("Telegram callback challenge must fit the 1..64-byte opaque callback_data shape")
    # ASCII-only regex makes character count equal byte count.
    return value


class TelegramChatKind(str, Enum):
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


@dataclass(frozen=True, slots=True)
class TelegramPairedChat:
    chat_ref: str
    telegram_chat_id_ref: str
    kind: TelegramChatKind
    allowed_sender_refs: tuple[str, ...]
    privileged_intake_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "chat_ref", _safe_ref(self.chat_ref, "chat_ref"))
        object.__setattr__(
            self,
            "telegram_chat_id_ref",
            _safe_ref(self.telegram_chat_id_ref, "telegram_chat_id_ref"),
        )
        if not isinstance(self.kind, TelegramChatKind):
            try:
                object.__setattr__(self, "kind", TelegramChatKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Telegram chat kind") from exc
        if len(self.allowed_sender_refs) > MAX_TELEGRAM_SENDERS_PER_CHAT:
            raise ContractError("Telegram allowed sender list exceeds bound")
        senders = tuple(_safe_ref(value, "sender_ref") for value in self.allowed_sender_refs)
        if len(senders) != len(set(senders)):
            raise ContractError("Telegram sender refs must be unique")
        if self.kind is TelegramChatKind.PRIVATE and len(senders) != 1:
            raise ContractError("paired private Telegram chat requires exactly one sender")
        if self.kind is not TelegramChatKind.PRIVATE and self.privileged_intake_allowed and not senders:
            raise ContractError("privileged group/channel intake requires explicit sender allowlist")
        if not isinstance(self.privileged_intake_allowed, bool):
            raise ContractError("privileged_intake_allowed must be boolean")
        object.__setattr__(self, "allowed_sender_refs", senders)

    def allows_sender(self, sender_ref: str, *, privileged: bool) -> bool:
        sender = _safe_ref(sender_ref, "sender_ref")
        if sender not in self.allowed_sender_refs:
            return False
        if privileged and not self.privileged_intake_allowed:
            return False
        return True

    def safe_dict(self) -> dict[str, Any]:
        return {
            "chat_ref": self.chat_ref,
            "telegram_chat_id_ref": self.telegram_chat_id_ref,
            "kind": self.kind.value,
            "allowed_sender_refs": list(self.allowed_sender_refs),
            "privileged_intake_allowed": self.privileged_intake_allowed,
            "telegram_identity_alone_is_padiem_authority": False,
        }


@dataclass(frozen=True, slots=True)
class TelegramBotScope:
    binding_ref: str
    workspace_ref: str
    bot_ref: str
    telegram_bot_user_ref: str
    paired_chats: tuple[TelegramPairedChat, ...]

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "workspace_ref", "bot_ref", "telegram_bot_user_ref"):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        if not self.paired_chats or len(self.paired_chats) > MAX_TELEGRAM_CHATS:
            raise ContractError("Telegram bot scope requires 1..128 paired chats")
        if any(not isinstance(item, TelegramPairedChat) for item in self.paired_chats):
            raise ContractError("paired_chats must contain TelegramPairedChat values")
        refs = tuple(item.chat_ref for item in self.paired_chats)
        ids = tuple(item.telegram_chat_id_ref for item in self.paired_chats)
        if len(refs) != len(set(refs)) or len(ids) != len(set(ids)):
            raise ContractError("Telegram paired chat identities must be unique")

    def chat(self, chat_ref: str) -> TelegramPairedChat | None:
        target = _safe_ref(chat_ref, "chat_ref")
        return next((item for item in self.paired_chats if item.chat_ref == target), None)

    def authorizes(
        self,
        *,
        binding_ref: str,
        workspace_ref: str,
        bot_ref: str,
        chat_ref: str,
        sender_ref: str,
        privileged: bool = False,
    ) -> bool:
        if (
            _safe_ref(binding_ref, "binding_ref") != self.binding_ref
            or _safe_ref(workspace_ref, "workspace_ref") != self.workspace_ref
            or _safe_ref(bot_ref, "bot_ref") != self.bot_ref
        ):
            return False
        paired = self.chat(chat_ref)
        return paired is not None and paired.allows_sender(sender_ref, privileged=privileged)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-telegram-bot-scope.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "bot_ref": self.bot_ref,
            "telegram_bot_user_ref": self.telegram_bot_user_ref,
            "paired_chats": [item.safe_dict() for item in self.paired_chats],
            "arbitrary_private_chat_read": False,
            "contact_harvesting": False,
        }


class TelegramIngressMode(str, Enum):
    WEBHOOK = "webhook"
    GET_UPDATES = "get_updates"


@dataclass(frozen=True, slots=True)
class TelegramIngressConfig:
    mode: TelegramIngressMode
    allowed_update_types: tuple[str, ...]
    webhook_secret_binding_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, TelegramIngressMode):
            try:
                object.__setattr__(self, "mode", TelegramIngressMode(self.mode))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Telegram ingress mode") from exc
        if not self.allowed_update_types or len(self.allowed_update_types) > 32:
            raise ContractError("Telegram ingress requires 1..32 explicit allowed update types")
        update_types = tuple(_normalize_update_type(value) for value in self.allowed_update_types)
        if len(update_types) != len(set(update_types)):
            raise ContractError("Telegram allowed update types must be unique")
        object.__setattr__(self, "allowed_update_types", update_types)
        object.__setattr__(
            self,
            "webhook_secret_binding_ref",
            _optional_ref(self.webhook_secret_binding_ref, "webhook_secret_binding_ref"),
        )
        if self.mode is TelegramIngressMode.WEBHOOK and self.webhook_secret_binding_ref is None:
            raise ContractError("Telegram webhook mode requires opaque secret binding ref")
        if self.mode is TelegramIngressMode.GET_UPDATES and self.webhook_secret_binding_ref is not None:
            raise ContractError("Telegram getUpdates mode cannot carry webhook secret binding")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "allowed_update_types": list(self.allowed_update_types),
            "webhook_secret_binding_ref": self.webhook_secret_binding_ref,
            "webhook_and_getupdates_simultaneous": False,
            "raw_webhook_secret_present": False,
        }


@dataclass(frozen=True, slots=True)
class TelegramWebhookProof:
    proof_ref: str
    secret_header_verified: bool
    verified_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "proof_ref", _safe_ref(self.proof_ref, "proof_ref"))
        if not isinstance(self.secret_header_verified, bool):
            raise ContractError("secret_header_verified must be boolean")
        object.__setattr__(self, "verified_at", _aware(self.verified_at, "verified_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "proof_ref": self.proof_ref,
            "secret_header_verified": self.secret_header_verified,
            "verified_at": self.verified_at.isoformat().replace("+00:00", "Z"),
            "proof_kind": "X-Telegram-Bot-Api-Secret-Token equality at trusted ingress",
            "hmac_signature": False,
            "raw_secret_present": False,
        }


class TelegramFileQuarantineState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class TelegramFileManifest:
    file_ref: str
    file_unique_ref: str
    filename: str
    mime_type: str
    size_bytes: int
    quarantine_state: TelegramFileQuarantineState = TelegramFileQuarantineState.PENDING
    sha256: str | None = None
    quarantine_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_ref", _safe_ref(self.file_ref, "file_ref"))
        object.__setattr__(self, "file_unique_ref", _safe_ref(self.file_unique_ref, "file_unique_ref"))
        object.__setattr__(self, "filename", _bounded_text(self.filename, "filename", 512))
        object.__setattr__(self, "mime_type", _bounded_text(self.mime_type, "mime_type", 255).lower())
        _bounded_nonnegative_int(self.size_bytes, "size_bytes")
        if self.size_bytes > MAX_TELEGRAM_FILE_BYTES:
            raise ContractError("Telegram file exceeds Padiem quarantine bound")
        if not isinstance(self.quarantine_state, TelegramFileQuarantineState):
            try:
                object.__setattr__(
                    self,
                    "quarantine_state",
                    TelegramFileQuarantineState(self.quarantine_state),
                )
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Telegram file quarantine state") from exc
        if self.sha256 is not None:
            object.__setattr__(self, "sha256", _fingerprint(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "quarantine_evidence_ref",
            _optional_ref(self.quarantine_evidence_ref, "quarantine_evidence_ref"),
        )
        if self.quarantine_state is TelegramFileQuarantineState.ACCEPTED:
            if self.sha256 is None or self.quarantine_evidence_ref is None:
                raise ContractError("accepted Telegram file requires SHA-256 and quarantine evidence")
        elif self.quarantine_evidence_ref is not None:
            raise ContractError("non-accepted Telegram file cannot carry accepted quarantine evidence")

    def model_usable(self) -> bool:
        return (
            self.quarantine_state is TelegramFileQuarantineState.ACCEPTED
            and self.sha256 is not None
            and self.quarantine_evidence_ref is not None
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "file_ref": self.file_ref,
            "file_unique_ref": self.file_unique_ref,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "quarantine_state": self.quarantine_state.value,
            "sha256": self.sha256,
            "quarantine_evidence_ref": self.quarantine_evidence_ref,
            "model_usable": self.model_usable(),
            "raw_bytes_present": False,
        }


@dataclass(frozen=True, slots=True)
class TelegramInboundUpdate:
    update_id: int
    binding_ref: str
    workspace_ref: str
    bot_ref: str
    chat_ref: str
    sender_ref: str
    update_type: str
    text: str
    replay: ReplayDisposition
    webhook_proof: TelegramWebhookProof | None = None
    message_ref: str | None = None
    callback_query_ref: str | None = None
    callback_data: str | None = None
    files: tuple[TelegramFileManifest, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "update_id", _bounded_nonnegative_int(self.update_id, "update_id"))
        for field_name in ("binding_ref", "workspace_ref", "bot_ref", "chat_ref", "sender_ref"):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "update_type", _normalize_update_type(self.update_type))
        object.__setattr__(
            self,
            "text",
            _bounded_text(self.text, "Telegram inbound text", MAX_TELEGRAM_MESSAGE_CHARS),
        )
        if not isinstance(self.replay, ReplayDisposition):
            try:
                object.__setattr__(self, "replay", ReplayDisposition(self.replay))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Telegram replay disposition") from exc
        if self.webhook_proof is not None and not isinstance(self.webhook_proof, TelegramWebhookProof):
            raise ContractError("webhook_proof must be TelegramWebhookProof")
        object.__setattr__(self, "message_ref", _optional_ref(self.message_ref, "message_ref"))
        object.__setattr__(
            self,
            "callback_query_ref",
            _optional_ref(self.callback_query_ref, "callback_query_ref"),
        )
        if self.callback_data is not None:
            if not isinstance(self.callback_data, str) or len(self.callback_data.encode("utf-8")) > 64:
                raise ContractError("Telegram callback_data exceeds 64 bytes")
            object.__setattr__(self, "callback_data", redact_secrets(self.callback_data))
        if self.update_type == "callback_query":
            if self.callback_query_ref is None or self.callback_data is None:
                raise ContractError("callback_query update requires callback query ref and data")
        if len(self.files) > MAX_TELEGRAM_FILES_PER_UPDATE:
            raise ContractError("Telegram inbound file count exceeds bound")
        if any(not isinstance(item, TelegramFileManifest) for item in self.files):
            raise ContractError("Telegram inbound files must be TelegramFileManifest values")

    @property
    def event_ref(self) -> str:
        return f"telegram-update:{self.update_id}"

    def accepted_by(
        self,
        *,
        scope: TelegramBotScope,
        ingress: TelegramIngressConfig,
        privileged: bool = False,
    ) -> bool:
        if not isinstance(scope, TelegramBotScope) or not isinstance(ingress, TelegramIngressConfig):
            raise ContractError("invalid Telegram inbound acceptance contract")
        if self.replay is not ReplayDisposition.NEW:
            return False
        if self.update_type not in ingress.allowed_update_types:
            return False
        if ingress.mode is TelegramIngressMode.WEBHOOK:
            if self.webhook_proof is None or not self.webhook_proof.secret_header_verified:
                return False
        elif self.webhook_proof is not None:
            return False
        return scope.authorizes(
            binding_ref=self.binding_ref,
            workspace_ref=self.workspace_ref,
            bot_ref=self.bot_ref,
            chat_ref=self.chat_ref,
            sender_ref=self.sender_ref,
            privileged=privileged,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-telegram-inbound-update.v1",
            "update_id": self.update_id,
            "event_ref": self.event_ref,
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "bot_ref": self.bot_ref,
            "chat_ref": self.chat_ref,
            "sender_ref": self.sender_ref,
            "update_type": self.update_type,
            "text": self.text,
            "replay": self.replay.value,
            "webhook_proof": self.webhook_proof.safe_dict() if self.webhook_proof else None,
            "message_ref": self.message_ref,
            "callback_query_ref": self.callback_query_ref,
            "callback_data": self.callback_data,
            "files": [item.safe_dict() for item in self.files],
            "inbound_content_trusted": False,
            "telegram_identity_alone_is_padiem_authority": False,
        }


class TelegramApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class TelegramCallbackChallenge:
    challenge_ref: str
    binding_ref: str
    workspace_ref: str
    bot_ref: str
    chat_ref: str
    sender_ref: str
    approval_ref: str
    evidence_ref: str
    decision: TelegramApprovalDecision
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "challenge_ref", _challenge_ref(self.challenge_ref))
        for field_name in (
            "binding_ref",
            "workspace_ref",
            "bot_ref",
            "chat_ref",
            "sender_ref",
            "approval_ref",
            "evidence_ref",
        ):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        if not isinstance(self.decision, TelegramApprovalDecision):
            try:
                object.__setattr__(self, "decision", TelegramApprovalDecision(self.decision))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Telegram approval decision") from exc
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued:
            raise ContractError("Telegram callback challenge expiry must follow issuance")
        if (expires - issued).total_seconds() > 3600:
            raise ContractError("Telegram callback challenge lifetime cannot exceed one hour")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        if self.consumed_at is not None:
            consumed = _aware(self.consumed_at, "consumed_at")
            if consumed < issued:
                raise ContractError("Telegram callback challenge cannot be consumed before issuance")
            object.__setattr__(self, "consumed_at", consumed)

    def usable_at(self, now: datetime) -> bool:
        current = _aware(now, "now")
        return self.consumed_at is None and self.issued_at <= current < self.expires_at

    def matches_callback(
        self,
        *,
        callback_data: str,
        binding_ref: str,
        workspace_ref: str,
        bot_ref: str,
        chat_ref: str,
        sender_ref: str,
        now: datetime,
    ) -> bool:
        try:
            data = _challenge_ref(callback_data)
        except ContractError:
            return False
        return (
            self.usable_at(now)
            and data == self.challenge_ref
            and _safe_ref(binding_ref, "binding_ref") == self.binding_ref
            and _safe_ref(workspace_ref, "workspace_ref") == self.workspace_ref
            and _safe_ref(bot_ref, "bot_ref") == self.bot_ref
            and _safe_ref(chat_ref, "chat_ref") == self.chat_ref
            and _safe_ref(sender_ref, "sender_ref") == self.sender_ref
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "challenge_ref": self.challenge_ref,
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "bot_ref": self.bot_ref,
            "chat_ref": self.chat_ref,
            "sender_ref": self.sender_ref,
            "approval_ref": self.approval_ref,
            "evidence_ref": self.evidence_ref,
            "decision": self.decision.value,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "consumed_at": self.consumed_at.isoformat().replace("+00:00", "Z") if self.consumed_at else None,
            "client_data_is_approval_authority": False,
            "durable_atomic_consume_required": True,
        }


@dataclass(frozen=True, slots=True)
class TelegramApprovedDocument:
    file_ref: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    quarantine_evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_ref", _safe_ref(self.file_ref, "file_ref"))
        object.__setattr__(self, "filename", _bounded_text(self.filename, "filename", 512))
        object.__setattr__(self, "mime_type", _bounded_text(self.mime_type, "mime_type", 255).lower())
        _bounded_nonnegative_int(self.size_bytes, "size_bytes")
        if self.size_bytes > MAX_TELEGRAM_FILE_BYTES:
            raise ContractError("approved Telegram document exceeds Padiem bound")
        object.__setattr__(self, "sha256", _fingerprint(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "quarantine_evidence_ref",
            _safe_ref(self.quarantine_evidence_ref, "quarantine_evidence_ref"),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "file_ref": self.file_ref,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "quarantine_evidence_ref": self.quarantine_evidence_ref,
        }


class TelegramOutboundCapability(str, Enum):
    SEND_MESSAGE = "telegram.send_message"
    SEND_DOCUMENT = "telegram.send_document"
    EDIT_MESSAGE = "telegram.edit_message"
    ANSWER_CALLBACK = "telegram.answer_callback"


@dataclass(frozen=True, slots=True)
class TelegramOutboundMaterial:
    binding_ref: str
    workspace_ref: str
    bot_ref: str
    capability: TelegramOutboundCapability
    chat_ref: str
    text_sha256: str
    message_ref: str | None = None
    callback_query_ref: str | None = None
    callback_challenge_ref: str | None = None
    document: TelegramApprovedDocument | None = None

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "workspace_ref", "bot_ref", "chat_ref"):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        if not isinstance(self.capability, TelegramOutboundCapability):
            try:
                object.__setattr__(self, "capability", TelegramOutboundCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Telegram outbound capability") from exc
        object.__setattr__(self, "text_sha256", _fingerprint(self.text_sha256, "text_sha256"))
        object.__setattr__(self, "message_ref", _optional_ref(self.message_ref, "message_ref"))
        object.__setattr__(
            self,
            "callback_query_ref",
            _optional_ref(self.callback_query_ref, "callback_query_ref"),
        )
        if self.callback_challenge_ref is not None:
            object.__setattr__(self, "callback_challenge_ref", _challenge_ref(self.callback_challenge_ref))
        if self.document is not None and not isinstance(self.document, TelegramApprovedDocument):
            raise ContractError("document must be TelegramApprovedDocument")

        if self.capability is TelegramOutboundCapability.SEND_MESSAGE:
            if any((self.message_ref, self.callback_query_ref, self.callback_challenge_ref, self.document)):
                raise ContractError("send_message cannot carry edit/callback/document identity")
        elif self.capability is TelegramOutboundCapability.SEND_DOCUMENT:
            if self.document is None or any((self.message_ref, self.callback_query_ref, self.callback_challenge_ref)):
                raise ContractError("send_document requires one approved document only")
        elif self.capability is TelegramOutboundCapability.EDIT_MESSAGE:
            if self.message_ref is None or any((self.callback_query_ref, self.callback_challenge_ref, self.document)):
                raise ContractError("edit_message requires exact message identity")
        elif self.capability is TelegramOutboundCapability.ANSWER_CALLBACK:
            if self.callback_query_ref is None or self.callback_challenge_ref is None:
                raise ContractError("answer_callback requires exact callback query and challenge")
            if self.message_ref is not None or self.document is not None:
                raise ContractError("answer_callback cannot carry edit/document identity")

    @property
    def target_ref(self) -> str:
        prefix = f"telegram:{self.workspace_ref}:bot:{self.bot_ref}:chat:{self.chat_ref}"
        if self.capability is TelegramOutboundCapability.SEND_MESSAGE:
            return f"{prefix}:new-message"
        if self.capability is TelegramOutboundCapability.SEND_DOCUMENT:
            return f"{prefix}:new-document"
        if self.capability is TelegramOutboundCapability.EDIT_MESSAGE:
            return f"{prefix}:message:{self.message_ref}"
        return f"{prefix}:callback:{self.callback_query_ref}"

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "bot_ref": self.bot_ref,
            "capability": self.capability.value,
            "chat_ref": self.chat_ref,
            "text_sha256": self.text_sha256,
            "message_ref": self.message_ref,
            "callback_query_ref": self.callback_query_ref,
            "callback_challenge_ref": self.callback_challenge_ref,
            "document": self.document.canonical_dict() if self.document else None,
            "bulk_send": False,
        }

    @property
    def material_fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def version_ref(self) -> str:
        return f"telegram-material:{self.material_fingerprint}"


@dataclass(frozen=True, slots=True)
class TelegramOutboundApproval:
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


class TelegramOutboundPreflightDecision(str, Enum):
    ALLOW = "allow"
    OUT_OF_SCOPE = "out_of_scope"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    TARGET_MISMATCH = "target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    VERSION_BINDING_MISMATCH = "version_binding_mismatch"


def telegram_outbound_preflight(
    *,
    scope: TelegramBotScope,
    material: TelegramOutboundMaterial,
    approval: TelegramOutboundApproval,
    intent: ConnectorWriteIntent,
    sender_ref: str,
) -> TelegramOutboundPreflightDecision:
    if not all(
        [
            isinstance(scope, TelegramBotScope),
            isinstance(material, TelegramOutboundMaterial),
            isinstance(approval, TelegramOutboundApproval),
            isinstance(intent, ConnectorWriteIntent),
        ]
    ):
        raise ContractError("invalid Telegram outbound preflight contract")
    if not scope.authorizes(
        binding_ref=material.binding_ref,
        workspace_ref=material.workspace_ref,
        bot_ref=material.bot_ref,
        chat_ref=material.chat_ref,
        sender_ref=sender_ref,
        privileged=True,
    ):
        return TelegramOutboundPreflightDecision.OUT_OF_SCOPE
    if intent.connector_id != "telegram" or intent.tool_name != material.capability.value:
        return TelegramOutboundPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != material.binding_ref or intent.target_ref != material.target_ref:
        return TelegramOutboundPreflightDecision.TARGET_MISMATCH
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return TelegramOutboundPreflightDecision.APPROVAL_MISMATCH
    if approval.material_fingerprint != material.material_fingerprint:
        return TelegramOutboundPreflightDecision.MATERIAL_CHANGED
    if intent.payload_fingerprint != material.material_fingerprint:
        return TelegramOutboundPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != material.version_ref:
        return TelegramOutboundPreflightDecision.VERSION_BINDING_MISMATCH
    return TelegramOutboundPreflightDecision.ALLOW


@dataclass(frozen=True, slots=True)
class TelegramOutboundReceipt:
    connector_receipt: ConnectorWriteReceipt
    capability: TelegramOutboundCapability
    approved_target_ref: str
    result_message_ref: str | None = None
    callback_answered: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.connector_receipt, ConnectorWriteReceipt):
            raise ContractError("connector_receipt must be ConnectorWriteReceipt")
        if self.connector_receipt.connector_id != "telegram":
            raise ContractError("Telegram receipt requires telegram connector receipt")
        if not isinstance(self.capability, TelegramOutboundCapability):
            try:
                object.__setattr__(self, "capability", TelegramOutboundCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Telegram receipt capability") from exc
        object.__setattr__(
            self,
            "approved_target_ref",
            _safe_ref(self.approved_target_ref, "approved_target_ref"),
        )
        if self.connector_receipt.target_ref != self.approved_target_ref:
            raise ContractError("Telegram receipt target does not match approved target")
        object.__setattr__(
            self,
            "result_message_ref",
            _optional_ref(self.result_message_ref, "result_message_ref"),
        )
        if not isinstance(self.callback_answered, bool):
            raise ContractError("callback_answered must be boolean")
        if self.capability is TelegramOutboundCapability.ANSWER_CALLBACK:
            if not self.callback_answered or self.result_message_ref is not None:
                raise ContractError("answer_callback receipt requires successful callback answer only")
        else:
            if self.result_message_ref is None or self.callback_answered:
                raise ContractError("Telegram message/document/edit receipt requires returned Message identity")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_receipt": self.connector_receipt.safe_dict(),
            "capability": self.capability.value,
            "approved_target_ref": self.approved_target_ref,
            "result_message_ref": self.result_message_ref,
            "callback_answered": self.callback_answered,
            "trusted_provider_receipt": True,
            "model_text_counts_as_delivery": False,
        }


TELEGRAM_OFFICIAL_BOT_API_REQUIRED = True
TELEGRAM_PERSONAL_MTProto_SESSION_SUPPORTED = False
TELEGRAM_WEBHOOK_SECRET_HEADER_SUPPORTED = True
TELEGRAM_WEBHOOK_SECRET_IS_HMAC_SIGNATURE = False
TELEGRAM_WEBHOOK_AND_GETUPDATES_SIMULTANEOUS = False
TELEGRAM_UPDATE_ID_DEDUP_REQUIRED = True
TELEGRAM_CALLBACK_DATA_MAX_BYTES = 64
TELEGRAM_CALLBACK_DATA_IS_APPROVAL_AUTHORITY = False
TELEGRAM_CALLBACK_DURABLE_ATOMIC_CONSUME_REQUIRED = True
TELEGRAM_RAW_BOT_TOKEN_IN_B54 = False
TELEGRAM_RAW_WEBHOOK_SECRET_IN_B54 = False
TELEGRAM_AUTONOMOUS_SPAM_SUPPORTED = False
REAL_TELEGRAM_BOT_CONFIGURED = False
REAL_TELEGRAM_SEND_CONFIGURED = False
