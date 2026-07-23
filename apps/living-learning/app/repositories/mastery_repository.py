"""Mastery repository for Living Learning."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class MasteryRecord:
    id: str
    learner_id: str
    concept_id: str
    mastery_level: str
    practice_count: int
    correct_count: int
    last_practiced_at: str
    updated_at: str


def _row_to_record(row: sqlite3.Row) -> MasteryRecord:
    return MasteryRecord(
        id=row["id"],
        learner_id=row["learner_id"],
        concept_id=row["concept_id"],
        mastery_level=row["mastery_level"],
        practice_count=row["practice_count"],
        correct_count=row["correct_count"],
        last_practiced_at=row["last_practiced_at"],
        updated_at=row["updated_at"],
    )


_COLS = [
    "id", "learner_id", "concept_id", "mastery_level",
    "practice_count", "correct_count", "last_practiced_at", "updated_at",
]
_SELECT = ", ".join(_COLS)


def upsert_mastery(
    conn: sqlite3.Connection,
    *,
    learner_id: str,
    concept_id: str,
    mastery_level: str = "unknown",
    practice_increment: int = 0,
    correct_increment: int = 0,
    commit: bool = True,
) -> MasteryRecord:
    now = _utcnow()
    existing = conn.execute(
        "SELECT * FROM learner_mastery WHERE learner_id = ? AND concept_id = ?",
        (learner_id, concept_id),
    ).fetchone()

    if existing:
        new_practice = existing["practice_count"] + practice_increment
        new_correct = existing["correct_count"] + correct_increment
        if mastery_level != "unknown":
            new_level = mastery_level
        elif new_practice >= 5 and new_correct >= 4:
            new_level = "proficient"
        elif new_practice >= 3 and new_correct >= 2:
            new_level = "developing"
        elif new_practice > 0:
            new_level = "beginning"
        else:
            new_level = "unknown"

        conn.execute(
            """UPDATE learner_mastery SET
                mastery_level = ?, practice_count = ?, correct_count = ?,
                last_practiced_at = ?, updated_at = ?
            WHERE learner_id = ? AND concept_id = ?""",
            (new_level, new_practice, new_correct, now, now, learner_id, concept_id),
        )
    else:
        mastery_id = f"mstr_{secrets.token_urlsafe(16)}"
        if mastery_level != "unknown":
            new_level = mastery_level
        elif practice_increment >= 5 and correct_increment >= 4:
            new_level = "proficient"
        elif practice_increment >= 3 and correct_increment >= 2:
            new_level = "developing"
        elif practice_increment > 0:
            new_level = "beginning"
        else:
            new_level = "unknown"

        conn.execute(
            f"INSERT INTO learner_mastery ({_SELECT}) VALUES (?,?,?,?,?,?,?,?)",
            (mastery_id, learner_id, concept_id, new_level, practice_increment, correct_increment, now, now),
        )

    if commit:
        conn.commit()

    row = conn.execute(
        "SELECT * FROM learner_mastery WHERE learner_id = ? AND concept_id = ?",
        (learner_id, concept_id),
    ).fetchone()
    return _row_to_record(row)  # type: ignore[return-value]


def get_mastery(
    conn: sqlite3.Connection, learner_id: str, concept_id: str
) -> MasteryRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM learner_mastery WHERE learner_id = ? AND concept_id = ?",
        (learner_id, concept_id),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_all_mastery_for_learner(
    conn: sqlite3.Connection, learner_id: str
) -> list[MasteryRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM learner_mastery WHERE learner_id = ?",
        (learner_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]