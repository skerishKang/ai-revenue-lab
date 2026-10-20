"""#5080: one additive Android handoff table and one reviewed release gate (058)."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "migration_058", ROOT / ".github/scripts/b62_d1_migration_058_schema.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _query(*extras: str):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    for sql in extras:
        db.executescript(sql)

    blocks = []
    for statement in module.QUERY.strip().split(";"):
        if statement.strip():
            blocks.append({
                "success": True,
                "results": [dict(row) for row in db.execute(statement)],
            })
    db.close()
    return {"success": True, "result": blocks}


def test_additive_table_is_exact_and_absent_is_missing():
    source = module.source()
    assert module.classify(_query(source)) == "exact"
    # No table at all is the applicable pre-058 state: the deployed worker
    # answers POST /auth/android/handoff with 503 android_handoff_unavailable.
    assert module.classify(_query()) == "missing"


def test_reshaped_or_partial_table_is_drift():
    # Missing columns / wrong PK / wrong FK / missing index all stay drift; the
    # gate never mutates an existing different table.
    for sql in (
        "CREATE TABLE padiem_android_auth_handoffs (handoff_id TEXT);",
        "CREATE TABLE padiem_android_auth_handoffs ("
        "handoff_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, "
        "code_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'awaiting_login', "
        "pending_user_id TEXT REFERENCES users(id) ON DELETE CASCADE, "
        "attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, pending_at TEXT, confirmed_at TEXT, "
        "claimed_at TEXT, expires_at TEXT NOT NULL);",
        # A different status vocabulary is a different table.
        "CREATE TABLE padiem_android_auth_handoffs ("
        "handoff_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, "
        "code_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
        "pending_user_id TEXT REFERENCES users(id) ON DELETE CASCADE, "
        "attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, pending_at TEXT, confirmed_at TEXT, "
        "claimed_at TEXT, expires_at TEXT NOT NULL);",
    ):
        assert module.classify(_query(sql)) == "drift", sql


def test_missing_index_is_drift():
    reviewed = module.source()
    without_index = reviewed.split("CREATE INDEX")[0]
    assert module.classify(_query(without_index)) == "drift"


@pytest.mark.parametrize(
    ("original", "replacement"),
    (
        ("DEFAULT 'awaiting_login'", "DEFAULT 'pending'"),
        ("attempts INTEGER NOT NULL DEFAULT 0", "attempts INTEGER NOT NULL DEFAULT 1"),
        ("pending_user_id TEXT REFERENCES users(id) ON DELETE CASCADE",
         "pending_user_id TEXT REFERENCES users(id)"),
        ("expires_at TEXT NOT NULL", "expires_at TEXT"),
        ("CHECK (attempts >= 0)", "CHECK (attempts >= 1)"),
    ),
)
def test_default_or_check_drift_is_not_exact(original, replacement):
    # These changes preserve columns/PK/FK, so metadata-only checks miss them.
    reviewed = module.source()
    assert original in reviewed
    assert module.classify(_query(reviewed.replace(original, replacement))) == "drift"


def test_source_is_additive_only():
    source = module.source()
    upper = module.norm(source)
    assert upper.count("create table if not exists padiem_android_auth_handoffs") == 1
    assert upper.count(
        "create index if not exists idx_padiem_android_auth_handoffs_expires_at"
    ) == 1
    for forbidden in (
        "drop table", "drop index", "delete from", "alter table",
        "create trigger", "insert into", "update ",
    ):
        assert forbidden not in upper
    assert "references users(id) on delete cascade" in upper
    assert "primary key" in upper


def test_malformed_schema_responses_fail_closed():
    for payload in (
        None, {}, {"success": False}, {"success": True, "result": []},
        {"success": True, "result": [{"success": True, "results": "x"}] * 4},
    ):
        with pytest.raises((ValueError, TypeError)):
            module.classify(payload)


def test_canonical_migration_gate_is_dispatch_only_and_confirmed():
    workflow = (
        ROOT / ".github/workflows/b62-claw-d1-migration-058-gate.yml"
    ).read_text(encoding="utf-8")
    assert "b62_d1_migration_058_schema.py" in workflow
    assert "058_android_auth_handoff.sql" in workflow
    assert "APPLY_B62_CLAW_D1_MIGRATION_058_FROM_EXACT_MAIN" in workflow
    assert "workflow_dispatch" in workflow
    assert "environment: production" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply_migration_058" in workflow
    # Applying is a separate dispatched mode, never a push/PR path.
    assert "push:" not in workflow.split("permissions:", 1)[0]
    assert "mode == 'apply_migration_058'" in workflow
    # The gate must not deploy a Worker, create a database or read row data.
    assert "wrangler deploy" not in workflow
    assert "d1 create" not in workflow
    assert "ROW_DATA_READ=0" in workflow


def test_gate_never_emits_the_database_identifier():
    workflow = (
        ROOT / ".github/workflows/b62-claw-d1-migration-058-gate.yml"
    ).read_text(encoding="utf-8")
    assert "::add-mask::" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    # The live database id is resolved from the worker binding, never guessed.
    assert "workers/scripts/${B62_WORKER}/settings" in workflow


def test_recovery_bookmark_is_read_with_get_and_never_created():
    # POST on the Time Travel bookmark endpoint CREATES a recovery bookmark.
    # The gate only proves that recovery exists, so it must GET it, exactly as
    # the existing 040 and 054 migration gates do.
    workflow = (
        ROOT / ".github/workflows/b62-claw-d1-migration-058-gate.yml"
    ).read_text(encoding="utf-8")
    assert "time_travel/bookmark" in workflow
    lines = workflow.splitlines()
    bookmark_calls = []
    for index, line in enumerate(lines):
        if "time_travel/bookmark" not in line:
            continue
        # The curl invocation carries the URL on its own continuation line.
        invocation = "\n".join(lines[max(0, index - 3):index])
        assert "curl" in invocation, invocation
        bookmark_calls.append(invocation)
    assert bookmark_calls, "the recovery bookmark readback must exist"
    for invocation in bookmark_calls:
        assert "-X POST" not in invocation, invocation
        assert "-X DELETE" not in invocation, invocation
        assert "-X PUT" not in invocation, invocation
