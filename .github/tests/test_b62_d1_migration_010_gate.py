from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-claw-d1-migration-010-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_010_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/010_claw_task_alert.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_010", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _payload(
    *,
    table=True,
    index_created=True,
    index_kind_status=True,
    index_member_updated=True,
    columns=None,
    table_sql=None,
    index_created_sql=None,
    index_kind_status_sql=None,
    index_member_updated_sql=None,
):
    migration = MIGRATION.read_text(encoding="utf-8")
    objects = []
    if table:
        objects.append(
            {
                "name": "claw_task_alert",
                "type": "table",
                "sql": table_sql or migration.split("CREATE INDEX", 1)[0].strip(),
            }
        )
    if index_created:
        objects.append(
            {
                "name": "idx_claw_task_alert_workspace_created",
                "type": "index",
                "sql": index_created_sql
                or "CREATE INDEX idx_claw_task_alert_workspace_created ON claw_task_alert (workspace_id, created_at DESC)",
            }
        )
    if index_kind_status:
        objects.append(
            {
                "name": "idx_claw_task_alert_workspace_kind_status",
                "type": "index",
                "sql": index_kind_status_sql
                or "CREATE INDEX idx_claw_task_alert_workspace_kind_status ON claw_task_alert (workspace_id, kind, status)",
            }
        )
    if index_member_updated:
        objects.append(
            {
                "name": "idx_claw_task_alert_member_updated",
                "type": "index",
                "sql": index_member_updated_sql
                or "CREATE INDEX idx_claw_task_alert_member_updated ON claw_task_alert (member_id, updated_at DESC) WHERE member_id != '' AND kind = 'alert'",
            }
        )
    expected_columns = (
        "id",
        "workspace_id",
        "kind",
        "status",
        "title",
        "created_at",
        "updated_at",
        "member_id",
        "due_date",
        "source_id",
        "linked_ref",
        "severity",
        "kind_value",
        "visible_to_all",
    )
    column_rows = [{"name": name} for name in (expected_columns if columns is None else columns)] if table else []
    return {
        "success": True,
        "result": [_result(objects), _result(column_rows), _result([])],
    }


def test_schema_classifier_contract() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_payload()) == "exact"
    assert helper.classify_schema(_payload(table=False, index_created=False, index_kind_status=False, index_member_updated=False)) == "missing"
    assert helper.classify_schema(_payload(index_created=False)) == "drift"
    assert helper.classify_schema(_payload(index_kind_status=False)) == "drift"
    assert helper.classify_schema(_payload(index_member_updated=False)) == "drift"
    assert helper.classify_schema(_payload(columns=("id", "workspace_id"))) == "drift"
    assert helper.classify_schema(
        _payload(table_sql="CREATE TABLE claw_task_alert (id TEXT PRIMARY KEY)")
    ) == "drift"
    assert helper.classify_schema(_payload(table=False, index_created=True)) == "drift"
    assert helper.classify_schema(_payload(table=False, index_kind_status=True)) == "drift"
    assert helper.classify_schema(_payload(table=False, index_member_updated=True)) == "drift"


def test_index_sql_structure_variation_is_drift() -> None:
    helper = _load_helper()
    # workspace_created: missing DESC on created_at
    assert helper.classify_schema(
        _payload(
            index_created_sql=(
                "CREATE INDEX idx_claw_task_alert_workspace_created "
                "ON claw_task_alert (workspace_id, created_at)"
            )
        )
    ) == "drift"
    # workspace_created: reversed column order
    assert helper.classify_schema(
        _payload(
            index_created_sql=(
                "CREATE INDEX idx_claw_task_alert_workspace_created "
                "ON claw_task_alert (created_at DESC, workspace_id)"
            )
        )
    ) == "drift"
    # workspace_kind_status: wrong column order
    assert helper.classify_schema(
        _payload(
            index_kind_status_sql=(
                "CREATE INDEX idx_claw_task_alert_workspace_kind_status "
                "ON claw_task_alert (workspace_id, status, kind)"
            )
        )
    ) == "drift"
    # workspace_kind_status: missing a column
    assert helper.classify_schema(
        _payload(
            index_kind_status_sql=(
                "CREATE INDEX idx_claw_task_alert_workspace_kind_status "
                "ON claw_task_alert (workspace_id, kind)"
            )
        )
    ) == "drift"
    # member_updated: dropped updated_at from the key
    assert helper.classify_schema(
        _payload(
            index_member_updated_sql=(
                "CREATE INDEX idx_claw_task_alert_member_updated "
                "ON claw_task_alert (member_id) "
                "WHERE member_id != '' AND kind = 'alert'"
            )
        )
    ) == "drift"
    # member_updated: missing DESC on updated_at
    assert helper.classify_schema(
        _payload(
            index_member_updated_sql=(
                "CREATE INDEX idx_claw_task_alert_member_updated "
                "ON claw_task_alert (member_id, updated_at) "
                "WHERE member_id != '' AND kind = 'alert'"
            )
        )
    ) == "drift"


def test_member_id_predicate_alone_is_drift() -> None:
    helper = _load_helper()
    # kind = 'alert' kept, but the member_id != '' predicate is dropped
    assert helper.classify_schema(
        _payload(
            index_member_updated_sql=(
                "CREATE INDEX idx_claw_task_alert_member_updated "
                "ON claw_task_alert (member_id, updated_at DESC) "
                "WHERE kind = 'alert'"
            )
        )
    ) == "drift"


def test_kind_alert_predicate_alone_is_drift() -> None:
    helper = _load_helper()
    # member_id != '' kept, but the kind = 'alert' predicate is dropped
    assert helper.classify_schema(
        _payload(
            index_member_updated_sql=(
                "CREATE INDEX idx_claw_task_alert_member_updated "
                "ON claw_task_alert (member_id, updated_at DESC) "
                "WHERE member_id != ''"
            )
        )
    ) == "drift"


def test_migration_is_additive_and_bounded() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS claw_task_alert" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_claw_task_alert_workspace_created" in migration
    upper = migration.upper()
    assert "DROP TABLE" not in upper
    assert "DROP INDEX" not in upper
    assert "DELETE FROM" not in upper
    assert "ALTER TABLE" not in upper


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_CLAW_D1_MIGRATION_010_FROM_EXACT_MAIN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "apps/padiem-chat/migrations/010_claw_task_alert.sql" in workflow
    assert "B62_D1_MIGRATION_010_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 010 schema is structurally different" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_DATA_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "idx_claw_task_alert_workspace_kind_status" in workflow
    assert "idx_claw_task_alert_member_updated" in workflow


if __name__ == "__main__":
    test_schema_classifier_contract()
    test_index_sql_structure_variation_is_drift()
    test_member_id_predicate_alone_is_drift()
    test_kind_alert_predicate_alone_is_drift()
    test_migration_is_additive_and_bounded()
    test_workflow_is_exact_main_and_migration_specific()
