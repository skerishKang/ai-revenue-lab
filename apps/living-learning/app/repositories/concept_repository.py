"""Concept repository for Living Learning."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.models import Concept
from app.domain.enums import ConceptPrerequisiteError


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class ConceptRecord:
    id: str
    curriculum_id: str
    name: str
    description: str
    prerequisites: list[str]
    sequence_order: int
    created_at: str


def _row_to_record(row: sqlite3.Row) -> ConceptRecord:
    return ConceptRecord(
        id=row["id"],
        curriculum_id=row["curriculum_id"],
        name=row["name"],
        description=row["description"],
        prerequisites=json.loads(row["prerequisites"]) if row["prerequisites"] else [],
        sequence_order=row["sequence_order"],
        created_at=row["created_at"],
    )


_COLS = ["id", "curriculum_id", "name", "description", "prerequisites", "sequence_order", "created_at"]
_SELECT = ", ".join(_COLS)


def create_concept(
    conn: sqlite3.Connection,
    *,
    curriculum_id: str,
    name: str,
    description: str = "",
    prerequisites: list[str] | None = None,
    sequence_order: int = 0,
    commit: bool = True,
) -> ConceptRecord:
    now = _utcnow()
    concept_id = f"concept_{secrets.token_urlsafe(16)}"
    prerequisites = prerequisites or []
    conn.execute(
        f"INSERT INTO concepts ({_SELECT}) VALUES (?,?,?,?,?,?,?)",
        (concept_id, curriculum_id, name, description, json.dumps(prerequisites), sequence_order, now),
    )
    if commit:
        conn.commit()
    return get_concept_by_id(conn, concept_id)  # type: ignore[return-value]


def get_concept_by_id(conn: sqlite3.Connection, concept_id: str) -> ConceptRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM concepts WHERE id = ?", (concept_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_concepts_by_curriculum(conn: sqlite3.Connection, curriculum_id: str) -> list[ConceptRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order",
        (curriculum_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def validate_prerequisites(
    conn: sqlite3.Connection,
    concept_id: str,
    learner_id: str,
) -> tuple[bool, list[str]]:
    concept = get_concept_by_id(conn, concept_id)
    if not concept:
        return False, ["concept_not_found"]

    if not concept.prerequisites:
        return True, []

    missing = []
    for prereq_id in concept.prerequisites:
        prereq = get_concept_by_id(conn, prereq_id)
        if not prereq:
            missing.append(prereq_id)
            continue
        mastery_row = conn.execute(
            "SELECT mastery_level FROM learner_mastery WHERE learner_id = ? AND concept_id = ?",
            (learner_id, prereq_id),
        ).fetchone()
        if not mastery_row or mastery_row["mastery_level"] not in ("proficient", "developing"):
            missing.append(prereq_id)

    return len(missing) == 0, missing