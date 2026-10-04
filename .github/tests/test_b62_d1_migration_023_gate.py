from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-b66-d1-migration-023-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_023_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/023_b66_company_profile.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_023", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _payload(*, state: str):
    if state == "missing":
        return {"success": True, "result": [_result([]), _result([]), _result([]), _result([])]}
    table_sql = """CREATE TABLE b66_company_profile (
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      workspace_id TEXT NOT NULL,
      company TEXT,
      representative TEXT,
      contact_person TEXT,
      business_number TEXT,
      address TEXT,
      phone TEXT,
      email TEXT,
      default_validity_days INTEGER CHECK (default_validity_days IS NULL OR (default_validity_days >= 0 AND default_validity_days <= 3650)),
      default_tax_mode TEXT CHECK (default_tax_mode IS NULL OR default_tax_mode IN ('EXCLUSIVE', 'INCLUSIVE', 'EXEMPT')),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (user_id, workspace_id)
    )"""
    if state == "drift":
        table_sql = table_sql.replace("default_validity_days <= 3650", "default_validity_days <= 30")
    objects = [
        {"name": "b66_company_profile", "type": "table", "sql": table_sql},
        {
            "name": "idx_b66_company_profile_workspace_updated",
            "type": "index",
            "sql": "CREATE INDEX idx_b66_company_profile_workspace_updated ON b66_company_profile (workspace_id, updated_at DESC)",
        },
    ]
    columns = [{"name": name} for name in (
        "user_id", "workspace_id", "company", "representative", "contact_person",
        "business_number", "address", "phone", "email", "default_validity_days",
        "default_tax_mode", "created_at", "updated_at",
    )]
    index_columns = [{"name": name} for name in ("workspace_id", "updated_at")]
    foreign_keys = [{"table": "users", "from": "user_id", "to": "id", "on_delete": "CASCADE"}]
    return {
        "success": True,
        "result": [_result(objects), _result(columns), _result(index_columns), _result(foreign_keys)],
    }


def test_schema_classifier_missing_exact_drift() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_payload(state="missing")) == "missing"
    assert helper.classify_schema(_payload(state="exact")) == "exact"
    assert helper.classify_schema(_payload(state="drift")) == "drift"


def test_classifier_rejects_wrong_index_or_foreign_key() -> None:
    helper = _load_helper()
    bad_index = _payload(state="exact")
    bad_index["result"][2]["results"][0]["name"] = "user_id"
    assert helper.classify_schema(bad_index) == "drift"
    bad_fk = _payload(state="exact")
    bad_fk["result"][3]["results"][0]["on_delete"] = "NO ACTION"
    assert helper.classify_schema(bad_fk) == "drift"


def test_classifier_accepts_schema_created_by_migration() -> None:
    helper = _load_helper()
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE users (id TEXT PRIMARY KEY);
        """
    )
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    objects = [
        dict(row)
        for row in db.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name IN ('b66_company_profile','idx_b66_company_profile_workspace_updated') "
            "ORDER BY name"
        ).fetchall()
    ]
    columns = [dict(row) for row in db.execute("PRAGMA table_info(b66_company_profile)").fetchall()]
    index_columns = [
        dict(row)
        for row in db.execute(
            "PRAGMA index_info(idx_b66_company_profile_workspace_updated)"
        ).fetchall()
    ]
    foreign_keys = [
        dict(row)
        for row in db.execute("PRAGMA foreign_key_list(b66_company_profile)").fetchall()
    ]
    payload = {
        "success": True,
        "result": [
            _result(objects),
            _result(columns),
            _result(index_columns),
            _result(foreign_keys),
        ],
    }
    assert helper.classify_schema(payload) == "exact"


def test_migration_is_additive_and_preserves_existing_rows() -> None:
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
        CREATE TABLE conversations (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO users VALUES ('usr_1','google','sub','u@example.test','U','','t','t');
        INSERT INTO conversations VALUES ('chat_1','usr_1','hello','t','t');
        """
    )
    before_users = db.execute("SELECT * FROM users").fetchall()
    before_conversations = db.execute("SELECT * FROM conversations").fetchall()
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    assert db.execute("SELECT * FROM users").fetchall() == before_users
    assert db.execute("SELECT * FROM conversations").fetchall() == before_conversations
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_contract_allows_partial_profile_without_invented_defaults() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()
    assert "CREATE TABLE IF NOT EXISTS b66_company_profile" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_b66_company_profile_workspace_updated" in sql
    assert "PRIMARY KEY (user_id, workspace_id)" in sql
    assert "default_validity_days INTEGER" in sql
    assert "default_tax_mode TEXT" in sql
    assert "DEFAULT 7" not in upper
    assert "DEFAULT 30" not in upper
    for forbidden in ("DROP TABLE", "ALTER TABLE", "DELETE FROM", "UPDATE ", "INSERT INTO "):
        assert forbidden not in upper


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_B66_D1_MIGRATION_023_FROM_EXACT_MAIN" in workflow
    assert "apps/padiem-chat/migrations/023_b66_company_profile.sql" in workflow
    assert "B62_D1_MIGRATION_023_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 023 schema is structurally different" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_DATA_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    assert "foreign_key_list(b66_company_profile)" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_023'" in workflow
    for forbidden in ("wrangler d1 create", "d1 migrations apply", "wrangler deploy"):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_schema_classifier_missing_exact_drift()
    test_classifier_rejects_wrong_index_or_foreign_key()
    test_classifier_accepts_schema_created_by_migration()
    test_migration_is_additive_and_preserves_existing_rows()
    test_migration_contract_allows_partial_profile_without_invented_defaults()
    test_workflow_is_exact_main_and_migration_specific()
    print("B62_D1_MIGRATION_023_GATE_TESTS=PASS")
