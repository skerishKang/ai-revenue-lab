"""Traveler invitation claim against a verified external identity.

Flow: Firebase login -> submit invitation code -> one-way digest verification ->
link the verified (provider, subject) identity to a traveler. The raw invitation
code is never stored; only its SHA-256 digest exists in ``traveler_tokens``.
Claiming consumes the active token so a code cannot be replayed, and an identity
already bound to a different traveler cannot re-claim.

Transaction contract: ``claim_invitation`` owns the entire transaction. It
performs a single commit on success and rolls back on any failure path. Callers
must NOT wrap the call in an additional ``with conn:`` or issue commits.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app import external_identity_repository as eid_repo
from app.security import constant_time_compare, hash_token


@dataclass(frozen=True)
class ClaimResult:
    ok: bool
    traveler_id: str | None = None
    error: str | None = None  # generic, secret-safe code


def _find_active_token(conn: sqlite3.Connection, code: str):
    digest = hash_token(code)
    row = conn.execute(
        "SELECT id, traveler_id, token_hash FROM traveler_tokens WHERE is_active = 1",
    ).fetchall()
    for r in row:
        if constant_time_compare(r["token_hash"], digest):
            return r
    return None


def _consume_token_if_active(conn: sqlite3.Connection, token_id: str) -> bool:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cursor = conn.execute(
        "UPDATE traveler_tokens "
        "SET is_active = 0, rotated_at = ? "
        "WHERE id = ? AND is_active = 1",
        (now, token_id),
    )
    return cursor.rowcount == 1


def claim_invitation(
    conn: sqlite3.Connection,
    *,
    provider: str,
    subject: str,
    invitation_code: str,
) -> ClaimResult:
    """Link a verified external identity to a traveler via an invitation code.

    Transaction ownership: this function commits on success and rolls back on
    any failure. The caller must not issue additional commits or wrap in
    ``with conn:``.
    """
    if not invitation_code:
        return ClaimResult(ok=False, error="invalid_invitation")

    try:
        token_row = _find_active_token(conn, invitation_code)
        if token_row is None:
            conn.rollback()
            return ClaimResult(ok=False, error="invalid_invitation")

        traveler_id = token_row["traveler_id"]
        traveler = conn.execute(
            "SELECT status FROM travelers WHERE id = ?", (traveler_id,)
        ).fetchone()
        if traveler is None or traveler["status"] != "active":
            conn.rollback()
            return ClaimResult(ok=False, error="traveler_inactive")

        existing_claim = conn.execute(
            "SELECT subject FROM external_identities "
            "WHERE traveler_id = ? AND revoked_at IS NULL",
            (traveler_id,),
        ).fetchone()
        if existing_claim is not None and existing_claim["subject"] != subject:
            conn.rollback()
            return ClaimResult(ok=False, error="invalid_invitation")

        identity = eid_repo.get_identity(conn, provider, subject)
        if identity is not None:
            if identity.is_revoked:
                conn.rollback()
                return ClaimResult(ok=False, error="identity_revoked")
            if identity.operator_id is not None:
                conn.rollback()
                return ClaimResult(ok=False, error="invalid_invitation")
            if identity.traveler_id is not None:
                if identity.traveler_id == traveler_id:
                    if not _consume_token_if_active(conn, token_row["id"]):
                        conn.rollback()
                        return ClaimResult(ok=False, error="invalid_invitation")
                    conn.commit()
                    return ClaimResult(ok=True, traveler_id=traveler_id)
                conn.rollback()
                return ClaimResult(ok=False, error="invalid_invitation")
        else:
            identity = eid_repo.ensure_identity(
                conn, provider, subject, principal_type="traveler", commit=False
            )

        if not _consume_token_if_active(conn, token_row["id"]):
            conn.rollback()
            return ClaimResult(ok=False, error="invalid_invitation")

        linked = eid_repo.link_traveler(conn, identity.id, traveler_id, commit=False)
        if linked is None:
            conn.rollback()
            return ClaimResult(ok=False, error="invalid_invitation")

        conn.commit()
        return ClaimResult(ok=True, traveler_id=traveler_id)
    except Exception:
        conn.rollback()
        return ClaimResult(ok=False, error="invalid_invitation")
