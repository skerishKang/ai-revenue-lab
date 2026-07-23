"""Episode repository — canon and personal branch episodes.

Episodes are the primary narrative output. All episodes start as
``pending_review`` and remain there until explicit human publication.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.database.errors import IntegrityError
from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class EpisodeRecord:
    id: str
    world_id: str
    episode_type: str
    episode_number: int
    title: str
    synopsis: str
    canon_snapshot_id: str | None
    canon_checkpoint_id: str | None
    prior_episode_id: str | None
    reader_id: str | None
    scene_list_json: str
    character_ids_json: str
    location_ids_json: str
    prose_json: str
    clue_refs_json: str | None
    world_state_deltas_json: str | None
    applied_reader_input_json: str | None
    unresolved_threads_json: str
    next_choice_options_json: str
    content_classification: str
    review_state: str
    generation_run_id: str | None
    created_at: str


class EpisodeValidationError(ValueError):
    pass


class EpisodeNotFoundError(RuntimeError):
    pass


_EPISODE_COLS = [
    "id", "world_id", "episode_type", "episode_number", "title",
    "synopsis", "canon_snapshot_id", "canon_checkpoint_id",
    "prior_episode_id", "reader_id", "scene_list_json",
    "character_ids_json", "location_ids_json", "prose_json",
    "clue_refs_json", "world_state_deltas_json",
    "applied_reader_input_json", "unresolved_threads_json",
    "next_choice_options_json", "content_classification",
    "review_state", "generation_run_id", "created_at",
]
_EPISODE_SELECT = ", ".join(_EPISODE_COLS)


def _row_to_record(row: sqlite3.Row) -> EpisodeRecord:
    return EpisodeRecord(
        id=row["id"],
        world_id=row["world_id"],
        episode_type=row["episode_type"],
        episode_number=row["episode_number"],
        title=row["title"],
        synopsis=row["synopsis"],
        canon_snapshot_id=row["canon_snapshot_id"],
        canon_checkpoint_id=row["canon_checkpoint_id"],
        prior_episode_id=row["prior_episode_id"],
        reader_id=row["reader_id"],
        scene_list_json=row["scene_list_json"],
        character_ids_json=row["character_ids_json"],
        location_ids_json=row["location_ids_json"],
        prose_json=row["prose_json"],
        clue_refs_json=row["clue_refs_json"],
        world_state_deltas_json=row["world_state_deltas_json"],
        applied_reader_input_json=row["applied_reader_input_json"],
        unresolved_threads_json=row["unresolved_threads_json"],
        next_choice_options_json=row["next_choice_options_json"],
        content_classification=row["content_classification"],
        review_state=row["review_state"],
        generation_run_id=row["generation_run_id"],
        created_at=row["created_at"],
    )


def create_episode(
    conn: sqlite3.Connection,
    *,
    episode_id: str,
    world_id: str,
    episode_type: str,
    episode_number: int,
    title: str,
    synopsis: str,
    scene_list: list,
    character_ids: list,
    location_ids: list,
    prose: list,
    clue_refs: list | None = None,
    world_state_deltas: dict | None = None,
    applied_reader_input: dict | None = None,
    unresolved_threads: list | None = None,
    next_choice_options: list | None = None,
    content_classification: str = "adult",
    canon_snapshot_id: str | None = None,
    canon_checkpoint_id: str | None = None,
    prior_episode_id: str | None = None,
    reader_id: str | None = None,
    generation_run_id: str | None = None,
) -> EpisodeRecord:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"INSERT INTO episodes ({_EPISODE_SELECT}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?)",
            (
                episode_id, world_id, episode_type, episode_number,
                title, synopsis, canon_snapshot_id, canon_checkpoint_id,
                prior_episode_id, reader_id,
                json.dumps(scene_list),
                json.dumps(character_ids),
                json.dumps(location_ids),
                json.dumps(prose),
                json.dumps(clue_refs) if clue_refs else None,
                json.dumps(world_state_deltas) if world_state_deltas else None,
                json.dumps(applied_reader_input) if applied_reader_input else None,
                json.dumps(unresolved_threads or []),
                json.dumps(next_choice_options or []),
                content_classification, "pending_review",
                generation_run_id, now,
            ),
        )
        conn.commit()
        return get_episode_by_id(conn, episode_id)  # type: ignore
    except IntegrityError as exc:
        conn.rollback()
        raise EpisodeValidationError(
            f"episode already exists (duplicate ID or number): {exc}"
        ) from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_episode_by_id(conn: sqlite3.Connection, episode_id: str) -> EpisodeRecord | None:
    row = conn.execute(
        f"SELECT {_EPISODE_SELECT} FROM episodes WHERE id = ?",
        (episode_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_episodes_by_world(
    conn: sqlite3.Connection, world_id: str, episode_type: str | None = None
) -> list[EpisodeRecord]:
    if episode_type:
        rows = conn.execute(
            f"SELECT {_EPISODE_SELECT} FROM episodes "
            "WHERE world_id = ? AND episode_type = ? ORDER BY episode_number",
            (world_id, episode_type),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_EPISODE_SELECT} FROM episodes "
            "WHERE world_id = ? ORDER BY episode_number",
            (world_id,),
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_latest_canon_episode(conn: sqlite3.Connection, world_id: str) -> EpisodeRecord | None:
    row = conn.execute(
        f"SELECT {_EPISODE_SELECT} FROM episodes "
        "WHERE world_id = ? AND episode_type = 'canon' "
        "ORDER BY episode_number DESC LIMIT 1",
        (world_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_latest_published_episode(conn: sqlite3.Connection, world_id: str) -> EpisodeRecord | None:
    row = conn.execute(
        f"SELECT {_EPISODE_SELECT} FROM episodes "
        "WHERE world_id = ? AND review_state = 'published' "
        "ORDER BY episode_number DESC LIMIT 1",
        (world_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_latest_published_canon_episode(
    conn: sqlite3.Connection, world_id: str
) -> EpisodeRecord | None:
    """Latest *published canon* episode for a world.

    Reader-facing canon screens and choice submission must anchor on canon
    only — never on a published personal branch. Filtering on
    ``episode_type = 'canon'`` guarantees a reader's own published branch can
    never be mistaken for the shared canon checkpoint.
    """
    row = conn.execute(
        f"SELECT {_EPISODE_SELECT} FROM episodes "
        "WHERE world_id = ? AND episode_type = 'canon' "
        "AND review_state = 'published' "
        "ORDER BY episode_number DESC LIMIT 1",
        (world_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_next_episode_number(
    conn: sqlite3.Connection, world_id: str, episode_type: str
) -> int:
    """Atomically reserve and return the next episode number.

    The caller must own an active write transaction (normally
    ``BEGIN IMMEDIATE``). The durable sequence row is advanced before the
    transaction commits, so concurrent requests with different idempotency
    keys cannot observe and reuse the same number while provider work is in
    flight. Gaps after failed generation are allowed; number reuse is not.
    """
    if not conn.in_transaction:
        raise RepositoryTransactionError(
            "episode number allocation requires an active transaction"
        )
    if episode_type not in {"canon", "personal_branch"}:
        raise EpisodeValidationError(f"unsupported episode type: {episode_type}")

    episode_row = conn.execute(
        "SELECT COALESCE(MAX(episode_number), 0) + 1 AS floor_number "
        "FROM episodes WHERE world_id = ? AND episode_type = ?",
        (world_id, episode_type),
    ).fetchone()
    floor_number = int(episode_row["floor_number"])

    sequence_row = conn.execute(
        "SELECT next_episode_number FROM episode_number_sequences "
        "WHERE world_id = ? AND episode_type = ?",
        (world_id, episode_type),
    ).fetchone()

    if sequence_row is None:
        allocated = floor_number
        conn.execute(
            "INSERT INTO episode_number_sequences "
            "(world_id, episode_type, next_episode_number) VALUES (?, ?, ?)",
            (world_id, episode_type, allocated + 1),
        )
        return allocated

    allocated = max(int(sequence_row["next_episode_number"]), floor_number)
    updated = conn.execute(
        "UPDATE episode_number_sequences SET next_episode_number = ? "
        "WHERE world_id = ? AND episode_type = ?",
        (allocated + 1, world_id, episode_type),
    ).rowcount
    if updated != 1:
        raise EpisodeValidationError("failed to reserve next episode number")
    return allocated


def publish_episode(conn: sqlite3.Connection, episode_id: str) -> bool:
    """Explicit human publication — never automatic."""
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE episodes SET review_state = 'published' "
            "WHERE id = ? AND review_state = 'pending_review'",
            (episode_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def reject_episode(conn: sqlite3.Connection, episode_id: str) -> bool:
    """Explicit human rejection — never automatic."""
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE episodes SET review_state = 'rejected' "
            "WHERE id = ? AND review_state = 'pending_review'",
            (episode_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def publish_episode_in_tx(conn: sqlite3.Connection, episode_id: str) -> bool:
    """Set ``review_state='published'`` inside a caller-owned transaction.

    Unlike :func:`publish_episode`, this does NOT begin or commit a
    transaction — the calling service owns it so the state change and its
    audit row commit or roll back atomically. The ``pending_review`` guard
    makes a duplicate/stale decision a no-op (returns ``False``) instead of
    corrupting state, and the ``episode_type='personal_branch'`` guard ensures
    the editorial review flow can never publish a canon episode (canon is
    published only through the standalone :func:`publish_episode`).
    """
    if not conn.in_transaction:
        raise RepositoryTransactionError(
            "publish_episode_in_tx requires an active transaction"
        )
    cursor = conn.execute(
        "UPDATE episodes SET review_state = 'published' "
        "WHERE id = ? AND review_state = 'pending_review' "
        "AND episode_type = 'personal_branch'",
        (episode_id,),
    )
    return cursor.rowcount > 0


def reject_episode_in_tx(conn: sqlite3.Connection, episode_id: str) -> bool:
    """Set ``review_state='rejected'`` inside a caller-owned transaction.

    Transaction-aware counterpart of :func:`reject_episode`; see
    :func:`publish_episode_in_tx` for the contract (including the
    ``personal_branch``-only guard that keeps canon out of the review flow).
    """
    if not conn.in_transaction:
        raise RepositoryTransactionError(
            "reject_episode_in_tx requires an active transaction"
        )
    cursor = conn.execute(
        "UPDATE episodes SET review_state = 'rejected' "
        "WHERE id = ? AND review_state = 'pending_review' "
        "AND episode_type = 'personal_branch'",
        (episode_id,),
    )
    return cursor.rowcount > 0


def get_pending_branch_episodes(
    conn: sqlite3.Connection,
) -> list[EpisodeRecord]:
    """Get all personal branch episodes with pending_review state."""
    rows = conn.execute(
        f"SELECT {_EPISODE_SELECT} FROM episodes "
        "WHERE episode_type = 'personal_branch' AND review_state = 'pending_review' "
        "ORDER BY created_at"
    ).fetchall()
    return [_row_to_record(r) for r in rows]
