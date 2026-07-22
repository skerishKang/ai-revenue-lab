"""Editorial review service — atomic approve/reject with an audit trail.

This service owns a single ``BEGIN IMMEDIATE`` write transaction so that the
episode ``review_state`` transition and the immutable ``review_decisions``
audit row commit or roll back together. A decision is applied only while the
episode is still ``pending_review``; the guarded update makes a stale or
duplicate decision fail cleanly instead of double-applying.
"""

from __future__ import annotations

import sqlite3

from app import episode_repository as ep_repo
from app import review_decision_repository as rd_repo


class ReviewDecisionError(RuntimeError):
    """Raised when a review decision cannot be applied (e.g. already decided)."""


def _ensure_idle(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise ReviewDecisionError(
            "review service requires an idle connection"
        )


def approve_branch(
    conn: sqlite3.Connection,
    *,
    branch_id: str,
    episode_id: str,
) -> None:
    """Atomically publish a pending branch episode and record the approval."""
    _ensure_idle(conn)
    try:
        conn.execute("BEGIN IMMEDIATE")
        changed = ep_repo.publish_episode_in_tx(conn, episode_id)
        if not changed:
            raise ReviewDecisionError("branch already decided")
        rd_repo.record_decision_in_tx(
            conn,
            branch_id=branch_id,
            episode_id=episode_id,
            decision="approved",
            prior_state="pending_review",
            new_state="published",
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def reject_branch(
    conn: sqlite3.Connection,
    *,
    branch_id: str,
    episode_id: str,
    rejection_reason: str,
) -> None:
    """Atomically reject a pending branch episode and record the rejection."""
    _ensure_idle(conn)
    if not rejection_reason or not rejection_reason.strip():
        raise ReviewDecisionError("rejection reason is required")
    try:
        conn.execute("BEGIN IMMEDIATE")
        changed = ep_repo.reject_episode_in_tx(conn, episode_id)
        if not changed:
            raise ReviewDecisionError("branch already decided")
        rd_repo.record_decision_in_tx(
            conn,
            branch_id=branch_id,
            episode_id=episode_id,
            decision="rejected",
            prior_state="pending_review",
            new_state="rejected",
            rejection_reason=rejection_reason,
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
