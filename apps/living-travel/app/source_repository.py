"""Source repository for Living Travel."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.enums import SourceConfidence


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class SourceRecord:
    id: str
    source_url: str
    publisher: str
    source_type: str
    original_language: str
    publication_date: str
    access_date: str
    destination: str
    locality: str
    category: str
    claims: list[str] = field(default_factory=list)
    confidence: str = SourceConfidence.approximate
    state: str = "single_source"
    verification_notes: str = ""
    created_at: str = ""


def _row_to_record(row: sqlite3.Row) -> SourceRecord:
    return SourceRecord(
        id=row["id"],
        source_url=row["source_url"],
        publisher=row["publisher"],
        source_type=row["source_type"],
        original_language=row["original_language"],
        publication_date=row["publication_date"],
        access_date=row["access_date"],
        destination=row["destination"],
        locality=row["locality"],
        category=row["category"],
        claims=json.loads(row["claims"]) if row["claims"] else [],
        confidence=row["confidence"],
        state=row["state"],
        verification_notes=row["verification_notes"],
        created_at=row["created_at"],
    )


_COLS = [
    "id", "source_url", "publisher", "source_type", "original_language",
    "publication_date", "access_date", "destination", "locality", "category",
    "claims", "confidence", "state", "verification_notes", "created_at",
]
_SELECT = ", ".join(_COLS)


def create_source(
    conn: sqlite3.Connection,
    *,
    source_url: str,
    publisher: str,
    source_type: str,
    destination: str,
    category: str,
    locality: str = "",
    original_language: str = "ko",
    publication_date: str = "",
    access_date: str = "",
    claims: list[str] | None = None,
    confidence: str = SourceConfidence.approximate,
    state: str = "single_source",
    verification_notes: str = "",
) -> SourceRecord:
    now = _utcnow()
    source_id = f"src_{secrets.token_urlsafe(16)}"
    claims = claims or []
    conn.execute(
        f"INSERT INTO sources ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            source_id, source_url, publisher, source_type, original_language,
            publication_date, access_date, destination, locality, category,
            json.dumps(claims), confidence, state, verification_notes, now,
        ),
    )
    conn.commit()
    return get_source_by_id(conn, source_id)  # type: ignore[return-value]


def get_source_by_id(conn: sqlite3.Connection, source_id: str) -> SourceRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_sources_by_destination(conn: sqlite3.Connection, destination: str) -> list[SourceRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM sources WHERE destination = ?",
        (destination,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
