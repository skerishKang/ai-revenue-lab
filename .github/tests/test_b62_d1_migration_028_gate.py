"""#3396: additive D1 028 and production-release workflow source guards."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b62_d1_migration_028_schema.py"
WORKFLOW = ROOT / ".github/workflows/b62-b66-d1-migration-028-gate.yml"
MIGRATION = ROOT / "apps/padiem-chat/migrations/028_b66_guided_draft.sql"

spec = importlib.util.spec_from_file_location("b62_d1_028", HELPER)
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def snapshot(db):
    db.row_factory = sqlite3.Row
    parts = []
    for statement in guard.QUERY.split(";"):
        if not statement.strip():
            continue
        rows = [dict(row) for row in db.execute(statement).fetchall()]
        parts.append({"success": True, "results": rows})
    return {"success": True, "result": parts}


def database():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    return db


def test_source():
    sql = guard.source_sql()
    assert "CREATE TABLE IF NOT EXISTS b66_guided_draft" in sql
    assert guard.norm(sql) == guard.norm(guard.EXPECTED_SOURCE)
    db = database()
    db.executescript(sql)
    db.executescript(sql)  # additive, idempotent
    assert guard.classify(snapshot(db)) == "exact"
    db.close()


def test_missing_drift_and_parent():
    db = database()
    assert guard.classify(snapshot(db)) == "missing"
    db.executescript(guard.source_sql())
    assert guard.classify(snapshot(db)) == "exact"
    db.execute("CREATE INDEX injected_index ON b66_guided_draft(updated_at)")
    assert guard.classify(snapshot(db)) == "drift"
    db.close()
    db = sqlite3.connect(":memory:")
    assert guard.classify(snapshot(db)) == "drift"
    db.close()


def test_altered_constraint():
    db = database()
    db.execute("""CREATE TABLE b66_guided_draft (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE SET NULL,
        workspace_id TEXT NOT NULL, state_json TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(user_id, workspace_id))""")
    assert guard.classify(snapshot(db)) == "drift"
    db.close()


def test_fail_closed():
    for bad in ({}, {"success": False, "result": []},
                {"success": True, "result": []},
                {"success": True, "result": [{"success": False, "results": []}] * 4}):
        try:
            guard.classify(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed D1 schema evidence accepted")
    assert MIGRATION.exists()


def test_workflow():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "pull_request:", "workflow_dispatch:", "environment: production",
        "APPLY_B62_B66_D1_MIGRATION_028_FROM_EXACT_MAIN",
        "github.event_name == 'workflow_dispatch'",
        "github.event.pull_request.head.sha",
        'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"',
        "scripts/b62_d1_migration_028_schema.py classify",
        "scripts/b62_d1_migration_028_schema.py check-apply",
        "CUSTOMER_ROW_MUTATION=0",
        "PADIEM_CHAT_DB", "cancel-in-progress: false",
    ):
        assert required in workflow, required
    assert workflow.count("environment: production") == 1
    assert "pull_request_target:" not in workflow
    assert "secrets.CLOUDFLARE_API_TOKEN" in workflow
    assert "refs/heads/main" in workflow


if __name__ == "__main__":
    for test in (test_source, test_missing_drift_and_parent,
                 test_altered_constraint, test_fail_closed, test_workflow):
        test()
        print(test.__name__.upper() + "=PASS")
    print("B62_D1_MIGRATION_028_SOURCE_CONTRACT=PASS")
