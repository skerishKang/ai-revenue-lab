from __future__ import annotations

from dataclasses import replace

import pytest

from padiem_ai_core.drive_capability import DriveFileProjection
from padiem_ai_core.drive_index_freshness import (
    DriveIndexFreshness,
    DriveIndexSourceSnapshot,
    drive_index_freshness,
    drive_index_freshness_snapshot,
)


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


def test_exact_drive_version_is_current() -> None:
    current = projection()
    indexed = DriveIndexSourceSnapshot.from_projection(current)

    assert drive_index_freshness(indexed, current) is DriveIndexFreshness.CURRENT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 8),
        ("modified_time", "2026-10-01T01:00:00Z"),
        ("md5_checksum", "b" * 32),
        ("sha256_checksum", "c" * 64),
        ("head_revision_id", "revision_8"),
    ],
)
def test_any_version_fact_change_is_stale(field: str, value: object) -> None:
    current = projection()
    indexed = DriveIndexSourceSnapshot.from_projection(current)

    assert drive_index_freshness(indexed, replace(current, **{field: value})) is DriveIndexFreshness.STALE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("file_id", "file_legal_2"),
        ("drive_id", "shared_drive_2"),
        ("mime_type", "application/vnd.google-apps.document"),
    ],
)
def test_source_identity_change_is_stale(field: str, value: object) -> None:
    current = projection()
    indexed = DriveIndexSourceSnapshot.from_projection(current)

    assert drive_index_freshness(indexed, replace(current, **{field: value})) is DriveIndexFreshness.STALE


def test_missing_version_evidence_is_unverifiable_not_current() -> None:
    current = projection(
        version=None,
        modified_time=None,
        md5_checksum=None,
        sha256_checksum=None,
        head_revision_id=None,
    )
    indexed = DriveIndexSourceSnapshot.from_projection(current)

    assert drive_index_freshness(indexed, current) is DriveIndexFreshness.UNVERIFIABLE


def test_lost_version_fact_forces_refresh() -> None:
    current = projection()
    indexed = DriveIndexSourceSnapshot.from_projection(current)

    assert drive_index_freshness(indexed, replace(current, md5_checksum=None)) is DriveIndexFreshness.STALE


def test_contract_accepts_only_canonical_projection() -> None:
    with pytest.raises(TypeError):
        DriveIndexSourceSnapshot.from_projection({"file_id": "caller"})  # type: ignore[arg-type]


def test_architecture_snapshot_keeps_drive_as_authority() -> None:
    snapshot = drive_index_freshness_snapshot()

    assert snapshot["document_authority"] == "google_drive"
    assert snapshot["index_role"] == "derived_projection"
    assert snapshot["index_is_primary_truth"] is False
    assert snapshot["raw_document_content_retained"] is False
    assert snapshot["execution_provider_authority"] is False
    assert snapshot["version_change_is_stale"] is True
    assert snapshot["missing_version_evidence_is_current"] is False
