"""Learner repository for Living Learning."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.models import SyntheticLearnerProfile


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class LearnerRecord:
    id: str
    display_name: str
    preferred_language: str
    topic: str
    target_duration_minutes: int
    pacing_feedback_style: str
    example_preference: str
    theory_density: str
    review_question_count: int
    jargon_level: str
    interests: list[str]
    exclusions: list[str]
    status: str
    created_at: str
    updated_at: str


def _row_to_record(row: sqlite3.Row) -> LearnerRecord:
    return LearnerRecord(
        id=row["id"],
        display_name=row["display_name"],
        preferred_language=row["preferred_language"],
        topic=row["topic"],
        target_duration_minutes=row["target_duration_minutes"],
        pacing_feedback_style=row["pacing_feedback_style"],
        example_preference=row["example_preference"],
        theory_density=row["theory_density"],
        review_question_count=row["review_question_count"],
        jargon_level=row["jargon_level"],
        interests=json.loads(row["interests"]) if row["interests"] else [],
        exclusions=json.loads(row["exclusions"]) if row["exclusions"] else [],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_COLS = [
    "id", "display_name", "preferred_language", "topic",
    "target_duration_minutes", "pacing_feedback_style", "example_preference",
    "theory_density", "review_question_count", "jargon_level",
    "interests", "exclusions", "status", "created_at", "updated_at",
]
_SELECT = ", ".join(_COLS)


def create_learner(
    conn: sqlite3.Connection,
    *,
    topic: str,
    display_name: str = "학습자",
    preferred_language: str = "ko",
    target_duration_minutes: int = 10,
    pacing_feedback_style: str = "moderate",
    example_preference: str = "code_first",
    theory_density: str = "balanced",
    review_question_count: int = 3,
    jargon_level: str = "simplified",
    interests: list[str] | None = None,
    exclusions: list[str] | None = None,
    commit: bool = True,
) -> LearnerRecord:
    now = _utcnow()
    learner_id = f"lr_{secrets.token_urlsafe(16)}"
    interests = interests or []
    exclusions = exclusions or []
    conn.execute(
        f"INSERT INTO learners ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            learner_id, display_name, preferred_language, topic,
            target_duration_minutes, pacing_feedback_style, example_preference,
            theory_density, review_question_count, jargon_level,
            json.dumps(interests), json.dumps(exclusions), "active", now, now,
        ),
    )
    if commit:
        conn.commit()
    return get_learner_by_id(conn, learner_id)  # type: ignore[return-value]


def get_learner_by_id(conn: sqlite3.Connection, learner_id: str) -> LearnerRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM learners WHERE id = ?", (learner_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def update_learner_preferences(
    conn: sqlite3.Connection,
    learner_id: str,
    *,
    pacing_feedback_style: str | None = None,
    example_preference: str | None = None,
    theory_density: str | None = None,
    review_question_count: int | None = None,
    jargon_level: str | None = None,
    commit: bool = True,
) -> LearnerRecord | None:
    updates = []
    params = []
    if pacing_feedback_style is not None:
        updates.append("pacing_feedback_style = ?")
        params.append(pacing_feedback_style)
    if example_preference is not None:
        updates.append("example_preference = ?")
        params.append(example_preference)
    if theory_density is not None:
        updates.append("theory_density = ?")
        params.append(theory_density)
    if review_question_count is not None:
        updates.append("review_question_count = ?")
        params.append(review_question_count)
    if jargon_level is not None:
        updates.append("jargon_level = ?")
        params.append(jargon_level)

    if updates:
        updates.append("updated_at = ?")
        params.append(_utcnow())
        params.append(learner_id)
        conn.execute(
            f"UPDATE learners SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        if commit:
            conn.commit()
    return get_learner_by_id(conn, learner_id)