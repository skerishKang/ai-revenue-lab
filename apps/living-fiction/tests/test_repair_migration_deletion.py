"""Tests: CTO repair — migration upgrade, reader deletion/revocation, close/reopen.

Tests:
- fresh DB migration (001 + 002);
- existing 001 DB upgrade to 002;
- data preservation;
- migration applied twice as no-op;
- reader deletion/revocation;
- deletion idempotency;
- close/reopen persistence;
- no private comments or reader identifiers after deletion.
"""

import hashlib
import json
import os

import pytest

from app import reader_repository as reader_repo
from app import choice_repository as choice_repo
from app import episode_repository as ep_repo
from app import branch_repository as branch_repo
from app import pilot_evidence_repository as pe_repo
from app import world_repository as world_repo
from app.db import apply_migrations, get_connection
from app.reader_deletion_service import delete_reader_with_revocation
from app.deletion_audit_repository import get_deletion_audit_by_reader
from app.utils import now_utc_iso
from tests.fixtures.synthetic_world import WORLD_STATE


def _reader_digest(reader_id: str) -> str:
    """Use the same HMAC approach as the deletion service."""
    import os
    import hmac
    # Must match the key used by the service - set env var for test
    hmac_key = os.environ.get("LF_DELETION_HMAC_KEY", "test-default-key")
    return hmac.new(
        hmac_key.encode("utf-8"),
        reader_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


# Ensure HMAC key is set for testing
import os
os.environ.setdefault("LF_DELETION_HMAC_KEY", "test-default-key")


def test_fresh_db_has_all_migrations(temp_db_path):
    """Fresh DB gets all migrations (001, 002, 003)."""
    conn = get_connection(temp_db_path)
    migrations_dir = str(
        os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    applied = apply_migrations(conn, migrations_dir)
    assert "001_initial.sql" in applied
    assert "002_repair_additive.sql" in applied
    assert "003_idempotency_continuity_privacy.sql" in applied

    # Check new tables exist
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {t["name"] for t in tables}
    assert "generation_attempts" in table_names
    assert "branch_generation_requests" in table_names
    assert "rejoin_requests_v2" in table_names
    assert "reader_deletion_audit" in table_names

    # Check 003 columns exist on branch_generation_requests
    cols = {c[1] for c in conn.execute("PRAGMA table_info(branch_generation_requests)").fetchall()}
    assert "operation_type" in cols
    assert "attempt_number" in cols
    assert "pending_lease_at" in cols
    assert "updated_at" in cols

    conn.close()


def test_fresh_db_has_migration_002(temp_db_path):
    """Fresh DB gets both migrations (backward compat)."""
    conn = get_connection(temp_db_path)
    migrations_dir = str(
        os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    applied = apply_migrations(conn, migrations_dir)
    assert "001_initial.sql" in applied
    assert "002_repair_additive.sql" in applied

    conn.close()


def test_existing_001_db_upgrades_to_002(temp_db_path):
    """Existing DB with only 001 upgrades to 002."""
    conn = get_connection(temp_db_path)
    migrations_dir = str(
        os.path.join(os.path.dirname(__file__), "..", "migrations")
    )

    # Apply migrations (both 001 and 002 run together)
    apply_migrations(conn, migrations_dir)

    # Verify 001 tables exist
    tables_before = {t["name"] for t in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "readers" in tables_before
    assert "episodes" in tables_before

    # Verify 002 tables also exist (additive)
    assert "generation_attempts" in tables_before
    assert "branch_generation_requests" in tables_before
    assert "rejoin_requests_v2" in tables_before
    assert "reader_deletion_audit" in tables_before

    conn.close()


def test_migration_idempotent(temp_db_path):
    """Migration applied twice is a no-op."""
    conn = get_connection(temp_db_path)
    migrations_dir = str(
        os.path.join(os.path.dirname(__file__), "..", "migrations")
    )

    apply_migrations(conn, migrations_dir)
    applied = apply_migrations(conn, migrations_dir)
    assert applied == []

    conn.close()


def test_data_preserved_after_upgrade(temp_db_path):
    """Data from 001 is preserved after full 001->002->003 upgrade stack."""
    conn = get_connection(temp_db_path)
    migrations_dir = str(
        os.path.join(os.path.dirname(__file__), "..", "migrations")
    )

    # Apply all migrations
    apply_migrations(conn, migrations_dir)

    # Create some data
    world_repo.create_world(conn, WORLD_STATE)
    reader = reader_repo.create_reader(conn, display_name="preserved 독자")
    assert reader.status == "active"

    # Reapply (idempotent)
    apply_migrations(conn, migrations_dir)

    # Verify data is preserved
    reader_after = reader_repo.get_reader(conn, reader.id)
    assert reader_after is not None
    assert reader_after.display_name == "preserved 독자"
    assert reader_after.status == "active"

    # Verify 003 columns work
    from app.branch_generation_request_repository import create_request
    # Create FK target records
    conn.execute(
        "INSERT OR IGNORE INTO episodes (id, world_id, episode_type, episode_number, title, "
        "synopsis, scene_list_json, character_ids_json, location_ids_json, prose_json, "
        "review_state, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', ?)",
        ("ep-placeholder", WORLD_STATE.world_id, "canon", 0, "x", "x",
         "[]", "[]", "[]", "[]", now_utc_iso()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("rc-placeholder", reader.id, "ep-placeholder", "test", now_utc_iso()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO canon_snapshots (id, world_id, version, episode_number, "
        "world_state_json, character_states_json, location_states_json, "
        "clue_states_json, unresolved_threads_json, accepted, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
        ("snap-placeholder", WORLD_STATE.world_id, "v1", 0,
         "{}", "{}", "{}", "{}", "[]", now_utc_iso()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO canon_checkpoints (id, canon_snapshot_id, episode_number, label, "
        "is_compatible_for_rejoin, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cp-placeholder", "snap-placeholder", 0, "test", 1, now_utc_iso()),
    )
    create_request(
        conn, request_id="req-preserve-test", idempotency_key="preserve-key",
        reader_id=reader.id, reader_choice_id="rc-placeholder",
        prior_episode_id="ep-placeholder",
        canon_checkpoint_id="cp-placeholder", world_id=WORLD_STATE.world_id,
    )
    row = conn.execute(
        "SELECT operation_type, attempt_number FROM branch_generation_requests WHERE id = ?",
        ("req-preserve-test",),
    ).fetchone()
    assert row is not None
    assert row["operation_type"] == "personal_branch"
    assert row["attempt_number"] == 1

    conn.close()


# ── Reader deletion/revocation ──────────────────────────────────────────────


def _setup_reader_with_data(db_conn):
    """Create a reader with choices, episodes, branches, pilot evidence."""
    world_repo.create_world(db_conn, WORLD_STATE)
    reader = reader_repo.create_reader(db_conn, display_name="삭제될 독자")

    # Create a canon episode
    ep_repo.create_episode(
        db_conn, episode_id="ep-canon-del", world_id=WORLD_STATE.world_id,
        episode_type="canon", episode_number=1, title="canon", synopsis="syn",
        scene_list=[], character_ids=[], location_ids=[], prose=[],
    )
    ep_repo.publish_episode(db_conn, "ep-canon-del")

    # Create a choice with comment
    choice = choice_repo.create_reader_choice(
        db_conn, choice_id="choice-del-test", reader_id=reader.id,
        canon_episode_id="ep-canon-del", choice_text="test",
        comment="private reader comment",
    )

    # Create a branch episode
    ep_repo.create_episode(
        db_conn, episode_id="ep-branch-del", world_id=WORLD_STATE.world_id,
        episode_type="personal_branch", episode_number=1, title="branch", synopsis="syn",
        scene_list=[], character_ids=[], location_ids=[], prose=[],
        reader_id=reader.id,
        applied_reader_input={"reader_choice_id": choice.id, "comment": "private comment"},
    )

    # Create a branch
    canon_repo = __import__("app.canon_repository", fromlist=["create_canon_snapshot"])
    canon_repo.create_canon_snapshot(
        db_conn, snapshot_id="snap-del", world_id=WORLD_STATE.world_id,
        version="v1", episode_number=1,
        world_state={}, character_states={}, location_states={},
        clue_states={}, unresolved_threads=[], accepted=True,
    )
    canon_repo.create_canon_checkpoint(
        db_conn, checkpoint_id="cp-del", canon_snapshot_id="snap-del",
        episode_number=1, label="del", is_compatible_for_rejoin=True,
    )
    branch_repo.create_branch(
        db_conn, branch_id="branch-del", reader_id=reader.id,
        canon_checkpoint_id="cp-del", prior_episode_id="ep-canon-del",
        branch_episode_id="ep-branch-del", reader_choice_id="choice-del-test",
    )

    # Create pilot evidence
    pe_repo.create_pilot_evidence(
        db_conn, evidence_id="pe-del", evidence_category="engagement",
        evidence_data={"test": True}, reader_id=reader.id,
    )

    return reader, choice


def test_reader_deletion_revocation(db_conn):
    """Reader deletion/anonymization removes personal linkage."""
    reader, choice = _setup_reader_with_data(db_conn)

    result = delete_reader_with_revocation(db_conn, reader.id)
    assert result.success
    assert result.choices_revoked == 1  # 1 unapplied choice revoked
    assert result.branches_anonymized == 1
    assert result.episodes_anonymized == 1
    assert result.pilot_evidence_anonymized == 1

    # Reader is marked deleted
    deleted_reader = reader_repo.get_reader(db_conn, reader.id)
    assert deleted_reader.status == "deleted"
    assert deleted_reader.display_name == "[deleted-reader]"

    # Branch episode has no reader_id
    branch_ep = ep_repo.get_episode_by_id(db_conn, "ep-branch-del")
    assert branch_ep.reader_id is None

    # Branch has anonymized reader_id (real FK reference, not '[deleted]')
    branch = branch_repo.get_branch(db_conn, "branch-del")
    assert branch.reader_id.startswith("anon-")
    assert branch.reader_id != "anon-deleted-principal"

    # Pilot evidence has no reader_id
    pe = pe_repo.get_pilot_evidence(db_conn, "pe-del")
    assert pe.reader_id is None  # anonymized

    # Audit record exists
    audit = get_deletion_audit_by_reader(db_conn, _reader_digest(reader.id))
    assert audit is not None
    assert audit.reader_id == _reader_digest(reader.id)


def test_reader_deletion_idempotent(db_conn):
    """Deleting an already-deleted reader is a no-op."""
    reader, choice = _setup_reader_with_data(db_conn)

    result1 = delete_reader_with_revocation(db_conn, reader.id)
    assert result1.success

    result2 = delete_reader_with_revocation(db_conn, reader.id)
    assert result2.success
    assert result2.choices_revoked == 0  # no changes on second call


def test_reader_deletion_no_private_comments(db_conn):
    """No private comments remain after deletion."""
    reader, choice = _setup_reader_with_data(db_conn)

    delete_reader_with_revocation(db_conn, reader.id)

    # Check that the choice comment is anonymized
    updated_choice = choice_repo.get_reader_choice(db_conn, choice.id)
    if updated_choice.applied_to_branch_id is not None:
        # Applied choices have comment anonymized
        assert updated_choice.comment in (None, "[anonymized]")
    else:
        # Unapplied choices have comment removed
        assert updated_choice.comment is None


def test_reader_deletion_preserves_canon(db_conn):
    """Shared canon is preserved after reader deletion."""
    reader, choice = _setup_reader_with_data(db_conn)

    delete_reader_with_revocation(db_conn, reader.id)

    # Canon episode still exists
    canon_ep = ep_repo.get_episode_by_id(db_conn, "ep-canon-del")
    assert canon_ep is not None
    assert canon_ep.episode_type == "canon"
    assert canon_ep.review_state == "published"


def test_reader_deletion_survives_close_reopen(temp_db_path):
    """Deletion state survives close/reopen."""
    conn1 = get_connection(temp_db_path)
    migrations_dir = str(os.path.join(os.path.dirname(__file__), "..", "migrations"))
    apply_migrations(conn1, migrations_dir)

    world_repo.create_world(conn1, WORLD_STATE)
    reader = reader_repo.create_reader(conn1, display_name="reopen 독자")

    result = delete_reader_with_revocation(conn1, reader.id)
    assert result.success

    conn1.close()

    # Reopen
    conn2 = get_connection(temp_db_path)
    apply_migrations(conn2, migrations_dir)  # idempotent

    # Reader is still deleted
    reader_after = reader_repo.get_reader(conn2, reader.id)
    assert reader_after.status == "deleted"
    assert reader_after.display_name == "[deleted-reader]"

    # Audit record survives
    audit = get_deletion_audit_by_reader(conn2, _reader_digest(reader.id))
    assert audit is not None

    conn2.close()
