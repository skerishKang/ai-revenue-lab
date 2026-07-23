from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.participant_repository import RepositoryTransactionError, _now_utc_iso

if TYPE_CHECKING:
    from app.db_runtime import RuntimeConnection


class GenerationRequestError(Exception):
    """Raised for invalid generation-request operations."""


@dataclass(frozen=True)
class GenerationRequestRecord:
    id: str
    idempotency_key: str
    participant_id: str
    input_id: str | None
    edition_id: str | None
    status: str
    created_at: str
    completed_at: str | None
    already_claimed: bool = False


_SELECT = (
    "id, idempotency_key, participant_id, input_id, edition_id, "
    "status, created_at, completed_at"
)


def _row_to_record(row: Any, *, already_claimed: bool = False) -> GenerationRequestRecord:
    return GenerationRequestRecord(
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        participant_id=row["participant_id"],
        input_id=row["input_id"],
        edition_id=row["edition_id"],
        status=row["status"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        already_claimed=already_claimed,
    )


def get_generation_request_by_key(
    conn: RuntimeConnection,
    idempotency_key: str,
) -> GenerationRequestRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM generation_requests WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def claim_generation_request(
    conn: RuntimeConnection,
    *,
    idempotency_key: str,
    participant_id: str,
    input_id: str | None = None,
) -> GenerationRequestRecord:
    """Atomically claim a generation request by idempotency_key.

    Uses ``INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`` and inspects
    ``rowcount`` so that two concurrent submissions of the same key never both
    succeed: exactly one caller observes ``already_claimed=False`` (it owns the
    claim); every other caller observes ``already_claimed=True`` and receives
    the existing record (which carries ``edition_id`` once completed).
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise GenerationRequestError("idempotency_key must be a non-empty string")
    if not isinstance(participant_id, str) or not participant_id.strip():
        raise GenerationRequestError("participant_id must be a non-empty string")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    idempotency_key = idempotency_key.strip()
    participant_id = participant_id.strip()
    request_id = str(uuid.uuid4())
    now = _now_utc_iso()

    conn.begin_write()
    try:
        cursor = conn.execute(
            "INSERT INTO generation_requests "
            "(id, idempotency_key, participant_id, input_id, status, created_at) "
            "VALUES (?, ?, ?, ?, 'claimed', ?) "
            "ON CONFLICT (idempotency_key) DO NOTHING",
            (request_id, idempotency_key, participant_id, input_id, now),
        )
        claimed_now = cursor.rowcount == 1
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise

    if claimed_now:
        return GenerationRequestRecord(
            id=request_id,
            idempotency_key=idempotency_key,
            participant_id=participant_id,
            input_id=input_id,
            edition_id=None,
            status="claimed",
            created_at=now,
            completed_at=None,
            already_claimed=False,
        )

    existing = get_generation_request_by_key(conn, idempotency_key)
    if existing is None:
        raise GenerationRequestError(
            "idempotency claim conflicted but no record was found"
        )
    return GenerationRequestRecord(
        id=existing.id,
        idempotency_key=existing.idempotency_key,
        participant_id=existing.participant_id,
        input_id=existing.input_id,
        edition_id=existing.edition_id,
        status=existing.status,
        created_at=existing.created_at,
        completed_at=existing.completed_at,
        already_claimed=True,
    )


def complete_generation_request(
    conn: RuntimeConnection,
    *,
    idempotency_key: str,
    edition_id: str,
) -> None:
    """Record the produced edition against a claimed generation request."""
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    now = _now_utc_iso()
    conn.begin_write()
    try:
        cursor = conn.execute(
            "UPDATE generation_requests "
            "SET edition_id = ?, status = 'completed', completed_at = ? "
            "WHERE idempotency_key = ? AND status = 'claimed'",
            (edition_id, now, idempotency_key),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise GenerationRequestError(
                "generation request is not in the claimed state"
            )
    except GenerationRequestError:
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
