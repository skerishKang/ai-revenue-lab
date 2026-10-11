"""Drive-authoritative index freshness contract (#3331, parent #3330).

Google Drive remains the durable authority for user files.  Padiem may retain
derived search/index projections, but a projection is reusable only while its
recorded Drive source identity and reviewed version evidence still match a
fresh canonical DriveFileProjection.

This module carries metadata only.  It owns no Drive I/O, OAuth authority,
document bytes, parser runtime, filesystem, vector store, or execution backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .drive_capability import DriveFileProjection


class DriveIndexFreshness(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class DriveIndexSourceSnapshot:
    """Metadata-only source identity for one derived Drive index projection."""

    file_id: str
    mime_type: str
    drive_id: str | None
    version: int | None
    modified_time: str | None
    md5_checksum: str | None
    sha256_checksum: str | None
    head_revision_id: str | None

    @classmethod
    def from_projection(cls, projection: DriveFileProjection) -> "DriveIndexSourceSnapshot":
        if not isinstance(projection, DriveFileProjection):
            raise TypeError("Drive index source requires a canonical DriveFileProjection")
        return cls(
            file_id=projection.file_id,
            mime_type=projection.mime_type,
            drive_id=projection.drive_id,
            version=projection.version,
            modified_time=projection.modified_time,
            md5_checksum=projection.md5_checksum,
            sha256_checksum=projection.sha256_checksum,
            head_revision_id=projection.head_revision_id,
        )

    @property
    def version_facts(self) -> tuple[object, ...]:
        return (
            self.version,
            self.modified_time,
            self.md5_checksum,
            self.sha256_checksum,
            self.head_revision_id,
        )

    @property
    def has_version_evidence(self) -> bool:
        return any(value is not None for value in self.version_facts)


def drive_index_freshness(
    indexed: DriveIndexSourceSnapshot,
    current: DriveFileProjection,
) -> DriveIndexFreshness:
    """Judge whether a derived index projection is reusable.

    Identity drift or any change in reviewed version facts is stale.  When
    neither the stored nor current projection carries usable version evidence,
    freshness cannot be proven and callers must refresh/fail closed rather than
    treating the index as primary truth.
    """

    if not isinstance(indexed, DriveIndexSourceSnapshot):
        raise TypeError("indexed source must be a DriveIndexSourceSnapshot")
    current_snapshot = DriveIndexSourceSnapshot.from_projection(current)

    if (
        indexed.file_id != current_snapshot.file_id
        or indexed.drive_id != current_snapshot.drive_id
        or indexed.mime_type != current_snapshot.mime_type
    ):
        return DriveIndexFreshness.STALE

    if not indexed.has_version_evidence and not current_snapshot.has_version_evidence:
        return DriveIndexFreshness.UNVERIFIABLE

    if indexed.version_facts != current_snapshot.version_facts:
        return DriveIndexFreshness.STALE

    return DriveIndexFreshness.CURRENT


def drive_index_freshness_snapshot() -> dict[str, object]:
    """Deterministic architecture posture for source/contract tests."""

    return {
        "document_authority": "google_drive",
        "index_role": "derived_projection",
        "index_is_primary_truth": False,
        "raw_document_content_retained": False,
        "execution_provider_authority": False,
        "version_change_is_stale": True,
        "missing_version_evidence_is_current": False,
    }


__all__ = [
    "DriveIndexFreshness",
    "DriveIndexSourceSnapshot",
    "drive_index_freshness",
    "drive_index_freshness_snapshot",
]
