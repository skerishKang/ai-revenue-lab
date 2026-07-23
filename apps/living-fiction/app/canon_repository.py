"""Canon snapshot and checkpoint repository.

Accepted canon snapshots are immutable and versioned. A canon checkpoint
references a snapshot and is the rejoin target for branches.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.database.errors import IntegrityError
from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class CanonSnapshotRecord:
    id: str
    world_id: str
    version: str
    episode_number: int
    accepted: bool
    world_state_json: str
    character_states_json: str
    location_states_json: str
    clue_states_json: str
    unresolved_threads_json: str
    created_at: str


@dataclass(frozen=True)
class CanonCheckpointRecord:
    id: str
    canon_snapshot_id: str
    episode_number: int
    label: str
    is_compatible_for_rejoin: bool
    created_at: str


class CanonSnapshotNotFoundError(RuntimeError):
    pass


class CanonValidationError(ValueError):
    pass


def _snapshot_row_to_record(row: sqlite3.Row) -> CanonSnapshotRecord:
    return CanonSnapshotRecord(
        id=row["id"],
        world_id=row["world_id"],
        version=row["version"],
        episode_number=row["episode_number"],
        accepted=bool(row["accepted"]),
        world_state_json=row["world_state_json"],
        character_states_json=row["character_states_json"],
        location_states_json=row["location_states_json"],
        clue_states_json=row["clue_states_json"],
        unresolved_threads_json=row["unresolved_threads_json"],
        created_at=row["created_at"],
    )


def _checkpoint_row_to_record(row: sqlite3.Row) -> CanonCheckpointRecord:
    return CanonCheckpointRecord(
        id=row["id"],
        canon_snapshot_id=row["canon_snapshot_id"],
        episode_number=row["episode_number"],
        label=row["label"],
        is_compatible_for_rejoin=bool(row["is_compatible_for_rejoin"]),
        created_at=row["created_at"],
    )


def create_canon_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    world_id: str,
    version: str,
    episode_number: int,
    world_state: dict,
    character_states: dict,
    location_states: dict,
    clue_states: dict,
    unresolved_threads: list,
    accepted: bool = False,
) -> CanonSnapshotRecord:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO canon_snapshots "
            "(id, world_id, version, episode_number, accepted, "
            "world_state_json, character_states_json, location_states_json, "
            "clue_states_json, unresolved_threads_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot_id, world_id, version, episode_number,
                1 if accepted else 0,
                json.dumps(world_state),
                json.dumps(character_states),
                json.dumps(location_states),
                json.dumps(clue_states),
                json.dumps(unresolved_threads),
                now,
            ),
        )
        conn.commit()
        return CanonSnapshotRecord(
            id=snapshot_id, world_id=world_id, version=version,
            episode_number=episode_number, accepted=accepted,
            world_state_json=json.dumps(world_state),
            character_states_json=json.dumps(character_states),
            location_states_json=json.dumps(location_states),
            clue_states_json=json.dumps(clue_states),
            unresolved_threads_json=json.dumps(unresolved_threads),
            created_at=now,
        )
    except IntegrityError as exc:
        conn.rollback()
        raise CanonValidationError(f"snapshot already exists: {exc}") from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_canon_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> CanonSnapshotRecord | None:
    row = conn.execute(
        "SELECT * FROM canon_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    return _snapshot_row_to_record(row) if row else None


def get_latest_canon_snapshot(conn: sqlite3.Connection, world_id: str) -> CanonSnapshotRecord | None:
    row = conn.execute(
        "SELECT * FROM canon_snapshots WHERE world_id = ? AND accepted = 1 "
        "ORDER BY episode_number DESC LIMIT 1",
        (world_id,),
    ).fetchone()
    return _snapshot_row_to_record(row) if row else None


def is_canon_snapshot_immutable(conn: sqlite3.Connection, snapshot_id: str) -> bool:
    """An accepted canon snapshot is immutable."""
    row = conn.execute(
        "SELECT accepted FROM canon_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        return False
    return bool(row["accepted"])


def try_mutate_canon_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> None:
    """Attempt to mutate an accepted canon snapshot — should always fail."""
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT accepted FROM canon_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            conn.rollback()
            raise CanonSnapshotNotFoundError(f"snapshot not found: {snapshot_id}")
        if bool(row["accepted"]):
            conn.rollback()
            raise CanonValidationError(
                f"accepted canon snapshot {snapshot_id} is immutable"
            )
        # Not accepted yet — mutation allowed
        conn.execute(
            "UPDATE canon_snapshots SET version = version || '_mut' WHERE id = ?",
            (snapshot_id,),
        )
        conn.commit()
    except (CanonValidationError, CanonSnapshotNotFoundError):
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def create_canon_checkpoint(
    conn: sqlite3.Connection,
    *,
    checkpoint_id: str,
    canon_snapshot_id: str,
    episode_number: int,
    label: str,
    is_compatible_for_rejoin: bool = True,
) -> CanonCheckpointRecord:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO canon_checkpoints "
            "(id, canon_snapshot_id, episode_number, label, "
            "is_compatible_for_rejoin, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                checkpoint_id, canon_snapshot_id, episode_number, label,
                1 if is_compatible_for_rejoin else 0, now,
            ),
        )
        conn.commit()
        return CanonCheckpointRecord(
            id=checkpoint_id, canon_snapshot_id=canon_snapshot_id,
            episode_number=episode_number, label=label,
            is_compatible_for_rejoin=is_compatible_for_rejoin,
            created_at=now,
        )
    except IntegrityError as exc:
        conn.rollback()
        raise CanonValidationError(f"checkpoint already exists: {exc}") from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_canon_checkpoint(conn: sqlite3.Connection, checkpoint_id: str) -> CanonCheckpointRecord | None:
    row = conn.execute(
        "SELECT * FROM canon_checkpoints WHERE id = ?",
        (checkpoint_id,),
    ).fetchone()
    return _checkpoint_row_to_record(row) if row else None
