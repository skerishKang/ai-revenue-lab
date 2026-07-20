"""Pilot evidence repository — privacy-safe evidence records.

Records evidence categories without claiming actual events. No payer
identity, account/card data, credentials, or private reader text.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class PilotEvidenceRecord:
    id: str
    evidence_category: str
    canon_episode_id: str | None
    branch_episode_id: str | None
    reader_id: str | None
    evidence_data_json: str
    privacy_safe: bool
    created_at: str


_COLS = [
    "id", "evidence_category", "canon_episode_id", "branch_episode_id",
    "reader_id", "evidence_data_json", "privacy_safe", "created_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> PilotEvidenceRecord:
    return PilotEvidenceRecord(
        id=row["id"],
        evidence_category=row["evidence_category"],
        canon_episode_id=row["canon_episode_id"],
        branch_episode_id=row["branch_episode_id"],
        reader_id=row["reader_id"],
        evidence_data_json=row["evidence_data_json"],
        privacy_safe=bool(row["privacy_safe"]),
        created_at=row["created_at"],
    )


def create_pilot_evidence(
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    evidence_category: str,
    evidence_data: dict,
    canon_episode_id: str | None = None,
    branch_episode_id: str | None = None,
    reader_id: str | None = None,
    privacy_safe: bool = True,
) -> PilotEvidenceRecord:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"INSERT INTO pilot_evidence ({_SELECT}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence_id, evidence_category, canon_episode_id,
                branch_episode_id, reader_id,
                json.dumps(evidence_data),
                1 if privacy_safe else 0, now,
            ),
        )
        conn.commit()
        return PilotEvidenceRecord(
            id=evidence_id, evidence_category=evidence_category,
            canon_episode_id=canon_episode_id,
            branch_episode_id=branch_episode_id,
            reader_id=reader_id,
            evidence_data_json=json.dumps(evidence_data),
            privacy_safe=privacy_safe, created_at=now,
        )
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_pilot_evidence(conn: sqlite3.Connection, evidence_id: str) -> PilotEvidenceRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM pilot_evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_all_pilot_evidence(conn: sqlite3.Connection) -> list[PilotEvidenceRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM pilot_evidence ORDER BY created_at"
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_pilot_evidence_by_category(
    conn: sqlite3.Connection, category: str
) -> list[PilotEvidenceRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM pilot_evidence "
        "WHERE evidence_category = ? ORDER BY created_at",
        (category,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
