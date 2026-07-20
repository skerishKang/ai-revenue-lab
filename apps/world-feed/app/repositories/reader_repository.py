import json
import sqlite3
from dataclasses import dataclass

from app.db import transaction_scope
from app.domain.models import ReaderProfileInput
from app.repositories.common import (
    DuplicateRecordError,
    InactiveReaderError,
    now_utc_iso,
)


@dataclass(frozen=True)
class ReaderRecord:
    reader_id: str
    display_name: str
    language: str
    preferences: dict
    active: bool
    created_at: str


_READER_COLS = ["reader_id", "display_name", "language", "preferences", "active", "created_at"]
_READER_SELECT = ", ".join(_READER_COLS)


def _row_to_record(row: sqlite3.Row) -> ReaderRecord:
    return ReaderRecord(
        reader_id=row["reader_id"],
        display_name=row["display_name"],
        language=row["language"],
        preferences=json.loads(row["preferences"] or "{}"),
        active=bool(row["active"]),
        created_at=row["created_at"],
    )


def create_reader(
    conn: sqlite3.Connection, profile: ReaderProfileInput
) -> ReaderRecord:
    now = now_utc_iso()
    with transaction_scope(conn):
        try:
            conn.execute(
                """
                INSERT INTO readers (
                    reader_id, display_name, language, preferences, active,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.reader_id,
                    profile.display_name,
                    profile.language.value,
                    profile.preferences.model_dump_json(),
                    1 if profile.active else 0,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError(
                f"reader already exists: {profile.reader_id}"
            ) from exc
        return get_reader_by_id(conn, profile.reader_id)


def get_reader_by_id(
    conn: sqlite3.Connection, reader_id: str
) -> ReaderRecord | None:
    row = conn.execute(
        f"SELECT {_READER_SELECT} FROM readers WHERE reader_id = ?",
        (reader_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def require_active_reader(conn: sqlite3.Connection, reader_id: str) -> ReaderRecord:
    reader = get_reader_by_id(conn, reader_id)
    if reader is None:
        raise InactiveReaderError(f"unknown reader: {reader_id}")
    if not reader.active:
        raise InactiveReaderError(f"reader is inactive: {reader_id}")
    return reader


def set_reader_active(
    conn: sqlite3.Connection, reader_id: str, active: bool
) -> ReaderRecord:
    with transaction_scope(conn):
        existing = conn.execute(
            "SELECT reader_id FROM readers WHERE reader_id = ?", (reader_id,)
        ).fetchone()
        if existing is None:
            raise InactiveReaderError(f"unknown reader: {reader_id}")
        conn.execute(
            "UPDATE readers SET active = ? WHERE reader_id = ?",
            (1 if active else 0, reader_id),
        )
        return get_reader_by_id(conn, reader_id)


def list_readers(conn: sqlite3.Connection) -> list[ReaderRecord]:
    rows = conn.execute(
        f"SELECT {_READER_SELECT} FROM readers ORDER BY reader_id"
    ).fetchall()
    return [_row_to_record(r) for r in rows]
