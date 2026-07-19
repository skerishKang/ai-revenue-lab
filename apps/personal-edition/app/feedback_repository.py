import json
import sqlite3
import uuid
from dataclasses import dataclass

from app.participant_repository import RepositoryTransactionError, _now_utc_iso


@dataclass(frozen=True)
class FeedbackRecord:
    id: str
    participant_id: str
    edition_id: str
    direction_choices: str
    selected_section_id: str | None
    free_text: str | None
    submitted_at: str
    applied_to_next_edition: int


class FeedbackValidationError(ValueError):
    pass


class FeedbackNotFoundError(RuntimeError):
    pass


_FEEDBACK_COLS = [
    "id",
    "participant_id",
    "edition_id",
    "direction_choices",
    "selected_section_id",
    "free_text",
    "submitted_at",
    "applied_to_next_edition",
]
_FEEDBACK_SELECT = ", ".join(_FEEDBACK_COLS)


def _validate_feedback(
    participant_id: str,
    edition_id: str,
    direction_choices: str,
) -> None:
    if not isinstance(participant_id, str) or not participant_id.strip():
        raise FeedbackValidationError(
            "participant_id must be a non-empty string"
        )
    if not isinstance(edition_id, str) or not edition_id.strip():
        raise FeedbackValidationError(
            "edition_id must be a non-empty string"
        )
    if not isinstance(direction_choices, str) or not direction_choices.strip():
        raise FeedbackValidationError(
            "direction_choices must be a non-empty string"
        )


def _validate_json_field(value: str | None, field_name: str) -> None:
    if value is None:
        return
    try:
        json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FeedbackValidationError(
            f"{field_name} must be valid JSON"
        ) from exc


def _row_to_record(row: sqlite3.Row) -> FeedbackRecord:
    return FeedbackRecord(
        id=row["id"],
        participant_id=row["participant_id"],
        edition_id=row["edition_id"],
        direction_choices=row["direction_choices"],
        selected_section_id=row["selected_section_id"],
        free_text=row["free_text"],
        submitted_at=row["submitted_at"],
        applied_to_next_edition=row["applied_to_next_edition"],
    )


def create_feedback(
    conn: sqlite3.Connection,
    *,
    participant_id: str,
    edition_id: str,
    direction_choices: str,
    selected_section_id: str | None = None,
    free_text: str | None = None,
    submitted_at: str | None = None,
) -> FeedbackRecord:
    _validate_feedback(participant_id, edition_id, direction_choices)

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    participant_id = participant_id.strip()
    edition_id = edition_id.strip()
    direction_choices = direction_choices.strip()
    now = submitted_at or _now_utc_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        participant = conn.execute(
            "SELECT 1 FROM participants WHERE id = ? AND status = 'active'",
            (participant_id,),
        ).fetchone()
        if not participant:
            conn.rollback()
            raise FeedbackValidationError(
                "participant does not exist or is not active"
            )

        edition = conn.execute(
            "SELECT 1 FROM editions WHERE id = ? AND participant_id = ?",
            (edition_id, participant_id),
        ).fetchone()
        if not edition:
            conn.rollback()
            raise FeedbackValidationError(
                "edition does not exist or belongs to another participant"
            )

        feedback_id = str(uuid.uuid4())

        cursor = conn.execute(
            "INSERT INTO feedback "
            "(id, participant_id, edition_id, direction_choices, "
            "selected_section_id, free_text, submitted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                feedback_id,
                participant_id,
                edition_id,
                direction_choices,
                selected_section_id,
                free_text,
                now,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise RuntimeError("failed to insert feedback record")

        conn.commit()
        return FeedbackRecord(
            id=feedback_id,
            participant_id=participant_id,
            edition_id=edition_id,
            direction_choices=direction_choices,
            selected_section_id=selected_section_id,
            free_text=free_text,
            submitted_at=now,
            applied_to_next_edition=0,
        )
    except (FeedbackValidationError, RepositoryTransactionError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_feedback_by_id(
    conn: sqlite3.Connection, feedback_id: str
) -> FeedbackRecord | None:
    row = conn.execute(
        f"SELECT {_FEEDBACK_SELECT} FROM feedback WHERE id = ?",
        (feedback_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_feedback_by_edition(
    conn: sqlite3.Connection, edition_id: str
) -> list[FeedbackRecord]:
    rows = conn.execute(
        f"SELECT {_FEEDBACK_SELECT} FROM feedback "
        "WHERE edition_id = ? ORDER BY submitted_at",
        (edition_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def mark_feedback_applied(
    conn: sqlite3.Connection, feedback_id: str
) -> FeedbackRecord | None:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE feedback SET applied_to_next_edition = 1 "
            "WHERE id = ? AND applied_to_next_edition = 0",
            (feedback_id,),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return get_feedback_by_id(conn, feedback_id)
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def delete_feedback(conn: sqlite3.Connection, feedback_id: str) -> bool:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "DELETE FROM feedback WHERE id = ?",
            (feedback_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
