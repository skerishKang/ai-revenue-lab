from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .ops_communications import AttachmentMetadata
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


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


class AttachmentScanVerdict(str, Enum):
    CLEAN = "clean"
    MALICIOUS = "malicious"
    UNSCANNABLE = "unscannable"


@dataclass(frozen=True, slots=True)
class TrustedAttachmentScanReceipt:
    scan_id: str
    attachment_id: str
    attachment_sha256: str
    size_bytes: int
    mime_type: str
    verdict: AttachmentScanVerdict
    scanned_at: datetime
    scanner_policy_ref: str
    authority_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("scan_id", "attachment_id", "mime_type", "scanner_policy_ref", "authority_ref", "evidence_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        sha = self.attachment_sha256.strip().lower() if isinstance(self.attachment_sha256, str) else ""
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ContractError("attachment_sha256 must be lowercase SHA-256")
        object.__setattr__(self, "attachment_sha256", sha)
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ContractError("size_bytes must be a non-negative integer")
        if not isinstance(self.verdict, AttachmentScanVerdict):
            try:
                object.__setattr__(self, "verdict", AttachmentScanVerdict(self.verdict))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid attachment scan verdict") from exc
        object.__setattr__(self, "scanned_at", _aware(self.scanned_at, "scanned_at"))

    @classmethod
    def from_attachment(
        cls,
        *,
        scan_id: str,
        attachment: AttachmentMetadata,
        verdict: AttachmentScanVerdict,
        scanned_at: datetime,
        scanner_policy_ref: str,
        authority_ref: str,
        evidence_ref: str,
    ) -> "TrustedAttachmentScanReceipt":
        if not isinstance(attachment, AttachmentMetadata):
            raise ContractError("attachment must be AttachmentMetadata")
        return cls(
            scan_id=scan_id,
            attachment_id=attachment.attachment_id,
            attachment_sha256=attachment.sha256,
            size_bytes=attachment.size_bytes,
            mime_type=attachment.mime_type,
            verdict=verdict,
            scanned_at=scanned_at,
            scanner_policy_ref=scanner_policy_ref,
            authority_ref=authority_ref,
            evidence_ref=evidence_ref,
        )

    def matches(self, attachment: AttachmentMetadata) -> bool:
        return (
            isinstance(attachment, AttachmentMetadata)
            and self.attachment_id == attachment.attachment_id
            and self.attachment_sha256 == attachment.sha256
            and self.size_bytes == attachment.size_bytes
            and self.mime_type == attachment.mime_type
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "attachment_id": self.attachment_id,
            "attachment_sha256": self.attachment_sha256,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
            "verdict": self.verdict.value,
            "scanned_at": self.scanned_at.isoformat().replace("+00:00", "Z"),
            "scanner_policy_ref": self.scanner_policy_ref,
            "authority_ref": self.authority_ref,
            "evidence_ref": self.evidence_ref,
            "attachment_content": False,
            "scanner_endpoint": False,
            "scanner_credential": False,
        }


def require_clean_attachment_scans(
    attachments: tuple[AttachmentMetadata, ...],
    receipts: tuple[TrustedAttachmentScanReceipt, ...],
) -> None:
    if not isinstance(attachments, tuple) or not all(isinstance(item, AttachmentMetadata) for item in attachments):
        raise ContractError("attachments must be AttachmentMetadata tuple")
    if not isinstance(receipts, tuple) or not all(isinstance(item, TrustedAttachmentScanReceipt) for item in receipts):
        raise ContractError("scan receipts must be TrustedAttachmentScanReceipt tuple")
    if not attachments:
        if receipts:
            raise ContractError("scan receipts supplied for message without attachments")
        return
    by_attachment: dict[str, TrustedAttachmentScanReceipt] = {}
    for receipt in receipts:
        if receipt.attachment_id in by_attachment:
            raise ContractError("duplicate attachment scan receipt")
        by_attachment[receipt.attachment_id] = receipt
    if set(by_attachment) != {item.attachment_id for item in attachments}:
        raise ContractError("every attachment requires exactly one scan receipt")
    for attachment in attachments:
        receipt = by_attachment[attachment.attachment_id]
        if not receipt.matches(attachment):
            raise ContractError("attachment scan receipt does not match exact attachment metadata")
        if receipt.verdict is not AttachmentScanVerdict.CLEAN:
            raise ContractError("only CLEAN attachment scan verdict permits review release")


REAL_ATTACHMENT_SCANNER_CONFIGURED = False
MALWARE_SCAN_BYPASS_SUPPORTED = False
