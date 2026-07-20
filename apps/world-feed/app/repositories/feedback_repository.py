import json
import sqlite3
from dataclasses import dataclass

from app.db import transaction_scope
from app.domain.models import FeedbackInput
from app.repositories.common import now_utc_iso


@dataclass(frozen=True)
class FeedbackRecord:
    id: str
    reader_id: str
    prior_brief_id: str | None
    idempotency_key: str
    action: str
    detail: str
    applied_to_brief_id: str | None
    created_at: str


_FEEDBACK_COLS = [
    "id", "reader_id", "prior_brief_id", "idempotency_key", "action",
    "detail", "applied_to_brief_id", "created_at",
]
_FEEDBACK_SELECT = ", ".join(_FEEDBACK_COLS)


def _row_to_record(row: sqlite3.Row) -> FeedbackRecord:
    return FeedbackRecord(
        id=row["id"],
        reader_id=row["reader_id"],
        prior_brief_id=row["prior_brief_id"],
        idempotency_key=row["idempotency_key"],
        action=row["action"],
        detail=row["detail"],
        applied_to_brief_id=row["applied_to_brief_id"],
        created_at=row["created_at"],
    )


def persist_feedback(
    conn: sqlite3.Connection, feedback: FeedbackInput
) -> FeedbackRecord:
    """Persist feedback exactly once.

    The ``idempotency_key`` UNIQUE constraint guarantees a duplicate submit
    returns the original record instead of applying feedback twice.
    """
    now = now_utc_iso()
    with transaction_scope(conn):
        existing = conn.execute(
            "SELECT id FROM feedback WHERE idempotency_key = ?",
            (feedback.idempotency_key,),
        ).fetchone()
        if existing is not None:
            return get_feedback_by_id(conn, existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO feedback (
                id, reader_id, prior_brief_id, idempotency_key, action,
                detail, applied_to_brief_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                feedback.feedback_id,
                feedback.reader_id,
                feedback.prior_brief_id,
                feedback.idempotency_key,
                feedback.action.value,
                feedback.detail,
                now,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("failed to insert feedback record")
        return get_feedback_by_id(conn, feedback.feedback_id)


def get_feedback_by_id(
    conn: sqlite3.Connection, feedback_id: str
) -> FeedbackRecord | None:
    row = conn.execute(
        f"SELECT {_FEEDBACK_SELECT} FROM feedback WHERE id = ?",
        (feedback_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_feedback_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> FeedbackRecord | None:
    row = conn.execute(
        f"SELECT {_FEEDBACK_SELECT} FROM feedback WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    return _row_to_record(row) if row else None


def mark_applied(
    conn: sqlite3.Connection, feedback_id: str, brief_id: str
) -> FeedbackRecord | None:
    """Mark feedback applied to a brief, exactly once.

    If already applied (non-NULL), the existing target is preserved and no
    second application occurs.
    """
    with transaction_scope(conn):
        existing = get_feedback_by_id(conn, feedback_id)
        if existing is None:
            return None
        if existing.applied_to_brief_id is not None:
            return existing
        conn.execute(
            "UPDATE feedback SET applied_to_brief_id = ? WHERE id = ?",
            (brief_id, feedback_id),
        )
        return get_feedback_by_id(conn, feedback_id)


def list_feedback_for_reader(
    conn: sqlite3.Connection, reader_id: str
) -> list[FeedbackRecord]:
    rows = conn.execute(
        f"SELECT {_FEEDBACK_SELECT} FROM feedback WHERE reader_id = ? "
        "ORDER BY created_at, id",
        (reader_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
