import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.participant_repository import RepositoryTransactionError, _now_utc_iso


@dataclass(frozen=True)
class InputRecord:
    id: str
    participant_id: str
    sequence_number: int
    raw_text: str
    normalized_text: str | None
    consent_confirmed: int
    submitted_at: str
    deleted_at: str | None


class InputValidationError(ValueError):
    pass


class InputNotFoundError(RuntimeError):
    pass


_INPUT_COLS = [
    "id",
    "participant_id",
    "sequence_number",
    "raw_text",
    "normalized_text",
    "consent_confirmed",
    "submitted_at",
    "deleted_at",
]
_INPUT_SELECT = ", ".join(_INPUT_COLS)


def _validate_input(
    participant_id: str,
    raw_text: str,
    consent_confirmed: int,
) -> None:
    if not isinstance(participant_id, str) or not participant_id.strip():
        raise InputValidationError("participant_id must be a non-empty string")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise InputValidationError("raw_text must be a non-empty string")
    if consent_confirmed not in (0, 1):
        raise InputValidationError("consent_confirmed must be 0 or 1")


def _row_to_record(row: sqlite3.Row) -> InputRecord:
    return InputRecord(
        id=row["id"],
        participant_id=row["participant_id"],
        sequence_number=row["sequence_number"],
        raw_text=row["raw_text"],
        normalized_text=row["normalized_text"],
        consent_confirmed=row["consent_confirmed"],
        submitted_at=row["submitted_at"],
        deleted_at=row["deleted_at"],
    )


def create_input(
    conn: sqlite3.Connection,
    *,
    participant_id: str,
    raw_text: str,
    consent_confirmed: int = 1,
    submitted_at: str | None = None,
) -> InputRecord:
    _validate_input(participant_id, raw_text, consent_confirmed)

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    participant_id = participant_id.strip()
    raw_text = raw_text.strip()
    now = submitted_at or _now_utc_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        participant = conn.execute(
            "SELECT 1 FROM participants WHERE id = ? AND status = 'active'",
            (participant_id,),
        ).fetchone()
        if not participant:
            conn.rollback()
            raise InputValidationError(
                "participant does not exist or is not active"
            )

        max_seq = conn.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) AS ms "
            "FROM inputs WHERE participant_id = ?",
            (participant_id,),
        ).fetchone()["ms"]
        sequence_number = max_seq + 1

        input_id = str(uuid.uuid4())

        cursor = conn.execute(
            "INSERT INTO inputs "
            "(id, participant_id, sequence_number, raw_text, "
            "consent_confirmed, submitted_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (input_id, participant_id, sequence_number, raw_text,
             consent_confirmed, now),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise RuntimeError("failed to insert input record")

        conn.commit()
        return InputRecord(
            id=input_id,
            participant_id=participant_id,
            sequence_number=sequence_number,
            raw_text=raw_text,
            normalized_text=None,
            consent_confirmed=consent_confirmed,
            submitted_at=now,
            deleted_at=None,
        )
    except (InputValidationError, RepositoryTransactionError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_input_by_id(
    conn: sqlite3.Connection, input_id: str
) -> InputRecord | None:
    row = conn.execute(
        f"SELECT {_INPUT_SELECT} FROM inputs WHERE id = ?",
        (input_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_inputs_by_participant(
    conn: sqlite3.Connection, participant_id: str
) -> list[InputRecord]:
    rows = conn.execute(
        f"SELECT {_INPUT_SELECT} FROM inputs "
        "WHERE participant_id = ? ORDER BY sequence_number",
        (participant_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def update_input_normalized_text(
    conn: sqlite3.Connection,
    input_id: str,
    normalized_text: str,
) -> InputRecord | None:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE inputs SET normalized_text = ? WHERE id = ?",
            (normalized_text, input_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return get_input_by_id(conn, input_id)
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def delete_input(conn: sqlite3.Connection, input_id: str) -> bool:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    now = _now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE inputs SET deleted_at = ? WHERE id = ? "
            "AND deleted_at IS NULL",
            (now, input_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
