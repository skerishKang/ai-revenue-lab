"""Freshness-gated retrieval from Drive-derived document indexes (#3345).

Google Drive remains the durable document authority. A stored page/chunk
projection is derived data and may become a located RetrievedItem only after
its recorded Drive source snapshot is proven CURRENT against a fresh canonical
DriveFileProjection.

This module composes the existing #3331 freshness authority with the #3333
located-retrieval authority. It owns no Drive I/O, index storage, ranking,
parser, vector database, OAuth authority, model execution, or product UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from .document_semantics import DocumentSegment
from .drive_capability import DriveFileProjection
from .drive_index_freshness import (
    DriveIndexFreshness,
    DriveIndexSourceSnapshot,
    drive_index_freshness,
)
from .retrieval import RetrievedItem


DRIVE_INDEX_RETRIEVAL_PROVIDER = "padiem_drive_index"
DRIVE_INDEX_RETRIEVAL_SOURCE_TYPE = "drive_file"


class DriveIndexRetrievalError(ValueError):
    """Safe fail-closed error at the Drive-derived retrieval boundary."""

    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


@dataclass(frozen=True, slots=True)
class DriveIndexedSegment:
    """One derived index segment bound to its canonical Drive source snapshot.

    The segment owns the document locator. No page/section locator field is
    accepted here, so callers cannot relabel index text with a new exact page.
    Retrieval identity fields are passed through the existing RetrievedItem
    validator when the freshness gate succeeds.
    """

    item_id: str
    namespace: str
    source_ref: str
    source_snapshot: DriveIndexSourceSnapshot
    segment: DocumentSegment

    def __post_init__(self) -> None:
        if not isinstance(self.source_snapshot, DriveIndexSourceSnapshot):
            raise TypeError("Drive indexed segment requires a canonical source snapshot")
        if not isinstance(self.segment, DocumentSegment):
            raise TypeError("Drive indexed segment requires a canonical DocumentSegment")
        if self.segment.locator is None:
            raise DriveIndexRetrievalError(
                "missing_document_locator",
                "Drive indexed retrieval requires canonical document locator provenance.",
            )


def retrieve_current_drive_index_segment(
    indexed: DriveIndexedSegment,
    current_source: DriveFileProjection,
    *,
    content: str | None = None,
) -> RetrievedItem:
    """Mint a located retrieval item only from a CURRENT Drive-derived index.

    current_source must be a fresh canonical Drive metadata projection obtained
    by the product/Engine authority before this pure function is called. STALE
    and UNVERIFIABLE projections fail closed before any RetrievedItem is
    created. On success, #3333's canonical segment constructor supplies the
    locator and reuses its chunk-substring guard.
    """

    if not isinstance(indexed, DriveIndexedSegment):
        raise TypeError("indexed must be a DriveIndexedSegment")
    if not isinstance(current_source, DriveFileProjection):
        raise TypeError("current_source must be a canonical DriveFileProjection")

    freshness = drive_index_freshness(indexed.source_snapshot, current_source)
    if freshness is DriveIndexFreshness.STALE:
        raise DriveIndexRetrievalError(
            "stale_drive_index",
            "Drive-derived retrieval index is stale and must be refreshed.",
        )
    if freshness is DriveIndexFreshness.UNVERIFIABLE:
        raise DriveIndexRetrievalError(
            "unverifiable_drive_index",
            "Drive-derived retrieval index freshness cannot be verified.",
        )
    if freshness is not DriveIndexFreshness.CURRENT:
        raise DriveIndexRetrievalError(
            "drive_index_freshness_unknown",
            "Drive-derived retrieval index freshness is not usable.",
        )

    return RetrievedItem.from_document_segment(
        id=indexed.item_id,
        namespace=indexed.namespace,
        source_type=DRIVE_INDEX_RETRIEVAL_SOURCE_TYPE,
        provider=DRIVE_INDEX_RETRIEVAL_PROVIDER,
        source_ref=indexed.source_ref,
        segment=indexed.segment,
        title=current_source.name,
        content=content,
    )


def drive_index_retrieval_snapshot() -> dict[str, object]:
    """Deterministic source posture for architecture/conformance tests."""

    return {
        "document_authority": "google_drive",
        "index_role": "derived_projection",
        "current_drive_metadata_required": True,
        "freshness_check_before_retrieval": True,
        "stale_index_retrievable": False,
        "unverifiable_index_retrievable": False,
        "locator_source": "canonical_document_segment",
        "index_is_primary_truth": False,
        "drive_io": False,
        "model_call": False,
    }


__all__ = [
    "DRIVE_INDEX_RETRIEVAL_PROVIDER",
    "DRIVE_INDEX_RETRIEVAL_SOURCE_TYPE",
    "DriveIndexRetrievalError",
    "DriveIndexedSegment",
    "drive_index_retrieval_snapshot",
    "retrieve_current_drive_index_segment",
]
