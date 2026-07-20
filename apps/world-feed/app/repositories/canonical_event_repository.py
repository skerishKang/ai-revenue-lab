import json
import sqlite3
import uuid
from dataclasses import dataclass

from app.db import transaction_scope
from app.repositories.common import now_utc_iso


@dataclass(frozen=True)
class CanonicalEventRecord:
    id: str
    canonical_key: str
    country: str
    locality: str
    title_original: str
    title_localized: str
    category: str
    start_date: str | None
    end_date: str | None
    organizer: str
    status: str
    uncertainty_note: str | None
    source_ids: list[str]
    conflicting_source_ids: list[str]
    eligible: bool
    created_at: str
    updated_at: str


_EVENT_COLS = [
    "id", "canonical_key", "country", "locality", "title_original",
    "title_localized", "category", "start_date", "end_date", "organizer",
    "status", "uncertainty_note", "source_ids", "conflicting_source_ids",
    "eligible", "created_at", "updated_at",
]
_EVENT_SELECT = ", ".join(_EVENT_COLS)


def _row_to_record(row: sqlite3.Row) -> CanonicalEventRecord:
    return CanonicalEventRecord(
        id=row["id"],
        canonical_key=row["canonical_key"],
        country=row["country"],
        locality=row["locality"],
        title_original=row["title_original"],
        title_localized=row["title_localized"],
        category=row["category"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        organizer=row["organizer"],
        status=row["status"],
        uncertainty_note=row["uncertainty_note"],
        source_ids=json.loads(row["source_ids"] or "[]"),
        conflicting_source_ids=json.loads(row["conflicting_source_ids"] or "[]"),
        eligible=bool(row["eligible"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def upsert_canonical_event(
    conn: sqlite3.Connection,
    *,
    canonical_key: str,
    country: str,
    locality: str,
    title_original: str,
    title_localized: str,
    category: str,
    start_date: str | None,
    end_date: str | None,
    organizer: str,
    status: str,
    uncertainty_note: str | None,
    source_ids: list[str],
    conflicting_source_ids: list[str],
    eligible: bool,
) -> CanonicalEventRecord:
    now = now_utc_iso()
    event_id = str(uuid.uuid4())
    with transaction_scope(conn):
        existing = conn.execute(
            "SELECT id, created_at FROM canonical_events WHERE canonical_key = ?",
            (canonical_key,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO canonical_events (
                    id, canonical_key, country, locality, title_original,
                    title_localized, category, start_date, end_date, organizer,
                    status, uncertainty_note, source_ids,
                    conflicting_source_ids, eligible, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, canonical_key, country, locality, title_original,
                    title_localized, category, start_date, end_date, organizer,
                    status, uncertainty_note, json.dumps(source_ids),
                    json.dumps(conflicting_source_ids), 1 if eligible else 0,
                    now, now,
                ),
            )
            created_at = now
        else:
            conn.execute(
                """
                UPDATE canonical_events SET
                    country = ?, locality = ?, title_original = ?,
                    title_localized = ?, category = ?, start_date = ?,
                    end_date = ?, organizer = ?, status = ?, uncertainty_note = ?,
                    source_ids = ?, conflicting_source_ids = ?, eligible = ?,
                    updated_at = ?
                WHERE canonical_key = ?
                """,
                (
                    country, locality, title_original, title_localized,
                    category, start_date, end_date, organizer, status,
                    uncertainty_note, json.dumps(source_ids),
                    json.dumps(conflicting_source_ids), 1 if eligible else 0,
                    now, canonical_key,
                ),
            )
            created_at = existing["created_at"]
        return CanonicalEventRecord(
            id=existing["id"] if existing else event_id,
            canonical_key=canonical_key,
            country=country,
            locality=locality,
            title_original=title_original,
            title_localized=title_localized,
            category=category,
            start_date=start_date,
            end_date=end_date,
            organizer=organizer,
            status=status,
            uncertainty_note=uncertainty_note,
            source_ids=list(source_ids),
            conflicting_source_ids=list(conflicting_source_ids),
            eligible=eligible,
            created_at=created_at,
            updated_at=now,
        )


def get_event_by_id(
    conn: sqlite3.Connection, event_id: str
) -> CanonicalEventRecord | None:
    row = conn.execute(
        f"SELECT {_EVENT_SELECT} FROM canonical_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def list_events(conn: sqlite3.Connection) -> list[CanonicalEventRecord]:
    rows = conn.execute(
        f"SELECT {_EVENT_SELECT} FROM canonical_events "
        "ORDER BY canonical_key"
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def list_eligible_events(conn: sqlite3.Connection) -> list[CanonicalEventRecord]:
    rows = conn.execute(
        f"SELECT {_EVENT_SELECT} FROM canonical_events WHERE eligible = 1 "
        "ORDER BY canonical_key"
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def count_events(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM canonical_events").fetchone()
    return int(row["n"])
