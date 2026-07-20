"""Exercise and response repositories for Living Learning."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class ExerciseRecord:
    id: str
    lesson_id: str
    question: str
    options: list[str]
    correct_answer: str
    explanation: str
    difficulty: str
    sequence_order: int
    created_at: str


def _row_to_record(row: sqlite3.Row) -> ExerciseRecord:
    return ExerciseRecord(
        id=row["id"],
        lesson_id=row["lesson_id"],
        question=row["question"],
        options=json.loads(row["options"]) if row["options"] else [],
        correct_answer=row["correct_answer"],
        explanation=row["explanation"],
        difficulty=row["difficulty"],
        sequence_order=row["sequence_order"],
        created_at=row["created_at"],
    )


_COLS = [
    "id", "lesson_id", "question", "options", "correct_answer",
    "explanation", "difficulty", "sequence_order", "created_at",
]
_SELECT = ", ".join(_COLS)


def create_exercise(
    conn: sqlite3.Connection,
    *,
    lesson_id: str,
    question: str,
    options: list[str] | None = None,
    correct_answer: str = "",
    explanation: str = "",
    difficulty: str = "easy",
    sequence_order: int = 0,
    commit: bool = True,
) -> ExerciseRecord:
    now = _utcnow()
    exercise_id = f"ex_{secrets.token_urlsafe(16)}"
    options = options or []
    conn.execute(
        f"INSERT INTO exercises ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            exercise_id, lesson_id, question, json.dumps(options),
            correct_answer, explanation, difficulty, sequence_order, now,
        ),
    )
    if commit:
        conn.commit()
    return get_exercise_by_id(conn, exercise_id)  # type: ignore[return-value]


def get_exercise_by_id(conn: sqlite3.Connection, exercise_id: str) -> ExerciseRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM exercises WHERE id = ?", (exercise_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_exercises_by_lesson(
    conn: sqlite3.Connection, lesson_id: str
) -> list[ExerciseRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM exercises WHERE lesson_id = ? ORDER BY sequence_order",
        (lesson_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


@dataclass(frozen=True)
class ExerciseResponseRecord:
    id: str
    exercise_id: str
    learner_id: str
    selected_answer: str
    is_correct: bool
    responded_at: str


def _response_row_to_record(row: sqlite3.Row) -> ExerciseResponseRecord:
    return ExerciseResponseRecord(
        id=row["id"],
        exercise_id=row["exercise_id"],
        learner_id=row["learner_id"],
        selected_answer=row["selected_answer"],
        is_correct=bool(row["is_correct"]),
        responded_at=row["responded_at"],
    )


def record_exercise_response(
    conn: sqlite3.Connection,
    *,
    exercise_id: str,
    learner_id: str,
    selected_answer: str,
    is_correct: bool,
    commit: bool = True,
) -> ExerciseResponseRecord:
    now = _utcnow()
    response_id = f"resp_{secrets.token_urlsafe(16)}"
    conn.execute(
        "INSERT INTO exercise_responses (id, exercise_id, learner_id, selected_answer, is_correct, responded_at) VALUES (?,?,?,?,?,?)",
        (response_id, exercise_id, learner_id, selected_answer, int(is_correct), now),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT * FROM exercise_responses WHERE id = ?", (response_id,)
    ).fetchone()
    return _response_row_to_record(row)  # type: ignore[return-value]


def get_responses_by_learner(
    conn: sqlite3.Connection, learner_id: str
) -> list[ExerciseResponseRecord]:
    rows = conn.execute(
        "SELECT * FROM exercise_responses WHERE learner_id = ? ORDER BY responded_at",
        (learner_id,),
    ).fetchall()
    return [_response_row_to_record(r) for r in rows]


@dataclass(frozen=True)
class ComprehensionResponseRecord:
    id: str
    lesson_id: str
    learner_id: str
    understood: bool
    difficulty_rating: int
    free_text: str
    response_id: str
    responded_at: str


def _comp_row_to_record(row: sqlite3.Row) -> ComprehensionResponseRecord:
    return ComprehensionResponseRecord(
        id=row["id"],
        lesson_id=row["lesson_id"],
        learner_id=row["learner_id"],
        understood=bool(row["understood"]),
        difficulty_rating=row["difficulty_rating"],
        free_text=row["free_text"],
        response_id=row["response_id"],
        responded_at=row["responded_at"],
    )


def record_comprehension_response(
    conn: sqlite3.Connection,
    *,
    lesson_id: str,
    learner_id: str,
    understood: bool = True,
    difficulty_rating: int = 3,
    free_text: str = "",
    commit: bool = True,
) -> ComprehensionResponseRecord:
    now = _utcnow()
    record_id = f"comp_{secrets.token_urlsafe(16)}"
    response_id_val = f"resp_{secrets.token_urlsafe(16)}"
    conn.execute(
        "INSERT INTO comprehension_responses (id, lesson_id, learner_id, understood, difficulty_rating, free_text, response_id, responded_at) VALUES (?,?,?,?,?,?,?,?)",
        (record_id, lesson_id, learner_id, int(understood), difficulty_rating, free_text, response_id_val, now),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT * FROM comprehension_responses WHERE id = ?", (record_id,)
    ).fetchone()
    return _comp_row_to_record(row)  # type: ignore[return-value]