"""Transactional reader revocation for World Feed."""

from __future__ import annotations

from app.privacy import revoked_reader_token
from app.repositories import reader_repository


def delete_reader(conn, reader_id: str) -> dict:
    """Revoke a reader transactionally (idempotent after close/reopen).

    Personal brief linkage and private feedback text are removed. Shared
    canonical events and source records remain as non-personal records.
    Pilot evidence keeps only anonymized linkage for export-safe audits.
    """
    from app.db import atomic

    token = revoked_reader_token(reader_id)
    with atomic(conn):
        existing = reader_repository.get_reader_by_id(conn, reader_id)
        if existing is None:
            return {"reader_id": reader_id, "status": "already_absent"}
        conn.execute(
            "UPDATE pilot_evidence SET reader_id = ?, detail = '' "
            "WHERE reader_id = ?",
            (token, reader_id),
        )
        conn.execute("DELETE FROM feedback WHERE reader_id = ?", (reader_id,))
        conn.execute("DELETE FROM briefs WHERE reader_id = ?", (reader_id,))
        conn.execute("DELETE FROM readers WHERE reader_id = ?", (reader_id,))
    return {"reader_id": reader_id, "status": "deleted", "revoked_as": token}
