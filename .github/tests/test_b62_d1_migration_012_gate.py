from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
    legacy_users = """CREATE TABLE users (
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
    exact_users = legacy_users.replace(
        "CHECK (auth_provider = 'google')",
        "CHECK (auth_provider IN ('google', 'password'))",
    )
    users_columns = [{"name": name} for name in (
        "id", "auth_provider", "provider_subject", "email",
        "display_name", "picture_url", "created_at", "updated_at",
    )]
    if state == "legacy":
        objects = [{"name": "users", "type": "table", "sql": legacy_users}]
        return {
            "success": True,
            "result": [
                _result(objects), _result(users_columns), _result([]), _result([])
            ],
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
        objects = [
            {"name": "users", "type": "table", "sql": exact_users},
            {
                "name": "password_credentials",
                "type": "table",
                "sql": credential_sql,
            },
            {
                "name": "idx_password_credentials_username",
                "type": "index",
                "sql": "CREATE INDEX idx_password_credentials_username ON password_credentials(username COLLATE NOCASE)",
            },
        ]
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
    objects = [{"name": "users", "type": "table", "sql": exact_users}]
    return {
        "success": True,
        "result": [_result(objects), _result(users_columns), _result([]), _result([])],
    }


def test_schema_classifier_legacy_exact_drift() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_payload(state="legacy")) == "legacy"
    assert helper.classify_schema(_payload(state="exact")) == "exact"
    assert helper.classify_schema(_payload(state="drift")) == "drift"


def test_migration_preserves_google_users_and_existing_foreign_keys() -> None:
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
    db.executescript(MIGRATION.read_text(encoding="utf-8"))

    assert db.execute("SELECT id, auth_provider, email FROM users").fetchall() == [
        ("usr_google", "google", "g@example.test")
    ]
    assert db.execute("SELECT id, user_id FROM conversations").fetchall() == [
        ("chat_1", "usr_google")
    ]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    db.execute(
        "INSERT INTO users VALUES ('usr_password','password','owner.test','p@example.test','Password','','t','t')"
    )
    db.execute(
        "INSERT INTO password_credentials VALUES ('usr_password','owner.test','hash',0,NULL,'t','t')"
    )
    db.execute(
        "INSERT INTO conversations VALUES ('chat_2','usr_password','hello','t','t')"
    )
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_is_bounded_to_users_rebuild_and_password_credentials() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "PRAGMA foreign_keys = OFF" in sql
    assert "CREATE TABLE users_012" in sql
    assert "INSERT INTO users_012" in sql
    assert "DROP TABLE users" in sql
    assert "ALTER TABLE users_012 RENAME TO users" in sql
    assert "CREATE TABLE password_credentials" in sql
    assert "PRAGMA foreign_key_check" in sql
    assert "DELETE FROM" not in sql.upper()
    for unrelated in (
        "conversations",
        "projects",
        "claw_run_history",
        "claw_approved_memory",
    ):
        assert f"DROP TABLE {unrelated}" not in sql


if __name__ == "__main__":
    test_schema_classifier_legacy_exact_drift()
    test_migration_preserves_google_users_and_existing_foreign_keys()
    test_migration_is_bounded_to_users_rebuild_and_password_credentials()
    print("B62_D1_MIGRATION_012_GATE_TESTS=PASS")
