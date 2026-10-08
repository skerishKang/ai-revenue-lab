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


def _index_sql(*, unique: bool = False, table: str = "b66_quote_history", partial: bool = False) -> str:
    keyword = "CREATE UNIQUE INDEX" if unique else "CREATE INDEX"
    clause = " WHERE user_id IS NOT NULL" if partial else ""
    return (
        f"{keyword} idx_b66_quote_history_owner_workspace_updated "
        f"ON {table} (user_id, workspace_id, updated_at DESC){clause}"
    )


def _index_list_row(*, unique: int = 0, partial: int = 0) -> dict:
    return {
        "name": "idx_b66_quote_history_owner_workspace_updated",
        "unique": unique,
        "origin": "c",
        "partial": partial,
    }


def _payload(*, state: str):
    if state == "missing":
        return {"success": True, "result": [_result([]) for _ in range(6)]}

    table_sql = _table_sql()
    index_sql = _index_sql()
    index_list = [_index_list_row()]

    if state == "drift":
        table_sql = table_sql.replace(
            "REFERENCES users(id) ON DELETE CASCADE",
            "REFERENCES users(id) ON DELETE SET NULL",
        )
    elif state == "foreign_table_index":
        # index name matches, but it is owned by another table (absent from index_list)
        index_sql = _index_sql(table="other_table")
        index_list = [_index_list_row()]
        index_list[0]["name"] = "idx_other_table_owner_workspace_updated"
    elif state == "unique_index":
        index_sql = _index_sql(unique=True)
        index_list = [_index_list_row(unique=1)]
    elif state == "partial_index":
        index_sql = _index_sql(partial=True)
        index_list = [_index_list_row(partial=1)]

    objects = [
        {"name": "b66_quote_history", "type": "table", "sql": table_sql},
        {
            "name": "idx_b66_quote_history_owner_workspace_updated",
            "type": "index",
            "sql": index_sql,
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
            _result(index_list),
            _result(index_columns),
            _result(index_detail),
            _result(foreign_keys),
        ],
    }


def _sqlite_payload(db) -> dict:
    """Build the gate's six query results from a real SQLite database."""

    def rows(sql: str) -> list[dict]:
        return [dict(row) for row in db.execute(sql).fetchall()]

    return {
        "success": True,
        "result": [
            _result(rows(
                "SELECT name, type, sql FROM sqlite_master WHERE name IN "
                "('b66_quote_history','idx_b66_quote_history_owner_workspace_updated') "
                "ORDER BY name"
            )),
            _result(rows("PRAGMA table_info(b66_quote_history)")),
            _result(rows("PRAGMA index_list(b66_quote_history)")),
            _result(rows("PRAGMA index_info(idx_b66_quote_history_owner_workspace_updated)")),
            _result(rows("PRAGMA index_xinfo(idx_b66_quote_history_owner_workspace_updated)")),
            _result(rows("PRAGMA foreign_key_list(b66_quote_history)")),
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
    wrong_order["result"][3]["results"][0]["name"] = "workspace_id"
    assert helper.classify_schema(wrong_order) == "drift"

    ascending_updated_at = _payload(state="exact")
    ascending_updated_at["result"][4]["results"][2]["desc"] = 0
    assert helper.classify_schema(ascending_updated_at) == "drift"

    bad_fk = _payload(state="exact")
    bad_fk["result"][5]["results"][0]["on_delete"] = "NO ACTION"
    assert helper.classify_schema(bad_fk) == "drift"


def test_classifier_rejects_foreign_unique_and_partial_index() -> None:
    helper = _load_helper()

    # FOREIGN_TABLE_INDEX: name matches but the index is owned by another table.
    foreign = _payload(state="foreign_table_index")
    assert helper.classify_schema(foreign) == "drift"
    # the same defect proved by the sqlite_master SQL alone (index_list still names it)
    foreign_sql_only = _payload(state="exact")
    foreign_sql_only["result"][0]["results"][1]["sql"] = _index_sql(table="other_table")
    assert helper.classify_schema(foreign_sql_only) == "drift"

    # UNIQUE_INDEX: proved by the index SQL and, independently, by index_list.unique.
    assert helper.classify_schema(_payload(state="unique_index")) == "drift"
    unique_flag_only = _payload(state="exact")
    unique_flag_only["result"][2]["results"][0]["unique"] = 1
    assert helper.classify_schema(unique_flag_only) == "drift"

    # PARTIAL_INDEX: proved by the index SQL and, independently, by index_list.partial.
    assert helper.classify_schema(_payload(state="partial_index")) == "drift"
    partial_flag_only = _payload(state="exact")
    partial_flag_only["result"][2]["results"][0]["partial"] = 1
    assert helper.classify_schema(partial_flag_only) == "drift"


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
    index_list = [dict(row) for row in db.execute("PRAGMA index_list(b66_quote_history)").fetchall()]
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
            _result(index_list),
            _result(index_columns),
            _result(index_detail),
            _result(foreign_keys),
        ],
    }
    assert helper.classify_schema(payload) == "exact"


def test_classifier_rejects_real_sqlite_foreign_unique_and_partial_index() -> None:
    """Independent reproduction of the three CENTRAL defects against real SQLite."""
    helper = _load_helper()
    migration = MIGRATION.read_text(encoding="utf-8")

    def fresh_db():
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE users (id TEXT PRIMARY KEY);
            """
        )
        db.executescript(migration)
        return db

    # control: the reviewed migration index classifies exact
    assert helper.classify_schema(_sqlite_payload(fresh_db())) == "exact"

    # FOREIGN_TABLE_INDEX: same name, wrong owning table -> DRIFT
    foreign = fresh_db()
    foreign.executescript(
        """
        DROP INDEX idx_b66_quote_history_owner_workspace_updated;
        CREATE TABLE other_table (user_id TEXT, workspace_id TEXT, updated_at TEXT);
        CREATE INDEX idx_b66_quote_history_owner_workspace_updated
        ON other_table (user_id, workspace_id, updated_at DESC);
        """
    )
    assert helper.classify_schema(_sqlite_payload(foreign)) == "drift"

    # UNIQUE_INDEX -> DRIFT
    unique = fresh_db()
    unique.executescript(
        """
        DROP INDEX idx_b66_quote_history_owner_workspace_updated;
        CREATE UNIQUE INDEX idx_b66_quote_history_owner_workspace_updated
        ON b66_quote_history (user_id, workspace_id, updated_at DESC);
        """
    )
    assert helper.classify_schema(_sqlite_payload(unique)) == "drift"

    # PARTIAL_INDEX -> DRIFT
    partial = fresh_db()
    partial.executescript(
        """
        DROP INDEX idx_b66_quote_history_owner_workspace_updated;
        CREATE INDEX idx_b66_quote_history_owner_workspace_updated
        ON b66_quote_history (user_id, workspace_id, updated_at DESC)
        WHERE user_id IS NOT NULL;
        """
    )
    assert helper.classify_schema(_sqlite_payload(partial)) == "drift"


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
    # 4. table, columns, primary key, foreign key, and index ownership + order + DESC.
    assert "table_info(b66_quote_history)" in workflow
    assert "index_list(b66_quote_history)" in workflow
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
    test_classifier_rejects_foreign_unique_and_partial_index()
    test_classifier_accepts_schema_created_by_migration()
    test_classifier_rejects_real_sqlite_foreign_unique_and_partial_index()
    test_migration_is_additive_and_preserves_existing_rows()
    test_migration_contract_is_additive_and_allows_foreign_keys_pragma()
    test_workflow_is_pr_safe_and_migration_specific()
    print("B62_D1_MIGRATION_025_GATE_TESTS=PASS")
