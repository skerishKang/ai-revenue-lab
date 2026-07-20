import json
import re
import sqlite3
from dataclasses import dataclass

from app.db import transaction_scope
from app.repositories.common import now_utc_iso


@dataclass(frozen=True)
class BriefRecord:
    id: str
    brief_number: str
    reader_id: str
    language: str
    generation_run_id: str
    sequence: str
    status: str
    title: str
    deck: str
    body_json: str
    selected_event_ids: list[str]
    feedback_id: str | None
    validation_status: str
    created_at: str


_BRIEF_COLS = [
    "id", "brief_number", "reader_id", "language", "generation_run_id",
    "sequence", "status", "title", "deck", "body_json",
    "selected_event_ids", "feedback_id", "validation_status", "created_at",
]
_BRIEF_SELECT = ", ".join(_BRIEF_COLS)


def _row_to_record(row: sqlite3.Row) -> BriefRecord:
    return BriefRecord(
        id=row["id"],
        brief_number=row["brief_number"],
        reader_id=row["reader_id"],
        language=row["language"],
        generation_run_id=row["generation_run_id"],
        sequence=row["sequence"],
        status=row["status"],
        title=row["title"],
        deck=row["deck"],
        body_json=row["body_json"],
        selected_event_ids=json.loads(row["selected_event_ids"] or "[]"),
        feedback_id=row["feedback_id"],
        validation_status=row["validation_status"],
        created_at=row["created_at"],
    )


def _next_brief_number(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT COUNT(*) AS n FROM briefs").fetchone()
    num = int(row["n"]) + 1
    return f"WF-{num:04d}"


def create_brief(
    conn: sqlite3.Connection,
    *,
    reader_id: str,
    language: str,
    generation_run_id: str,
    sequence: str,
    status: str,
    title: str,
    deck: str,
    body_json: str,
    selected_event_ids: list[str],
    feedback_id: str | None = None,
    validation_status: str = "pending",
) -> BriefRecord:
    import uuid

    now = now_utc_iso()
    with transaction_scope(conn):
        brief_id = str(uuid.uuid4())
        # Retry brief-number assignment to honour the UNIQUE constraint even
        # under concurrent inserts (duplicate brief numbers are forbidden).
        for _ in range(20):
            try:
                brief_number = _next_brief_number(conn)
                conn.execute(
                    """
                    INSERT INTO briefs (
                        id, brief_number, reader_id, language,
                        generation_run_id, sequence, status, title, deck,
                        body_json, selected_event_ids, feedback_id,
                        validation_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        brief_id, brief_number, reader_id, language,
                        generation_run_id, sequence, status, title, deck,
                        body_json, json.dumps(selected_event_ids),
                        feedback_id, validation_status, now,
                    ),
                )
                break
            except sqlite3.IntegrityError:
                continue
        else:
            raise RuntimeError("could not assign a unique brief number")
        return get_brief_by_id(conn, brief_id)


def get_brief_by_id(
    conn: sqlite3.Connection, brief_id: str
) -> BriefRecord | None:
    row = conn.execute(
        f"SELECT {_BRIEF_SELECT} FROM briefs WHERE id = ?", (brief_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_brief_by_number(
    conn: sqlite3.Connection, brief_number: str
) -> BriefRecord | None:
    row = conn.execute(
        f"SELECT {_BRIEF_SELECT} FROM briefs WHERE brief_number = ?",
        (brief_number,),
    ).fetchone()
    return _row_to_record(row) if row else None


def list_briefs_for_reader(
    conn: sqlite3.Connection, reader_id: str
) -> list[BriefRecord]:
    rows = conn.execute(
        f"SELECT {_BRIEF_SELECT} FROM briefs WHERE reader_id = ? "
        "ORDER BY sequence, created_at",
        (reader_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_latest_by_reader_sequence(
    conn: sqlite3.Connection, reader_id: str, sequence: str
) -> BriefRecord | None:
    row = conn.execute(
        f"SELECT {_BRIEF_SELECT} FROM briefs "
        "WHERE reader_id = ? AND sequence = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (reader_id, sequence),
    ).fetchone()
    return _row_to_record(row) if row else None


def count_briefs(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM briefs").fetchone()
    return int(row["n"])
