"""Feedback repository for Living Travel."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class FeedbackRecord:
    id: str
    traveler_id: str
    edition_id: str
    direction_choices: list[str]
    selected_section_id: str
    free_text: str
    applied_to_next_edition: bool
    created_at: str


def _row_to_record(row: sqlite3.Row) -> FeedbackRecord:
    return FeedbackRecord(
        id=row["id"],
        traveler_id=row["traveler_id"],
        edition_id=row["edition_id"],
        direction_choices=json.loads(row["direction_choices"]) if row["direction_choices"] else [],
        selected_section_id=row["selected_section_id"],
        free_text=row["free_text"],
        applied_to_next_edition=bool(row["applied_to_next_edition"]),
        created_at=row["created_at"],
    )


_COLS = [
    "id", "traveler_id", "edition_id", "direction_choices",
    "selected_section_id", "free_text", "applied_to_next_edition", "created_at",
]
_SELECT = ", ".join(_COLS)


def create_feedback(
    conn: sqlite3.Connection,
    *,
    traveler_id: str,
    edition_id: str,
    direction_choices: list[str] | None = None,
    selected_section_id: str = "",
    free_text: str = "",
) -> FeedbackRecord:
    now = _utcnow()
    feedback_id = f"fb_{secrets.token_urlsafe(16)}"
    direction_choices = direction_choices or []
    conn.execute(
        f"INSERT INTO feedback ({_SELECT}) VALUES (?,?,?,?,?,?,?,?)",
        (
            feedback_id, traveler_id, edition_id,
            json.dumps(direction_choices), selected_section_id, free_text, 0, now,
        ),
    )
    conn.commit()
    return get_feedback_by_id(conn, feedback_id)  # type: ignore[return-value]


def get_feedback_by_id(conn: sqlite3.Connection, feedback_id: str) -> FeedbackRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM feedback WHERE id = ?", (feedback_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_feedback_by_edition(conn: sqlite3.Connection, edition_id: str) -> list[FeedbackRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM feedback WHERE edition_id = ? ORDER BY created_at",
        (edition_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_unapplied_feedback_for_traveler(
    conn: sqlite3.Connection, traveler_id: str
) -> list[FeedbackRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM feedback WHERE traveler_id = ? AND applied_to_next_edition = 0",
        (traveler_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def mark_feedback_applied(conn: sqlite3.Connection, feedback_id: str) -> bool:
    cur = conn.execute(
        "UPDATE feedback SET applied_to_next_edition = 1 WHERE id = ?",
        (feedback_id,),
    )
    conn.commit()
    return cur.rowcount > 0
