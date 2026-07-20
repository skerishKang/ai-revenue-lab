import sqlite3
import uuid
from dataclasses import dataclass

from app.db import transaction_scope
from app.domain.models import PilotEvidenceInput
from app.repositories.common import now_utc_iso


@dataclass(frozen=True)
class PilotEvidenceRecord:
    id: str
    reader_id: str
    brief_id: str
    evidence_type: str
    anonymous_token: str
    detail: str
    recorded_at: str


_EVIDENCE_COLS = [
    "id", "reader_id", "brief_id", "evidence_type", "anonymous_token",
    "detail", "recorded_at",
]
_EVIDENCE_SELECT = ", ".join(_EVIDENCE_COLS)


def _row_to_record(row: sqlite3.Row) -> PilotEvidenceRecord:
    return PilotEvidenceRecord(
        id=row["id"],
        reader_id=row["reader_id"],
        brief_id=row["brief_id"],
        evidence_type=row["evidence_type"],
        anonymous_token=row["anonymous_token"],
        detail=row["detail"],
        recorded_at=row["recorded_at"],
    )


def record_evidence(
    conn: sqlite3.Connection, evidence: PilotEvidenceInput
) -> PilotEvidenceRecord:
    """Record a privacy-safe pilot signal.

    Only anonymous tokens and evidence type are stored; no personal
    identifiers are persisted.
    """
    now = now_utc_iso()
    with transaction_scope(conn):
        evidence_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO pilot_evidence (
                id, reader_id, brief_id, evidence_type, anonymous_token,
                detail, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                evidence.reader_id,
                evidence.brief_id,
                evidence.evidence_type.value,
                evidence.anonymous_token,
                evidence.detail,
                now,
            ),
        )
        return get_evidence_by_id(conn, evidence_id)


def get_evidence_by_id(
    conn: sqlite3.Connection, evidence_id: str
) -> PilotEvidenceRecord | None:
    row = conn.execute(
        f"SELECT {_EVIDENCE_SELECT} FROM pilot_evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def list_evidence_for_reader(
    conn: sqlite3.Connection, reader_id: str
) -> list[PilotEvidenceRecord]:
    rows = conn.execute(
        f"SELECT {_EVIDENCE_SELECT} FROM pilot_evidence WHERE reader_id = ? "
        "ORDER BY recorded_at, id",
        (reader_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def count_evidence(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM pilot_evidence").fetchone()
    return int(row["n"])
