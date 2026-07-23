"""Reader repository — reader profile, activation, deletion.

Readers are independent entities. A deleted or inactive reader cannot
create choices or branches.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.database.errors import IntegrityError
from app.utils import new_id, now_utc_iso


@dataclass(frozen=True)
class ReaderRecord:
    id: str
    display_name: str
    status: str
    created_at: str
    deleted_at: str | None


class ReaderValidationError(ValueError):
    pass


class ReaderNotFoundError(RuntimeError):
    pass


class RepositoryTransactionError(RuntimeError):
    """Raised when a repository write is attempted on an in-transaction connection."""


def _row_to_record(row: sqlite3.Row) -> ReaderRecord:
    return ReaderRecord(
        id=row["id"],
        display_name=row["display_name"],
        status=row["status"],
        created_at=row["created_at"],
        deleted_at=row["deleted_at"],
    )


def create_reader(
    conn: sqlite3.Connection,
    *,
    display_name: str,
    reader_id: str | None = None,
) -> ReaderRecord:
    if not display_name or not display_name.strip():
        raise ReaderValidationError("display_name must be non-empty")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    rid = reader_id or new_id()
    now = now_utc_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO readers (id, display_name, status, created_at) "
            "VALUES (?, ?, 'active', ?)",
            (rid, display_name.strip(), now),
        )
        conn.commit()
        return ReaderRecord(
            id=rid,
            display_name=display_name.strip(),
            status="active",
            created_at=now,
            deleted_at=None,
        )
    except IntegrityError as exc:
        conn.rollback()
        raise ReaderValidationError(f"reader already exists: {exc}") from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_reader(conn: sqlite3.Connection, reader_id: str) -> ReaderRecord | None:
    row = conn.execute(
        "SELECT * FROM readers WHERE id = ?",
        (reader_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def is_reader_active(conn: sqlite3.Connection, reader_id: str) -> bool:
    row = conn.execute(
        "SELECT status, deleted_at FROM readers WHERE id = ?",
        (reader_id,),
    ).fetchone()
    if row is None:
        return False
    return row["status"] == "active" and row["deleted_at"] is None


def delete_reader(conn: sqlite3.Connection, reader_id: str) -> bool:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE readers SET status = 'deleted', deleted_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (now, reader_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_all_readers(conn: sqlite3.Connection) -> list[ReaderRecord]:
    rows = conn.execute(
        "SELECT * FROM readers ORDER BY created_at"
    ).fetchall()
    return [_row_to_record(r) for r in rows]
