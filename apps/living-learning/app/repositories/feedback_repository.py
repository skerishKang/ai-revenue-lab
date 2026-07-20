"""Feedback repository for Living Learning with exactly-once semantics."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "[CARD_REDACTED]"),
    (r"\b\d{3}[\s-]?\d{3,4}[\s-]?\d{4}\b", "[PHONE_REDACTED]"),
    (r"\b\d{6}[\s-]?\d{7}\b", "[ID_REDACTED]"),
    (r"\b(sk-|ak-|pk-)[A-Za-z0-9]{20,}\b", "[API_KEY_REDACTED]"),
    (r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+", "[PASSWORD_REDACTED]"),
    (r"(?i)\b(token|secret|bearer)\s*[:=]\s*\S+", "[TOKEN_REDACTED]"),
]


def _sanitize_free_text(text: str) -> str:
    result = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = re.sub(pattern, replacement, result)
    return result


@dataclass(frozen=True)
class FeedbackRecord:
    id: str
    lesson_id: str
    learner_id: str
    lesson_generation: int
    direction_choices: list[str]
    free_text: str
    applied_status: str
    applied_to_lesson_id: str
    created_at: str


def _row_to_record(row: sqlite3.Row) -> FeedbackRecord:
    return FeedbackRecord(
        id=row["id"],
        lesson_id=row["lesson_id"],
        learner_id=row["learner_id"],
        lesson_generation=row["lesson_generation"],
        direction_choices=json.loads(row["direction_choices"]) if row["direction_choices"] else [],
        free_text=row["free_text"],
        applied_status=row["applied_status"],
        applied_to_lesson_id=row["applied_to_lesson_id"] or "",
        created_at=row["created_at"],
    )


_COLS = [
    "id", "lesson_id", "learner_id", "lesson_generation", "direction_choices",
    "free_text", "applied_status", "applied_to_lesson_id", "created_at",
]
_SELECT = ", ".join(_COLS)


def create_feedback(
    conn: sqlite3.Connection,
    *,
    lesson_id: str,
    learner_id: str,
    lesson_generation: int = 1,
    direction_choices: list[str] | None = None,
    free_text: str = "",
    commit: bool = True,
) -> FeedbackRecord:
    existing = get_feedback_by_lesson_and_generation(
        conn, lesson_id, lesson_generation
    )
    if existing:
        return existing

    now = _utcnow()
    feedback_id = f"fb_{secrets.token_urlsafe(16)}"
    direction_choices = direction_choices or []
    sanitized_text = _sanitize_free_text(free_text)
    conn.execute(
        f"INSERT INTO feedback ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            feedback_id, lesson_id, learner_id, lesson_generation,
            json.dumps(direction_choices), sanitized_text, "not_applied", "", now,
        ),
    )
    if commit:
        conn.commit()
    return get_feedback_by_id(conn, feedback_id)  # type: ignore[return-value]


def get_feedback_by_id(conn: sqlite3.Connection, feedback_id: str) -> FeedbackRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM feedback WHERE id = ?", (feedback_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_feedback_by_lesson(
    conn: sqlite3.Connection, lesson_id: str
) -> list[FeedbackRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM feedback WHERE lesson_id = ? ORDER BY created_at",
        (lesson_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_feedback_by_lesson_and_generation(
    conn: sqlite3.Connection, lesson_id: str, lesson_generation: int
) -> FeedbackRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM feedback WHERE lesson_id = ? AND lesson_generation = ?",
        (lesson_id, lesson_generation),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_unapplied_feedback_for_lesson(
    conn: sqlite3.Connection, lesson_id: str
) -> list[FeedbackRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM feedback WHERE lesson_id = ? AND applied_status = 'not_applied'",
        (lesson_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def mark_feedback_applied(
    conn: sqlite3.Connection,
    feedback_id: str,
    applied_to_lesson_id: str,
    applied_status: str = "applied_to_second",
    commit: bool = True,
) -> bool:
    cur = conn.execute(
        "UPDATE feedback SET applied_status = ?, applied_to_lesson_id = ? WHERE id = ? AND applied_status = 'not_applied'",
        (applied_status, applied_to_lesson_id, feedback_id),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0


def is_feedback_applied(conn: sqlite3.Connection, feedback_id: str) -> bool:
    row = conn.execute(
        "SELECT applied_status FROM feedback WHERE id = ?", (feedback_id,)
    ).fetchone()
    return row is not None and row["applied_status"] != "not_applied"


def is_feedback_for_learner(conn: sqlite3.Connection, feedback_id: str, learner_id: str) -> bool:
    row = conn.execute(
        "SELECT learner_id FROM feedback WHERE id = ?", (feedback_id,)
    ).fetchone()
    return row is not None and row["learner_id"] == learner_id