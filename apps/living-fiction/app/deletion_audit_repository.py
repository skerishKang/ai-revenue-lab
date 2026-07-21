"""Reader deletion/revocation audit repository.

Tracks what was anonymized/removed when a reader is deleted.
Survives close/reopen for verification.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.utils import now_utc_iso


@dataclass(frozen=True)
class ReaderDeletionAuditRecord:
    id: str
    reader_id: str
    anonymized_display_name: str | None
    choices_revoked_count: int
    branches_anonymized_count: int
    episodes_anonymized_count: int
    rejoin_requests_removed_count: int
    pilot_evidence_anonymized_count: int
    deleted_at: str
    created_at: str


_COLS = [
    "id", "reader_id", "anonymized_display_name",
    "choices_revoked_count", "branches_anonymized_count",
    "episodes_anonymized_count", "rejoin_requests_removed_count",
    "pilot_evidence_anonymized_count", "deleted_at", "created_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> ReaderDeletionAuditRecord:
    return ReaderDeletionAuditRecord(
        id=row["id"],
        reader_id=row["reader_id"],
        anonymized_display_name=row["anonymized_display_name"],
        choices_revoked_count=row["choices_revoked_count"],
        branches_anonymized_count=row["branches_anonymized_count"],
        episodes_anonymized_count=row["episodes_anonymized_count"],
        rejoin_requests_removed_count=row["rejoin_requests_removed_count"],
        pilot_evidence_anonymized_count=row["pilot_evidence_anonymized_count"],
        deleted_at=row["deleted_at"],
        created_at=row["created_at"],
    )


def create_deletion_audit(
    conn: sqlite3.Connection,
    *,
    audit_id: str,
    reader_id: str,
    anonymized_display_name: str | None,
    choices_revoked_count: int,
    branches_anonymized_count: int,
    episodes_anonymized_count: int,
    rejoin_requests_removed_count: int,
    pilot_evidence_anonymized_count: int,
    deleted_at: str,
) -> ReaderDeletionAuditRecord:
    """Create a deletion audit record (within service-owned transaction, no commit)."""
    now = now_utc_iso()
    conn.execute(
        f"INSERT INTO reader_deletion_audit ({_SELECT}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            audit_id, reader_id, anonymized_display_name,
            choices_revoked_count, branches_anonymized_count,
            episodes_anonymized_count, rejoin_requests_removed_count,
            pilot_evidence_anonymized_count, deleted_at, now,
        ),
    )
    row = conn.execute(
        f"SELECT {_SELECT} FROM reader_deletion_audit WHERE id = ?",
        (audit_id,),
    ).fetchone()
    return _row_to_record(row)


def get_deletion_audit_by_reader(
    conn: sqlite3.Connection, reader_id: str
) -> ReaderDeletionAuditRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM reader_deletion_audit WHERE reader_id = ?",
        (reader_id,),
    ).fetchone()
    return _row_to_record(row) if row else None
