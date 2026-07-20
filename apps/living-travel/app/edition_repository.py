"""Edition repository for Living Travel."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.enums import EditionGenerationStatus, PublicationState


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class EditionRecord:
    id: str
    traveler_id: str
    edition_number: int
    prior_edition_id: str | None
    input_id: str | None
    generation_status: str
    structured_content: dict
    publication_state: str
    created_at: str
    updated_at: str


def _row_to_record(row: sqlite3.Row) -> EditionRecord:
    sc = row["structured_content"]
    return EditionRecord(
        id=row["id"],
        traveler_id=row["traveler_id"],
        edition_number=row["edition_number"],
        prior_edition_id=row["prior_edition_id"],
        input_id=row["input_id"],
        generation_status=row["generation_status"],
        structured_content=json.loads(sc) if sc else {},
        publication_state=row["publication_state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_COLS = [
    "id", "traveler_id", "edition_number", "prior_edition_id", "input_id",
    "generation_status", "structured_content", "publication_state",
    "created_at", "updated_at",
]
_SELECT = ", ".join(_COLS)


def create_edition(
    conn: sqlite3.Connection,
    *,
    traveler_id: str,
    edition_number: int,
    prior_edition_id: str | None = None,
    input_id: str | None = None,
) -> EditionRecord:
    now = _utcnow()
    edition_id = f"ed_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO editions ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            edition_id, traveler_id, edition_number, prior_edition_id, input_id,
            EditionGenerationStatus.input_received, "{}",
            PublicationState.pending, now, now,
        ),
    )
    conn.commit()
    return get_edition_by_id(conn, edition_id)  # type: ignore[return-value]


def get_edition_by_id(conn: sqlite3.Connection, edition_id: str) -> EditionRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM editions WHERE id = ?", (edition_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_editions_by_traveler(conn: sqlite3.Connection, traveler_id: str) -> list[EditionRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM editions WHERE traveler_id = ? ORDER BY edition_number",
        (traveler_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def update_edition_generation_status(
    conn: sqlite3.Connection, edition_id: str, status: str
) -> bool:
    now = _utcnow()
    cur = conn.execute(
        "UPDATE editions SET generation_status = ?, updated_at = ? WHERE id = ?",
        (status, now, edition_id),
    )
    conn.commit()
    return cur.rowcount > 0


def update_edition_content(
    conn: sqlite3.Connection, edition_id: str, content: dict
) -> bool:
    now = _utcnow()
    cur = conn.execute(
        "UPDATE editions SET structured_content = ?, updated_at = ? WHERE id = ?",
        (json.dumps(content), now, edition_id),
    )
    conn.commit()
    return cur.rowcount > 0


def update_edition_publication(
    conn: sqlite3.Connection, edition_id: str, state: str
) -> bool:
    now = _utcnow()
    cur = conn.execute(
        "UPDATE editions SET publication_state = ?, updated_at = ? WHERE id = ?",
        (state, now, edition_id),
    )
    conn.commit()
    return cur.rowcount > 0
