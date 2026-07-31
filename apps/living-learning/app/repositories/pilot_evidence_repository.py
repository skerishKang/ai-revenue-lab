"""Pilot evidence repository for Living Learning."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class PilotEvidenceRecord:
    id: str
    evidence_type: str
    learner_id: str
    lesson_id: str
    offer_description: str
    consent_recorded: bool
    created_at: str


def _row_to_record(row: sqlite3.Row) -> PilotEvidenceRecord:
    return PilotEvidenceRecord(
        id=row["id"],
        evidence_type=row["evidence_type"],
        learner_id=row["learner_id"],
        lesson_id=row["lesson_id"],
        offer_description=row["offer_description"],
        consent_recorded=bool(row["consent_recorded"]),
        created_at=row["created_at"],
    )


_COLS = [
    "id", "evidence_type", "learner_id", "lesson_id",
    "offer_description", "consent_recorded", "created_at",
]
_SELECT = ", ".join(_COLS)


def create_pilot_evidence(
    conn: sqlite3.Connection,
    *,
    learner_id: str,
    lesson_id: str,
    evidence_type: str = "free_sample",
    offer_description: str = "",
    consent_recorded: bool = False,
    commit: bool = True,
) -> PilotEvidenceRecord:
    now = _utcnow()
    evidence_id = f"pe_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO pilot_evidence ({_SELECT}) VALUES (?,?,?,?,?,?,?)",
        (
            evidence_id, evidence_type, learner_id, lesson_id,
            offer_description, int(consent_recorded), now,
        ),
    )
    if commit:
        conn.commit()
    return get_pilot_evidence_by_id(conn, evidence_id)  # type: ignore[return-value]


def get_pilot_evidence_by_id(conn: sqlite3.Connection, evidence_id: str) -> PilotEvidenceRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM pilot_evidence WHERE id = ?", (evidence_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_pilot_evidence_by_learner(
    conn: sqlite3.Connection, learner_id: str
) -> list[PilotEvidenceRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM pilot_evidence WHERE learner_id = ? ORDER BY created_at",
        (learner_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]