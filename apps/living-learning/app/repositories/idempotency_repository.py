"""Concurrent idempotency repository with atomic claim/complete/fail pattern."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ttl_seconds(seconds: int) -> str:
    from datetime import timedelta
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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

    # Legacy compatibility properties
    @property
    def lesson_id(self) -> str:
        return self.resource_id

    @property
    def result(self) -> str:
        return self.result_json or ''


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


_COLS = [
    "id", "key_value", "operation_type", "learner_id", "resource_id",
    "request_fingerprint", "status", "result_json", "attempt_number",
    "lease_expires_at", "created_at", "updated_at",
]
_SELECT = ", ".join(_COLS)


def claim_idempotency_request(
    conn: sqlite3.Connection,
    key_value: str,
    *,
    operation_type: str = "lesson_generation",
    learner_id: str = "",
    resource_id: str = "",
    request_fingerprint: str = "",
    lease_ttl_seconds: int = 300,
    commit: bool = True,
) -> IdempotencyRecord | None:
    """Atomically claim an idempotency request.

    Returns the claimed record if successful, None if active pending conflict.
    On completed: returns existing completed record (replay).
    On failed/stale: reclaims the row.
    On new: inserts pending row.
    """
    # Check for existing record (read-only, no transaction needed for check)
    existing = conn.execute(
        f"SELECT {_SELECT} FROM idempotency_requests WHERE key_value = ?",
        (key_value,),
    ).fetchone()

    if existing is not None:
        rec = _row_to_record(existing)
        if rec.status == "completed":
            return rec
        elif rec.status == "pending":
            if rec.lease_expires_at and rec.lease_expires_at < _utcnow():
                # Reclaim stale pending
                conn.execute(
                    "UPDATE idempotency_requests SET status = 'pending', lease_expires_at = ?, updated_at = ? WHERE id = ?",
                    (_ttl_seconds(lease_ttl_seconds), _utcnow(), rec.id),
                )
                if commit:
                    conn.commit()
                return _row_to_record(conn.execute(
                    f"SELECT {_SELECT} FROM idempotency_requests WHERE id = ?", (rec.id,)
                ).fetchone())
            else:
                # Active pending - reject
                return None
        elif rec.status == "failed":
            conn.execute(
                "UPDATE idempotency_requests SET status = 'pending', attempt_number = attempt_number + 1, lease_expires_at = ?, updated_at = ? WHERE id = ?",
                (_ttl_seconds(lease_ttl_seconds), _utcnow(), rec.id),
            )
            if commit:
                conn.commit()
            return _row_to_record(conn.execute(
                f"SELECT {_SELECT} FROM idempotency_requests WHERE id = ?", (rec.id,)
            ).fetchone())

    # New request: insert pending
    new_id = f"idem_{secrets.token_urlsafe(16)}"
    try:
        conn.execute(
            f"INSERT INTO idempotency_requests ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                new_id, key_value, operation_type,
                learner_id or '', resource_id or key_value,
                request_fingerprint or key_value, "pending", None, 1,
                _ttl_seconds(lease_ttl_seconds), _utcnow(), _utcnow(),
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.IntegrityError:
        # Concurrent insert occurred, another request claimed it
        if commit:
            conn.rollback()
        return None

    return _row_to_record(conn.execute(
        f"SELECT {_SELECT} FROM idempotency_requests WHERE id = ?", (new_id,)
    ).fetchone())


def complete_idempotency_request(
    conn: sqlite3.Connection,
    key_value: str,
    resource_id: str = "",
    *,
    result: str = "",
    result_json: str | None = None,
    commit: bool = True,
) -> IdempotencyRecord | None:
    """Mark an idempotency request as completed with result."""
    actual_result = result_json or result or '{}'
    target_resource = resource_id or key_value
    conn.execute(
        "UPDATE idempotency_requests SET status = 'completed', result_json = ?, updated_at = ? WHERE key_value = ? AND resource_id = ? AND status = 'pending'",
        (actual_result, _utcnow(), key_value, target_resource),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        f"SELECT {_SELECT} FROM idempotency_requests WHERE key_value = ? AND resource_id = ?",
        (key_value, target_resource),
    ).fetchone()
    return _row_to_record(row) if row else None


def fail_idempotency_request(
    conn: sqlite3.Connection,
    key_value: str,
    *,
    commit: bool = True,
) -> IdempotencyRecord | None:
    """Mark an idempotency request as failed."""
    conn.execute(
        "UPDATE idempotency_requests SET status = 'failed', updated_at = ? WHERE key_value = ?",
        (_utcnow(), key_value),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        f"SELECT {_SELECT} FROM idempotency_requests WHERE key_value = ?",
        (key_value,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_idempotency_result(
    conn: sqlite3.Connection,
    key_value: str,
    operation_type: str = "",
    resource_id: str = "",
) -> IdempotencyRecord | None:
    """Get an idempotency record by key."""
    row = conn.execute(
        f"SELECT {_SELECT} FROM idempotency_requests WHERE key_value = ?",
        (key_value,),
    ).fetchone()
    return _row_to_record(row) if row else None


# Legacy compatibility
def check_idempotency_key(conn: sqlite3.Connection, key_value: str) -> IdempotencyRecord | None:
    """Legacy: check if any record exists for this key."""
    return get_idempotency_result(conn, key_value)


def store_idempotency_key(
    conn: sqlite3.Connection,
    key_value: str,
    lesson_id: str = "",
    result: str = "",
    *,
    commit: bool = True,
) -> IdempotencyRecord | None:
    """Legacy: store an idempotency key."""
    return complete_idempotency_request(conn, key_value, lesson_id, result=result, commit=commit)
