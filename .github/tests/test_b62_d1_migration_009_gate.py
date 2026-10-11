from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-claw-d1-migration-009-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_009_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/009_claw_run_history.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_009", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _payload(*, table=True, index=True, columns=None, index_columns=None, table_sql=None):
    migration = MIGRATION.read_text(encoding="utf-8")
    objects = []
    if table:
        objects.append(
            {
                "name": "claw_run_history",
                "type": "table",
                "sql": table_sql or migration.split("CREATE INDEX", 1)[0].strip(),
            }
        )
    if index:
        objects.append(
            {
                "name": "idx_claw_run_history_user_created",
                "type": "index",
                "sql": "CREATE INDEX idx_claw_run_history_user_created ON claw_run_history (user_id, created_at DESC)",
            }
        )
    expected_columns = (
        "id",
        "user_id",
        "run_id",
        "channel",
        "action",
        "title",
        "status",
        "created_at",
        "updated_at",
        "result_summary",
        "artifact_document_id",
        "artifact_filename",
        "artifact_media_type",
    )
    expected_index = ("user_id", "created_at")
    column_rows = [{"name": name} for name in (expected_columns if columns is None else columns)] if table else []
    index_rows = [{"name": name} for name in (expected_index if index_columns is None else index_columns)] if index else []
    return {
        "success": True,
        "result": [_result(objects), _result(column_rows), _result(index_rows)],
    }


def test_schema_classifier_contract() -> None:
    helper = _load_helper()
    assert helper.TABLE == "claw_run_history"
    assert helper.INDEX == "idx_claw_run_history_user_created"
    assert helper.classify_schema(_payload()) == "exact"
    assert helper.classify_schema(_payload(table=False, index=False)) == "missing"
    assert helper.classify_schema(_payload(index=False)) == "drift"
    assert helper.classify_schema(_payload(columns=("id", "user_id"))) == "drift"
    assert helper.classify_schema(_payload(index_columns=("user_id",))) == "drift"
    assert helper.classify_schema(
        _payload(table_sql="CREATE TABLE claw_run_history (id TEXT PRIMARY KEY)")
    ) == "drift"


def test_migration_is_additive_and_bounded() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS claw_run_history" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_claw_run_history_user_created" in migration
    upper = migration.upper()
    assert "DROP TABLE" not in upper
    assert "DROP INDEX" not in upper
    assert "DELETE FROM" not in upper
    assert "ALTER TABLE" not in upper


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_CLAW_D1_MIGRATION_009_FROM_EXACT_MAIN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "apps/padiem-chat/migrations/009_claw_run_history.sql" in workflow
    assert "B62_D1_MIGRATION_009_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 009 schema is structurally different" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_DATA_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow

    forbidden = (
        "wrangler d1 create",
        "d1 migrations apply",
        "pywrangler deploy",
        "wrangler deploy",
        "DROP TABLE",
        "DROP INDEX",
    )
    for token in forbidden:
        assert token not in workflow

    # The mutation path must be dispatch-only; PRs run source-contract only.
    assert "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_009'" in workflow


def test_gate_is_migration_009_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")
    for token in ("008", "010", "011"):
        assert token not in workflow
        assert token not in helper


if __name__ == "__main__":
    test_schema_classifier_contract()
    test_migration_is_additive_and_bounded()
    test_workflow_is_exact_main_and_migration_specific()
    test_gate_is_migration_009_only()
    print("B62_D1_MIGRATION_009_GATE_TESTS=PASS")
