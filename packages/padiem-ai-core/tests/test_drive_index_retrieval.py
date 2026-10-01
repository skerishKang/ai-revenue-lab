from __future__ import annotations

from dataclasses import replace

import pytest

from padiem_ai_core.document_semantics import (
    DocumentLocator,
    DocumentSegment,
    LocatorKind,
    LocatorPrecision,
)
from padiem_ai_core.drive_capability import DriveFileProjection
from padiem_ai_core.drive_index_freshness import DriveIndexSourceSnapshot
from padiem_ai_core.drive_index_retrieval import (
    DRIVE_INDEX_RETRIEVAL_PROVIDER,
    DRIVE_INDEX_RETRIEVAL_SOURCE_TYPE,
    DriveIndexedSegment,
    DriveIndexRetrievalError,
    drive_index_retrieval_snapshot,
    retrieve_current_drive_index_segment,
)
from padiem_ai_core.retrieval import RetrievalContractError, RetrievedItem


def projection(**overrides: object) -> DriveFileProjection:
    values: dict[str, object] = {
        "file_id": "file_legal_1",
        "name": "brief.pdf",
        "mime_type": "application/pdf",
        "drive_id": "shared_drive_1",
        "version": 7,
        "modified_time": "2026-10-01T00:00:00Z",
        "md5_checksum": "a" * 32,
        "sha256_checksum": None,
        "head_revision_id": "revision_7",
    }
    values.update(overrides)
    return DriveFileProjection(**values)  # type: ignore[arg-type]


def page_segment(page: int = 7) -> DocumentSegment:
    return DocumentSegment(
        text="Termination notice was received on the canonical source page.",
        order=page - 1,
        locator=DocumentLocator(
            kind=LocatorKind.PAGE,
            value=str(page),
            precision=LocatorPrecision.EXACT,
        ),
    )


def indexed_segment(
    source: DriveFileProjection | None = None,
    *,
    segment: DocumentSegment | None = None,
) -> DriveIndexedSegment:
    canonical = source or projection()
    return DriveIndexedSegment(
        item_id="chunk_page_7",
        namespace="project.legal",
        source_snapshot=DriveIndexSourceSnapshot.from_projection(canonical),
        segment=segment or page_segment(),
    )


def test_current_drive_source_mints_located_retrieved_item() -> None:
    current = projection()
    indexed = indexed_segment(current)

    retrieved = retrieve_current_drive_index_segment(
        indexed,
        current,
        content="Termination notice",
    )

    assert isinstance(retrieved, RetrievedItem)
    assert retrieved.provider == DRIVE_INDEX_RETRIEVAL_PROVIDER
    assert retrieved.source_type == DRIVE_INDEX_RETRIEVAL_SOURCE_TYPE
    assert retrieved.source_ref == "drive:file_legal_1"
    assert retrieved.title == "brief.pdf"
    assert retrieved.content == "Termination notice"
    assert retrieved.document_locator is indexed.segment.locator
    assert retrieved.to_public_dict()["document_locator"] == {
        "kind": "page",
        "value": "7",
        "precision": "exact",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 8),
        ("modified_time", "2026-10-01T01:00:00Z"),
        ("md5_checksum", "b" * 32),
        ("head_revision_id", "revision_8"),
        ("file_id", "file_legal_2"),
        ("drive_id", "shared_drive_2"),
        ("mime_type", "application/vnd.google-apps.document"),
    ],
)
def test_stale_or_identity_drift_denies_before_retrieval(
    field: str,
    value: object,
) -> None:
    indexed_source = projection()
    indexed = indexed_segment(indexed_source)
    current = replace(indexed_source, **{field: value})

    with pytest.raises(DriveIndexRetrievalError) as exc_info:
        retrieve_current_drive_index_segment(indexed, current)

    assert exc_info.value.code == "stale_drive_index"


def test_unverifiable_drive_source_never_becomes_current_by_default() -> None:
    no_version = projection(
        version=None,
        modified_time=None,
        md5_checksum=None,
        sha256_checksum=None,
        head_revision_id=None,
    )
    indexed = indexed_segment(no_version)

    with pytest.raises(DriveIndexRetrievalError) as exc_info:
        retrieve_current_drive_index_segment(indexed, no_version)

    assert exc_info.value.code == "unverifiable_drive_index"


def test_fresh_current_title_is_used_instead_of_index_owned_title() -> None:
    indexed_source = projection(name="old-name.pdf")
    indexed = indexed_segment(indexed_source)
    current = replace(indexed_source, name="renamed-current.pdf")

    retrieved = retrieve_current_drive_index_segment(indexed, current)

    assert retrieved.title == "renamed-current.pdf"


def test_locator_can_only_come_from_canonical_segment() -> None:
    no_locator = DocumentSegment(
        text="Canonical text without a locator.",
        order=0,
        locator=None,
    )

    with pytest.raises(DriveIndexRetrievalError) as exc_info:
        indexed_segment(segment=no_locator)

    assert exc_info.value.code == "missing_document_locator"

    with pytest.raises(TypeError):
        DriveIndexedSegment(
            item_id="forged_source",
            namespace="project.legal",
            source_snapshot=DriveIndexSourceSnapshot.from_projection(projection()),
            segment=page_segment(),
            source_ref="drive:other_file",
        )  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        DriveIndexedSegment(
            item_id="forged",
            namespace="project.legal",
            source_snapshot=DriveIndexSourceSnapshot.from_projection(projection()),
            segment=page_segment(),
            document_locator=DocumentLocator(
                kind=LocatorKind.PAGE,
                value="99",
                precision=LocatorPrecision.EXACT,
            ),
        )  # type: ignore[call-arg]


def test_chunk_must_remain_substring_of_canonical_segment() -> None:
    current = projection()
    indexed = indexed_segment(current)

    with pytest.raises(RetrievalContractError) as exc_info:
        retrieve_current_drive_index_segment(
            indexed,
            current,
            content="unrelated model-generated page text",
        )

    assert exc_info.value.code == "retrieval_locator_content_mismatch"


def test_only_canonical_drive_projection_can_prove_freshness() -> None:
    indexed = indexed_segment()

    with pytest.raises(TypeError):
        retrieve_current_drive_index_segment(
            indexed,
            {"file_id": "caller-claimed-current"},  # type: ignore[arg-type]
        )


def test_index_record_requires_canonical_snapshot_and_segment() -> None:
    with pytest.raises(TypeError):
        DriveIndexedSegment(
            item_id="chunk",
            namespace="project.legal",
            source_snapshot={"file_id": "caller"},  # type: ignore[arg-type]
            segment=page_segment(),
        )

    with pytest.raises(TypeError):
        DriveIndexedSegment(
            item_id="chunk",
            namespace="project.legal",
            source_snapshot=DriveIndexSourceSnapshot.from_projection(projection()),
            segment={"text": "caller"},  # type: ignore[arg-type]
        )


def test_architecture_snapshot_keeps_drive_authoritative_and_index_derived() -> None:
    snapshot = drive_index_retrieval_snapshot()

    assert snapshot == {
        "document_authority": "google_drive",
        "index_role": "derived_projection",
        "current_drive_metadata_required": True,
        "freshness_check_before_retrieval": True,
        "stale_index_retrievable": False,
        "unverifiable_index_retrievable": False,
        "locator_source": "canonical_document_segment",
        "source_ref_source": "drive_source_snapshot",
        "index_is_primary_truth": False,
        "drive_io": False,
        "model_call": False,
    }
