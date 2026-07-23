"""Deactivation request repository (backend-aware).

Creates at most one durable pending deactivation request per traveler.
Uses SQLite ``INSERT OR IGNORE`` on the SQLite backend and the equivalent
``INSERT ... ON CONFLICT DO NOTHING`` on PostgreSQL, relying on the partial
unique index ``ux_deactivation_requests_one_pending``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.security import generate_high_entropy_token


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def create_deactivation_request(conn, traveler_id: str) -> str:
    """Idempotently create a pending deactivation request; returns its id."""
    now = _utcnow()
    request_id = "dr_" + generate_high_entropy_token(8)
    backend = getattr(conn, "backend", "sqlite")
    if backend == "postgresql":
        conn.execute(
            "INSERT INTO deactivation_requests "
            "(id, traveler_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'pending', ?, ?) ON CONFLICT DO NOTHING",
            (request_id, traveler_id, now, now),
        )
    else:
        conn.execute(
            "INSERT OR IGNORE INTO deactivation_requests "
            "(id, traveler_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (request_id, traveler_id, now, now),
        )
    return request_id
