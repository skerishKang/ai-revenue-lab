from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.participant_repository import RepositoryTransactionError, _now_utc_iso

if TYPE_CHECKING:
    from app.db_runtime import RuntimeConnection

MAX_CLAIM_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 600


class GenerationRequestError(Exception):
    """Raised for invalid generation-request operations."""


class GenerationRequestOwnershipError(GenerationRequestError):
    """Raised when a claim is attempted by a non-owner of the idempotency key."""


@dataclass(frozen=True)
class GenerationRequestRecord:
    id: str
    idempotency_key: str
    participant_id: str
    input_id: str
    edition_id: str | None
    status: str
    claim_token: str
    lease_expires_at: str | None
    failed_at: str | None
    failure_category: str | None
    created_at: str
    completed_at: str | None
    updated_at: str
    already_claimed: bool = False


_SELECT = (
    "id, idempotency_key, participant_id, input_id, edition_id, "
    "status, claim_token, lease_expires_at, failed_at, failure_category, "
    "created_at, completed_at, updated_at"
)


def _add_seconds(iso_ts: str, seconds: int) -> str:
    dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    dt += timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _row_to_record(
    row: Any, *, already_claimed: bool = False
) -> GenerationRequestRecord:
    return GenerationRequestRecord(
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        participant_id=row["participant_id"],
        input_id=row["input_id"],
        edition_id=row["edition_id"],
        status=row["status"],
        claim_token=row["claim_token"],
        lease_expires_at=row["lease_expires_at"],
        failed_at=row["failed_at"],
        failure_category=row["failure_category"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        updated_at=row["updated_at"],
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
    input_id: str,
    claim_token: str | None = None,
    lease_duration_seconds: int = DEFAULT_LEASE_SECONDS,
    now: str | None = None,
) -> GenerationRequestRecord:
    """Atomically claim a generation request by idempotency_key.

    Uses ``INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`` and inspects
    ``rowcount``.  On conflict the existing row is locked (``SELECT ...
    FOR UPDATE`` on PostgreSQL) and evaluated:

    - **completed** — replay (``already_claimed=True``, ``edition_id`` set).
    - **claimed + valid lease** — in-progress (``already_claimed=True``).
    - **claimed + expired lease** — conditional reclaim with a new token/lease.
    - **failed** — same-owner reclaim (reset to claimed).

    Ownership is verified on every conflict path: ``participant_id`` and
    ``input_id`` must match the existing record, otherwise
    :class:`GenerationRequestOwnershipError` is raised with a fixed safe
    message (no raw identifiers are interpolated).
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise GenerationRequestError(
            "idempotency_key must be a non-empty string"
        )
    if not isinstance(participant_id, str) or not participant_id.strip():
        raise GenerationRequestError(
            "participant_id must be a non-empty string"
        )
    if not isinstance(input_id, str) or not input_id.strip():
        raise GenerationRequestError("input_id must be a non-empty string")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    idempotency_key = idempotency_key.strip()
    participant_id = participant_id.strip()
    input_id = input_id.strip()
    request_id = str(uuid.uuid4())
    token = claim_token or str(uuid.uuid4())
    now = now or _now_utc_iso()
    lease_expires_at = _add_seconds(now, lease_duration_seconds)
    lock_suffix = getattr(conn, "row_lock_suffix", "")

    conn.begin_write()
    try:
        for _attempt in range(MAX_CLAIM_ATTEMPTS):
            cursor = conn.execute(
                "INSERT INTO generation_requests "
                "(id, idempotency_key, participant_id, input_id, status, "
                "claim_token, lease_expires_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'claimed', ?, ?, ?, ?) "
                "ON CONFLICT (idempotency_key) DO NOTHING",
                (
                    request_id,
                    idempotency_key,
                    participant_id,
                    input_id,
                    token,
                    lease_expires_at,
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 1:
                conn.commit()
                return GenerationRequestRecord(
                    id=request_id,
                    idempotency_key=idempotency_key,
                    participant_id=participant_id,
                    input_id=input_id,
                    edition_id=None,
                    status="claimed",
                    claim_token=token,
                    lease_expires_at=lease_expires_at,
                    failed_at=None,
                    failure_category=None,
                    created_at=now,
                    completed_at=None,
                    updated_at=now,
                    already_claimed=False,
                )

            existing = conn.execute(
                f"SELECT {_SELECT} FROM generation_requests "
                f"WHERE idempotency_key = ?{lock_suffix}",
                (idempotency_key,),
            ).fetchone()

            if existing is None:
                continue

            if (
                existing["participant_id"] != participant_id
                or existing["input_id"] != input_id
            ):
                conn.rollback()
                raise GenerationRequestOwnershipError(
                    "generation request belongs to a different participant "
                    "or input"
                )

            if existing["status"] == "completed":
                conn.commit()
                return _row_to_record(existing, already_claimed=True)

            if existing["status"] == "claimed":
                existing_lease = existing["lease_expires_at"]
                if existing_lease is not None and existing_lease > now:
                    conn.commit()
                    return _row_to_record(existing, already_claimed=True)
                cursor = conn.execute(
                    "UPDATE generation_requests "
                    "SET claim_token = ?, lease_expires_at = ?, updated_at = ? "
                    "WHERE idempotency_key = ? AND status = 'claimed' "
                    "AND (lease_expires_at IS NULL OR lease_expires_at <= ?)",
                    (token, lease_expires_at, now, idempotency_key, now),
                )
                if cursor.rowcount == 1:
                    conn.commit()
                    return GenerationRequestRecord(
                        id=existing["id"],
                        idempotency_key=idempotency_key,
                        participant_id=participant_id,
                        input_id=input_id,
                        edition_id=None,
                        status="claimed",
                        claim_token=token,
                        lease_expires_at=lease_expires_at,
                        failed_at=None,
                        failure_category=None,
                        created_at=existing["created_at"],
                        completed_at=None,
                        updated_at=now,
                        already_claimed=False,
                    )
                continue

            if existing["status"] == "failed":
                cursor = conn.execute(
                    "UPDATE generation_requests "
                    "SET status = 'claimed', claim_token = ?, "
                    "lease_expires_at = ?, failed_at = NULL, "
                    "failure_category = NULL, updated_at = ? "
                    "WHERE idempotency_key = ? AND status = 'failed'",
                    (token, lease_expires_at, now, idempotency_key),
                )
                if cursor.rowcount == 1:
                    conn.commit()
                    return GenerationRequestRecord(
                        id=existing["id"],
                        idempotency_key=idempotency_key,
                        participant_id=participant_id,
                        input_id=input_id,
                        edition_id=None,
                        status="claimed",
                        claim_token=token,
                        lease_expires_at=lease_expires_at,
                        failed_at=None,
                        failure_category=None,
                        created_at=existing["created_at"],
                        completed_at=None,
                        updated_at=now,
                        already_claimed=False,
                    )
                continue

        conn.rollback()
        raise GenerationRequestError(
            "unable to claim generation request after maximum attempts"
        )
    except (GenerationRequestError, GenerationRequestOwnershipError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def complete_generation_request(
    conn: RuntimeConnection,
    *,
    idempotency_key: str,
    edition_id: str,
    claim_token: str,
    now: str | None = None,
) -> None:
    """Record the produced edition against a claimed generation request.

    The UPDATE is conditional on ``status = 'claimed'`` and a matching
    ``claim_token`` so that a stale or foreign token cannot complete a
    request it does not own.
    """
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    now = now or _now_utc_iso()
    conn.begin_write()
    try:
        cursor = conn.execute(
            "UPDATE generation_requests "
            "SET edition_id = ?, status = 'completed', completed_at = ?, "
            "updated_at = ? "
            "WHERE idempotency_key = ? AND status = 'claimed' "
            "AND COALESCE(claim_token, '') = ?",
            (edition_id, now, now, idempotency_key, claim_token),
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


def fail_generation_request(
    conn: RuntimeConnection,
    *,
    idempotency_key: str,
    claim_token: str,
    failure_category: str,
    now: str | None = None,
) -> None:
    """Transition a claimed generation request to the failed state.

    The UPDATE is conditional on ``status = 'claimed'`` and a matching
    ``claim_token``.  A failed request can later be reclaimed by the same
    owner via :func:`claim_generation_request`.
    """
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    now = now or _now_utc_iso()
    conn.begin_write()
    try:
        cursor = conn.execute(
            "UPDATE generation_requests "
            "SET status = 'failed', failed_at = ?, failure_category = ?, "
            "updated_at = ? "
            "WHERE idempotency_key = ? AND status = 'claimed' "
            "AND COALESCE(claim_token, '') = ?",
            (now, failure_category, now, idempotency_key, claim_token),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise GenerationRequestError(
                "generation request is not in a fail-eligible claimed state"
            )
    except GenerationRequestError:
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
