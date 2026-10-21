from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-d1-migration-062-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_062_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/062_password_reset.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_062", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _objects() -> list[dict[str, object]]:
    return [
        {
            "name": "password_reset_tokens",
            "type": "table",
            "sql": (
                "CREATE TABLE password_reset_tokens ("
                "token_id TEXT PRIMARY KEY, "
                "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "token_digest TEXT NOT NULL UNIQUE, "
                "issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, "
                "consumed_at TEXT, revoked_at TEXT, "
                "attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"
            ),
        },
        {
            "name": "password_reset_audit",
            "type": "table",
            "sql": (
                "CREATE TABLE password_reset_audit ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event TEXT NOT NULL CHECK (event IN ('requested','issued',"
                "'delivered','delivery_failed','consumed','rejected','expired')), "
                "user_id TEXT, identifier_digest TEXT NOT NULL, "
                "reason_code TEXT, occurred_at TEXT NOT NULL)"
            ),
        },
        {
            "name": "idx_password_reset_tokens_user",
            "type": "index",
            "sql": "CREATE INDEX idx_password_reset_tokens_user ON password_reset_tokens(user_id, created_at DESC)",
        },
        {
            "name": "idx_password_reset_tokens_expiry",
            "type": "index",
            "sql": "CREATE INDEX idx_password_reset_tokens_expiry ON password_reset_tokens(expires_at)",
        },
        {
            "name": "idx_password_reset_audit_identifier",
            "type": "index",
            "sql": "CREATE INDEX idx_password_reset_audit_identifier ON password_reset_audit(identifier_digest, occurred_at DESC)",
        },
        {
            "name": "idx_password_reset_audit_occurred",
            "type": "index",
            "sql": "CREATE INDEX idx_password_reset_audit_occurred ON password_reset_audit(occurred_at)",
        },
        {
            "name": "idx_password_reset_audit_user",
            "type": "index",
            "sql": "CREATE INDEX idx_password_reset_audit_user ON password_reset_audit(user_id, occurred_at DESC)",
        },
    ]


def _token_columns() -> list[dict[str, object]]:
    return [
        {"name": name, "type": type_name, "notnull": notnull, "pk": pk}
        for name, type_name, notnull, pk in (
            ("token_id", "TEXT", 0, 1),
            ("user_id", "TEXT", 1, 0),
            ("token_digest", "TEXT", 1, 0),
            ("issued_at", "TEXT", 1, 0),
            ("expires_at", "TEXT", 1, 0),
            ("consumed_at", "TEXT", 0, 0),
            ("revoked_at", "TEXT", 0, 0),
            ("attempts", "INTEGER", 1, 0),
            ("created_at", "TEXT", 1, 0),
        )
    ]


def _audit_columns() -> list[dict[str, object]]:
    return [
        {"name": name, "type": type_name, "notnull": notnull, "pk": pk}
        for name, type_name, notnull, pk in (
            ("id", "INTEGER", 0, 1),
            ("event", "TEXT", 1, 0),
            ("user_id", "TEXT", 0, 0),
            ("identifier_digest", "TEXT", 1, 0),
            ("reason_code", "TEXT", 0, 0),
            ("occurred_at", "TEXT", 1, 0),
        )
    ]


def _foreign_keys() -> list[dict[str, object]]:
    return [
        {
            "id": 0,
            "seq": 0,
            "table": "users",
            "from": "user_id",
            "to": "id",
            "on_update": "NO ACTION",
            "on_delete": "CASCADE",
            "match": "NONE",
        }
    ]


def _payload(*, state: str):
    if state == "missing":
        return {
            "success": True,
            "result": [_result([]), _result([]), _result([]), _result([])],
        }
    objects = _objects()
    token_columns = _token_columns()
    audit_columns = _audit_columns()
    foreign_keys = _foreign_keys()
    if state == "exact":
        return {
            "success": True,
            "result": [
                _result(objects),
                _result(token_columns),
                _result(audit_columns),
                _result(foreign_keys),
            ],
        }
    if state == "partial":
        # One table applied and the other missing: the gate does not own it.
        return {
            "success": True,
            "result": [
                _result([objects[0]]),
                _result(token_columns),
                _result([]),
                _result([]),
            ],
        }
    # drift: the token table exists but its columns are not the reviewed ones.
    return {
        "success": True,
        "result": [
            _result(objects),
            _result(token_columns[:2]),
            _result(audit_columns),
            _result(foreign_keys),
        ],
    }


def test_schema_classifier_missing_exact_drift() -> None:
    helper = _load_helper()
    assert helper.classify(_payload(state="missing")) == "missing"
    assert helper.classify(_payload(state="exact")) == "exact"
    assert helper.classify(_payload(state="drift")) == "drift"
    assert helper.classify(_payload(state="partial")) == "drift"


def test_source_contract_proves_the_migration_is_additive() -> None:
    helper = _load_helper()
    text = helper.source()
    assert "CREATE TABLE IF NOT EXISTS password_reset_tokens" in text
    assert "CREATE TABLE IF NOT EXISTS password_reset_audit" in text
    for forbidden in (
        "DROP TABLE",
        "ALTER TABLE",
        "DELETE FROM",
        "UPDATE USERS",
        "UPDATE PASSWORD_CREDENTIALS",
        "INSERT INTO USERS",
        "PRAGMA FOREIGN_KEYS",
    ):
        assert forbidden not in text.upper()


def test_migration_is_additive_and_preserves_the_account_rows() -> None:
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
        CREATE TABLE password_credentials (
          user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          username TEXT NOT NULL COLLATE NOCASE UNIQUE,
          password_hash TEXT NOT NULL,
          failed_attempts INTEGER NOT NULL DEFAULT 0,
          locked_until TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO users VALUES ('usr_1','google','sub-1','a@example.test','A','','t','t');
        INSERT INTO password_credentials VALUES ('usr_1','a@example.test','hash',0,NULL,'t','t');
        """
    )
    before_users = db.execute("SELECT * FROM users").fetchall()
    before_credentials = db.execute("SELECT * FROM password_credentials").fetchall()

    db.executescript(MIGRATION.read_text(encoding="utf-8"))

    assert db.execute("SELECT * FROM users").fetchall() == before_users
    assert db.execute("SELECT * FROM password_credentials").fetchall() == before_credentials
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    # The reset token row references the account and the audit ledger accepts
    # both a known and an unknown identifier digest.
    db.execute(
        "INSERT INTO password_reset_tokens VALUES ('prst_1','usr_1','digest','t','t',NULL,NULL,0,'t')"
    )
    db.execute(
        "INSERT INTO password_reset_audit(event, user_id, identifier_digest, reason_code, occurred_at) "
        "VALUES ('issued','usr_1','digest',NULL,'t')"
    )
    db.execute(
        "INSERT INTO password_reset_audit(event, user_id, identifier_digest, reason_code, occurred_at) "
        "VALUES ('requested',NULL,'digest',NULL,'t')"
    )
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_contains_no_existing_table_mutation() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()
    assert "CREATE TABLE IF NOT EXISTS password_reset_tokens" in sql
    assert "CREATE TABLE IF NOT EXISTS password_reset_audit" in sql
    for forbidden in (
        "DROP TABLE",
        "ALTER TABLE",
        "DELETE FROM",
        "UPDATE USERS",
        "UPDATE PASSWORD_CREDENTIALS",
        "INSERT INTO USERS",
        "PRAGMA FOREIGN_KEYS",
        "PRAGMA DEFERRED_FOREIGN_KEYS",
    ):
        assert forbidden not in upper


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_D1_MIGRATION_062_FROM_EXACT_MAIN" in workflow
    assert "apps/padiem-chat/migrations/062_password_reset.sql" in workflow
    assert "B62_D1_MIGRATION_062_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 062 schema is structurally different" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_CONTENT_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    assert "B62_D1_MIGRATION_062_ACCOUNT_ROWS_PRESERVED=PASS" in workflow
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_062'"
        in workflow
    )
    for forbidden in (
        "wrangler d1 create",
        "d1 migrations apply",
        "pywrangler deploy",
        "wrangler deploy",
    ):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_schema_classifier_missing_exact_drift()
    test_source_contract_proves_the_migration_is_additive()
    test_migration_is_additive_and_preserves_the_account_rows()
    test_migration_contains_no_existing_table_mutation()
    test_workflow_is_exact_main_and_migration_specific()
    print("B62_D1_MIGRATION_062_GATE_TESTS=PASS")
