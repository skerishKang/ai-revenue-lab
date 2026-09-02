from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .contracts import ContractError
from .ops_attachment_scan import TrustedAttachmentScanReceipt, require_clean_attachment_scans
from .ops_communications import AttachmentPolicy, InboundCommunication
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


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def inbound_fingerprint(message: InboundCommunication, *, provider_event_ref: str) -> str:
    if not isinstance(message, InboundCommunication):
        raise ContractError("message must be InboundCommunication")
    provider_ref = _ref(provider_event_ref, "provider_event_ref")
    metadata = message.safe_metadata()
    payload = {
        "provider_event_ref": provider_ref,
        "inbound_id": message.inbound_id,
        "workspace_id": message.workspace_id,
        "channel": message.channel.value,
        "sender_ref": message.sender_ref,
        "thread_ref": message.thread_ref,
        "received_at": message.received_at.isoformat(),
        "body_sha256": metadata["body_sha256"],
        "attachments": [
            {
                "attachment_id": item.attachment_id,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "mime_type": item.mime_type,
            }
            for item in message.attachments
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class InboundQuarantineState(str, Enum):
    QUARANTINED = "quarantined"
    RELEASED_FOR_REVIEW = "released_for_review"


@dataclass(frozen=True, slots=True)
class InboundQuarantineRecord:
    provider_event_ref: str
    inbound_id: str
    workspace_id: str
    fingerprint: str
    state: InboundQuarantineState
    quarantined_at: datetime
    released_at: datetime | None = None
    review_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("provider_event_ref", "inbound_id", "workspace_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        digest = self.fingerprint.strip().lower() if isinstance(self.fingerprint, str) else ""
        if not _SHA256_RE.fullmatch(digest):
            raise ContractError("fingerprint must be a lowercase SHA-256 digest")
        object.__setattr__(self, "fingerprint", digest)
        if not isinstance(self.state, InboundQuarantineState):
            try:
                object.__setattr__(self, "state", InboundQuarantineState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid quarantine state") from exc
        quarantined = _aware(self.quarantined_at, "quarantined_at")
        object.__setattr__(self, "quarantined_at", quarantined)
        if self.state is InboundQuarantineState.QUARANTINED:
            if self.released_at is not None or self.review_ref is not None:
                raise ContractError("quarantined record cannot contain release metadata")
        else:
            if self.released_at is None or self.review_ref is None:
                raise ContractError("released record requires released_at and review_ref")
            released = _aware(self.released_at, "released_at")
            if released < quarantined:
                raise ContractError("released_at cannot precede quarantine")
            object.__setattr__(self, "released_at", released)
            object.__setattr__(self, "review_ref", _ref(self.review_ref, "review_ref"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider_event_ref": self.provider_event_ref,
            "inbound_id": self.inbound_id,
            "workspace_id": self.workspace_id,
            "fingerprint": self.fingerprint,
            "state": self.state.value,
            "quarantined_at": self.quarantined_at.isoformat().replace("+00:00", "Z"),
            "released_at": self.released_at.isoformat().replace("+00:00", "Z") if self.released_at else None,
            "review_ref": self.review_ref,
            "raw_body_in_projection": False,
            "trusted_execution_input": False,
            "trusted_business_data": False,
            "automatic_record_creation": False,
            "attachment_scan_required": True,
        }


class InMemoryInboundQuarantine:
    def __init__(self, *, attachment_policy: AttachmentPolicy | None = None) -> None:
        self.attachment_policy = attachment_policy or AttachmentPolicy()
        self._by_provider_event: dict[str, InboundQuarantineRecord] = {}
        self._message_by_event: dict[str, InboundCommunication] = {}

    def quarantine(
        self,
        message: InboundCommunication,
        *,
        provider_event_ref: str,
        now: datetime,
    ) -> InboundQuarantineRecord:
        if not isinstance(message, InboundCommunication):
            raise ContractError("message must be InboundCommunication")
        provider_ref = _ref(provider_event_ref, "provider_event_ref")
        fingerprint = inbound_fingerprint(message, provider_event_ref=provider_ref)
        existing = self._by_provider_event.get(provider_ref)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise ContractError("provider event replay conflicts with quarantined content")
            return existing
        record = InboundQuarantineRecord(
            provider_event_ref=provider_ref,
            inbound_id=message.inbound_id,
            workspace_id=message.workspace_id,
            fingerprint=fingerprint,
            state=InboundQuarantineState.QUARANTINED,
            quarantined_at=now,
        )
        self._by_provider_event[provider_ref] = record
        self._message_by_event[provider_ref] = message
        return record

    def release_for_review(
        self,
        provider_event_ref: str,
        *,
        review_ref: str,
        now: datetime,
        scan_receipts: tuple[TrustedAttachmentScanReceipt, ...] = (),
    ) -> InboundQuarantineRecord:
        provider_ref = _ref(provider_event_ref, "provider_event_ref")
        review = _ref(review_ref, "review_ref")
        release_time = _aware(now, "now")
        try:
            existing = self._by_provider_event[provider_ref]
            message = self._message_by_event[provider_ref]
        except KeyError as exc:
            raise ContractError("provider event is not quarantined") from exc
        if existing.state is InboundQuarantineState.RELEASED_FOR_REVIEW:
            if existing.review_ref == review:
                return existing
            raise ContractError("released inbound event cannot be rebound to another review")
        self.attachment_policy.require_accepted(message.attachments)
        require_clean_attachment_scans(message.attachments, scan_receipts)
        for receipt in scan_receipts:
            if receipt.scanned_at < existing.quarantined_at:
                raise ContractError("attachment scan cannot predate quarantine")
            if receipt.scanned_at > release_time:
                raise ContractError("attachment scan cannot be from the future")
        released = InboundQuarantineRecord(
            provider_event_ref=existing.provider_event_ref,
            inbound_id=existing.inbound_id,
            workspace_id=existing.workspace_id,
            fingerprint=existing.fingerprint,
            state=InboundQuarantineState.RELEASED_FOR_REVIEW,
            quarantined_at=existing.quarantined_at,
            released_at=release_time,
            review_ref=review,
        )
        self._by_provider_event[provider_ref] = released
        return released

    def record(self, provider_event_ref: str) -> InboundQuarantineRecord:
        provider_ref = _ref(provider_event_ref, "provider_event_ref")
        try:
            return self._by_provider_event[provider_ref]
        except KeyError as exc:
            raise ContractError("provider event is not quarantined") from exc


REAL_INBOUND_WEBHOOK_PROVIDER_CONFIGURED = False
AUTO_INBOUND_BUSINESS_RECORD_CREATION_SUPPORTED = False
