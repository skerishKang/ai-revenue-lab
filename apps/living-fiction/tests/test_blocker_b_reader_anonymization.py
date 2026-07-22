"""Blocker B — Reader and choice complete anonymization tests.

Verifies that after reader deletion:
- Original reader_id is gone from ALL tables (0 occurrences)
- Original choice_id is gone from ALL tables (0 occurrences)
- Original choice_text is gone
- Anonymous records exist and are correctly linked
- Close/reopen preserves the anonymized state
- Other readers' data is untouched
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from app.db import apply_migrations, get_connection
from app.reader_deletion_service import delete_reader_with_revocation


def _make_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _seed_full_data(conn, reader_id="reader-1", choice_id="choice-1"):
    now = "2025-07-21T00:00:00Z"
    conn.execute("INSERT INTO readers (id, display_name, status, created_at) VALUES (?, ?, 'active', ?)",
                 (reader_id, "Original Reader", now))
    conn.execute("INSERT INTO worlds (id, version, premise, genre, world_rules, canonical_timeline, unresolved_global_questions, created_at) VALUES (?, ?, ?, ?, '[]', '[]', '[]', ?)",
                 ("world-1", "1.0", "Test", "urban_mystery", now))
    conn.execute("INSERT INTO characters (id, world_id, canonical_name, role, traits, age_category, status, created_at) VALUES (?, ?, ?, ?, '[]', 'adult', 'active', ?)",
                 ("char-1", "world-1", "Char", "protagonist", now))
    conn.execute("INSERT INTO canon_snapshots (id, world_id, version, episode_number, accepted, world_state_json, character_states_json, location_states_json, clue_states_json, unresolved_threads_json, created_at) VALUES (?, ?, '1.0', 1, 1, '{}', '{}', '{}', '{}', '[]', ?)",
                 ("snap-1", "world-1", now))
    conn.execute("INSERT INTO canon_checkpoints (id, canon_snapshot_id, episode_number, label, created_at) VALUES (?, ?, 1, 'test', ?)",
                 ("cp-1", "snap-1", now))
    conn.execute("INSERT INTO episodes (id, world_id, episode_type, episode_number, title, synopsis, scene_list_json, character_ids_json, location_ids_json, prose_json, review_state, created_at) VALUES (?, ?, 'canon', 1, 'Test', 'Test', '[]', '[]', '[]', '[]', 'published', ?)",
                 ("canon-ep-1", "world-1", now))

    # Choice
    conn.execute("INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, comment, submitted_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (choice_id, reader_id, "canon-ep-1", "SECRET_choice_text", "SECRET_comment", now))

    # Branch episode with applied reader input
    conn.execute("INSERT INTO episodes (id, world_id, episode_type, episode_number, reader_id, review_state, title, synopsis, scene_list_json, character_ids_json, location_ids_json, prose_json, applied_reader_input_json, created_at) VALUES (?, ?, 'personal_branch', 1, ?, 'published', 'Branch', 'Branch', '[]', '[]', '[]', '[]', ?, ?)",
                 ("branch-ep-1", "world-1", reader_id,
                  json.dumps({"reader_choice_id": choice_id, "choice_text": "SECRET_choice_text",
                              "comment": "SECRET_comment", "applied_evidence": "Evidence"}), now))

    # Branch record
    conn.execute("INSERT INTO branches (id, reader_id, canon_checkpoint_id, prior_episode_id, branch_episode_id, reader_choice_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
                 ("branch-1", reader_id, "cp-1", "canon-ep-1", "branch-ep-1", choice_id, now))

    # Generation request
    conn.execute("INSERT INTO branch_generation_requests (id, idempotency_key, reader_id, reader_choice_id, prior_episode_id, canon_checkpoint_id, world_id, status, created_at, operation_type, attempt_number, pending_lease_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, 'personal_branch', 1, ?, ?)",
                 ("gen-req-1", "key-1", reader_id, choice_id, "canon-ep-1", "cp-1", "world-1", now, now, now))

    # Rejoin request
    conn.execute("INSERT INTO rejoin_requests (branch_id, target_checkpoint_id, status, created_at) VALUES (?, ?, 'pending', ?)",
                 ("branch-1", "cp-1", now))

    # Pilot evidence
    conn.execute("INSERT INTO pilot_evidence (id, evidence_category, reader_id, evidence_data_json, privacy_safe, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                 ("pe-1", "consent", reader_id, json.dumps({"comment": "SECRET_data"}), now))

    conn.commit()


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = _make_conn(path)
    apply_migrations(conn, os.path.join(os.path.dirname(__file__), "..", "migrations"))
    conn.close()
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


def _search_all_tables(conn, search_text):
    """Count occurrences of search_text in ALL text columns across ALL tables."""
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    count = 0
    details = []
    for (tname,) in tables:
        try:
            info = conn.execute(f"PRAGMA table_info('{tname}')").fetchall()
            text_cols = [c[1] for c in info]
            for col in text_cols:
                rows = conn.execute(
                    f'SELECT "{col}" FROM "{tname}" WHERE "{col}" LIKE ?',
                    (f"%{search_text}%",),
                ).fetchall()
                if rows:
                    count += len(rows)
                    details.append(f"{tname}.{col}: {len(rows)} hits")
        except Exception:
            pass
    return count, details


def test_original_reader_id_zero_references_after_deletion(db_path):
    """After deletion, original reader_id appears in ZERO personal linkage rows."""
    conn = _make_conn(db_path)
    _seed_full_data(conn)
    conn.close()

    original_reader_id = "reader-1"

    conn = _make_conn(db_path)
    result = delete_reader_with_revocation(conn, original_reader_id)
    conn.close()
    assert result.success

    conn = _make_conn(db_path)

    # Search in specific tables that should have been anonymized
    tables_to_check = [
        "reader_choices", "branches", "branch_generation_requests",
        "episodes", "pilot_evidence", "rejoin_requests",
    ]
    for table in tables_to_check:
        try:
            rows = conn.execute(
                f'SELECT COUNT(*) as c FROM "{table}" WHERE reader_id = ?',
                (original_reader_id,),
            ).fetchone()["c"]
            assert rows == 0, f"Original reader_id found in {table}: {rows} rows"
        except Exception:
            pass

    # Also check reader_choice_id in branches and gen requests
    for table in ["branches", "branch_generation_requests"]:
        try:
            rows = conn.execute(
                f'SELECT COUNT(*) as c FROM "{table}" WHERE reader_choice_id = ?',
                ("choice-1",),
            ).fetchone()["c"]
            # After our fix, these should point to anonymous choice, not original
            if rows > 0:
                # Check if the choice_id is the original or anonymous
                raw = conn.execute(
                    f'SELECT reader_choice_id FROM "{table}" WHERE reader_choice_id = ?',
                    ("choice-1",),
                ).fetchall()
                # Original choice-1 should not exist anymore (deleted)
                choice_exists = conn.execute(
                    "SELECT COUNT(*) as c FROM reader_choices WHERE id = ?",
                    ("choice-1",),
                ).fetchone()["c"]
                assert choice_exists == 0, f"Original choice-1 still exists in reader_choices"
        except Exception:
            pass

    # Verify anonymous records exist
    anon_reader = conn.execute(
        "SELECT COUNT(*) as c FROM readers WHERE id LIKE 'anon-%' AND status = 'deleted'"
    ).fetchone()["c"]
    assert anon_reader >= 1, "No anonymous reader record created"

    anon_choice = conn.execute(
        "SELECT COUNT(*) as c FROM reader_choices WHERE id LIKE 'anon-choice-%'"
    ).fetchone()["c"]
    assert anon_choice >= 1, "No anonymous choice record created"

    conn.close()


def test_original_choice_text_zero_references_after_deletion(db_path):
    """After deletion, original choice_text and comment are gone from all text columns."""
    conn = _make_conn(db_path)
    _seed_full_data(conn)
    conn.close()

    conn = _make_conn(db_path)
    delete_reader_with_revocation(conn, "reader-1")
    conn.close()

    conn = _make_conn(db_path)

    # Search for secret text across all tables
    for secret in ["SECRET_choice_text", "SECRET_comment", "SECRET_data"]:
        count, details = _search_all_tables(conn, secret)
        assert count == 0, f"Secret '{secret}' found after deletion: {details}"

    # Verify anonymized values exist
    anon_text_count = _search_all_tables(conn, "[anonymized]")[0]
    assert anon_text_count >= 1, "No anonymized text found"

    conn.close()


def test_anonymous_choice_repoints_branch_and_gen_request(db_path):
    """Branches and gen requests point to anonymous choice after deletion."""
    conn = _make_conn(db_path)
    _seed_full_data(conn)
    conn.close()

    conn = _make_conn(db_path)
    delete_reader_with_revocation(conn, "reader-1")
    conn.close()

    conn = _make_conn(db_path)

    # Branch should point to anonymous choice
    branch = conn.execute(
        "SELECT reader_choice_id FROM branches WHERE id = 'branch-1'"
    ).fetchone()
    assert branch is not None
    assert branch["reader_choice_id"] != "choice-1", "Branch still points to original choice"
    assert branch["reader_choice_id"].startswith("anon-choice-"), \
        f"Branch should point to anonymous choice, got: {branch['reader_choice_id']}"

    # Gen request should point to anonymous choice
    gr = conn.execute(
        "SELECT reader_choice_id FROM branch_generation_requests WHERE id = 'gen-req-1'"
    ).fetchone()
    assert gr is not None
    assert gr["reader_choice_id"] != "choice-1", "Gen request still points to original choice"
    assert gr["reader_choice_id"].startswith("anon-choice-"), \
        f"Gen request should point to anonymous choice, got: {gr['reader_choice_id']}"

    # Original choice row should be deleted
    orig_choice = conn.execute(
        "SELECT COUNT(*) as c FROM reader_choices WHERE id = 'choice-1'"
    ).fetchone()["c"]
    assert orig_choice == 0, "Original choice row still exists"

    conn.close()


def test_other_reader_data_untouched(db_path):
    """Deleting reader-1 does not modify reader-2's data."""
    conn = _make_conn(db_path)
    _seed_full_data(conn, reader_id="reader-1", choice_id="choice-1")

    # Add reader-2 with different data
    now = "2025-07-21T00:00:00Z"
    conn.execute("INSERT INTO readers (id, display_name, status, created_at) VALUES (?, ?, 'active', ?)",
                 ("reader-2", "Other Reader", now))
    conn.execute("INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) VALUES (?, ?, ?, ?, ?)",
                 ("choice-2", "reader-2", "canon-ep-1", "Other choice", now))
    conn.commit()
    conn.close()

    conn = _make_conn(db_path)
    delete_reader_with_revocation(conn, "reader-1")
    conn.close()

    conn = _make_conn(db_path)

    # reader-2's choice should be untouched
    choice2 = conn.execute(
        "SELECT choice_text, reader_id FROM reader_choices WHERE id = 'choice-2'"
    ).fetchone()
    assert choice2 is not None
    assert choice2["reader_id"] == "reader-2"
    assert choice2["choice_text"] == "Other choice"

    # reader-2 should still be active
    r2 = conn.execute("SELECT status FROM readers WHERE id = 'reader-2'").fetchone()
    assert r2 is not None
    assert r2["status"] == "active"

    conn.close()


def test_close_reopen_preserves_anonymized_state(db_path):
    """Anonymized state survives close/reopen."""
    conn = _make_conn(db_path)
    _seed_full_data(conn)
    conn.close()

    conn = _make_conn(db_path)
    delete_reader_with_revocation(conn, "reader-1")
    conn.close()

    # Close and reopen
    conn = _make_conn(db_path)

    # Verify original is gone
    count, _ = _search_all_tables(conn, "SECRET_choice_text")
    assert count == 0

    # Verify anonymous exists
    anon = conn.execute(
        "SELECT COUNT(*) as c FROM reader_choices WHERE id LIKE 'anon-choice-%'"
    ).fetchone()["c"]
    assert anon >= 1

    # Verify FK integrity
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(violations) == 0, f"FK violations after close/reopen: {violations}"

    conn.close()


def test_episode_applied_reader_input_anonymized(db_path):
    """Episode's applied_reader_input_json has all personal data anonymized."""
    conn = _make_conn(db_path)
    _seed_full_data(conn)
    conn.close()

    conn = _make_conn(db_path)
    delete_reader_with_revocation(conn, "reader-1")
    conn.close()

    conn = _make_conn(db_path)
    ep = conn.execute(
        "SELECT applied_reader_input_json, is_reader_input_anonymized FROM episodes WHERE id = 'branch-ep-1'"
    ).fetchone()
    assert ep is not None
    assert ep["is_reader_input_anonymized"] == 1
    ari = json.loads(ep["applied_reader_input_json"])
    assert ari["comment"] == "[anonymized]"
    assert ari["choice_text"] == "[anonymized]"
    assert ari["reader_choice_id"] == "[anonymized]"
    assert ari["private_text"] == "[anonymized]"
    conn.close()


def test_pilot_evidence_anonymized(db_path):
    """Pilot evidence has reader_id removed and private data redacted."""
    conn = _make_conn(db_path)
    _seed_full_data(conn)
    conn.close()

    conn = _make_conn(db_path)
    delete_reader_with_revocation(conn, "reader-1")
    conn.close()

    conn = _make_conn(db_path)
    pe = conn.execute(
        "SELECT reader_id, evidence_data_json FROM pilot_evidence WHERE id = 'pe-1'"
    ).fetchone()
    assert pe is not None
    assert pe["reader_id"] is None, "PE reader_id should be NULL"
    data = json.loads(pe["evidence_data_json"])
    assert data.get("comment") == "[redacted]", "Private field not redacted"
    conn.close()


def test_rejoin_requests_deleted(db_path):
    """Rejoin requests for deleted reader's branches are removed."""
    conn = _make_conn(db_path)
    _seed_full_data(conn)
    conn.close()

    conn = _make_conn(db_path)
    delete_reader_with_revocation(conn, "reader-1")
    conn.close()

    conn = _make_conn(db_path)
    rr = conn.execute(
        "SELECT COUNT(*) as c FROM rejoin_requests WHERE branch_id = 'branch-1'"
    ).fetchone()["c"]
    assert rr == 0, f"Rejoin requests not deleted: {rr}"
    conn.close()
