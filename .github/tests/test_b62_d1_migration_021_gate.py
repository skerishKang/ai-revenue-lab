from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-b66-d1-migration-021-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_021_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/021_b66_saved_quote_skill.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_021", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _payload(state: str):
    if state == "missing":
        return {"success": True, "result": [_result([]), _result([]), _result([])]}

    table_sql = """CREATE TABLE b66_saved_quote_skill (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      workspace_id TEXT NOT NULL,
      skill_id TEXT NOT NULL,
      skill_name TEXT NOT NULL,
      skill_fingerprint TEXT NOT NULL,
      skill_version INTEGER NOT NULL CHECK (skill_version >= 1),
      skill_json TEXT NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('approved', 'disabled')),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (user_id, workspace_id, skill_id, skill_version)
    )"""
    index_sql = """CREATE INDEX idx_b66_saved_quote_skill_owner_workspace_status
      ON b66_saved_quote_skill (user_id, workspace_id, status, updated_at DESC)"""
    if state == "drift":
        table_sql = table_sql.replace("skill_version >= 1", "skill_version >= 0")
    objects = [
        {"name": "b66_saved_quote_skill", "type": "table", "sql": table_sql},
        {
            "name": "idx_b66_saved_quote_skill_owner_workspace_status",
            "type": "index",
            "sql": index_sql,
        },
    ]
    columns = [{"name": name} for name in (
        "id", "user_id", "workspace_id", "skill_id", "skill_name",
        "skill_fingerprint", "skill_version", "skill_json", "status",
        "created_at", "updated_at",
    )]
    index_columns = [{"name": name} for name in (
        "user_id", "workspace_id", "status", "updated_at",
    )]
    return {
        "success": True,
        "result": [_result(objects), _result(columns), _result(index_columns)],
    }


def test_classifier_missing_exact_drift():
    helper = _load_helper()
    assert helper.classify_schema(_payload("missing")) == "missing"
    assert helper.classify_schema(_payload("exact")) == "exact"
    assert helper.classify_schema(_payload("drift")) == "drift"


def test_migration_is_additive_and_owner_scoped():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE users (
          id TEXT PRIMARY KEY,
          auth_provider TEXT NOT NULL,
          provider_subject TEXT NOT NULL,
          email TEXT NOT NULL,
          display_name TEXT NOT NULL DEFAULT '',
          picture_url TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO users VALUES
          ('usr_a','google','sub-a','a@example.test','A','','t','t'),
          ('usr_b','google','sub-b','b@example.test','B','','t','t');
        """
    )
    before = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    assert db.execute("SELECT * FROM users ORDER BY id").fetchall() == before
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    db.execute(
        """INSERT INTO b66_saved_quote_skill
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "b66skill_" + "a" * 32,
            "usr_a",
            "workspace-a",
            "skill-a",
            "견적서",
            "f" * 64,
            1,
            "{}",
            "approved",
            "t",
            "t",
        ),
    )
    assert db.execute(
        "SELECT user_id, workspace_id, status FROM b66_saved_quote_skill"
    ).fetchall() == [("usr_a", "workspace-a", "approved")]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_has_no_destructive_or_row_mutation_sql():
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()
    assert "CREATE TABLE IF NOT EXISTS b66_saved_quote_skill" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_b66_saved_quote_skill_owner_workspace_status" in sql
    for forbidden in (
        "DROP TABLE",
        "ALTER TABLE",
        "DELETE FROM",
        "UPDATE ",
        "INSERT INTO",
        "REPLACE INTO",
    ):
        assert forbidden not in upper


def test_workflow_is_exact_main_and_migration_specific():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    target = "$" + "{TARGET_SHA}"
    assert f'test "$(git rev-parse origin/main)" = "{target}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_B66_D1_MIGRATION_021_FROM_EXACT_MAIN" in workflow
    assert "apps/padiem-chat/migrations/021_b66_saved_quote_skill.sql" in workflow
    assert "b62_d1_migration_021_schema.py" in workflow
    assert "B62_D1_MIGRATION_021_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 021 schema is structurally different" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_DATA_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    assert "inputs.mode == 'apply_migration_021'" in workflow
    for forbidden in (
        "wrangler d1 create",
        "d1 migrations apply",
        "pywrangler deploy",
        "wrangler deploy",
    ):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_classifier_missing_exact_drift()
    test_migration_is_additive_and_owner_scoped()
    test_migration_has_no_destructive_or_row_mutation_sql()
    test_workflow_is_exact_main_and_migration_specific()
    print("B62_D1_MIGRATION_021_GATE_TESTS=PASS")
