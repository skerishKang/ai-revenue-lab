"""Service-owned rejoin operation.

Creates one service operation that:
- loads the branch;
- loads its persisted branch episode and divergence state;
- derives unresolved consequences from persisted state;
- loads the target checkpoint and accepted canon snapshot;
- verifies same world and canon lineage;
- verifies checkpoint compatibility and ordering;
- requires an explanation for every unresolved consequence;
- creates/updates the rejoin request;
- marks the branch rejoined;
- commits all changes atomically.

Does not allow mark_branch_rejoined to bypass rejoin validation.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.branch_repository import BranchRecord, get_branch
from app.canon_repository import (
    CanonCheckpointRecord,
    CanonSnapshotRecord,
    get_canon_checkpoint,
    get_canon_snapshot,
)
from app.pipeline.errors import ContinuityError, RejoinValidationError
from app.utils import new_id, now_utc_iso


@dataclass(frozen=True)
class RejoinResult:
    rejoin_request_id: str
    branch_id: str
    target_checkpoint_id: str
    approved: bool
    rejection_reason: str | None
    unresolved_consequences_count: int


def _derive_unresolved_consequences(
    conn: sqlite3.Connection,
    branch: BranchRecord,
) -> list[str]:
    """Derive unresolved consequences from persisted branch/episode state."""
    consequences: list[str] = []

    # Load branch episode
    row = conn.execute(
        "SELECT unresolved_threads_json, world_state_deltas_json "
        "FROM episodes WHERE id = ?",
        (branch.branch_episode_id,),
    ).fetchone()
    if row is None:
        return consequences

    threads = json.loads(row["unresolved_threads_json"]) if row["unresolved_threads_json"] else []
    for thread in threads:
        consequences.append(str(thread))

    # Load branch divergence state
    if branch.divergence_state_json:
        try:
            divergence = json.loads(branch.divergence_state_json)
            if isinstance(divergence, dict):
                facts = divergence.get("branch_only_facts", [])
                if isinstance(facts, list):
                    for fact in facts:
                        consequences.append(f"branch-only fact: {fact}")
        except json.JSONDecodeError:
            pass

    # Load branch_only_facts_json
    if branch.branch_only_facts_json:
        try:
            facts = json.loads(branch.branch_only_facts_json)
            if isinstance(facts, list):
                for fact in facts:
                    if f"branch-only fact: {fact}" not in consequences:
                        consequences.append(f"branch-only fact: {fact}")
        except json.JSONDecodeError:
            pass

    return consequences


def perform_rejoin(
    conn: sqlite3.Connection,
    *,
    branch_id: str,
    target_checkpoint_id: str,
    explanations: list[dict[str, str]] | None = None,
) -> RejoinResult:
    """Service-owned rejoin operation.

    ``explanations`` is a list of {"consequence": "...", "explanation": "..."}.
    Every derived unresolved consequence must have a corresponding explanation.
    """
    if conn.in_transaction:
        raise RuntimeError("rejoin requires an idle connection")

    # 1. Load branch
    branch = get_branch(conn, branch_id)
    if branch is None:
        raise RejoinValidationError(f"branch not found: {branch_id}")

    if branch.status != "active":
        raise RejoinValidationError(
            f"branch {branch_id} is not active (status: {branch.status})"
        )

    # 2. Load target checkpoint
    target = get_canon_checkpoint(conn, target_checkpoint_id)
    if target is None:
        raise RejoinValidationError(
            f"target checkpoint not found: {target_checkpoint_id}"
        )

    if not target.is_compatible_for_rejoin:
        raise RejoinValidationError(
            f"checkpoint {target_checkpoint_id} is not compatible for rejoin"
        )

    # 3. Load accepted canon snapshot
    snapshot = get_canon_snapshot(conn, target.canon_snapshot_id)
    if snapshot is None:
        raise RejoinValidationError(
            f"canon snapshot not found: {target.canon_snapshot_id}"
        )

    if not snapshot.accepted:
        raise RejoinValidationError(
            f"canon snapshot {snapshot.id} is not accepted"
        )

    # 4. Verify same world and canon lineage
    # Load the branch's canon checkpoint to check lineage
    branch_checkpoint = get_canon_checkpoint(conn, branch.canon_checkpoint_id)
    if branch_checkpoint is None:
        raise RejoinValidationError(
            f"branch canon checkpoint not found: {branch.canon_checkpoint_id}"
        )

    branch_snapshot = get_canon_snapshot(conn, branch_checkpoint.canon_snapshot_id)
    if branch_snapshot is None:
        raise RejoinValidationError(
            f"branch canon snapshot not found: {branch_checkpoint.canon_snapshot_id}"
        )

    if branch_snapshot.world_id != snapshot.world_id:
        raise RejoinValidationError(
            f"world mismatch: branch belongs to world {branch_snapshot.world_id}, "
            f"target checkpoint belongs to world {snapshot.world_id}"
        )

    # 5. Verify checkpoint ordering — target must be at or after branch's checkpoint
    if target.episode_number < branch_checkpoint.episode_number:
        raise RejoinValidationError(
            f"target checkpoint episode {target.episode_number} is before "
            f"branch divergence checkpoint episode {branch_checkpoint.episode_number}"
        )

    # Also verify against the branch's prior episode
    prior_episode = conn.execute(
        "SELECT episode_number FROM episodes WHERE id = ?",
        (branch.prior_episode_id,),
    ).fetchone()
    if prior_episode is None:
        raise RejoinValidationError(
            f"branch prior episode not found: {branch.prior_episode_id}"
        )

    if target.episode_number < prior_episode["episode_number"]:
        raise RejoinValidationError(
            f"target checkpoint episode {target.episode_number} is before "
            f"branch prior episode {prior_episode['episode_number']}"
        )

    # 6. Derive unresolved consequences from persisted state
    derived_consequences = _derive_unresolved_consequences(conn, branch)

    # 7. Require explanation for every unresolved consequence
    explanation_map: dict[str, str] = {}
    if explanations:
        for entry in explanations:
            consequence = entry.get("consequence", "").strip()
            explanation = entry.get("explanation", "").strip()
            if consequence and explanation:
                explanation_map[consequence] = explanation

    unexplained: list[str] = []
    for consequence in derived_consequences:
        if consequence not in explanation_map:
            unexplained.append(consequence)

    if unexplained:
        raise RejoinValidationError(
            f"unresolved consequences require explanation: "
            f"{len(unexplained)} unexplained. "
            f"First: {unexplained[0][:100] if unexplained else 'none'}"
        )

    # 8. Atomic rejoin: create rejoin request + mark branch rejoined
    rejoin_request_id = new_id()
    now = now_utc_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Create v2 rejoin request
        conn.execute(
            "INSERT INTO rejoin_requests_v2 "
            "(id, branch_id, target_checkpoint_id, target_snapshot_id, "
            "derived_consequences_json, explanation, status, validated_at, "
            "created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?)",
            (
                rejoin_request_id, branch_id, target_checkpoint_id,
                snapshot.id,
                json.dumps(derived_consequences),
                json.dumps(explanations or []),
                now, now,
            ),
        )

        # Mark branch rejoined
        cursor = conn.execute(
            "UPDATE branches SET status = 'rejoined', "
            "rejoin_checkpoint_id = ?, "
            "rejoin_explanation = ?, rejoined_at = ? "
            "WHERE id = ? AND status = 'active'",
            (
                target_checkpoint_id,
                json.dumps(explanations or []),
                now, branch_id,
            ),
        )

        if cursor.rowcount == 0:
            conn.rollback()
            raise RejoinValidationError(
                f"branch {branch_id} could not be marked rejoined "
                f"(already rejoined or not active)"
            )

        conn.commit()
    except RejoinValidationError:
        if conn.in_transaction:
            conn.rollback()
        raise
    except Exception as exc:
        if conn.in_transaction:
            conn.rollback()
        raise RejoinValidationError(f"rejoin failed: {exc}") from exc

    return RejoinResult(
        rejoin_request_id=rejoin_request_id,
        branch_id=branch_id,
        target_checkpoint_id=target_checkpoint_id,
        approved=True,
        rejection_reason=None,
        unresolved_consequences_count=len(derived_consequences),
    )
