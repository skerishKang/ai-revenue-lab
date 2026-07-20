"""Branch generation request repository — idempotency tracking.

Ensures duplicate/retry requests do not create duplicate episodes or
apply the same reader input twice. Uses an idempotency key to deduplicate.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class BranchGenerationRequestRecord:
    id: str
    idempotency_key: str
    reader_id: str
    reader_choice_id: str
    prior_episode_id: str
    canon_checkpoint_id: str
    world_id: str
    branch_episode_id: str | None
    status: str
    error_message: str | None
    created_at: str
    completed_at: str | None


_COLS = [
    "id", "idempotency_key", "reader_id", "reader_choice_id",
    "prior_episode_id", "canon_checkpoint_id", "world_id",
    "branch_episode_id", "status", "error_message",
    "created_at", "completed_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> BranchGenerationRequestRecord:
    return BranchGenerationRequestRecord(
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        reader_id=row["reader_id"],
        reader_choice_id=row["reader_choice_id"],
        prior_episode_id=row["prior_episode_id"],
        canon_checkpoint_id=row["canon_checkpoint_id"],
        world_id=row["world_id"],
        branch_episode_id=row["branch_episode_id"],
        status=row["status"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


def get_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> BranchGenerationRequestRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM branch_generation_requests "
        "WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    return _row_to_record(row) if row else None


def create_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    idempotency_key: str,
    reader_id: str,
    reader_choice_id: str,
    prior_episode_id: str,
    canon_checkpoint_id: str,
    world_id: str,
) -> BranchGenerationRequestRecord:
    """Create a branch generation request (within service-owned transaction, no commit)."""
    now = now_utc_iso()
    conn.execute(
        f"INSERT INTO branch_generation_requests ({_SELECT}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'pending', NULL, ?, NULL)",
        (
            request_id, idempotency_key, reader_id, reader_choice_id,
            prior_episode_id, canon_checkpoint_id, world_id, now,
        ),
    )
    row = conn.execute(
        f"SELECT {_SELECT} FROM branch_generation_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    return _row_to_record(row)


def mark_completed(
    conn: sqlite3.Connection,
    request_id: str,
    branch_episode_id: str,
) -> None:
    """Mark a request as completed (within service-owned transaction, no commit)."""
    conn.execute(
        "UPDATE branch_generation_requests SET status = 'completed', "
        "branch_episode_id = ?, completed_at = ? WHERE id = ?",
        (branch_episode_id, now_utc_iso(), request_id),
    )


def mark_failed(
    conn: sqlite3.Connection,
    request_id: str,
    error_message: str,
) -> None:
    """Mark a request as failed (within service-owned transaction, no commit)."""
    conn.execute(
        "UPDATE branch_generation_requests SET status = 'failed', "
        "error_message = ?, completed_at = ? WHERE id = ?",
        (error_message, now_utc_iso(), request_id),
    )
