"""Pilot evidence repository for Living Travel."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class PilotEvidenceRecord:
    id: str
    evidence_type: str
    traveler_id: str
    edition_id: str
    offer_description: str
    price_krw: int
    consent_recorded: bool
    payment_evidence: str
    created_at: str


def _row_to_record(row: sqlite3.Row) -> PilotEvidenceRecord:
    return PilotEvidenceRecord(
        id=row["id"],
        evidence_type=row["evidence_type"],
        traveler_id=row["traveler_id"],
        edition_id=row["edition_id"],
        offer_description=row["offer_description"],
        price_krw=row["price_krw"],
        consent_recorded=bool(row["consent_recorded"]),
        payment_evidence=row["payment_evidence"],
        created_at=row["created_at"],
    )


_COLS = [
    "id", "evidence_type", "traveler_id", "edition_id",
    "offer_description", "price_krw", "consent_recorded",
    "payment_evidence", "created_at",
]
_SELECT = ", ".join(_COLS)


def create_pilot_evidence(
    conn: sqlite3.Connection,
    *,
    evidence_type: str,
    traveler_id: str,
    edition_id: str,
    offer_description: str,
    price_krw: int = 0,
    consent_recorded: bool = False,
    payment_evidence: str = "",
    commit: bool = True,
) -> PilotEvidenceRecord:
    now = _utcnow()
    evidence_id = f"pe_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO pilot_evidence ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            evidence_id, evidence_type, traveler_id, edition_id,
            offer_description, price_krw, int(consent_recorded),
            payment_evidence, now,
        ),
    )
    if commit:
        conn.commit()
    return get_pilot_evidence_by_id(conn, evidence_id)  # type: ignore[return-value]


def get_pilot_evidence_by_id(
    conn: sqlite3.Connection, evidence_id: str
) -> PilotEvidenceRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM pilot_evidence WHERE id = ?", (evidence_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def get_pilot_evidence_by_traveler(
    conn: sqlite3.Connection, traveler_id: str
) -> list[PilotEvidenceRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM pilot_evidence WHERE traveler_id = ? ORDER BY created_at",
        (traveler_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
