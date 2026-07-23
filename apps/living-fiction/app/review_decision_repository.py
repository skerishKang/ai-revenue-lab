"""Review decision audit repository — immutable editorial decisions.

Every approve/reject decision is recorded exactly once, inside the same
transaction that transitions the episode's ``review_state``. This guarantees
the state change and its audit trail commit or roll back together, so there
is never a published/rejected episode without a decision record (or vice
versa). Decision rows are append-only and never updated.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.reader_repository import RepositoryTransactionError
from app.utils import new_id, now_utc_iso


@dataclass(frozen=True)
class ReviewDecisionRecord:
    id: str
    branch_id: str
    episode_id: str
    decision: str
    rejection_reason: str | None
    decided_at: str
    actor_type: str
    prior_state: str
    new_state: str


class ReviewDecisionValidationError(ValueError):
    pass


_COLS = [
    "id", "branch_id", "episode_id", "decision", "rejection_reason",
    "decided_at", "actor_type", "prior_state", "new_state",
]
_SELECT = ", ".join(_COLS)

_VALID_DECISIONS = ("approved", "rejected")


def _row_to_record(row: sqlite3.Row) -> ReviewDecisionRecord:
    return ReviewDecisionRecord(
        id=row["id"],
        branch_id=row["branch_id"],
        episode_id=row["episode_id"],
        decision=row["decision"],
        rejection_reason=row["rejection_reason"],
        decided_at=row["decided_at"],
        actor_type=row["actor_type"],
        prior_state=row["prior_state"],
        new_state=row["new_state"],
    )


def record_decision_in_tx(
    conn: sqlite3.Connection,
    *,
    branch_id: str,
    episode_id: str,
    decision: str,
    prior_state: str,
    new_state: str,
    rejection_reason: str | None = None,
    actor_type: str = "admin",
    decision_id: str | None = None,
) -> ReviewDecisionRecord:
    """Insert an immutable decision row inside a caller-owned transaction.

    Does NOT begin or commit — the review service owns the transaction so the
    episode state change and this audit row are atomic.
    """
    if not conn.in_transaction:
        raise RepositoryTransactionError(
            "record_decision_in_tx requires an active transaction"
        )
    if decision not in _VALID_DECISIONS:
        raise ReviewDecisionValidationError(f"invalid decision: {decision}")
    if decision == "rejected" and not (rejection_reason and rejection_reason.strip()):
        raise ReviewDecisionValidationError(
            "rejection_reason is required for a rejected decision"
        )

    did = decision_id or new_id()
    now = now_utc_iso()
    conn.execute(
        "INSERT INTO review_decisions "
        "(id, branch_id, episode_id, decision, rejection_reason, decided_at, "
        "actor_type, prior_state, new_state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            did, branch_id, episode_id, decision, rejection_reason, now,
            actor_type, prior_state, new_state,
        ),
    )
    return ReviewDecisionRecord(
        id=did,
        branch_id=branch_id,
        episode_id=episode_id,
        decision=decision,
        rejection_reason=rejection_reason,
        decided_at=now,
        actor_type=actor_type,
        prior_state=prior_state,
        new_state=new_state,
    )


def get_decisions_for_episode(
    conn: sqlite3.Connection, episode_id: str
) -> list[ReviewDecisionRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM review_decisions "
        "WHERE episode_id = ? ORDER BY decided_at",
        (episode_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_decisions_for_branch(
    conn: sqlite3.Connection, branch_id: str
) -> list[ReviewDecisionRecord]:
    rows = conn.execute(
        f"SELECT {_SELECT} FROM review_decisions "
        "WHERE branch_id = ? ORDER BY decided_at",
        (branch_id,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]
