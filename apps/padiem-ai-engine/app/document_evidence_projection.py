"""Evidence-storage projection of a resolved document for Engine E5B-S3 (#1750).

Evidence retention is the counterpart of the context projection: it keeps the
full segment body, segment provenance locators and the internal ``att_*``
reference behind an engine-minted evidence id. The wire never sees a storage
locator; the repr redacts internal references so logs cannot leak them. Only
an in-memory port exists in S3 — durable evidence storage arrives with S4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Protocol

from padiem_ai_core.document_semantics import (
    DocumentLocator,
    LocatorKind,
    LocatorPrecision,
)
from padiem_ai_core.document_normalization import NormalizedDocument

from app.trusted_document_resolver import (
    ResolvedDocumentMeta,
    require_document_reference,
)

MAX_EVIDENCE_LOCATOR_CHARS = 256


def _default_document_locator(document: NormalizedDocument) -> DocumentLocator:
    for segment in document.segments:
        if segment.locator is not None:
            return segment.locator
    return DocumentLocator(kind=LocatorKind.SECTION, value="section:1", precision=LocatorPrecision.EXACT)


@dataclass(frozen=True, slots=True, repr=False)
class EvidenceStorageProjection:
    """Complete document retention behind an engine-minted evidence id."""

    evidence_id: str
    att_ref: str
    normalized_document: NormalizedDocument = field(repr=False)
    document_locator: DocumentLocator = field(repr=False)
    storage_locator: str = field(repr=False)
    created_at: datetime

    @classmethod
    def from_resolver_result(
        cls,
        att_ref: object,
        document: NormalizedDocument,
        meta: ResolvedDocumentMeta,
        storage_locator: str,
        *,
        evidence_id: str | None = None,
        created_at: datetime | None = None,
    ) -> "EvidenceStorageProjection":
        reference = require_document_reference(att_ref)
        if not isinstance(document, NormalizedDocument):
            raise ValueError("evidence projection requires a canonical NormalizedDocument")
        if not isinstance(meta, ResolvedDocumentMeta):
            raise ValueError("evidence projection requires a ResolvedDocumentMeta")
        if (
            not isinstance(storage_locator, str)
            or not storage_locator
            or len(storage_locator) > MAX_EVIDENCE_LOCATOR_CHARS
        ):
            raise ValueError("evidence storage locator must be a bounded opaque token")
        stamp = created_at if created_at is not None else datetime.now(timezone.utc)
        if not isinstance(stamp, datetime) or stamp.tzinfo is None:
            raise ValueError("evidence created_at must be timezone-aware")
        minted = evidence_id if evidence_id is not None else uuid.uuid4().hex
        if not isinstance(minted, str) or len(minted) < 16 or len(minted) > 64:
            raise ValueError("evidence id must be a bounded server token")
        return cls(
            evidence_id=minted,
            att_ref=reference,
            normalized_document=document,
            document_locator=_default_document_locator(document),
            storage_locator=storage_locator,
            created_at=stamp,
        )

    def __repr__(self) -> str:
        return (
            "EvidenceStorageProjection("
            f"evidence_id={self.evidence_id}, name={self.normalized_document.name}, "
            f"segment_count={self.normalized_document.segment_count}, "
            f"status={self.normalized_document.status.value}, "
            "att_ref=redacted, storage_locator=redacted)"
        )


class EvidenceStoragePort(Protocol):
    """Retention of evidence projections behind engine-minted ids."""

    def store(self, projection: EvidenceStorageProjection) -> str: ...

    def retrieve(self, evidence_id: str) -> EvidenceStorageProjection: ...


class InMemoryEvidenceStoragePort:
    """Test/demo evidence retention; no database, object store or provider."""

    def __init__(self) -> None:
        self._records: dict[str, EvidenceStorageProjection] = {}

    def store(self, projection: EvidenceStorageProjection) -> str:
        if not isinstance(projection, EvidenceStorageProjection):
            raise ValueError("evidence storage accepts EvidenceStorageProjection only")
        if projection.evidence_id in self._records:
            raise ValueError("evidence id already exists in this store")
        self._records[projection.evidence_id] = projection
        return projection.evidence_id

    def retrieve(self, evidence_id: str) -> EvidenceStorageProjection:
        if not isinstance(evidence_id, str) or evidence_id not in self._records:
            raise KeyError("evidence id is unknown")
        return self._records[evidence_id]
