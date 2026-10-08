from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-b66-d1-migration-025-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_025_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/025_b66_quote_history.sql"

COLUMNS = (
    "id", "user_id", "workspace_id", "quote_no", "issue_date", "saved_skill_id",
    "skill_fingerprint", "snapshot_json", "sender_json", "created_at", "updated_at",
)


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_025", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _table_sql() -> str:
    return """CREATE TABLE b66_quote_history (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      workspace_id TEXT NOT NULL,
      quote_no TEXT,
      issue_date TEXT,
      saved_skill_id TEXT,
      skill_fingerprint TEXT,
      snapshot_json TEXT NOT NULL,
      sender_json TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )"""


def _payload(*, state: str):
    if state == "missing":
        return {"success": True, "result": [_result([]) for _ in range(5)]}

    table_sql = _table_sql()
    if state == "drift":
        table_sql = table_sql.replace(
            "REFERENCES users(id) ON DELETE CASCADE",
            "REFERENCES users(id) ON DELETE SET NULL",
        )
    objects = [
        {"name": "b66_quote_history", "type": "table", "sql": table_sql},
        {
            "name": "idx_b66_quote_history_owner_workspace_updated",
            "type": "index",
            "sql": (
                "CREATE INDEX idx_b66_quote_history_owner_workspace_updated "
                "ON b66_quote_history (user_id, workspace_id, updated_at DESC)"
            ),
        },
    ]
    columns = [
        {"name": name, "pk": 1 if name == "id" else 0}
        for name in COLUMNS
    ]
    index_columns = [{"name": name} for name in ("user_id", "workspace_id", "updated_at")]
    index_detail = [
        {"name": "user_id", "desc": 0, "key": 1},
        {"name": "workspace_id", "desc": 0, "key": 1},
        {"name": "updated_at", "desc": 1, "key": 1},
        {"name": None, "desc": 0, "key": 0},
    ]
    foreign_keys = [{"table": "users", "from": "user_id", "to": "id", "on_delete": "CASCADE"}]
    return {
        "success": True,
        "result": [
            _result(objects),
            _result(columns),
            _result(index_columns),
            _result(index_detail),
            _result(foreign_keys),
        ],
    }


def test_schema_classifier_missing_exact_drift() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_payload(state="missing")) == "missing"
    assert helper.classify_schema(_payload(state="exact")) == "exact"
    assert helper.classify_schema(_payload(state="drift")) == "drift"


def test_classifier_rejects_primary_key_index_and_direction_drift() -> None:
    helper = _load_helper()

    composite_pk = _payload(state="exact")
    composite_pk["result"][1]["results"][1]["pk"] = 1
    assert helper.classify_schema(composite_pk) == "drift"

    wrong_order = _payload(state="exact")
    wrong_order["result"][2]["results"][0]["name"] = "workspace_id"
    assert helper.classify_schema(wrong_order) == "drift"

    ascending_updated_at = _payload(state="exact")
    ascending_updated_at["result"][3]["results"][2]["desc"] = 0
    assert helper.classify_schema(ascending_updated_at) == "drift"

    bad_fk = _payload(state="exact")
    bad_fk["result"][4]["results"][0]["on_delete"] = "NO ACTION"
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
            "WHERE name IN "
            "('b66_quote_history','idx_b66_quote_history_owner_workspace_updated') "
            "ORDER BY name"
        ).fetchall()
    ]
    columns = [dict(row) for row in db.execute("PRAGMA table_info(b66_quote_history)").fetchall()]
    index_columns = [
        dict(row)
        for row in db.execute(
            "PRAGMA index_info(idx_b66_quote_history_owner_workspace_updated)"
        ).fetchall()
    ]
    index_detail = [
        dict(row)
        for row in db.execute(
            "PRAGMA index_xinfo(idx_b66_quote_history_owner_workspace_updated)"
        ).fetchall()
    ]
    foreign_keys = [
        dict(row)
        for row in db.execute("PRAGMA foreign_key_list(b66_quote_history)").fetchall()
    ]
    payload = {
        "success": True,
        "result": [
            _result(objects),
            _result(columns),
            _result(index_columns),
            _result(index_detail),
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
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_contract_is_additive_and_allows_foreign_keys_pragma() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()
    assert "CREATE TABLE IF NOT EXISTS b66_quote_history" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_b66_quote_history_owner_workspace_updated" in sql
    assert "id TEXT PRIMARY KEY" in sql
    assert "REFERENCES users(id) ON DELETE CASCADE" in sql
    assert "PRAGMA FOREIGN_KEYS = ON" in upper
    for forbidden in (
        "DROP TABLE",
        "ALTER TABLE",
        "DELETE FROM",
        "UPDATE ",
        "INSERT INTO",
        "PRAGMA DEFER_FOREIGN_KEYS",
    ):
        assert forbidden not in upper


def test_workflow_is_pr_safe_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # 1. PR runs tests only; production jobs are dispatch-gated.
    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert (
        "github.event_name == 'workflow_dispatch' "
        "&& inputs.mode != 'repository_preflight'"
    ) in workflow
    assert (
        "github.event_name == 'workflow_dispatch' "
        "&& inputs.mode == 'apply_migration_025'"
    ) in workflow
    # 2. modes are separated.
    for mode in ("repository_preflight", "cloudflare_readonly", "apply_migration_025"):
        assert mode in workflow
    # 3. schema is checked against the live PADIEM_CHAT_DB binding.
    assert "PADIEM_CHAT_DB" in workflow
    assert "workers/scripts/${B62_WORKER}/settings" in workflow
    # 4. table, columns, primary key, foreign key and index order + DESC.
    assert "table_info(b66_quote_history)" in workflow
    assert "index_info(idx_b66_quote_history_owner_workspace_updated)" in workflow
    assert "index_xinfo(idx_b66_quote_history_owner_workspace_updated)" in workflow
    assert "foreign_key_list(b66_quote_history)" in workflow
    # 5. exact skips, drift refuses, missing applies only after approval.
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 025 schema is structurally different" in workflow
    assert "Apply additive migration 025 only when absent" in workflow
    assert "APPLY_B62_B66_D1_MIGRATION_025_FROM_EXACT_MAIN" in workflow
    # 6. additive-only guard, and the additive SQL path is the reviewed migration.
    assert "migration 025 additive contract missing" in workflow
    assert "migration 025 is not additive" in workflow
    assert "apps/padiem-chat/migrations/025_b66_quote_history.sql" in workflow
    # 7. exact-main + schema reconfirmed immediately before mutation, exact read-back after.
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "B62_D1_MIGRATION_025_PREMUTATION_SCHEMA=PASS" in workflow
    assert "B62_D1_MIGRATION_025_POST_READBACK=PASS" in workflow
    assert "B62_D1_MIGRATION_025_FOREIGN_KEY_CHECK=PASS" in workflow
    # 8. owner approval is required to mutate production.
    assert "environment: production" in workflow
    assert "B62_D1_MIGRATION_025_AUTHORIZATION=PASS" in workflow
    # evidence discipline
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_DATA_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    for forbidden in (
        "wrangler d1 create",
        "d1 migrations apply",
        "pywrangler deploy",
        "wrangler deploy",
    ):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_schema_classifier_missing_exact_drift()
    test_classifier_rejects_primary_key_index_and_direction_drift()
    test_classifier_accepts_schema_created_by_migration()
    test_migration_is_additive_and_preserves_existing_rows()
    test_migration_contract_is_additive_and_allows_foreign_keys_pragma()
    test_workflow_is_pr_safe_and_migration_specific()
    print("B62_D1_MIGRATION_025_GATE_TESTS=PASS")
