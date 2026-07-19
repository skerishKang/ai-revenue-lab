import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app import security


@dataclass(frozen=True)
class ParticipantRecord:
    id: str
    display_name: str
    preferred_language: str
    status: str
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True)
class ProvisionedParticipant:
    participant: ParticipantRecord
    one_time_token: str


class DuplicateParticipantError(RuntimeError):
    pass


class TokenProvisioningError(RuntimeError):
    pass


class RepositoryTransactionError(RuntimeError):
    pass


MAX_TOKEN_COLLISION_RETRIES = 3

_PARTICIPANT_COLS = [
    "id",
    "display_name",
    "preferred_language",
    "status",
    "created_at",
    "updated_at",
    "deleted_at",
]
_PARTICIPANT_SELECT = ", ".join(_PARTICIPANT_COLS)


def _now_utc_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _row_to_record(row: sqlite3.Row) -> ParticipantRecord:
    return ParticipantRecord(
        id=row["id"],
        display_name=row["display_name"],
        preferred_language=row["preferred_language"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def create_participant(
    conn: sqlite3.Connection,
    *,
    participant_id: str,
    display_name: str,
    preferred_language: str = "ko",
) -> ProvisionedParticipant:
    if not isinstance(participant_id, str):
        raise TypeError("participant_id must be a string")
    if not participant_id.strip():
        raise ValueError("participant_id must not be blank")
    if participant_id != participant_id.strip():
        raise ValueError(
            "participant_id must not contain leading or trailing whitespace"
        )

    if not isinstance(display_name, str):
        raise TypeError("display_name must be a string")
    if not display_name.strip():
        raise ValueError("display_name must not be blank")

    if preferred_language not in ("ko", "en"):
        raise ValueError("preferred_language must be 'ko' or 'en'")

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    participant_id = participant_id.strip()
    display_name = display_name.strip()
    now = _now_utc_iso()

    conn.execute("BEGIN IMMEDIATE")

    try:
        existing = conn.execute(
            "SELECT 1 FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
        if existing:
            conn.rollback()
            raise DuplicateParticipantError(
                "participant identifier already exists"
            )

        for _ in range(MAX_TOKEN_COLLISION_RETRIES):
            raw_token = security.generate_token()
            token_hash = security.hash_token(raw_token)

            cursor = conn.execute(
                "INSERT INTO participants "
                "(id, display_name, access_token_hash, preferred_language, "
                "tone_preference, length_preference, status, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'calm_editorial', 'standard', "
                "'active', ?, ?) "
                "ON CONFLICT(access_token_hash) DO NOTHING",
                (
                    participant_id,
                    display_name,
                    token_hash,
                    preferred_language,
                    now,
                    now,
                ),
            )

            if cursor.rowcount > 0:
                record = ParticipantRecord(
                    id=participant_id,
                    display_name=display_name,
                    preferred_language=preferred_language,
                    status="active",
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
                conn.commit()
                return ProvisionedParticipant(
                    participant=record,
                    one_time_token=raw_token,
                )

        conn.rollback()
        raise TokenProvisioningError(
            "participant token provisioning failed after bounded retries"
        )
    except (
        DuplicateParticipantError,
        TokenProvisioningError,
    ):
        raise
    except Exception:
        conn.rollback()
        raise


def get_active_participant_by_token(
    conn: sqlite3.Connection, raw_token: str
) -> ParticipantRecord | None:
    if not isinstance(raw_token, str) or not raw_token:
        return None

    candidate_hash = security.hash_token(raw_token)

    row = conn.execute(
        f"SELECT {_PARTICIPANT_SELECT}, access_token_hash "
        "FROM participants "
        "WHERE access_token_hash = ? "
        "AND status = 'active' "
        "AND deleted_at IS NULL",
        (candidate_hash,),
    ).fetchone()

    if row is None:
        return None

    if not security.verify_token(raw_token, row["access_token_hash"]):
        return None

    return _row_to_record(row)


def get_participant_by_id(
    conn: sqlite3.Connection, participant_id: str
) -> ParticipantRecord | None:
    row = conn.execute(
        f"SELECT {_PARTICIPANT_SELECT} FROM participants WHERE id = ?",
        (participant_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def delete_participant(
    conn: sqlite3.Connection, participant_id: str
) -> bool:
    if not isinstance(participant_id, str) or not participant_id:
        return False

    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )

    now = _now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")

    try:
        cursor = conn.execute(
            "UPDATE participants SET status = 'deleted', deleted_at = ?, "
            "updated_at = ? WHERE id = ? AND status = 'active'",
            (now, now, participant_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise
