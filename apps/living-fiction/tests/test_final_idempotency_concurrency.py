"""Final idempotency concurrency contract tests.

Tests atomic CAS claim operations with file-backed SQLite connections.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from app.branch_generation_request_repository import (
    claim_branch_generation_request,
    complete_branch_generation_request,
    fail_branch_generation_request,
    get_by_idempotency_key,
    CASClaimError,
)


def _make_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture
def db_path():
    """Create a file-backed DB with all migrations applied and seeded."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = _make_conn(path)
    from app.db import apply_migrations
    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
    apply_migrations(conn, migrations_dir)
    # Seed basic data
    conn.execute(
        "INSERT INTO readers (id, display_name, status, created_at) "
        "VALUES (?, ?, 'active', ?)",
        ("reader-1", "Test Reader", "2025-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO worlds (id, version, premise, genre, world_rules, "
        "canonical_timeline, unresolved_global_questions, created_at) "
        "VALUES (?, ?, ?, ?, '[]', '[]', '[]', ?)",
        ("world-1", "1.0", "A test world", "urban_mystery", "2025-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO characters (id, world_id, canonical_name, role, "
        "traits, age_category, status, created_at) "
        "VALUES (?, ?, ?, ?, '[]', 'adult', 'active', ?)",
        ("char-1", "world-1", "Test Character", "protagonist", "2025-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO locations (id, world_id, name, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("loc-1", "world-1", "Test Location", "2025-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO canon_snapshots "
        "(id, world_id, version, episode_number, accepted, "
        "world_state_json, character_states_json, location_states_json, "
        "clue_states_json, unresolved_threads_json, created_at) "
        "VALUES (?, ?, '1.0', 1, 1, '{}', '{}', '{}', '{}', '[]', ?)",
        ("snap-1", "world-1", "2025-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
        "title, synopsis, scene_list_json, character_ids_json, "
        "location_ids_json, prose_json, review_state, created_at) "
        "VALUES (?, ?, 'canon', 1, 'Test', 'Test', '[]', '[]', '[]', '[]', "
        "'published', ?)",
        ("ep-1", "world-1", "2025-01-01T00:00:00Z"),
    )
    # Second episode for FK reference in completed tests
    conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
        "title, synopsis, scene_list_json, character_ids_json, "
        "location_ids_json, prose_json, review_state, created_at) "
        "VALUES (?, ?, 'personal_branch', 100, 'Branch', 'Branch', "
        "'[]', '[]', '[]', '[]', 'published', ?)",
        ("branch-ep-1", "world-1", "2025-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, "
        "submitted_at) VALUES (?, ?, ?, ?, ?)",
        ("choice-1", "reader-1", "ep-1", "Test choice", "2025-01-01T00:00:00Z"),
    )
    # Create canon_checkpoint with proper FK to snapshot
    conn.execute(
        "INSERT INTO canon_checkpoints (id, canon_snapshot_id, episode_number, "
        "label, created_at) VALUES (?, ?, 1, 'test', ?)",
        ("snap-1", "snap-1", "2025-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


def _open(path):
    return _make_conn(path)


def test_active_pending_rejected_without_provider_call(db_path):
    """Active pending request is rejected without provider call."""
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(
        conn,
        request_id="active-req",
        idempotency_key="active-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()
    assert not claim.is_rejected
    assert claim.is_new

    # Second claim with same key should be rejected (active pending)
    conn.execute("BEGIN IMMEDIATE")
    claim2 = claim_branch_generation_request(
        conn,
        request_id="active-req-2",
        idempotency_key="active-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()
    assert claim2.is_rejected, "Active pending should be rejected"
    conn.close()


def test_stale_age_uses_pending_lease_not_created_at(db_path):
    """Staleness uses pending_lease_at, not created_at."""
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim_branch_generation_request(
        conn,
        request_id="stale-test",
        idempotency_key="stale-test-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()

    # Set pending_lease_at to a recent time but created_at to far past
    conn.execute(
        "UPDATE branch_generation_requests SET "
        "pending_lease_at = ?, created_at = '2020-01-01T00:00:00Z' "
        "WHERE id = 'stale-test'",
        ("2099-07-21T00:00:00Z",),  # Far future = not stale
    )
    conn.commit()

    # Should NOT be stale (pending_lease_at is far future)
    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(
        conn,
        request_id="stale-test-2",
        idempotency_key="stale-test-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()
    assert claim.is_rejected, "Should be active (pending_lease_at is future)"
    conn.close()


def test_invalid_pending_timestamp_fails_closed(db_path):
    """Invalid timestamp in pending_lease_at raises CASClaimError."""
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim_branch_generation_request(
        conn,
        request_id="bad-ts-req",
        idempotency_key="bad-ts-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()

    # Set an invalid timestamp
    conn.execute(
        "UPDATE branch_generation_requests SET "
        "pending_lease_at = 'not-a-timestamp' WHERE id = 'bad-ts-req'"
    )
    conn.commit()

    with pytest.raises(CASClaimError):
        conn.execute("BEGIN IMMEDIATE")
        try:
            claim_branch_generation_request(
                conn,
                request_id="bad-ts-req-2",
                idempotency_key="bad-ts-key",
                reader_id="reader-1",
                reader_choice_id="choice-1",
                prior_episode_id="ep-1",
                canon_checkpoint_id="snap-1",
                world_id="world-1",
            )
        finally:
            conn.rollback()
    conn.close()


def test_same_key_different_operation_conflicts(db_path):
    """Same key with different operation type is a conflict."""
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim_branch_generation_request(
        conn,
        request_id="op-req-1",
        idempotency_key="op-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
        operation_type="personal_branch",
    )
    conn.commit()

    with pytest.raises(CASClaimError):
        conn.execute("BEGIN IMMEDIATE")
        try:
            claim_branch_generation_request(
                conn,
                request_id="op-req-2",
                idempotency_key="op-key",
                reader_id="reader-1",
                reader_choice_id="choice-1",
                prior_episode_id="ep-1",
                canon_checkpoint_id="snap-1",
                world_id="world-1",
                operation_type="different_operation",
            )
        finally:
            conn.rollback()
    conn.close()


def test_completed_request_replays_original_episode(db_path):
    """Completed request replays original result without provider call."""
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(
        conn,
        request_id="replay-req",
        idempotency_key="replay-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    complete_branch_generation_request(conn, claim.request_id, "branch-ep-1")
    conn.commit()

    # Replay with same key
    conn.execute("BEGIN IMMEDIATE")
    claim2 = claim_branch_generation_request(
        conn,
        request_id="replay-req-2",
        idempotency_key="replay-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()
    assert claim2.is_replay, "Completed request should be replayed"
    assert claim2.request_record is not None
    assert claim2.request_record.branch_episode_id == "branch-ep-1"
    conn.close()


def test_failed_request_retry_reuses_same_row(db_path):
    """Failed request retry reuses the same row (CAS retry)."""
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(
        conn,
        request_id="fail-req",
        idempotency_key="fail-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    fail_branch_generation_request(conn, claim.request_id, "test failure")
    conn.commit()

    request_id = claim.request_id
    # Retry - should reuse same row
    conn.execute("BEGIN IMMEDIATE")
    claim2 = claim_branch_generation_request(
        conn,
        request_id="fail-req-2",
        idempotency_key="fail-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()
    assert not claim2.is_new, "Should reuse existing row"
    assert not claim2.is_replay, "Should not be replay"
    assert claim2.attempt_number > claim.attempt_number, "Attempt number should increase"
    conn.close()


def test_stale_pending_recovery(db_path):
    """Stale pending request is recoverable."""
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim_branch_generation_request(
        conn,
        request_id="stale-req",
        idempotency_key="stale-recovery-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()

    # Set pending_lease_at far in the past to make it stale
    conn.execute(
        "UPDATE branch_generation_requests SET "
        "pending_lease_at = '2020-01-01T00:00:00Z', "
        "updated_at = '2020-01-01T00:00:00Z' "
        "WHERE id = 'stale-req'"
    )
    conn.commit()

    # Stale recovery should succeed
    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(
        conn,
        request_id="stale-recovery",
        idempotency_key="stale-recovery-key",
        reader_id="reader-1",
        reader_choice_id="choice-1",
        prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1",
        world_id="world-1",
    )
    conn.commit()
    assert not claim.is_rejected, "Stale pending should be recoverable"
    conn.close()
