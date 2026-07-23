"""Operator review workflow: CAS state transitions + audit trail.

Generation and publication are separate concerns:

* ``generation_status`` — lifecycle of content generation (``pending_review``,
  ``generation_failed``, ...).
* ``publication_state`` — delivery gate (``pending`` → ``published``/``rejected``).

Approve/reject are atomic compare-and-set transitions guarded on
``generation_status='pending_review' AND publication_state='pending'``. Exactly
one concurrent reviewer wins; the loser (and any re-transition of an already
decided lesson) gets ``ReviewStateConflictError``. The state change and the
audit row are written in one transaction.
"""

from __future__ import annotations

import secrets
import sqlite3

from app.pipeline.errors import ReviewStateConflictError
from app.repositories.lesson_repository import LessonRecord, _row_to_record


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _transition(
    conn: sqlite3.Connection,
    lesson_id: str,
    target_publication_state: str,
    action: str,
    external_identity_id: str,
    reason: str,
) -> LessonRecord:
    """Atomically transition publication_state and record an audit event.

    CAS: only a lesson that is ``pending_review`` and still ``pending`` moves.
    ``rowcount != 1`` => conflict (already decided, not generated, or a
    concurrent reviewer won).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        rc = conn.execute(
            "UPDATE lessons SET publication_state = ?, updated_at = ? "
            "WHERE id = ? AND generation_status = 'pending_review' AND publication_state = 'pending'",
            (target_publication_state, _utcnow(), lesson_id),
        ).rowcount
        if rc != 1:
            raise ReviewStateConflictError(lesson_id)

        conn.execute(
            "INSERT INTO lesson_review_events (id, lesson_id, external_identity_id, action, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"rev_{secrets.token_urlsafe(16)}",
                lesson_id,
                external_identity_id,
                action,
                reason,
                _utcnow(),
            ),
        )
        row = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        conn.commit()
        return _row_to_record(row)
    except Exception:
        conn.rollback()
        raise


def approve_lesson(
    conn: sqlite3.Connection,
    lesson_id: str,
    *,
    external_identity_id: str,
    reason: str = "",
) -> LessonRecord:
    return _transition(conn, lesson_id, "published", "approved", external_identity_id, reason)


def reject_lesson(
    conn: sqlite3.Connection,
    lesson_id: str,
    *,
    external_identity_id: str,
    reason: str = "",
) -> LessonRecord:
    return _transition(conn, lesson_id, "rejected", "rejected", external_identity_id, reason)


def get_review_events(conn: sqlite3.Connection, lesson_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM lesson_review_events WHERE lesson_id = ? ORDER BY created_at",
        (lesson_id,),
    ).fetchall()
