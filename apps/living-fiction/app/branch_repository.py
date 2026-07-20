"""Branch repository — personal branches and rejoin tracking.

A branch references exactly one reader, prior published episode, canon
checkpoint, and reader choice. Branches may rejoin a compatible canon
checkpoint only when continuity rules permit.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class BranchRecord:
    id: str
    reader_id: str
    canon_checkpoint_id: str
    prior_episode_id: str
    branch_episode_id: str
    reader_choice_id: str
    divergence_state_json: str
    branch_only_facts_json: str
    status: str
    rejoin_checkpoint_id: str | None
    rejoin_explanation: str | None
    rejoined_at: str | None
    created_at: str


class BranchValidationError(ValueError):
    pass


class BranchNotFoundError(RuntimeError):
    pass


_COLS = [
    "id", "reader_id", "canon_checkpoint_id", "prior_episode_id",
    "branch_episode_id", "reader_choice_id", "divergence_state_json",
    "branch_only_facts_json", "status", "rejoin_checkpoint_id",
    "rejoin_explanation", "rejoined_at", "created_at",
]
_SELECT = ", ".join(_COLS)


def _row_to_record(row: sqlite3.Row) -> BranchRecord:
    return BranchRecord(
        id=row["id"],
        reader_id=row["reader_id"],
        canon_checkpoint_id=row["canon_checkpoint_id"],
        prior_episode_id=row["prior_episode_id"],
        branch_episode_id=row["branch_episode_id"],
        reader_choice_id=row["reader_choice_id"],
        divergence_state_json=row["divergence_state_json"] or "",
        branch_only_facts_json=row["branch_only_facts_json"] or "",
        status=row["status"],
        rejoin_checkpoint_id=row["rejoin_checkpoint_id"],
        rejoin_explanation=row["rejoin_explanation"],
        rejoined_at=row["rejoined_at"],
        created_at=row["created_at"],
    )


def create_branch(
    conn: sqlite3.Connection,
    *,
    branch_id: str,
    reader_id: str,
    canon_checkpoint_id: str,
    prior_episode_id: str,
    branch_episode_id: str,
    reader_choice_id: str,
    divergence_state: dict | None = None,
    branch_only_facts: list | None = None,
) -> BranchRecord:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"INSERT INTO branches ({_SELECT}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, NULL, ?)",
            (
                branch_id, reader_id, canon_checkpoint_id,
                prior_episode_id, branch_episode_id, reader_choice_id,
                json.dumps(divergence_state or {}),
                json.dumps(branch_only_facts or []),
                now,
            ),
        )
        conn.commit()
        return BranchRecord(
            id=branch_id, reader_id=reader_id,
            canon_checkpoint_id=canon_checkpoint_id,
            prior_episode_id=prior_episode_id,
            branch_episode_id=branch_episode_id,
            reader_choice_id=reader_choice_id,
            divergence_state_json=json.dumps(divergence_state or {}),
            branch_only_facts_json=json.dumps(branch_only_facts or []),
            status="active", rejoin_checkpoint_id=None,
            rejoin_explanation=None, rejoined_at=None,
            created_at=now,
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise BranchValidationError(
            f"duplicate branch (same reader+checkpoint+choice): {exc}"
        ) from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_branch(conn: sqlite3.Connection, branch_id: str) -> BranchRecord | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM branches WHERE id = ?",
        (branch_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_branches_by_reader(
    conn: sqlite3.Connection, reader_id: str
) -> list[BranchRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM branches WHERE reader_id = ? ORDER BY created_at",
        (reader_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def mark_branch_rejoined(
    conn: sqlite3.Connection,
    branch_id: str,
    rejoin_checkpoint_id: str,
    explanation: str,
) -> bool:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE branches SET status = 'rejoined', "
            "rejoin_checkpoint_id = ?, rejoin_explanation = ?, "
            "rejoined_at = ? WHERE id = ? AND status = 'active'",
            (rejoin_checkpoint_id, explanation, now, branch_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


@dataclass(frozen=True)
class RejoinRequestRecord:
    id: str
    branch_id: str
    target_checkpoint_id: str
    status: str
    rejection_reason: str | None
    unresolved_consequences_json: str
    created_at: str


def create_rejoin_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    branch_id: str,
    target_checkpoint_id: str,
    unresolved_consequences: list,
    status: str = "pending",
    rejection_reason: str | None = None,
) -> RejoinRequestRecord:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO rejoin_requests "
            "(id, branch_id, target_checkpoint_id, status, rejection_reason, "
            "unresolved_consequences_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                request_id, branch_id, target_checkpoint_id, status,
                rejection_reason,
                json.dumps(unresolved_consequences), now,
            ),
        )
        conn.commit()
        return RejoinRequestRecord(
            id=request_id, branch_id=branch_id,
            target_checkpoint_id=target_checkpoint_id,
            status=status, rejection_reason=rejection_reason,
            unresolved_consequences_json=json.dumps(unresolved_consequences),
            created_at=now,
        )
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
