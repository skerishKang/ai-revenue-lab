"""Final idempotency concurrency contract tests.

Tests real concurrent requests using ThreadPoolExecutor with separate
SQLite connections. Verifies that the CAS idempotency mechanism correctly
handles concurrent requests for the same and different keys.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.db import apply_migrations, get_connection


def _make_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = _make_conn(path)
    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
    apply_migrations(conn, migrations_dir)

    conn.execute("INSERT INTO readers (id, display_name, status, created_at) VALUES (?, ?, 'active', ?)",
        ("reader-1", "Test Reader", "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO worlds (id, version, premise, genre, world_rules, canonical_timeline, unresolved_global_questions, created_at) VALUES (?, ?, ?, ?, '[]', '[]', '[]', ?)",
        ("world-1", "1.0", "A test world", "urban_mystery", "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO characters (id, world_id, canonical_name, role, traits, age_category, status, location_id, created_at) VALUES (?, ?, ?, ?, '[]', 'adult', 'active', ?, ?)",
        ("char-1", "world-1", "Test Character", "protagonist", "loc-1", "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO locations (id, world_id, name, connected_locations, created_at) VALUES (?, ?, ?, ?, ?)",
        ("loc-1", "world-1", "Test Location", '["loc-2"]', "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO locations (id, world_id, name, connected_locations, created_at) VALUES (?, ?, ?, ?, ?)",
        ("loc-2", "world-1", "Other Location", '["loc-1"]', "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO canon_snapshots (id, world_id, version, episode_number, accepted, world_state_json, character_states_json, location_states_json, clue_states_json, unresolved_threads_json, created_at) VALUES (?, ?, '1.0', 1, 1, '{}', '{}', '{}', '{}', '[]', ?)",
        ("snap-1", "world-1", "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO episodes (id, world_id, episode_type, episode_number, title, synopsis, scene_list_json, character_ids_json, location_ids_json, prose_json, clue_refs_json, world_state_deltas_json, unresolved_threads_json, review_state, created_at) VALUES (?, ?, 'canon', 1, 'Test', 'Test', '[]', '[]', '[]', '[]', '[]', '{}', '[]', 'published', ?)",
        ("ep-1", "world-1", "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO episodes (id, world_id, episode_type, episode_number, title, synopsis, scene_list_json, character_ids_json, location_ids_json, prose_json, review_state, created_at) VALUES (?, ?, 'personal_branch', 100, 'Branch', 'Branch', '[]', '[]', '[]', '[]', 'published', ?)",
        ("branch-ep-1", "world-1", "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) VALUES (?, ?, ?, ?, ?)",
        ("choice-1", "reader-1", "ep-1", "Test choice", "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO canon_checkpoints (id, canon_snapshot_id, episode_number, label, created_at) VALUES (?, ?, 1, 'test', ?)",
        ("snap-1", "snap-1", "2025-01-01T00:00:00Z"))
    conn.commit()
    conn.close()
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


def _open(path):
    return _make_conn(path)


# ── CAS Idempotency Tests ────────────────────────────────────────────────


def test_active_pending_rejected_without_provider_call(db_path):
    from app.branch_generation_request_repository import claim_branch_generation_request
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(conn, request_id="active-req", idempotency_key="active-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    assert not claim.is_rejected and claim.is_new

    conn.execute("BEGIN IMMEDIATE")
    claim2 = claim_branch_generation_request(conn, request_id="active-req-2", idempotency_key="active-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    assert claim2.is_rejected, "Active pending should be rejected"
    conn.close()


def test_stale_age_uses_pending_lease_not_created_at(db_path):
    from app.branch_generation_request_repository import claim_branch_generation_request
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim_branch_generation_request(conn, request_id="stale-test", idempotency_key="stale-test-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    conn.execute("UPDATE branch_generation_requests SET pending_lease_at = ?, created_at = '2020-01-01T00:00:00Z' WHERE id = 'stale-test'",
        ("2099-07-21T00:00:00Z",))
    conn.commit()

    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(conn, request_id="stale-test-2", idempotency_key="stale-test-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    assert claim.is_rejected, "Should be active (pending_lease_at is future)"
    conn.close()


def test_invalid_pending_timestamp_fails_closed(db_path):
    from app.branch_generation_request_repository import claim_branch_generation_request, CASClaimError
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim_branch_generation_request(conn, request_id="bad-ts-req", idempotency_key="bad-ts-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    conn.execute("UPDATE branch_generation_requests SET pending_lease_at = 'not-a-timestamp' WHERE id = 'bad-ts-req'")
    conn.commit()

    with pytest.raises(CASClaimError):
        conn.execute("BEGIN IMMEDIATE")
        try:
            claim_branch_generation_request(conn, request_id="bad-ts-req-2", idempotency_key="bad-ts-key",
                reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
                canon_checkpoint_id="snap-1", world_id="world-1")
        finally:
            conn.rollback()
    conn.close()


def test_same_key_different_operation_conflicts(db_path):
    from app.branch_generation_request_repository import claim_branch_generation_request, CASClaimError
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim_branch_generation_request(conn, request_id="op-req-1", idempotency_key="op-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1", operation_type="personal_branch")
    conn.commit()

    with pytest.raises(CASClaimError):
        conn.execute("BEGIN IMMEDIATE")
        try:
            claim_branch_generation_request(conn, request_id="op-req-2", idempotency_key="op-key",
                reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
                canon_checkpoint_id="snap-1", world_id="world-1", operation_type="different_operation")
        finally:
            conn.rollback()
    conn.close()


def test_completed_request_replays_original_episode(db_path):
    from app.branch_generation_request_repository import claim_branch_generation_request, complete_branch_generation_request
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(conn, request_id="replay-req", idempotency_key="replay-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    complete_branch_generation_request(conn, claim.request_id, "branch-ep-1")
    conn.commit()

    conn.execute("BEGIN IMMEDIATE")
    claim2 = claim_branch_generation_request(conn, request_id="replay-req-2", idempotency_key="replay-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    assert claim2.is_replay and claim2.request_record.branch_episode_id == "branch-ep-1"
    conn.close()


def test_failed_request_retry_reuses_same_row(db_path):
    from app.branch_generation_request_repository import claim_branch_generation_request, fail_branch_generation_request
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(conn, request_id="fail-req", idempotency_key="fail-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    fail_branch_generation_request(conn, claim.request_id, "test failure")
    conn.commit()

    conn.execute("BEGIN IMMEDIATE")
    claim2 = claim_branch_generation_request(conn, request_id="fail-req-2", idempotency_key="fail-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    assert not claim2.is_new and not claim2.is_replay
    assert claim2.attempt_number > claim.attempt_number
    conn.close()


def test_stale_pending_recovery(db_path):
    from app.branch_generation_request_repository import claim_branch_generation_request
    conn = _open(db_path)
    conn.execute("BEGIN IMMEDIATE")
    claim_branch_generation_request(conn, request_id="stale-req", idempotency_key="stale-recovery-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    conn.execute("UPDATE branch_generation_requests SET pending_lease_at = '2020-01-01T00:00:00Z', updated_at = '2020-01-01T00:00:00Z' WHERE id = 'stale-req'")
    conn.commit()

    conn.execute("BEGIN IMMEDIATE")
    claim = claim_branch_generation_request(conn, request_id="stale-recovery", idempotency_key="stale-recovery-key",
        reader_id="reader-1", reader_choice_id="choice-1", prior_episode_id="ep-1",
        canon_checkpoint_id="snap-1", world_id="world-1")
    conn.commit()
    assert not claim.is_rejected
    conn.close()


# ── Real Concurrency Tests ────────────────────────────────────────────────


def test_concurrent_same_key_only_one_completes(db_path):
    """Multiple concurrent threads with same key: only one completes, others are rejected or replayed."""
    from app.branch_generation_request_repository import claim_branch_generation_request, complete_branch_generation_request

    num_threads = 5
    results = []
    errors = []

    def try_claim(thread_id):
        try:
            conn = _make_conn(db_path)
            conn.execute("BEGIN IMMEDIATE")
            claim = claim_branch_generation_request(conn,
                request_id=f"thread-{thread_id}", idempotency_key="concurrent-key",
                reader_id="reader-1", reader_choice_id="choice-1",
                prior_episode_id="ep-1", canon_checkpoint_id="snap-1", world_id="world-1")
            if claim.is_new:
                # Simulate work then complete
                import time
                time.sleep(0.01)
                complete_branch_generation_request(conn, claim.request_id, "branch-ep-1")
            conn.commit()
            conn.close()
            return {"thread_id": thread_id, "new": claim.is_new, "replay": claim.is_replay, "rejected": claim.is_rejected}
        except Exception as e:
            return {"thread_id": thread_id, "error": str(e)}

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(try_claim, i) for i in range(num_threads)]
        results = [f.result(timeout=30) for f in as_completed(futures)]

    # Exactly one thread should have gotten is_new=True
    new_count = sum(1 for r in results if r.get("new"))
    assert new_count == 1, f"Expected exactly 1 new claim, got {new_count}: {results}"

    # Others should be rejected (active pending) or replayed
    rejected_or_replay = sum(1 for r in results if r.get("rejected") or r.get("replay"))
    assert rejected_or_replay == num_threads - 1, f"Expected {num_threads - 1} rejected/replay, got {rejected_or_replay}"

    # Verify only one completed request exists
    conn = _open(db_path)
    completed = conn.execute(
        "SELECT COUNT(*) as cnt FROM branch_generation_requests WHERE idempotency_key = 'concurrent-key' AND status = 'completed'"
    ).fetchone()
    assert completed["cnt"] == 1
    conn.close()


def test_concurrent_different_keys_proceed_independently(db_path):
    """Different idempotency keys can proceed concurrently."""
    from app.branch_generation_request_repository import claim_branch_generation_request, complete_branch_generation_request

    num_threads = 3

    def try_claim(thread_id):
        try:
            conn = _make_conn(db_path)
            conn.execute("BEGIN IMMEDIATE")
            claim = claim_branch_generation_request(conn,
                request_id=f"thread-{thread_id}", idempotency_key=f"different-key-{thread_id}",
                reader_id="reader-1", reader_choice_id="choice-1",
                prior_episode_id="ep-1", canon_checkpoint_id="snap-1", world_id="world-1")
            if claim.is_new:
                complete_branch_generation_request(conn, claim.request_id, "branch-ep-1")
            conn.commit()
            conn.close()
            return {"thread_id": thread_id, "new": claim.is_new}
        except Exception as e:
            return {"thread_id": thread_id, "error": str(e)}

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(try_claim, i) for i in range(num_threads)]
        results = [f.result(timeout=30) for f in as_completed(futures)]

    # All should be new since they have different keys
    new_count = sum(1 for r in results if r.get("new"))
    assert new_count == num_threads, f"Expected {num_threads} new claims, got {new_count}: {results}"

    conn = _open(db_path)
    completed = conn.execute(
        "SELECT COUNT(*) as cnt FROM branch_generation_requests WHERE status = 'completed'"
    ).fetchone()
    assert completed["cnt"] == num_threads
    conn.close()


def test_concurrent_different_readers_same_episode(db_path):
    """Different readers with different choices can proceed concurrently."""
    from app.branch_generation_request_repository import claim_branch_generation_request, complete_branch_generation_request

    conn = _open(db_path)
    conn.execute("INSERT INTO readers (id, display_name, status, created_at) VALUES (?, ?, 'active', ?)",
        ("reader-2", "Reader Two", "2025-01-01T00:00:00Z"))
    conn.execute("INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) VALUES (?, ?, ?, ?, ?)",
        ("choice-2", "reader-2", "ep-1", "Second choice", "2025-01-01T00:00:00Z"))
    # Create extra branch episodes for each thread to reference
    for i in range(2):
        conn.execute(
            "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
            "title, synopsis, scene_list_json, character_ids_json, "
            "location_ids_json, prose_json, review_state, created_at) "
            "VALUES (?, ?, 'personal_branch', ?, 'Branch', 'Branch', "
            "'[]', '[]', '[]', '[]', 'published', ?)",
            (f"branch-ep-{i+2}", "world-1", 100 + i + 1, "2025-01-01T00:00:00Z"),
        )
    conn.commit()
    conn.close()

    def try_claim(reader_id, choice_id, key, ep_id):
        try:
            conn = _make_conn(db_path)
            conn.execute("BEGIN IMMEDIATE")
            claim = claim_branch_generation_request(conn,
                request_id=f"req-{reader_id}", idempotency_key=key,
                reader_id=reader_id, reader_choice_id=choice_id,
                prior_episode_id="ep-1", canon_checkpoint_id="snap-1", world_id="world-1")
            if claim.is_new:
                complete_branch_generation_request(conn, claim.request_id, ep_id)
            conn.commit()
            conn.close()
            return {"reader_id": reader_id, "new": claim.is_new, "replay": claim.is_replay, "rejected": claim.is_rejected}
        except Exception as e:
            return {"reader_id": reader_id, "error": str(e)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(try_claim, "reader-1", "choice-1", "multi-reader-reader-1", "branch-ep-2")
        f2 = executor.submit(try_claim, "reader-2", "choice-2", "multi-reader-reader-2", "branch-ep-3")
        results = [f1.result(timeout=30), f2.result(timeout=30)]

    # Each unique key should get is_new=True (different readers, different choices)
    new_count = sum(1 for r in results if r.get("new"))
    assert new_count == 2, f"Expected 2 new claims, got {new_count}: {results}"

    # Verify both completed requests exist
    conn = _open(db_path)
    completed = conn.execute(
        "SELECT COUNT(*) as cnt FROM branch_generation_requests WHERE status = 'completed'"
    ).fetchone()
    assert completed["cnt"] == 2
    conn.close()
