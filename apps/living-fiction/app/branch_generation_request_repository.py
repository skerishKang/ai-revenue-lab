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

Atomic CAS operations: claim, complete, fail within BEGIN IMMEDIATE.
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

# Maximum attempt number before giving up
MAX_ATTEMPT_NUMBER = 10


class CASClaimError(RuntimeError):
    """Raised when an atomic CAS claim fails (no rows updated)."""
    pass


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


def create_request_raw(
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
) -> None:
    """Insert a branch generation request row (within service-owned transaction)."""
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
    create_request_raw(
        conn, request_id=request_id, idempotency_key=idempotency_key,
        reader_id=reader_id, reader_choice_id=reader_choice_id,
        prior_episode_id=prior_episode_id, canon_checkpoint_id=canon_checkpoint_id,
        world_id=world_id, operation_type=operation_type,
    )
    row = conn.execute(
        f"SELECT {_SELECT} FROM branch_generation_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    return _row_to_record(row)


# ── Atomic CAS operations ────────────────────────────────────────────────

# CAS operation result type
from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class ClaimResult:
    """Result of a CAS claim operation."""
    request_id: str
    is_new: bool  # True if a new row was inserted
    is_replay: bool  # True if a completed request was replayed
    is_rejected: bool  # True if active pending was rejected
    attempt_number: int
    request_record: BranchGenerationRequestRecord | None = None


def claim_branch_generation_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    idempotency_key: str,
    reader_id: str,
    reader_choice_id: str | None,
    prior_episode_id: str | None,
    canon_checkpoint_id: str | None,
    world_id: str,
    operation_type: str = "personal_branch",
) -> ClaimResult:
    """Atomic CAS claim within an active transaction (BEGIN IMMEDIATE).

    Handles:
    - New idempotency key → insert new pending row
    - Completed key → replay (no insert, no provider call)
    - Active pending → reject
    - Stale pending → CAS reclaim with rowcount check
    - Failed → CAS retry with rowcount check

    Must be called within BEGIN IMMEDIATE.
    Returns ClaimResult describing what happened.
    """
    existing = get_by_idempotency_key(conn, idempotency_key)

    if existing is not None:
        # Resource binding check
        resource_mismatch = (
            existing.reader_id != (reader_id or "")
            or existing.reader_choice_id != (reader_choice_id or "")
            or existing.prior_episode_id != (prior_episode_id or "")
            or existing.canon_checkpoint_id != (canon_checkpoint_id or "")
            or existing.world_id != world_id
            or existing.operation_type != operation_type
        )
        if resource_mismatch:
            raise CASClaimError(
                "idempotency key conflict: key already bound to different resources"
            )

        if existing.status == "completed":
            # Replay completed request
            return ClaimResult(
                request_id=existing.id,
                is_new=False,
                is_replay=True,
                is_rejected=False,
                attempt_number=existing.attempt_number,
                request_record=existing,
            )

        elif existing.status == "failed":
            # CAS retry: UPDATE ... WHERE status='failed'
            now = now_utc_iso()
            updated = conn.execute(
                "UPDATE branch_generation_requests SET "
                "status = 'pending', "
                "attempt_number = attempt_number + 1, "
                "branch_episode_id = NULL, "
                "error_message = NULL, "
                "pending_lease_at = ?, "
                "updated_at = ?, "
                "completed_at = NULL "
                "WHERE id = ? AND status = 'failed'",
                (now, now, existing.id),
            ).rowcount
            if updated != 1:
                raise CASClaimError(
                    "failed atomic CAS for failed->pending transition"
                )
            # Re-read the updated record
            updated_record = get_by_idempotency_key(conn, idempotency_key)
            return ClaimResult(
                request_id=existing.id,
                is_new=False,
                is_replay=False,
                is_rejected=False,
                attempt_number=updated_record.attempt_number if updated_record else 0,
                request_record=updated_record,
            )

        elif existing.status == "pending":
            # Check staleness using pending_lease_at, not created_at
            import datetime
            from app.utils import parse_iso_datetime
            try:
                lease_ref = existing.pending_lease_at or existing.updated_at or existing.created_at
                lease_dt = parse_iso_datetime(lease_ref)
                if lease_dt is None:
                    raise CASClaimError(
                        f"invalid timestamp for pending lease: {lease_ref}"
                    )
                now = datetime.datetime.now(datetime.timezone.utc)
                age = (now - lease_dt).total_seconds()
                if age > REQUEST_TIMEOUT_SECONDS:
                    # Stale pending — CAS reclaim
                    now_ = now_utc_iso()
                    updated = conn.execute(
                        "UPDATE branch_generation_requests SET "
                        "status = 'pending', "
                        "attempt_number = attempt_number + 1, "
                        "branch_episode_id = NULL, "
                        "error_message = NULL, "
                        "pending_lease_at = ?, "
                        "updated_at = ? "
                        "WHERE id = ? AND status = 'pending'",
                        (now_, now_, existing.id),
                    ).rowcount
                    if updated != 1:
                        raise CASClaimError(
                            "failed atomic CAS for stale pending recovery"
                        )
                    updated_record = get_by_idempotency_key(conn, idempotency_key)
                    return ClaimResult(
                        request_id=existing.id,
                        is_new=False,
                        is_replay=False,
                        is_rejected=False,
                        attempt_number=updated_record.attempt_number if updated_record else 0,
                        request_record=updated_record,
                    )
                else:
                    # Active pending — reject
                    return ClaimResult(
                        request_id=existing.id,
                        is_new=False,
                        is_replay=False,
                        is_rejected=True,
                        attempt_number=existing.attempt_number,
                        request_record=existing,
                    )
            except (ValueError, TypeError):
                raise CASClaimError(
                    f"invalid timestamp parse for pending lease: "
                    f"{existing.pending_lease_at}"
                )

    # New request — insert
    create_request_raw(
        conn,
        request_id=request_id,
        idempotency_key=idempotency_key,
        reader_id=reader_id,
        reader_choice_id=reader_choice_id,
        prior_episode_id=prior_episode_id,
        canon_checkpoint_id=canon_checkpoint_id,
        world_id=world_id,
        operation_type=operation_type,
    )
    new_record = get_by_idempotency_key(conn, idempotency_key)
    return ClaimResult(
        request_id=request_id,
        is_new=True,
        is_replay=False,
        is_rejected=False,
        attempt_number=1,
        request_record=new_record,
    )


def complete_branch_generation_request(
    conn: sqlite3.Connection,
    request_id: str,
    branch_episode_id: str,
) -> None:
    """Atomic CAS complete within an active transaction.

    Must be called within BEGIN IMMEDIATE.
    Raises CASClaimError if no row was updated.
    """
    updated = conn.execute(
        "UPDATE branch_generation_requests SET status = 'completed', "
        "branch_episode_id = ?, completed_at = ?, updated_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (branch_episode_id, now_utc_iso(), now_utc_iso(), request_id),
    ).rowcount
    if updated != 1:
        raise CASClaimError(
            f"failed to complete generation request {request_id}: "
            f"no pending row found"
        )


def fail_branch_generation_request(
    conn: sqlite3.Connection,
    request_id: str,
    error_message: str | None,
) -> None:
    """Atomic CAS fail within an active transaction.

    Must be called within BEGIN IMMEDIATE.
    Raises CASClaimError if no row was updated.
    """
    updated = conn.execute(
        "UPDATE branch_generation_requests SET status = 'failed', "
        "error_message = ?, completed_at = ?, updated_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (error_message, now_utc_iso(), now_utc_iso(), request_id),
    ).rowcount
    if updated != 1:
        raise CASClaimError(
            f"failed to mark generation request {request_id} as failed: "
            f"no pending row found"
        )


# ── Legacy state transition helpers (kept for backward compat, use CAS instead) ──


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
