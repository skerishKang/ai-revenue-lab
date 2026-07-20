"""Input repository for Living Travel."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class InputRecord:
    id: str
    traveler_id: str
    sequence_number: int
    raw_text: str
    destination: str
    trip_duration_nights: int
    consent_confirmed: bool
    submitted_at: str


def _row_to_record(row: sqlite3.Row) -> InputRecord:
    return InputRecord(
        id=row["id"],
        traveler_id=row["traveler_id"],
        sequence_number=row["sequence_number"],
        raw_text=row["raw_text"],
        destination=row["destination"],
        trip_duration_nights=row["trip_duration_nights"],
        consent_confirmed=bool(row["consent_confirmed"]),
        submitted_at=row["submitted_at"],
    )


_COLS = [
    "id", "traveler_id", "sequence_number", "raw_text", "destination",
    "trip_duration_nights", "consent_confirmed", "submitted_at",
]
_SELECT = ", ".join(_COLS)


def create_input(
    conn: sqlite3.Connection,
    *,
    traveler_id: str,
    raw_text: str,
    destination: str,
    trip_duration_nights: int = 2,
    consent_confirmed: bool = True,
) -> InputRecord:
    now = _utcnow()
    input_id = f"in_{secrets.token_urlsafe(16)}"

    last = conn.execute(
        "SELECT MAX(sequence_number) as max_seq FROM travel_inputs WHERE traveler_id = ?",
        (traveler_id,),
    ).fetchone()
    seq = (last["max_seq"] or 0) + 1 if last else 1

    conn.execute(
        f"INSERT INTO travel_inputs ({_SELECT}) VALUES (?,?,?,?,?,?,?,?)",
        (input_id, traveler_id, seq, raw_text, destination, trip_duration_nights, int(consent_confirmed), now),
    )
    conn.commit()
    return get_input_by_id(conn, input_id)  # type: ignore[return-value]


def get_input_by_id(conn: sqlite3.Connection, input_id: str) -> InputRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM travel_inputs WHERE id = ?", (input_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_inputs_by_traveler(conn: sqlite3.Connection, traveler_id: str) -> list[InputRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM travel_inputs WHERE traveler_id = ? ORDER BY sequence_number",
        (traveler_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
