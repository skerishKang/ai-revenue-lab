"""Rejoin validation — checks for branch rejoin at compatible checkpoints.

Rejoin is allowed only at an explicit compatible checkpoint and cannot
erase unresolved branch consequences without explanation.
"""

from __future__ import annotations

import json
import sqlite3

from app.branch_repository import BranchRecord
from app.canon_repository import CanonCheckpointRecord, get_canon_checkpoint
from app.pipeline.errors import ContinuityError


def validate_rejoin(
    conn: sqlite3.Connection,
    branch: BranchRecord,
    target_checkpoint: CanonCheckpointRecord,
    unresolved_consequences: list[str],
    explanation: str | None = None,
) -> None:
    """Validate a rejoin request. Raises ContinuityError on failure.

    Rules:
    1. target checkpoint must be compatible for rejoin;
    2. branch must be active (not already rejoined);
    3. if there are unresolved consequences, an explanation must be provided;
    4. the target checkpoint's episode_number must be >= the branch's
       prior episode number.
    """
    if not target_checkpoint.is_compatible_for_rejoin:
        raise ContinuityError(
            f"checkpoint {target_checkpoint.id} is not compatible for rejoin"
        )

    if branch.status != "active":
        raise ContinuityError(
            f"branch {branch.id} is not active (status: {branch.status})"
        )

    if unresolved_consequences:
        if not explanation or not explanation.strip():
            raise ContinuityError(
                "rejoin cannot discard unresolved consequences without "
                "explanation"
            )

    # Get the branch's prior episode to check episode ordering
    prior_episode = conn.execute(
        "SELECT episode_number FROM episodes WHERE id = ?",
        (branch.prior_episode_id,),
    ).fetchone()
    if prior_episode is None:
        raise ContinuityError(
            f"branch prior episode {branch.prior_episode_id} not found"
        )

    if target_checkpoint.episode_number < prior_episode["episode_number"]:
        raise ContinuityError(
            f"target checkpoint episode {target_checkpoint.episode_number} "
            f"is before branch prior episode {prior_episode['episode_number']}"
        )
