"""Editorial review service — atomic approve/reject with an audit trail.

This service owns a single ``BEGIN IMMEDIATE`` write transaction so that the
episode ``review_state`` transition and the immutable ``review_decisions``
audit row commit or roll back together.

The episode under review is always resolved from the branch (never supplied by
the caller), and a decision is applied only to a *personal branch* episode that
is still ``pending_review``. Resolution and the guarded update together make a
stale, duplicate, mis-targeted, or canon-targeting decision fail cleanly with a
single :class:`ReviewDecisionError` instead of double-applying or ever touching
canon.
"""

from __future__ import annotations

import sqlite3

from app import branch_repository as branch_repo
from app import episode_repository as ep_repo
from app import review_decision_repository as rd_repo


class ReviewDecisionError(RuntimeError):
    """Raised when a review decision cannot be applied (e.g. already decided)."""


def _ensure_idle(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise ReviewDecisionError(
            "review service requires an idle connection"
        )


def _resolve_pending_branch_episode(
    conn: sqlite3.Connection, branch_id: str
) -> str:
    """Resolve and validate the branch's episode inside the write transaction.

    Returns the ``episode_id`` only when the branch exists, points at an
    existing ``personal_branch`` episode, and that episode is still
    ``pending_review``. Every other condition — missing branch, missing
    episode, branch/episode mismatch, a non-branch episode such as canon, or an
    already-decided episode — raises :class:`ReviewDecisionError` so the caller
    surfaces one privacy-safe 409 and never mutates canon or a settled branch.

    Must be called within an active transaction so the validation and the
    subsequent guarded state change are atomic.
    """
    branch = branch_repo.get_branch(conn, branch_id)
    if branch is None:
        raise ReviewDecisionError("branch not found")
    episode = ep_repo.get_episode_by_id(conn, branch.branch_episode_id)
    if episode is None:
        raise ReviewDecisionError("branch episode not found")
    if episode.id != branch.branch_episode_id:
        raise ReviewDecisionError("branch/episode mismatch")
    if episode.episode_type != "personal_branch":
        raise ReviewDecisionError(
            "only personal branch episodes are reviewable"
        )
    if episode.review_state != "pending_review":
        raise ReviewDecisionError("branch already decided")
    return episode.id


def approve_branch(
    conn: sqlite3.Connection,
    *,
    branch_id: str,
) -> None:
    """Atomically publish a pending branch episode and record the approval.

    The episode is resolved from the branch (never supplied by the caller), so
    a reviewer cannot target an arbitrary or canon episode.
    """
    _ensure_idle(conn)
    try:
        conn.execute("BEGIN IMMEDIATE")
        episode_id = _resolve_pending_branch_episode(conn, branch_id)
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
    rejection_reason: str,
) -> None:
    """Atomically reject a pending branch episode and record the rejection.

    The episode is resolved from the branch (never supplied by the caller). The
    reason is whitespace-normalized and must be non-empty after normalization.
    """
    _ensure_idle(conn)
    reason = " ".join((rejection_reason or "").split())
    if not reason:
        raise ReviewDecisionError("rejection reason is required")
    try:
        conn.execute("BEGIN IMMEDIATE")
        episode_id = _resolve_pending_branch_episode(conn, branch_id)
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
            rejection_reason=reason,
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
