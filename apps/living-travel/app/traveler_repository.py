"""Traveler repository for Living Travel."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.enums import TravelerStatus, TripContext


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class TravelerRecord:
    id: str
    display_name: str
    preferred_language: str
    destination: str
    trip_duration_nights: int
    trip_context: str
    budget_tendency: str
    pace_preference: str
    interests: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    tone_preference: str = "calm"
    length_preference: str = "medium"
    status: str = TravelerStatus.active
    created_at: str = ""
    updated_at: str = ""


def _row_to_record(row: sqlite3.Row) -> TravelerRecord:
    return TravelerRecord(
        id=row["id"],
        display_name=row["display_name"],
        preferred_language=row["preferred_language"],
        destination=row["destination"],
        trip_duration_nights=row["trip_duration_nights"],
        trip_context=row["trip_context"],
        budget_tendency=row["budget_tendency"],
        pace_preference=row["pace_preference"],
        interests=json.loads(row["interests"]) if row["interests"] else [],
        exclusions=json.loads(row["exclusions"]) if row["exclusions"] else [],
        tone_preference=row["tone_preference"],
        length_preference=row["length_preference"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_COLS = [
    "id", "display_name", "preferred_language", "destination",
    "trip_duration_nights", "trip_context", "budget_tendency",
    "pace_preference", "interests", "exclusions", "tone_preference",
    "length_preference", "status", "created_at", "updated_at",
]
_SELECT = ", ".join(_COLS)


def create_traveler(
    conn: sqlite3.Connection,
    *,
    display_name: str,
    destination: str,
    trip_duration_nights: int = 2,
    trip_context: str = "solo",
    budget_tendency: str = "moderate",
    pace_preference: str = "comfortable",
    interests: list[str] | None = None,
    exclusions: list[str] | None = None,
    tone_preference: str = "calm",
    length_preference: str = "medium",
    preferred_language: str = "ko",
) -> TravelerRecord:
    now = _utcnow()
    traveler_id = f"trav_{secrets.token_urlsafe(16)}"
    interests = interests or []
    exclusions = exclusions or []
    conn.execute(
        f"INSERT INTO travelers ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            traveler_id, display_name, preferred_language, destination,
            trip_duration_nights, trip_context, budget_tendency,
            pace_preference, json.dumps(interests), json.dumps(exclusions),
            tone_preference, length_preference, TravelerStatus.active, now, now,
        ),
    )
    conn.commit()
    return get_traveler_by_id(conn, traveler_id)  # type: ignore[return-value]


def get_traveler_by_id(conn: sqlite3.Connection, traveler_id: str) -> TravelerRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM travelers WHERE id = ? AND status = ?",
        (traveler_id, TravelerStatus.active),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_traveler_by_id_admin(conn: sqlite3.Connection, traveler_id: str) -> TravelerRecord | None:
    """Get any traveler including inactive."""
    row = conn.execute(
        f"SELECT {_SELECT} FROM travelers WHERE id = ?", (traveler_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_all_travelers(conn: sqlite3.Connection) -> list[TravelerRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM travelers WHERE status = ?",
        (TravelerStatus.active,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_all_travelers_admin(conn: sqlite3.Connection) -> list[TravelerRecord]:
    """Get all travelers including inactive."""
    rows = conn.execute(f"SELECT {_SELECT} FROM travelers ORDER BY created_at DESC").fetchall()
    return [_row_to_record(r) for r in rows]


def is_traveler_active(conn: sqlite3.Connection, traveler_id: str) -> bool:
    """Check if a traveler exists and is active (not deleted)."""
    row = conn.execute(
        "SELECT 1 FROM travelers WHERE id = ? AND status = ?",
        (traveler_id, TravelerStatus.active),
    ).fetchone()
    return row is not None


def activate_traveler(conn: sqlite3.Connection, traveler_id: str, *, commit: bool = True) -> bool:
    """Re-activate a previously deactivated traveler."""
    now = _utcnow()
    cur = conn.execute(
        "UPDATE travelers SET status = ?, updated_at = ? WHERE id = ?",
        (TravelerStatus.active, now, traveler_id),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0


def delete_traveler(conn: sqlite3.Connection, traveler_id: str, *, commit: bool = True) -> bool:
    now = _utcnow()
    cur = conn.execute(
        "UPDATE travelers SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
        (TravelerStatus.deleted, now, traveler_id, TravelerStatus.active),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0


def update_traveler_preferences(
    conn: sqlite3.Connection,
    traveler_id: str,
    *,
    destination: str | None = None,
    trip_duration_nights: int | None = None,
    interests: list[str] | None = None,
    trip_context: str | None = None,
    budget_tendency: str | None = None,
    pace_preference: str | None = None,
    exclusions: list[str] | None = None,
    tone_preference: str | None = None,
    length_preference: str | None = None,
    preferred_language: str | None = None,
    commit: bool = True,
) -> bool:
    """Update traveler preferences."""
    now = _utcnow()
    updates: list[str] = []
    params: list = []
    if destination is not None:
        updates.append("destination = ?")
        params.append(destination)
    if trip_duration_nights is not None:
        updates.append("trip_duration_nights = ?")
        params.append(trip_duration_nights)
    if interests is not None:
        updates.append("interests = ?")
        params.append(json.dumps(interests))
    if trip_context is not None:
        updates.append("trip_context = ?")
        params.append(trip_context)
    if budget_tendency is not None:
        updates.append("budget_tendency = ?")
        params.append(budget_tendency)
    if pace_preference is not None:
        updates.append("pace_preference = ?")
        params.append(pace_preference)
    if exclusions is not None:
        updates.append("exclusions = ?")
        params.append(json.dumps(exclusions))
    if tone_preference is not None:
        updates.append("tone_preference = ?")
        params.append(tone_preference)
    if length_preference is not None:
        updates.append("length_preference = ?")
        params.append(length_preference)
    if preferred_language is not None:
        updates.append("preferred_language = ?")
        params.append(preferred_language)
    updates.append("updated_at = ?")
    params.append(now)
    params.append(traveler_id)
    cur = conn.execute(
        f"UPDATE travelers SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0
