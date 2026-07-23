"""Adaptation-decision repository.

Every material change the adaptation step makes is recorded as an independent,
auditable ``adaptation_decisions`` row keyed by (learner, prior lesson, next
lesson, signal, dimension). This makes the "what changed and why" surface
queryable and lets the API expose a concrete change history rather than an
opaque "AI personalized" claim.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# Signal types: what input drove the adaptation.
SIGNAL_FEEDBACK = "feedback"
SIGNAL_COMPREHENSION = "comprehension"
SIGNAL_MASTERY = "mastery"

# Dimensions that can change between lessons.
DIMENSION_EXPLANATION_ORDER = "explanation_order"
DIMENSION_EXAMPLE_COUNT = "example_count"
DIMENSION_REVIEW_QUESTION_COUNT = "review_question_count"
DIMENSION_PACING = "pacing"
DIMENSION_TERMINOLOGY = "terminology"
DIMENSION_THEORY_DENSITY = "theory_density"


@dataclass(frozen=True)
class AdaptationDecisionRecord:
    id: str
    learner_id: str
    prior_lesson_id: str
    next_lesson_id: str
    signal_type: str
    signal_reference_id: str
    dimension: str
    before_value: str
    after_value: str
    reason: str
    created_at: str


_COLS = [
    "id", "learner_id", "prior_lesson_id", "next_lesson_id", "signal_type",
    "signal_reference_id", "dimension", "before_value", "after_value",
    "reason", "created_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> AdaptationDecisionRecord:
    return AdaptationDecisionRecord(
        id=row["id"],
        learner_id=row["learner_id"],
        prior_lesson_id=row["prior_lesson_id"],
        next_lesson_id=row["next_lesson_id"],
        signal_type=row["signal_type"],
        signal_reference_id=row["signal_reference_id"] or "",
        dimension=row["dimension"],
        before_value=row["before_value"] or "",
        after_value=row["after_value"] or "",
        reason=row["reason"] or "",
        created_at=row["created_at"],
    )


def record_adaptation_decision(
    conn: sqlite3.Connection,
    *,
    learner_id: str,
    prior_lesson_id: str,
    next_lesson_id: str,
    signal_type: str,
    dimension: str,
    before_value: str,
    after_value: str,
    reason: str,
    signal_reference_id: str = "",
    commit: bool = False,
) -> AdaptationDecisionRecord:
    decision_id = f"adapt_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO adaptation_decisions ({_SELECT}) VALUES ({','.join('?' for _ in _COLS)})",
        (
            decision_id, learner_id, prior_lesson_id, next_lesson_id,
            signal_type, signal_reference_id, dimension, before_value,
            after_value, reason, _utcnow(),
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        f"SELECT {_SELECT} FROM adaptation_decisions WHERE id = ?", (decision_id,)
    ).fetchone()
    return _row_to_record(row)  # type: ignore[return-value]


def get_adaptation_decisions_for_lesson(
    conn: sqlite3.Connection, next_lesson_id: str
) -> list[AdaptationDecisionRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM adaptation_decisions WHERE next_lesson_id = ? "
        "ORDER BY created_at",
        (next_lesson_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_adaptation_decisions_for_learner(
    conn: sqlite3.Connection, learner_id: str
) -> list[AdaptationDecisionRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM adaptation_decisions WHERE learner_id = ? "
        "ORDER BY created_at",
        (learner_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
