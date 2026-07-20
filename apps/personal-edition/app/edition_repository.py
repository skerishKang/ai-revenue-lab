import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.feedback_repository import (
    FeedbackValidationError,
    FeedbackRecord,
    _FEEDBACK_COLS,
    _FEEDBACK_SELECT,
)
from app.participant_repository import RepositoryTransactionError, _now_utc_iso

_UTC_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def _validate_timestamp(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _UTC_ISO_RE.match(value):
        raise EditionValidationError(
            f"{field_name} must be UTC ISO-8601 "
            "(YYYY-MM-DDTHH:MM:SS.mmmZ)"
        )
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise EditionValidationError(
            f"{field_name} must be a valid UTC ISO-8601 calendar timestamp"
        ) from exc


@dataclass(frozen=True)
class EditionRecord:
    id: str
    participant_id: str
    edition_number: int
    prior_edition_id: str | None
    input_id: str | None
    generation_status: str
    structured_content: str | None
    rendered_title: str | None
    drafted_at: str | None
    reviewed_at: str | None
    published_at: str | None
    human_correction_minutes: float | None
    reviewer_notes: str | None
    publication_state: str


class EditionValidationError(ValueError):
    pass


class EditionNotFoundError(RuntimeError):
    pass


class EditionStateConflict(RuntimeError):
    pass


_EDITION_COLS = [
    "id",
    "participant_id",
    "edition_number",
    "prior_edition_id",
    "input_id",
    "generation_status",
    "structured_content",
    "rendered_title",
    "drafted_at",
    "reviewed_at",
    "published_at",
    "human_correction_minutes",
    "reviewer_notes",
    "publication_state",
]
_EDITION_SELECT = ", ".join(_EDITION_COLS)

_VALID_GENERATION_STATUSES = frozenset({
    "input_received",
    "generation_pending",
    "generation_failed",
    "pending_review",
    "deleted",
})

_VALID_PUBLICATION_STATES = frozenset({
    "pending",
    "published",
    "rejected",
})

_PUBLICATION_TRANSITIONS = {
    "pending": ("published", "rejected"),
    "published": (),
    "rejected": (),
}

_GENERATION_TRANSITIONS = {
    "input_received": frozenset({"generation_pending", "generation_failed"}),
    "generation_pending": frozenset({"generation_failed", "pending_review"}),
    "generation_failed": frozenset({"generation_pending"}),
    "pending_review": frozenset(),
    "deleted": frozenset(),
}

_TERMINAL_PUBLICATION_STATES = frozenset({"published", "rejected"})


def _validate_edition(
    participant_id: str,
    edition_number: int,
) -> None:
    if not isinstance(participant_id, str) or not participant_id.strip():
        raise EditionValidationError("participant_id must be a non-empty string")
    if not isinstance(edition_number, int) or edition_number < 1:
        raise EditionValidationError("edition_number must be a positive integer")


def _validate_json_field(value: str | None, field_name: str) -> None:
    if value is None:
        return
    try:
        json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise EditionValidationError(
            f"{field_name} must be valid JSON"
        ) from exc


def _row_to_record(row: sqlite3.Row) -> EditionRecord:
    return EditionRecord(
        id=row["id"],
        participant_id=row["participant_id"],
        edition_number=row["edition_number"],
        prior_edition_id=row["prior_edition_id"],
        input_id=row["input_id"],
        generation_status=row["generation_status"],
        structured_content=row["structured_content"],
        rendered_title=row["rendered_title"],
        drafted_at=row["drafted_at"],
        reviewed_at=row["reviewed_at"],
        published_at=row["published_at"],
        human_correction_minutes=row["human_correction_minutes"],
        reviewer_notes=row["reviewer_notes"],
        publication_state=row["publication_state"],
    )


def _is_editable(gen_status: str, pub_state: str) -> bool:
    return gen_status == "pending_review" and pub_state == "pending"


def create_edition(
    conn: sqlite3.Connection,
    *,
    participant_id: str,
    edition_number: int,
    prior_edition_id: str | None = None,
    input_id: str | None = None,
    structured_content: str | None = None,
    rendered_title: str | None = None,
) -> EditionRecord:
    _validate_edition(participant_id, edition_number)
    _validate_json_field(structured_content, "structured_content")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    participant_id = participant_id.strip()
    now = _now_utc_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        participant = conn.execute(
            "SELECT 1 FROM participants WHERE id = ? AND status = 'active'",
            (participant_id,),
        ).fetchone()
        if not participant:
            conn.rollback()
            raise EditionValidationError(
                "participant does not exist or is not active"
            )

        existing = conn.execute(
            "SELECT 1 FROM editions "
            "WHERE participant_id = ? AND edition_number = ?",
            (participant_id, edition_number),
        ).fetchone()
        if existing:
            conn.rollback()
            raise EditionStateConflict(
                "edition number already exists for this participant"
            )

        if prior_edition_id is not None:
            prior = conn.execute(
                "SELECT participant_id FROM editions WHERE id = ?",
                (prior_edition_id,),
            ).fetchone()
            if not prior:
                conn.rollback()
                raise EditionValidationError(
                    "prior_edition_id references a non-existent edition"
                )
            if prior["participant_id"] != participant_id:
                conn.rollback()
                raise EditionValidationError(
                    "prior_edition_id must belong to the same participant"
                )

        if input_id is not None:
            inp = conn.execute(
                "SELECT participant_id, deleted_at FROM inputs WHERE id = ?",
                (input_id,),
            ).fetchone()
            if not inp:
                conn.rollback()
                raise EditionValidationError(
                    "input_id references a non-existent input"
                )
            if inp["participant_id"] != participant_id:
                conn.rollback()
                raise EditionValidationError(
                    "input_id must belong to the same participant"
                )
            if inp["deleted_at"] is not None:
                conn.rollback()
                raise EditionValidationError(
                    "input_id references a deleted input"
                )

        edition_id = str(uuid.uuid4())

        cursor = conn.execute(
            "INSERT INTO editions "
            "(id, participant_id, edition_number, prior_edition_id, "
            "input_id, generation_status, structured_content, "
            "rendered_title, publication_state, drafted_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending_review', ?, ?, 'pending', ?)",
            (
                edition_id,
                participant_id,
                edition_number,
                prior_edition_id,
                input_id,
                structured_content,
                rendered_title,
                now,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise RuntimeError("failed to insert edition record")

        conn.commit()
        return EditionRecord(
            id=edition_id,
            participant_id=participant_id,
            edition_number=edition_number,
            prior_edition_id=prior_edition_id,
            input_id=input_id,
            generation_status="pending_review",
            structured_content=structured_content,
            rendered_title=rendered_title,
            drafted_at=now,
            reviewed_at=None,
            published_at=None,
            human_correction_minutes=None,
            reviewer_notes=None,
            publication_state="pending",
        )
    except (
        EditionValidationError,
        EditionStateConflict,
        RepositoryTransactionError,
    ):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_edition_by_id(
    conn: sqlite3.Connection, edition_id: str
) -> EditionRecord | None:
    row = conn.execute(
        f"SELECT {_EDITION_SELECT} FROM editions WHERE id = ?",
        (edition_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_editions_by_participant(
    conn: sqlite3.Connection, participant_id: str
) -> list[EditionRecord]:
    rows = conn.execute(
        f"SELECT {_EDITION_SELECT} FROM editions "
        "WHERE participant_id = ? ORDER BY edition_number",
        (participant_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def update_edition_publication(
    conn: sqlite3.Connection,
    edition_id: str,
    new_publication_state: str,
) -> EditionRecord | None:
    if new_publication_state not in _VALID_PUBLICATION_STATES:
        raise EditionValidationError(
            f"publication_state must be one of {_VALID_PUBLICATION_STATES}"
        )

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute(
            "SELECT publication_state, generation_status, "
            "structured_content FROM editions WHERE id = ?",
            (edition_id,),
        ).fetchone()
        if current is None:
            conn.rollback()
            return None

        allowed = _PUBLICATION_TRANSITIONS.get(
            current["publication_state"], ()
        )
        if new_publication_state not in allowed:
            conn.rollback()
            raise EditionStateConflict(
                f"cannot transition from "
                f"'{current['publication_state']}' to "
                f"'{new_publication_state}'"
            )

        if current["generation_status"] != "pending_review":
            conn.rollback()
            raise EditionStateConflict(
                "can only publish or reject an edition "
                "that is pending review"
            )

        now = _now_utc_iso()
        if new_publication_state == "published":
            content = current["structured_content"]
            if content is None:
                conn.rollback()
                raise EditionStateConflict(
                    "cannot publish an edition without "
                    "structured content"
                )
            try:
                _validate_json_field(content, "structured_content")
            except EditionValidationError:
                conn.rollback()
                raise
            cursor = conn.execute(
                "UPDATE editions SET publication_state = 'published', "
                "reviewed_at = ?, published_at = ? WHERE id = ?",
                (now, now, edition_id),
            )
        elif new_publication_state == "rejected":
            cursor = conn.execute(
                "UPDATE editions SET publication_state = 'rejected', "
                "reviewed_at = ? WHERE id = ?",
                (now, edition_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE editions SET publication_state = ? WHERE id = ?",
                (new_publication_state, edition_id),
            )

        conn.commit()
        if cursor.rowcount == 0:
            return None
        return get_edition_by_id(conn, edition_id)
    except (EditionStateConflict, EditionValidationError,
            RepositoryTransactionError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def update_edition_generation_status(
    conn: sqlite3.Connection,
    edition_id: str,
    new_generation_status: str,
) -> EditionRecord | None:
    if new_generation_status not in _VALID_GENERATION_STATUSES:
        raise EditionValidationError(
            f"generation_status must be one of "
            f"{_VALID_GENERATION_STATUSES}"
        )

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute(
            "SELECT generation_status, publication_state "
            "FROM editions WHERE id = ?",
            (edition_id,),
        ).fetchone()
        if current is None:
            conn.rollback()
            return None

        if current["publication_state"] in _TERMINAL_PUBLICATION_STATES:
            conn.rollback()
            raise EditionStateConflict(
                "cannot change generation status of an edition "
                "with a terminal publication state"
            )

        allowed = _GENERATION_TRANSITIONS.get(
            current["generation_status"], frozenset()
        )
        if new_generation_status not in allowed:
            conn.rollback()
            raise EditionStateConflict(
                f"cannot transition generation status from "
                f"'{current['generation_status']}' to "
                f"'{new_generation_status}'"
            )

        cursor = conn.execute(
            "UPDATE editions SET generation_status = ? WHERE id = ?",
            (new_generation_status, edition_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return get_edition_by_id(conn, edition_id)
    except (EditionValidationError, RepositoryTransactionError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def update_edition_content(
    conn: sqlite3.Connection,
    edition_id: str,
    *,
    structured_content: str | None = None,
    rendered_title: str | None = None,
    reviewer_notes: str | None = None,
) -> EditionRecord | None:
    _validate_json_field(structured_content, "structured_content")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            "SELECT generation_status, publication_state "
            "FROM editions WHERE id = ?",
            (edition_id,),
        ).fetchone()
        if existing is None:
            conn.rollback()
            return None

        if not _is_editable(
            existing["generation_status"],
            existing["publication_state"],
        ):
            conn.rollback()
            raise EditionStateConflict(
                "cannot modify content of a published, rejected, "
                "or non-pending edition"
            )

        now = _now_utc_iso()
        updates = []
        params: list = []
        if structured_content is not None:
            updates.append("structured_content = ?")
            params.append(structured_content)
        if rendered_title is not None:
            updates.append("rendered_title = ?")
            params.append(rendered_title)
        if reviewer_notes is not None:
            updates.append("reviewer_notes = ?")
            params.append(reviewer_notes)

        if not updates:
            conn.rollback()
            return get_edition_by_id(conn, edition_id)

        updates.append("drafted_at = ?")
        params.append(now)
        params.append(edition_id)

        conn.execute(
            f"UPDATE editions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return get_edition_by_id(conn, edition_id)
    except (EditionValidationError, EditionStateConflict,
            RepositoryTransactionError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def delete_edition(conn: sqlite3.Connection, edition_id: str) -> bool:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute(
            "SELECT publication_state FROM editions WHERE id = ?",
            (edition_id,),
        ).fetchone()
        if current is None:
            conn.rollback()
            return False

        if current["publication_state"] == "published":
            conn.rollback()
            raise EditionStateConflict(
                "cannot delete a published edition"
            )

        cursor = conn.execute(
            "UPDATE editions SET generation_status = 'deleted', "
            "publication_state = 'pending' "
            "WHERE id = ? AND generation_status != 'deleted'",
            (edition_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    except (EditionStateConflict, RepositoryTransactionError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def create_edition_with_feedback_applied(
    conn: sqlite3.Connection,
    *,
    participant_id: str,
    edition_number: int,
    prior_edition_id: str | None = None,
    input_id: str | None = None,
    structured_content: str | None = None,
    rendered_title: str | None = None,
    feedback_id: str | None = None,
) -> EditionRecord:
    _validate_edition(participant_id, edition_number)
    _validate_json_field(structured_content, "structured_content")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    participant_id = participant_id.strip()
    now = _now_utc_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        participant = conn.execute(
            "SELECT 1 FROM participants WHERE id = ? AND status = 'active'",
            (participant_id,),
        ).fetchone()
        if not participant:
            conn.rollback()
            raise EditionValidationError(
                "participant does not exist or is not active"
            )

        existing = conn.execute(
            "SELECT 1 FROM editions "
            "WHERE participant_id = ? AND edition_number = ?",
            (participant_id, edition_number),
        ).fetchone()
        if existing:
            conn.rollback()
            raise EditionStateConflict(
                "edition number already exists for this participant"
            )

        if prior_edition_id is not None:
            prior = conn.execute(
                "SELECT participant_id FROM editions WHERE id = ?",
                (prior_edition_id,),
            ).fetchone()
            if not prior:
                conn.rollback()
                raise EditionValidationError(
                    "prior_edition_id references a non-existent edition"
                )
            if prior["participant_id"] != participant_id:
                conn.rollback()
                raise EditionValidationError(
                    "prior_edition_id must belong to the same participant"
                )

        if input_id is not None:
            inp = conn.execute(
                "SELECT participant_id, deleted_at FROM inputs WHERE id = ?",
                (input_id,),
            ).fetchone()
            if not inp:
                conn.rollback()
                raise EditionValidationError(
                    "input_id references a non-existent input"
                )
            if inp["participant_id"] != participant_id:
                conn.rollback()
                raise EditionValidationError(
                    "input_id must belong to the same participant"
                )
            if inp["deleted_at"] is not None:
                conn.rollback()
                raise EditionValidationError(
                    "input_id references a deleted input"
                )

        if feedback_id is not None:
            fb = conn.execute(
                f"SELECT {_FEEDBACK_SELECT} FROM feedback WHERE id = ?",
                (feedback_id,),
            ).fetchone()
            if not fb:
                conn.rollback()
                raise FeedbackValidationError(
                    "feedback_id references a non-existent feedback record"
                )
            if fb["participant_id"] != participant_id:
                conn.rollback()
                raise FeedbackValidationError(
                    "feedback must belong to the same participant"
                )
            if fb["edition_id"] != prior_edition_id:
                conn.rollback()
                raise FeedbackValidationError(
                    "feedback must be for the prior edition"
                )
            if fb["applied_to_next_edition"] != 0:
                conn.rollback()
                raise FeedbackValidationError(
                    "feedback has already been applied"
                )

        edition_id = str(uuid.uuid4())

        cursor = conn.execute(
            "INSERT INTO editions "
            "(id, participant_id, edition_number, prior_edition_id, "
            "input_id, generation_status, structured_content, "
            "rendered_title, publication_state, drafted_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending_review', ?, ?, 'pending', ?)",
            (
                edition_id,
                participant_id,
                edition_number,
                prior_edition_id,
                input_id,
                structured_content,
                rendered_title,
                now,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise RuntimeError("failed to insert edition record")

        if feedback_id is not None:
            cursor = conn.execute(
                "UPDATE feedback SET applied_to_next_edition = 1 "
                "WHERE id = ? AND applied_to_next_edition = 0",
                (feedback_id,),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                raise RuntimeError(
                    "failed to mark feedback as applied"
                )

        conn.commit()
        return EditionRecord(
            id=edition_id,
            participant_id=participant_id,
            edition_number=edition_number,
            prior_edition_id=prior_edition_id,
            input_id=input_id,
            generation_status="pending_review",
            structured_content=structured_content,
            rendered_title=rendered_title,
            drafted_at=now,
            reviewed_at=None,
            published_at=None,
            human_correction_minutes=None,
            reviewer_notes=None,
            publication_state="pending",
        )
    except (
        EditionValidationError,
        EditionStateConflict,
        FeedbackValidationError,
        RepositoryTransactionError,
    ):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
