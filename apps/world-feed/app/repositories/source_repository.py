import json
import sqlite3
from dataclasses import dataclass

from app.db import transaction_scope
from app.domain.models import SourceCard
from app.repositories.common import (
    DuplicateRecordError,
    NotFoundError,
    now_utc_iso,
)


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    country: str
    locality: str
    original_language: str
    source_tier: str
    publisher_name: str
    organization_type: str
    canonical_url: str
    publication_timestamp: str
    access_timestamp: str
    title: str
    text_extract: str
    category: str
    media_rights_state: str
    source_state: str
    conflict_penalty: float
    canonical_key: str
    checksum: str
    synthetic_flag: bool
    reviewer_notes: str
    created_at: str


_SOURCE_COLS = [
    "source_id", "country", "locality", "original_language", "source_tier",
    "publisher_name", "organization_type", "canonical_url",
    "publication_timestamp", "access_timestamp", "title", "text_extract",
    "category", "media_rights_state", "source_state", "conflict_penalty",
    "canonical_key", "checksum", "synthetic_flag", "reviewer_notes",
    "created_at",
]
_SOURCE_SELECT = ", ".join(_SOURCE_COLS)


def _row_to_record(row: sqlite3.Row) -> SourceRecord:
    return SourceRecord(
        source_id=row["source_id"],
        country=row["country"],
        locality=row["locality"],
        original_language=row["original_language"],
        source_tier=row["source_tier"],
        publisher_name=row["publisher_name"],
        organization_type=row["organization_type"],
        canonical_url=row["canonical_url"],
        publication_timestamp=row["publication_timestamp"],
        access_timestamp=row["access_timestamp"],
        title=row["title"],
        text_extract=row["text_extract"],
        category=row["category"],
        media_rights_state=row["media_rights_state"],
        source_state=row["source_state"],
        conflict_penalty=row["conflict_penalty"],
        canonical_key=row["canonical_key"],
        checksum=row["checksum"],
        synthetic_flag=bool(row["synthetic_flag"]),
        reviewer_notes=row["reviewer_notes"],
        created_at=row["created_at"],
    )


def create_source(
    conn: sqlite3.Connection, card: SourceCard
) -> SourceRecord:
    now = now_utc_iso()
    with transaction_scope(conn):
        try:
            conn.execute(
                """
                INSERT INTO sources (
                    source_id, country, locality, original_language,
                    source_tier, publisher_name, organization_type,
                    canonical_url, publication_timestamp, access_timestamp,
                    title, text_extract, category, media_rights_state,
                    source_state, conflict_penalty, canonical_key, checksum,
                    synthetic_flag, reviewer_notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.source_id, card.country, card.locality,
                    card.original_language.value, card.source_tier.value,
                    card.publisher_name, card.organization_type,
                    card.canonical_url, card.publication_timestamp,
                    card.access_timestamp, card.title, card.text_extract,
                    card.category.value, card.media_rights_state,
                    card.source_state.value, card.conflict_penalty,
                    card.canonical_key, card.checksum,
                    1 if card.synthetic_flag else 0, card.reviewer_notes, now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError(
                f"source card id already exists: {card.source_id}"
            ) from exc
        return get_source_by_id(conn, card.source_id)


def get_source_by_id(
    conn: sqlite3.Connection, source_id: str
) -> SourceRecord | None:
    row = conn.execute(
        f"SELECT {_SOURCE_SELECT} FROM sources WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def list_sources(conn: sqlite3.Connection) -> list[SourceRecord]:
    rows = conn.execute(
        f"SELECT {_SOURCE_SELECT} FROM sources ORDER BY created_at, source_id"
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def count_sources(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()
    return int(row["n"])
