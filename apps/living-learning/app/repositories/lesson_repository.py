"""Lesson repository for Living Learning."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class LessonRecord:
    id: str
    learner_id: str
    concept_id: str
    lesson_number: int
    prior_lesson_id: str
    generation_status: str
    publication_state: str
    lesson_plan_json: str
    lesson_content_json: str
    adaptation_summary: str
    created_at: str
    updated_at: str


def _row_to_record(row: sqlite3.Row) -> LessonRecord:
    return LessonRecord(
        id=row["id"],
        learner_id=row["learner_id"],
        concept_id=row["concept_id"],
        lesson_number=row["lesson_number"],
        prior_lesson_id=row["prior_lesson_id"] or "",
        generation_status=row["generation_status"],
        publication_state=row["publication_state"],
        lesson_plan_json=row["lesson_plan_json"],
        lesson_content_json=row["lesson_content_json"],
        adaptation_summary=row["adaptation_summary"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_COLS = [
    "id", "learner_id", "concept_id", "lesson_number", "prior_lesson_id",
    "generation_status", "publication_state", "lesson_plan_json",
    "lesson_content_json", "adaptation_summary", "created_at", "updated_at",
]
_SELECT = ", ".join(_COLS)


def create_lesson(
    conn: sqlite3.Connection,
    *,
    learner_id: str,
    concept_id: str,
    lesson_number: int = 1,
    prior_lesson_id: str = "",
    generation_status: str = "input_received",
    lesson_plan_json: str = "{}",
    lesson_content_json: str = "{}",
    adaptation_summary: str = "",
    commit: bool = True,
) -> LessonRecord:
    now = _utcnow()
    lesson_id = f"lesson_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO lessons ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            lesson_id, learner_id, concept_id, lesson_number, prior_lesson_id,
            generation_status, "pending", lesson_plan_json, lesson_content_json,
            adaptation_summary, now, now,
        ),
    )
    if commit:
        conn.commit()
    return get_lesson_by_id(conn, lesson_id)  # type: ignore[return-value]


def get_lesson_by_id(conn: sqlite3.Connection, lesson_id: str) -> LessonRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM lessons WHERE id = ?", (lesson_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_lessons_by_learner(
    conn: sqlite3.Connection, learner_id: str
) -> list[LessonRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM lessons WHERE learner_id = ? ORDER BY created_at",
        (learner_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_lessons_by_concept(
    conn: sqlite3.Connection, concept_id: str
) -> list[LessonRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM lessons WHERE concept_id = ? ORDER BY lesson_number",
        (concept_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def update_lesson_status(
    conn: sqlite3.Connection,
    lesson_id: str,
    *,
    generation_status: str | None = None,
    publication_state: str | None = None,
    lesson_plan_json: str | None = None,
    lesson_content_json: str | None = None,
    adaptation_summary: str | None = None,
    commit: bool = True,
) -> LessonRecord | None:
    updates = []
    params = []
    if generation_status is not None:
        updates.append("generation_status = ?")
        params.append(generation_status)
    if publication_state is not None:
        updates.append("publication_state = ?")
        params.append(publication_state)
    if lesson_plan_json is not None:
        updates.append("lesson_plan_json = ?")
        params.append(lesson_plan_json)
    if lesson_content_json is not None:
        updates.append("lesson_content_json = ?")
        params.append(lesson_content_json)
    if adaptation_summary is not None:
        updates.append("adaptation_summary = ?")
        params.append(adaptation_summary)

    if updates:
        updates.append("updated_at = ?")
        params.append(_utcnow())
        params.append(lesson_id)
        conn.execute(
            f"UPDATE lessons SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        if commit:
            conn.commit()
    return get_lesson_by_id(conn, lesson_id)


def close_lesson(conn: sqlite3.Connection, lesson_id: str, commit: bool = True) -> LessonRecord | None:
    return update_lesson_status(
        conn, lesson_id,
        publication_state="closed",
        commit=commit,
    )


def reopen_lesson(conn: sqlite3.Connection, lesson_id: str, commit: bool = True) -> LessonRecord | None:
    lesson = get_lesson_by_id(conn, lesson_id)
    if not lesson:
        return None
    new_lesson = create_lesson(
        conn,
        learner_id=lesson.learner_id,
        concept_id=lesson.concept_id,
        lesson_number=lesson.lesson_number + 1,
        prior_lesson_id=lesson_id,
        commit=commit,
    )
    return new_lesson


@dataclass(frozen=True)
class LearnerSessionRecord:
    session_id: str
    learner_id: str
    curriculum_id: str
    current_lesson_sequence: int
    last_activity_at: str
    created_at: str


def _session_row_to_record(row: sqlite3.Row) -> LearnerSessionRecord:
    return LearnerSessionRecord(
        session_id=row["session_id"],
        learner_id=row["learner_id"],
        curriculum_id=row["curriculum_id"],
        current_lesson_sequence=row["current_lesson_sequence"],
        last_activity_at=row["last_activity_at"],
        created_at=row["created_at"],
    )


def create_learner_session(
    conn: sqlite3.Connection,
    *,
    learner_id: str,
    curriculum_id: str,
    commit: bool = True,
) -> LearnerSessionRecord:
    session_id = f"sess_{secrets.token_urlsafe(16)}"
    now = _utcnow()
    conn.execute(
        """INSERT INTO learner_sessions (session_id, learner_id, curriculum_id, current_lesson_sequence, last_activity_at, created_at)
        VALUES (?, ?, ?, 0, ?, ?)""",
        (session_id, learner_id, curriculum_id, now, now),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT * FROM learner_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return _session_row_to_record(row)  # type: ignore[return-value]


def update_lesson_content(
    conn: sqlite3.Connection,
    lesson_id: str,
    *,
    lesson_plan_json: str | None = None,
    lesson_content_json: str | None = None,
    commit: bool = True,
) -> LessonRecord | None:
    updates = []
    params = []
    if lesson_plan_json is not None:
        updates.append("lesson_plan_json = ?")
        params.append(lesson_plan_json)
    if lesson_content_json is not None:
        updates.append("lesson_content_json = ?")
        params.append(lesson_content_json)

    if updates:
        updates.append("updated_at = ?")
        params.append(_utcnow())
        params.append(lesson_id)
        conn.execute(
            f"UPDATE lessons SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        if commit:
            conn.commit()
    return get_lesson_by_id(conn, lesson_id)