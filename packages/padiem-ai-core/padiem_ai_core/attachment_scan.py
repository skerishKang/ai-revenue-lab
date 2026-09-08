"""Shared attachment scan verdict gate contract (#1572).

Promoted-lane (Core) projection of the reviewed B54 inbound-review scan
contract (``apps/korean-ai-code-agent/src/kagent/ops_attachment_scan.py``),
ported into the Core attachment/evidence family so every product lane
consumes one fail-closed scan verdict mechanism.

This module is a projection of already-reviewed logic, not a new design.
It owns only the shared scan-verdict mechanics:

- the fixed trusted scan verdicts: ``CLEAN | MALICIOUS | UNSCANNABLE``,
- exact attachment binding (id + SHA-256 + size + MIME),
- the fail-closed release gate: missing, duplicate, mismatched, malicious
  and unscannable scan receipts all block release,
- the current-scan time bounds (a scan cannot predate quarantine and
  cannot be from the future).

It deliberately does NOT own:

- MIME/size admission policy: the type/size allowlist remains an
  independently required product-side check (B54 ``AttachmentPolicy``)
  and is never subsumed or bypassed by the scan gate,
- any scanner provider, endpoint, credential or attachment content:
  Core performs no network calls; a trusted host supplies receipts,
- quarantine record state or inbound message projections (product lanes
  keep those; B54 ``InboundQuarantine`` remains the reviewed reference),
- billing, credit or pricing authority.

No authority is ever minted from a scan receipt: release decisions remain
server-owned and fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_COUNTER = 2**63 - 1

# Honest capability flags (ported from the reviewed B54 contract). Core has
# no scanner engine and no bypass path; the gate fails closed instead.
REAL_ATTACHMENT_SCANNER_CONFIGURED = False
MALWARE_SCAN_BYPASS_SUPPORTED = False


class AttachmentScanContractError(ValueError):
    """Safe attachment scan contract failure (kagent ContractError port)."""


class AttachmentScanVerdict(str, Enum):
    """The only trusted scan verdicts accepted by the release gate."""

    CLEAN = "clean"
    MALICIOUS = "malicious"
    UNSCANNABLE = "unscannable"


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise AttachmentScanContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _counter(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_COUNTER:
        raise AttachmentScanContractError(f"{field_name} must be a bounded non-negative integer")
    return value


def _sha256(value: str, field_name: str) -> str:
    digest = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(digest):
        raise AttachmentScanContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return digest


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AttachmentScanContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class AttachmentMetadata:
    """Bounded inbound attachment metadata (kagent AttachmentMetadata port).

    Carries references and measurements only — never attachment content.
    """

    attachment_id: str
    file_name: str
    mime_type: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_id", _ref(self.attachment_id, "attachment_id"))
        file_name = self.file_name.strip() if isinstance(self.file_name, str) else ""
        if not file_name or len(file_name) > 255:
            raise AttachmentScanContractError("file_name must be bounded non-empty text")
        object.__setattr__(self, "file_name", file_name)
        mime = self.mime_type.strip().lower() if isinstance(self.mime_type, str) else ""
        if not mime or len(mime) > 160:
            raise AttachmentScanContractError("mime_type must be bounded non-empty text")
        object.__setattr__(self, "mime_type", mime)
        object.__setattr__(self, "size_bytes", _counter(self.size_bytes, "size_bytes"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "attachment_content": False,
            "storage_location": False,
        }


@dataclass(frozen=True, slots=True)
class TrustedAttachmentScanReceipt:
    """One trusted server-issued scan receipt binding one attachment exactly."""

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
        ref_fields = (
            "scan_id",
            "attachment_id",
            "mime_type",
            "scanner_policy_ref",
            "authority_ref",
            "evidence_ref",
        )
        for name in ref_fields:
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "attachment_sha256", _sha256(self.attachment_sha256, "attachment_sha256"))
        object.__setattr__(self, "size_bytes", _counter(self.size_bytes, "size_bytes"))
        if not isinstance(self.verdict, AttachmentScanVerdict):
            try:
                object.__setattr__(self, "verdict", AttachmentScanVerdict(self.verdict))
            except (TypeError, ValueError) as exc:
                raise AttachmentScanContractError("invalid attachment scan verdict") from exc
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
            raise AttachmentScanContractError("attachment must be AttachmentMetadata")
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
        """Bind id + SHA-256 + size + MIME exactly; every field must match."""

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
    *,
    quarantined_at: datetime | None = None,
    released_at: datetime | None = None,
) -> None:
    """Fail-closed release gate over trusted scan receipts.

    Every released attachment requires exactly one current trusted scan
    receipt bound to it exactly, and only a ``CLEAN`` verdict permits
    release. Missing, duplicate, mismatched, malicious and unscannable
    cases all fail closed. MIME/size admission policy remains an
    independently required product-side check outside this gate.

    When ``quarantined_at``/``released_at`` are supplied, the "current"
    time bounds are enforced as well (a scan cannot predate quarantine
    and cannot be from the future).
    """

    if not isinstance(attachments, tuple) or not all(
        isinstance(item, AttachmentMetadata) for item in attachments
    ):
        raise AttachmentScanContractError("attachments must be AttachmentMetadata tuple")
    if not isinstance(receipts, tuple) or not all(
        isinstance(item, TrustedAttachmentScanReceipt) for item in receipts
    ):
        raise AttachmentScanContractError("scan receipts must be TrustedAttachmentScanReceipt tuple")
    if (quarantined_at is None) != (released_at is None):
        raise AttachmentScanContractError("quarantined_at and released_at must be supplied together")
    if not attachments:
        if receipts:
            raise AttachmentScanContractError("scan receipts supplied for message without attachments")
        return
    by_attachment: dict[str, TrustedAttachmentScanReceipt] = {}
    for receipt in receipts:
        if receipt.attachment_id in by_attachment:
            raise AttachmentScanContractError("duplicate attachment scan receipt")
        by_attachment[receipt.attachment_id] = receipt
    if set(by_attachment) != {item.attachment_id for item in attachments}:
        raise AttachmentScanContractError("every attachment requires exactly one scan receipt")
    for attachment in attachments:
        receipt = by_attachment[attachment.attachment_id]
        if not receipt.matches(attachment):
            raise AttachmentScanContractError("attachment scan receipt does not match exact attachment metadata")
        if receipt.verdict is not AttachmentScanVerdict.CLEAN:
            raise AttachmentScanContractError("only CLEAN attachment scan verdict permits review release")
    if quarantined_at is not None and released_at is not None:
        lower = _aware(quarantined_at, "quarantined_at")
        upper = _aware(released_at, "released_at")
        if upper < lower:
            raise AttachmentScanContractError("released_at cannot precede quarantine")
        for receipt in receipts:
            if receipt.scanned_at < lower:
                raise AttachmentScanContractError("attachment scan cannot predate quarantine")
            if receipt.scanned_at > upper:
                raise AttachmentScanContractError("attachment scan cannot be from the future")
