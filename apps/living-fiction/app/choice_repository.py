"""Reader choice repository — reader choices and comments.

A reader choice may be applied once to one matching branch request.
Duplicate application is rejected.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class ReaderChoiceRecord:
    id: str
    reader_id: str
    canon_episode_id: str
    choice_text: str
    comment: str | None
    submitted_at: str
    applied_to_branch_id: str | None
    applied_at: str | None


class ChoiceValidationError(ValueError):
    pass


class ChoiceNotFoundError(RuntimeError):
    pass


_COLS = [
    "id", "reader_id", "canon_episode_id", "choice_text", "comment",
    "submitted_at", "applied_to_branch_id", "applied_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> ReaderChoiceRecord:
    return ReaderChoiceRecord(
        id=row["id"],
        reader_id=row["reader_id"],
        canon_episode_id=row["canon_episode_id"],
        choice_text=row["choice_text"],
        comment=row["comment"],
        submitted_at=row["submitted_at"],
        applied_to_branch_id=row["applied_to_branch_id"],
        applied_at=row["applied_at"],
    )


def create_reader_choice(
    conn: sqlite3.Connection,
    *,
    choice_id: str,
    reader_id: str,
    canon_episode_id: str,
    choice_text: str,
    comment: str | None = None,
) -> ReaderChoiceRecord:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO reader_choices "
            "(id, reader_id, canon_episode_id, choice_text, comment, "
            "submitted_at) VALUES (?, ?, ?, ?, ?, ?)",
            (choice_id, reader_id, canon_episode_id, choice_text,
             comment, now),
        )
        conn.commit()
        return ReaderChoiceRecord(
            id=choice_id, reader_id=reader_id,
            canon_episode_id=canon_episode_id,
            choice_text=choice_text, comment=comment,
            submitted_at=now,
            applied_to_branch_id=None, applied_at=None,
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ChoiceValidationError(
            f"duplicate choice (same reader+episode+choice): {exc}"
        ) from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_reader_choice(conn: sqlite3.Connection, choice_id: str) -> ReaderChoiceRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM reader_choices WHERE id = ?",
        (choice_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_choices_by_reader(
    conn: sqlite3.Connection, reader_id: str
) -> list[ReaderChoiceRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM reader_choices "
        "WHERE reader_id = ? ORDER BY submitted_at",
        (reader_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def is_choice_applied(conn: sqlite3.Connection, choice_id: str) -> bool:
    row = conn.execute(
        "SELECT applied_to_branch_id FROM reader_choices WHERE id = ?",
        (choice_id,),
    ).fetchone()
    if row is None:
        return False
    return row["applied_to_branch_id"] is not None


def mark_choice_applied(
    conn: sqlite3.Connection,
    choice_id: str,
    branch_episode_id: str,
) -> bool:
    """Mark a choice as applied to a specific branch episode.

    This does NOT commit — it is called within a service-owned transaction.
    Raises if already applied.
    """
    row = conn.execute(
        "SELECT applied_to_branch_id FROM reader_choices WHERE id = ?",
        (choice_id,),
    ).fetchone()
    if row is None:
        raise ChoiceNotFoundError(f"choice not found: {choice_id}")
    if row["applied_to_branch_id"] is not None:
        raise ChoiceValidationError(
            f"choice {choice_id} already applied to branch "
            f"{row['applied_to_branch_id']}"
        )
    now = now_utc_iso()
    cursor = conn.execute(
        "UPDATE reader_choices SET applied_to_branch_id = ?, applied_at = ? "
        "WHERE id = ? AND applied_to_branch_id IS NULL",
        (branch_episode_id, now, choice_id),
    )
    return cursor.rowcount > 0
