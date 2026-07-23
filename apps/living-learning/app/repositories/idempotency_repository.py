"""Atomic idempotency claim/complete/fail with a durable lifecycle.

Design goals (Issue #37 blockers A and B):

* **Atomic claim.** The operation key has a database-level ``UNIQUE``
  constraint. A claim is an ``INSERT OR IGNORE`` followed by a CAS-style read;
  under ``BEGIN IMMEDIATE`` exactly one concurrent caller becomes the owner.
  There is no read-then-write window in which two callers can both believe they
  own the key.

* **Durable lifecycle.** Statuses are ``pending``, ``completed``,
  ``failed_retryable`` and ``failed_terminal``. A claim never gets stuck in
  ``pending`` forever: on failure the service transitions it to
  ``failed_retryable`` (reclaimable), and a bounded lease lets a stale
  ``pending`` claim (e.g. from a crashed owner) be safely reclaimed.

* **Transaction ownership.** These functions never commit. The service layer
  owns the transaction boundary (``BEGIN IMMEDIATE`` / ``commit`` /
  ``rollback``) so a claim and the work it guards succeed or fail together.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.operation import OperationIdentity


def _utcnow(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _lease_deadline(lease_ttl_seconds: int, now: datetime | None = None) -> str:
    dt = (now or datetime.now(timezone.utc)) + timedelta(seconds=lease_ttl_seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# Lifecycle states.
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED_RETRYABLE = "failed_retryable"
STATUS_FAILED_TERMINAL = "failed_terminal"


@dataclass(frozen=True)
class IdempotencyRecord:
    id: str
    key_value: str
    operation_type: str
    learner_id: str
    resource_id: str
    request_fingerprint: str
    status: str
    result_json: str | None
    attempt_number: int
    lease_expires_at: str | None
    created_at: str
    updated_at: str

    @property
    def result(self) -> str:
        return self.result_json or ""


@dataclass(frozen=True)
class ClaimOutcome:
    """Result of a claim attempt.

    Exactly one of the flags is meaningful per outcome:
      * ``acquired``  — this caller is the owner (new or reclaimed).
      * ``replay``    — an existing ``completed`` record is returned.
      * ``terminal``  — an existing ``failed_terminal`` record blocks the op.
      * ``conflict``  — an active ``pending`` claim is held by another owner.
    """

    record: IdempotencyRecord | None
    acquired: bool = False
    replay: bool = False
    terminal: bool = False
    conflict: bool = False


_COLS = [
    "id", "key_value", "operation_type", "learner_id", "resource_id",
    "request_fingerprint", "status", "result_json", "attempt_number",
    "lease_expires_at", "created_at", "updated_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> IdempotencyRecord:
    return IdempotencyRecord(
        id=row["id"],
        key_value=row["key_value"],
        operation_type=row["operation_type"],
        learner_id=row["learner_id"],
        resource_id=row["resource_id"],
        request_fingerprint=row["request_fingerprint"],
        status=row["status"],
        result_json=row["result_json"],
        attempt_number=row["attempt_number"],
        lease_expires_at=row["lease_expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_operation(conn: sqlite3.Connection, operation_key: str) -> IdempotencyRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM idempotency_requests WHERE key_value = ?",
        (operation_key,),
    ).fetchone()
    return _row_to_record(row) if row else None


def claim_operation(
    conn: sqlite3.Connection,
    identity: OperationIdentity,
    *,
    lease_ttl_seconds: int = 300,
    now: datetime | None = None,
) -> ClaimOutcome:
    """Atomically claim an operation.

    Must be called inside an active transaction (the caller runs
    ``BEGIN IMMEDIATE``). Never commits.
    """
    operation_key = identity.operation_key
    now_iso = _utcnow(now)
    lease = _lease_deadline(lease_ttl_seconds, now)
    new_id = f"idem_{secrets.token_urlsafe(16)}"

    # Atomic owner election: the UNIQUE(key_value) index makes this INSERT
    # succeed for exactly one caller. OR IGNORE turns the loser's INSERT into a
    # no-op (rowcount 0) instead of raising.
    cur = conn.execute(
        f"INSERT OR IGNORE INTO idempotency_requests ({_SELECT}) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            new_id, operation_key, identity.task_type,
            identity.learner_id, identity.resource_id, identity.fingerprint,
            STATUS_PENDING, None, 1, lease, now_iso, now_iso,
        ),
    )
    if cur.rowcount == 1:
        rec = get_operation(conn, operation_key)
        return ClaimOutcome(record=rec, acquired=True)

    # A row already exists. Decide based on its lifecycle state, using CAS
    # (status-guarded UPDATE + rowcount) for any reclaim so a concurrent owner
    # transition cannot be clobbered.
    existing = get_operation(conn, operation_key)
    if existing is None:  # pragma: no cover - defensive
        return ClaimOutcome(record=None, conflict=True)

    if existing.status == STATUS_COMPLETED:
        return ClaimOutcome(record=existing, replay=True)

    if existing.status == STATUS_FAILED_TERMINAL:
        return ClaimOutcome(record=existing, terminal=True)

    if existing.status == STATUS_PENDING:
        stale = bool(existing.lease_expires_at) and existing.lease_expires_at < now_iso
        if not stale:
            return ClaimOutcome(record=existing, conflict=True)
        # Reclaim a stale pending claim (crashed/expired owner).
        rc = conn.execute(
            "UPDATE idempotency_requests SET status = ?, attempt_number = attempt_number + 1, "
            "lease_expires_at = ?, updated_at = ? "
            "WHERE id = ? AND status = ? AND lease_expires_at < ?",
            (STATUS_PENDING, lease, now_iso, existing.id, STATUS_PENDING, now_iso),
        ).rowcount
        if rc == 1:
            return ClaimOutcome(record=get_operation(conn, operation_key), acquired=True)
        return ClaimOutcome(record=get_operation(conn, operation_key), conflict=True)

    if existing.status == STATUS_FAILED_RETRYABLE:
        # Reclaim a retryable failure for a new attempt.
        rc = conn.execute(
            "UPDATE idempotency_requests SET status = ?, attempt_number = attempt_number + 1, "
            "lease_expires_at = ?, result_json = NULL, updated_at = ? "
            "WHERE id = ? AND status = ?",
            (STATUS_PENDING, lease, now_iso, existing.id, STATUS_FAILED_RETRYABLE),
        ).rowcount
        if rc == 1:
            return ClaimOutcome(record=get_operation(conn, operation_key), acquired=True)
        return ClaimOutcome(record=get_operation(conn, operation_key), conflict=True)

    return ClaimOutcome(record=existing, conflict=True)  # pragma: no cover


def complete_operation(
    conn: sqlite3.Connection,
    operation_key: str,
    *,
    result_json: str,
    now: datetime | None = None,
) -> IdempotencyRecord | None:
    """Transition a claimed (pending) operation to completed with its result.

    CAS-guarded: only a ``pending`` row is completed. Must run inside the
    caller's transaction; never commits.
    """
    conn.execute(
        "UPDATE idempotency_requests SET status = ?, result_json = ?, updated_at = ? "
        "WHERE key_value = ? AND status = ?",
        (STATUS_COMPLETED, result_json, _utcnow(now), operation_key, STATUS_PENDING),
    )
    return get_operation(conn, operation_key)


def fail_operation(
    conn: sqlite3.Connection,
    operation_key: str,
    *,
    terminal: bool = False,
    now: datetime | None = None,
) -> IdempotencyRecord | None:
    """Transition a claimed (pending) operation to a failed state.

    ``terminal=False`` → ``failed_retryable`` (reclaimable by a later attempt).
    ``terminal=True``  → ``failed_terminal`` (never reclaimed automatically).
    CAS-guarded on ``pending``; never commits.
    """
    target = STATUS_FAILED_TERMINAL if terminal else STATUS_FAILED_RETRYABLE
    conn.execute(
        "UPDATE idempotency_requests SET status = ?, updated_at = ? "
        "WHERE key_value = ? AND status = ?",
        (target, _utcnow(now), operation_key, STATUS_PENDING),
    )
    return get_operation(conn, operation_key)
