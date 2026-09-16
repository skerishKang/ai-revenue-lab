from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-auth-d1-migration-012-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_012_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/012_password_auth.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_012", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _payload(*, state: str):
    users_sql = """CREATE TABLE users (
      id TEXT PRIMARY KEY,
      auth_provider TEXT NOT NULL CHECK (auth_provider = 'google'),
      provider_subject TEXT NOT NULL,
      email TEXT NOT NULL,
      display_name TEXT NOT NULL DEFAULT '',
      picture_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (auth_provider, provider_subject)
    )"""
    users_columns = [{"name": name} for name in (
        "id", "auth_provider", "provider_subject", "email",
        "display_name", "picture_url", "created_at", "updated_at",
    )]
    objects = [{"name": "users", "type": "table", "sql": users_sql}]
    if state == "missing":
        return {
            "success": True,
            "result": [_result(objects), _result(users_columns), _result([]), _result([])],
        }
    if state == "exact":
        credential_sql = """CREATE TABLE password_credentials (
          user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          username TEXT NOT NULL COLLATE NOCASE UNIQUE,
          password_hash TEXT NOT NULL,
          failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts BETWEEN 0 AND 100),
          locked_until TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
        objects.extend([
            {"name": "password_credentials", "type": "table", "sql": credential_sql},
            {
                "name": "idx_password_credentials_username",
                "type": "index",
                "sql": "CREATE INDEX idx_password_credentials_username ON password_credentials(username COLLATE NOCASE)",
            },
        ])
        password_columns = [{"name": name} for name in (
            "user_id", "username", "password_hash", "failed_attempts",
            "locked_until", "created_at", "updated_at",
        )]
        return {
            "success": True,
            "result": [
                _result(objects),
                _result(users_columns),
                _result(password_columns),
                _result([{"name": "username"}]),
            ],
        }
    objects[0]["sql"] = users_sql.replace(
        "CHECK (auth_provider = 'google')",
        "CHECK (auth_provider IN ('google','password'))",
    )
    return {
        "success": True,
        "result": [_result(objects), _result(users_columns), _result([]), _result([])],
    }


def test_schema_classifier_missing_exact_drift() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_payload(state="missing")) == "missing"
    assert helper.classify_schema(_payload(state="exact")) == "exact"
    assert helper.classify_schema(_payload(state="drift")) == "drift"


def test_migration_is_additive_and_preserves_existing_google_ownership() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE users (
          id TEXT PRIMARY KEY,
          auth_provider TEXT NOT NULL CHECK (auth_provider = 'google'),
          provider_subject TEXT NOT NULL,
          email TEXT NOT NULL,
          display_name TEXT NOT NULL DEFAULT '',
          picture_url TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE (auth_provider, provider_subject)
        );
        CREATE TABLE conversations (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO users VALUES ('usr_google','google','sub-google','g@example.test','Google','','t','t');
        INSERT INTO conversations VALUES ('chat_1','usr_google','hello','t','t');
        """
    )
    before_users = db.execute("SELECT * FROM users").fetchall()
    before_conversations = db.execute("SELECT * FROM conversations").fetchall()

    db.executescript(MIGRATION.read_text(encoding="utf-8"))

    assert db.execute("SELECT * FROM users").fetchall() == before_users
    assert db.execute("SELECT * FROM conversations").fetchall() == before_conversations
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    db.execute(
        "INSERT INTO users VALUES ('usr_password','google','password:owner.test','p@example.test','Password','','t','t')"
    )
    db.execute(
        "INSERT INTO password_credentials VALUES ('usr_password','owner.test','hash',0,NULL,'t','t')"
    )
    db.execute(
        "INSERT INTO conversations VALUES ('chat_2','usr_password','hello','t','t')"
    )
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_contains_no_existing_table_mutation() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()
    assert "CREATE TABLE IF NOT EXISTS password_credentials" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_password_credentials_username" in sql
    for forbidden in (
        "DROP TABLE",
        "ALTER TABLE",
        "DELETE FROM",
        "UPDATE users",
        "INSERT INTO users",
        "PRAGMA foreign_keys",
        "PRAGMA defer_foreign_keys",
    ):
        assert forbidden not in upper if forbidden == forbidden.upper() else forbidden not in sql


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_AUTH_D1_MIGRATION_012_FROM_EXACT_MAIN" in workflow
    assert "apps/padiem-chat/migrations/012_password_auth.sql" in workflow
    assert "B62_D1_MIGRATION_012_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 012 schema is structurally different" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_DATA_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_012'" in workflow
    for forbidden in (
        "wrangler d1 create",
        "d1 migrations apply",
        "pywrangler deploy",
        "wrangler deploy",
    ):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_schema_classifier_missing_exact_drift()
    test_migration_is_additive_and_preserves_existing_google_ownership()
    test_migration_contains_no_existing_table_mutation()
    test_workflow_is_exact_main_and_migration_specific()
    print("B62_D1_MIGRATION_012_GATE_TESTS=PASS")
