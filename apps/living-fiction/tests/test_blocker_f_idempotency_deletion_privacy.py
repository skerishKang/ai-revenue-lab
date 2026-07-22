"""Deletion privacy tests for branch-generation idempotency keys.

The default key embeds reader and choice identifiers. Deletion must rotate
that opaque key as well as anonymizing the structured foreign-key columns.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.db import apply_migrations, get_connection
from app.reader_deletion_service import delete_reader_with_revocation


_MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
_NOW = "2026-07-22T00:00:00Z"


def _seed_request(conn, suffix: str, *, reader_status: str = "active") -> dict[str, str]:
    reader_id = f"reader-private-{suffix}"
    world_id = f"world-{suffix}"
    snapshot_id = f"snapshot-{suffix}"
    checkpoint_id = f"checkpoint-{suffix}"
    episode_id = f"canon-{suffix}"
    choice_id = f"choice-private-{suffix}"
    request_id = f"request-{suffix}"
    raw_key = (
        f"{reader_id}:{choice_id}:{episode_id}:{checkpoint_id}:personal_branch"
    )

    conn.execute(
        "INSERT INTO readers (id, display_name, status, created_at, deleted_at) "
        "VALUES (?, 'Private Reader', ?, ?, ?)",
        (reader_id, reader_status, _NOW, _NOW if reader_status == "deleted" else None),
    )
    conn.execute(
        "INSERT INTO worlds (id, version, premise, genre, world_rules, "
        "canonical_timeline, unresolved_global_questions, created_at) "
        "VALUES (?, '1.0', 'Synthetic world', 'urban_mystery', '[]', '[]', '[]', ?)",
        (world_id, _NOW),
    )
    conn.execute(
        "INSERT INTO canon_snapshots (id, world_id, version, episode_number, "
        "accepted, world_state_json, character_states_json, location_states_json, "
        "clue_states_json, unresolved_threads_json, created_at) "
        "VALUES (?, ?, '1.0', 1, 1, '{}', '[]', '[]', '[]', '[]', ?)",
        (snapshot_id, world_id, _NOW),
    )
    conn.execute(
        "INSERT INTO canon_checkpoints (id, canon_snapshot_id, episode_number, "
        "label, is_compatible_for_rejoin, created_at) "
        "VALUES (?, ?, 1, 'opening', 1, ?)",
        (checkpoint_id, snapshot_id, _NOW),
    )
    conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, title, "
        "synopsis, canon_snapshot_id, canon_checkpoint_id, scene_list_json, "
        "character_ids_json, location_ids_json, prose_json, clue_refs_json, "
        "world_state_deltas_json, unresolved_threads_json, next_choice_options_json, "
        "content_classification, review_state, created_at) "
        "VALUES (?, ?, 'canon', 1, 'Opening', 'Synthetic opening', ?, ?, '[]', "
        "'[]', '[]', '[]', '[]', '{}', '[]', '[]', 'adult', 'published', ?)",
        (episode_id, world_id, snapshot_id, checkpoint_id, _NOW),
    )
    conn.execute(
        "INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, "
        "comment, submitted_at) VALUES (?, ?, ?, 'Investigate carefully', "
        "'private comment', ?)",
        (choice_id, reader_id, episode_id, _NOW),
    )
    conn.execute(
        "INSERT INTO branch_generation_requests (id, idempotency_key, reader_id, "
        "reader_choice_id, prior_episode_id, canon_checkpoint_id, world_id, status, "
        "created_at, operation_type, attempt_number, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'personal_branch', 1, ?)",
        (
            request_id,
            raw_key,
            reader_id,
            choice_id,
            episode_id,
            checkpoint_id,
            world_id,
            _NOW,
            _NOW,
        ),
    )
    conn.commit()
    return {
        "reader_id": reader_id,
        "choice_id": choice_id,
        "request_id": request_id,
        "raw_key": raw_key,
    }


def _assert_request_key_is_anonymous(conn, ids: dict[str, str]) -> None:
    row = conn.execute(
        "SELECT idempotency_key, reader_id, reader_choice_id "
        "FROM branch_generation_requests WHERE id = ?",
        (ids["request_id"],),
    ).fetchone()
    assert row is not None
    assert row["idempotency_key"].startswith("anon-idem-")
    assert ids["reader_id"] not in row["idempotency_key"]
    assert ids["choice_id"] not in row["idempotency_key"]
    assert row["reader_id"] != ids["reader_id"]
    assert row["reader_choice_id"] != ids["choice_id"]


def test_reader_deletion_rotates_embedded_idempotency_key(temp_db_path):
    conn = get_connection(temp_db_path)
    apply_migrations(conn, str(_MIGRATIONS))
    ids = _seed_request(conn, "live")

    result = delete_reader_with_revocation(conn, ids["reader_id"])
    assert result.success is True
    _assert_request_key_is_anonymous(conn, ids)
    conn.close()

    reopened = get_connection(temp_db_path)
    _assert_request_key_is_anonymous(reopened, ids)
    reopened.close()


def test_migration_backfills_requests_for_already_deleted_readers(tmp_path):
    staged = tmp_path / "migrations"
    staged.mkdir()
    for migration in sorted(_MIGRATIONS.glob("*.sql")):
        if migration.name < "006_reader_idempotency_key_privacy.sql":
            shutil.copy2(migration, staged / migration.name)

    db_path = str(tmp_path / "legacy.db")
    conn = get_connection(db_path)
    apply_migrations(conn, str(staged))
    ids = _seed_request(conn, "legacy", reader_status="deleted")

    before = conn.execute(
        "SELECT idempotency_key FROM branch_generation_requests WHERE id = ?",
        (ids["request_id"],),
    ).fetchone()
    assert before["idempotency_key"] == ids["raw_key"]

    shutil.copy2(
        _MIGRATIONS / "006_reader_idempotency_key_privacy.sql",
        staged / "006_reader_idempotency_key_privacy.sql",
    )
    applied = apply_migrations(conn, str(staged))
    assert applied == ["006_reader_idempotency_key_privacy.sql"]

    row = conn.execute(
        "SELECT idempotency_key FROM branch_generation_requests WHERE id = ?",
        (ids["request_id"],),
    ).fetchone()
    assert row["idempotency_key"].startswith("anon-idem-")
    assert ids["reader_id"] not in row["idempotency_key"]
    assert ids["choice_id"] not in row["idempotency_key"]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    conn.close()
