"""External identity mapping repository.

Maps a verified external identity (provider + subject, e.g. Firebase UID) to an
optional internal traveler and/or operator principal. Firebase only proves who a
user is; Living Travel authorization (traveler/operator, data access) lives here.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class ExternalIdentityRecord:
    id: str
    provider: str
    subject: str
    principal_type: str
    traveler_id: str | None
    operator_id: str | None
    created_at: str
    revoked_at: str | None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


_COLS = [
    "id", "provider", "subject", "principal_type",
    "traveler_id", "operator_id", "created_at", "revoked_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row) -> ExternalIdentityRecord:
    return ExternalIdentityRecord(
        id=row["id"],
        provider=row["provider"],
        subject=row["subject"],
        principal_type=row["principal_type"],
        traveler_id=row["traveler_id"],
        operator_id=row["operator_id"],
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
    )


def get_identity(
    conn: sqlite3.Connection, provider: str, subject: str
) -> ExternalIdentityRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM external_identities "
        "WHERE provider = ? AND subject = ?",
        (provider, subject),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_identity_by_id(
    conn: sqlite3.Connection, identity_id: str
) -> ExternalIdentityRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM external_identities WHERE id = ?", (identity_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def ensure_identity(
    conn: sqlite3.Connection,
    provider: str,
    subject: str,
    *,
    principal_type: str = "pending",
    commit: bool = True,
) -> ExternalIdentityRecord:
    """Return the existing identity for (provider, subject) or create it.

    Uses INSERT ... ON CONFLICT DO NOTHING so concurrent first-login calls
    never raise an unhandled IntegrityError; the canonical row is always
    re-read after the insert attempt.
    """
    existing = get_identity(conn, provider, subject)
    if existing is not None:
        return existing
    identity_id = f"eid_{secrets.token_urlsafe(16)}"
    now = _utcnow()
    conn.execute(
        f"INSERT INTO external_identities ({_SELECT}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (provider, subject) DO NOTHING",
        (identity_id, provider, subject, principal_type, None, None, now, None),
    )
    if commit:
        conn.commit()
    return get_identity(conn, provider, subject)  # type: ignore[return-value]


def link_traveler(
    conn: sqlite3.Connection, identity_id: str, traveler_id: str, *, commit: bool = True
) -> ExternalIdentityRecord | None:
    """Link an identity to a traveler atomically.

    The UPDATE itself enforces: not revoked, not already an operator, and
    traveler_id is either NULL or already this traveler_id (idempotent re-link).
    Returns None if the row was not eligible.
    """
    cur = conn.execute(
        "UPDATE external_identities "
        "SET traveler_id = ?, principal_type = 'traveler' "
        "WHERE id = ? AND revoked_at IS NULL AND operator_id IS NULL "
        "AND (traveler_id IS NULL OR traveler_id = ?)",
        (traveler_id, identity_id, traveler_id),
    )
    if commit:
        conn.commit()
    if cur.rowcount == 0:
        return None
    return get_identity_by_id(conn, identity_id)


def link_operator(
    conn: sqlite3.Connection, identity_id: str, operator_id: str, *, commit: bool = True
) -> ExternalIdentityRecord | None:
    """Link an identity to an operator atomically.

    The UPDATE itself enforces: not revoked, not already a traveler, and
    operator_id is either NULL or already this operator_id (idempotent re-bind).
    Returns None if the row was not eligible.
    """
    cur = conn.execute(
        "UPDATE external_identities "
        "SET operator_id = ?, principal_type = 'operator' "
        "WHERE id = ? AND revoked_at IS NULL AND traveler_id IS NULL "
        "AND (operator_id IS NULL OR operator_id = ?)",
        (operator_id, identity_id, operator_id),
    )
    if commit:
        conn.commit()
    if cur.rowcount == 0:
        return None
    return get_identity_by_id(conn, identity_id)


def revoke_identity(
    conn: sqlite3.Connection, identity_id: str, *, commit: bool = True
) -> bool:
    now = _utcnow()
    cur = conn.execute(
        "UPDATE external_identities SET revoked_at = ? WHERE id = ?",
        (now, identity_id),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0
