"""Branch generation request repository - idempotency tracking.

Ensures duplicate/retry requests do not create duplicate episodes or
apply the same reader input twice. Uses an idempotency key to deduplicate.

Idempotency state machine:
- PENDING: request in progress (with timeout for stale recovery)
- COMPLETED: success - replay original result for same key
- FAILED: retry allowed via retry policy

Key binding: reader_id + reader_choice_id + prior_episode_id +
             canon_checkpoint_id + world_id + operation_type.
             Same key with different resources = conflict.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso

# Idempotency request timeout: 30 minutes
REQUEST_TIMEOUT_SECONDS = 1800


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
    operation_type: str = "personal_branch"
    attempt_number: int = 1
    pending_lease_at: str | None = None
    updated_at: str | None = None


_COLS = [
    "id", "idempotency_key", "reader_id", "reader_choice_id",
    "prior_episode_id", "canon_checkpoint_id", "world_id",
    "branch_episode_id", "status", "error_message",
    "created_at", "completed_at",
    "operation_type", "attempt_number", "pending_lease_at", "updated_at",
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
        operation_type=row["operation_type"] if "operation_type" in set(row.keys()) else "personal_branch",
        attempt_number=row["attempt_number"] if "attempt_number" in set(row.keys()) else 1,
        pending_lease_at=row["pending_lease_at"] if "pending_lease_at" in set(row.keys()) else None,
        updated_at=row["updated_at"] if "updated_at" in set(row.keys()) else None,
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


def get_by_resource_binding(
    conn: sqlite3.Connection,
    *,
    reader_id: str,
    reader_choice_id: str,
    prior_episode_id: str,
    canon_checkpoint_id: str,
    world_id: str,
    operation_type: str = "personal_branch",
) -> BranchGenerationRequestRecord | None:
    """Find an existing request with the exact same resource binding.

    operation_type is a REQUIRED part of the binding — different operation
    types produce different resource binding results even with the same IDs.
    """
    row = conn.execute(
        f"SELECT {_SELECT} FROM branch_generation_requests "
        "WHERE reader_id = ? AND reader_choice_id = ? "
        "AND prior_episode_id = ? AND canon_checkpoint_id = ? "
        "AND world_id = ? AND operation_type = ? LIMIT 1",
        (reader_id, reader_choice_id, prior_episode_id,
         canon_checkpoint_id, world_id, operation_type),
    ).fetchone()
    return _row_to_record(row) if row else None


def create_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    idempotency_key: str,
    reader_id: str,
    reader_choice_id: str | None = None,
    prior_episode_id: str | None = None,
    canon_checkpoint_id: str | None = None,
    world_id: str,
    operation_type: str = "personal_branch",
) -> BranchGenerationRequestRecord:
    """Create a branch generation request (within service-owned transaction, no commit)."""
    now = now_utc_iso()
    conn.execute(
        "INSERT INTO branch_generation_requests "
        "(id, idempotency_key, reader_id, reader_choice_id, "
        "prior_episode_id, canon_checkpoint_id, world_id, "
        "branch_episode_id, status, error_message, "
        "created_at, completed_at, "
        "operation_type, attempt_number, pending_lease_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'pending', NULL, ?, NULL, "
        "?, 1, ?, ?)",
        (
            request_id, idempotency_key, reader_id, reader_choice_id,
            prior_episode_id, canon_checkpoint_id, world_id, now,
            operation_type, now, now,
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
        "error_message = ?, completed_at = ?, updated_at = ? WHERE id = ?",
        (error_message, now_utc_iso(), now_utc_iso(), request_id),
    )


def transition_failed_to_pending(
    conn: sqlite3.Connection,
    request_id: str,
) -> None:
    """Transition a failed request back to pending for retry.

    Reuses the same row — does NOT insert a new row.
    Increments attempt_number, clears error_message and branch_episode_id.
    Updates pending_lease_at and updated_at timestamps.
    """
    conn.execute(
        "UPDATE branch_generation_requests SET "
        "status = 'pending', "
        "attempt_number = attempt_number + 1, "
        "branch_episode_id = NULL, "
        "error_message = NULL, "
        "pending_lease_at = ?, "
        "updated_at = ?, "
        "completed_at = NULL "
        "WHERE id = ?",
        (now_utc_iso(), now_utc_iso(), request_id),
    )


def transition_stale_pending_to_pending(
    conn: sqlite3.Connection,
    request_id: str,
) -> None:
    """Transition a stale pending request back to pending for recovery.

    Reuses the same row — does NOT insert a new row.
    Increments attempt_number, updates lease and timestamp.
    """
    conn.execute(
        "UPDATE branch_generation_requests SET "
        "status = 'pending', "
        "attempt_number = attempt_number + 1, "
        "branch_episode_id = NULL, "
        "error_message = NULL, "
        "pending_lease_at = ?, "
        "updated_at = ? "
        "WHERE id = ?",
        (now_utc_iso(), now_utc_iso(), request_id),
    )
