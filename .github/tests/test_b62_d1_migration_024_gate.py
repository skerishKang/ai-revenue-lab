from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-auth-d1-migration-024-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_024_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/024_auth_login_abuse.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_024", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _payload(*, state: str):
    if state == "missing":
        return {
            "success": True,
            "result": [_result([]), _result([]), _result([])],
        }

    table_sql = """CREATE TABLE auth_login_abuse_buckets (
      subject_type TEXT NOT NULL CHECK (subject_type IN ('identifier', 'network', 'global')),
      subject_key TEXT NOT NULL,
      bucket_start TEXT NOT NULL,
      failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
      updated_at TEXT NOT NULL,
      PRIMARY KEY (subject_type, subject_key, bucket_start)
    )"""
    if state == "drift":
        table_sql = table_sql.replace("failure_count >= 0", "failure_count >= 10")

    objects = [
        {
            "name": "auth_login_abuse_buckets",
            "type": "table",
            "sql": table_sql,
        },
        {
            "name": "idx_auth_login_abuse_buckets_updated_at",
            "type": "index",
            "sql": (
                "CREATE INDEX idx_auth_login_abuse_buckets_updated_at "
                "ON auth_login_abuse_buckets(updated_at)"
            ),
        },
    ]
    columns = [
        {"name": name}
        for name in (
            "subject_type",
            "subject_key",
            "bucket_start",
            "failure_count",
            "updated_at",
        )
    ]
    index_columns = [{"name": "updated_at"}]
    return {
        "success": True,
        "result": [
            _result(objects),
            _result(columns),
            _result(index_columns),
        ],
    }


def test_schema_classifier_missing_exact_drift() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_payload(state="missing")) == "missing"
    assert helper.classify_schema(_payload(state="exact")) == "exact"
    assert helper.classify_schema(_payload(state="drift")) == "drift"


def test_classifier_accepts_schema_created_by_migration() -> None:
    helper = _load_helper()
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    objects = [
        dict(row)
        for row in db.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name IN "
            "('auth_login_abuse_buckets','idx_auth_login_abuse_buckets_updated_at') "
            "ORDER BY name"
        ).fetchall()
    ]
    columns = [
        dict(row)
        for row in db.execute(
            "PRAGMA table_info(auth_login_abuse_buckets)"
        ).fetchall()
    ]
    index_columns = [
        dict(row)
        for row in db.execute(
            "PRAGMA index_info(idx_auth_login_abuse_buckets_updated_at)"
        ).fetchall()
    ]
    payload = {
        "success": True,
        "result": [
            _result(objects),
            _result(columns),
            _result(index_columns),
        ],
    }
    assert helper.classify_schema(payload) == "exact"


def test_migration_is_additive_and_preserves_existing_rows() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE users (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL
        );
        CREATE TABLE conversations (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL
        );
        INSERT INTO users VALUES ('usr_1','u@example.test');
        INSERT INTO conversations VALUES ('chat_1','usr_1');
        """
    )
    before_users = db.execute("SELECT * FROM users").fetchall()
    before_conversations = db.execute("SELECT * FROM conversations").fetchall()

    db.executescript(MIGRATION.read_text(encoding="utf-8"))

    assert db.execute("SELECT * FROM users").fetchall() == before_users
    assert db.execute("SELECT * FROM conversations").fetchall() == before_conversations


def test_migration_contract_is_opaque_and_additive() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()
    assert "CREATE TABLE IF NOT EXISTS auth_login_abuse_buckets" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_auth_login_abuse_buckets_updated_at" in sql
    assert "PRIMARY KEY (subject_type, subject_key, bucket_start)" in sql
    schema_sql = "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    ).lower()
    for raw_field in (
        "username",
        "email",
        "ip_address",
        "raw_ip",
        "password",
        "session_id",
        "oauth",
    ):
        assert raw_field not in schema_sql
    for forbidden in (
        "DROP TABLE",
        "ALTER TABLE",
        "DELETE FROM",
        "UPDATE ",
        "INSERT INTO ",
    ):
        assert forbidden not in upper


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8-sig")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_AUTH_D1_MIGRATION_024_FROM_EXACT_MAIN" in workflow
    assert "apps/padiem-chat/migrations/024_auth_login_abuse.sql" in workflow
    assert "B62_D1_MIGRATION_024_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 024 schema is structurally different" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_DATA_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    assert "table_info(auth_login_abuse_buckets)" in workflow
    assert "index_info(idx_auth_login_abuse_buckets_updated_at)" in workflow
    assert (
        "github.event_name == 'workflow_dispatch' "
        "&& inputs.mode == 'apply_migration_024'"
    ) in workflow
    for forbidden in (
        "wrangler d1 create",
        "d1 migrations apply",
        "pywrangler deploy",
        "wrangler deploy",
    ):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_schema_classifier_missing_exact_drift()
    test_classifier_accepts_schema_created_by_migration()
    test_migration_is_additive_and_preserves_existing_rows()
    test_migration_contract_is_opaque_and_additive()
    test_workflow_is_exact_main_and_migration_specific()
    print("B62_D1_MIGRATION_024_GATE_TESTS=PASS")
