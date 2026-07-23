"""Learner history: learning goals and immutable diagnostic snapshots.

Goals are superseded (not deleted) when replaced, preserving history. Diagnostic
snapshots are immutable append-only records that adaptation decisions can
reference for provenance.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class LearningGoalRecord:
    id: str
    learner_id: str
    goal_text: str
    status: str
    created_at: str
    superseded_at: str | None


@dataclass(frozen=True)
class DiagnosticSnapshotRecord:
    id: str
    learner_id: str
    coding_experience: str
    explanation_preference: str
    theory_practice_balance: str
    derived_difficulty: str
    created_at: str


def record_goal(
    conn: sqlite3.Connection,
    *,
    learner_id: str,
    goal_text: str,
    commit: bool = False,
) -> LearningGoalRecord:
    """Create a new active goal, superseding any currently-active goal."""
    now = _utcnow()
    conn.execute(
        "UPDATE learning_goals SET status = 'superseded', superseded_at = ? "
        "WHERE learner_id = ? AND status = 'active'",
        (now, learner_id),
    )
    goal_id = f"goal_{secrets.token_urlsafe(16)}"
    conn.execute(
        "INSERT INTO learning_goals (id, learner_id, goal_text, status, created_at) "
        "VALUES (?, ?, ?, 'active', ?)",
        (goal_id, learner_id, goal_text, now),
    )
    if commit:
        conn.commit()
    row = conn.execute("SELECT * FROM learning_goals WHERE id = ?", (goal_id,)).fetchone()
    return _goal_row(row)


def get_goals(conn: sqlite3.Connection, learner_id: str) -> list[LearningGoalRecord]:
    rows = conn.execute(
        "SELECT * FROM learning_goals WHERE learner_id = ? ORDER BY created_at", (learner_id,)
    ).fetchall()
    return [_goal_row(r) for r in rows]


def get_active_goal(conn: sqlite3.Connection, learner_id: str) -> LearningGoalRecord | None:
    row = conn.execute(
        "SELECT * FROM learning_goals WHERE learner_id = ? AND status = 'active'", (learner_id,)
    ).fetchone()
    return _goal_row(row) if row else None


def _goal_row(row: sqlite3.Row) -> LearningGoalRecord:
    return LearningGoalRecord(
        id=row["id"],
        learner_id=row["learner_id"],
        goal_text=row["goal_text"],
        status=row["status"],
        created_at=row["created_at"],
        superseded_at=row["superseded_at"],
    )


def record_diagnostic_snapshot(
    conn: sqlite3.Connection,
    *,
    learner_id: str,
    coding_experience: str,
    explanation_preference: str,
    theory_practice_balance: str,
    derived_difficulty: str,
    commit: bool = False,
) -> DiagnosticSnapshotRecord:
    """Append an immutable diagnostic snapshot."""
    snapshot_id = f"diag_{secrets.token_urlsafe(16)}"
    conn.execute(
        "INSERT INTO diagnostic_snapshots "
        "(id, learner_id, coding_experience, explanation_preference, theory_practice_balance, derived_difficulty, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot_id,
            learner_id,
            coding_experience,
            explanation_preference,
            theory_practice_balance,
            derived_difficulty,
            _utcnow(),
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute("SELECT * FROM diagnostic_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return _diag_row(row)


def get_diagnostic_snapshots(
    conn: sqlite3.Connection, learner_id: str
) -> list[DiagnosticSnapshotRecord]:
    rows = conn.execute(
        "SELECT * FROM diagnostic_snapshots WHERE learner_id = ? ORDER BY created_at",
        (learner_id,),
    ).fetchall()
    return [_diag_row(r) for r in rows]


def _diag_row(row: sqlite3.Row) -> DiagnosticSnapshotRecord:
    return DiagnosticSnapshotRecord(
        id=row["id"],
        learner_id=row["learner_id"],
        coding_experience=row["coding_experience"],
        explanation_preference=row["explanation_preference"],
        theory_practice_balance=row["theory_practice_balance"],
        derived_difficulty=row["derived_difficulty"],
        created_at=row["created_at"],
    )
