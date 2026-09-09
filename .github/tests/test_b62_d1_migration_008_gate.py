from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-claw-d1-migration-008-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_008_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/008_claw_document_metadata.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_008", HELPER)
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
                "name": "claw_document_metadata",
                "type": "table",
                "sql": table_sql or migration.split("CREATE INDEX", 1)[0].strip(),
            }
        )
    if index:
        objects.append(
            {
                "name": "idx_claw_document_metadata_tenant_active",
                "type": "index",
                "sql": "CREATE INDEX idx_claw_document_metadata_tenant_active ON claw_document_metadata (tenant_id, deleted_at, expires_at)",
            }
        )
    expected_columns = (
        "document_id",
        "tenant_id",
        "object_key",
        "filename",
        "media_type",
        "byte_length",
        "created_at",
        "expires_at",
        "deleted_at",
    )
    expected_index = ("tenant_id", "deleted_at", "expires_at")
    column_rows = [{"name": name} for name in (expected_columns if columns is None else columns)] if table else []
    index_rows = [{"name": name} for name in (expected_index if index_columns is None else index_columns)] if index else []
    return {
        "success": True,
        "result": [_result(objects), _result(column_rows), _result(index_rows)],
    }


def test_schema_classifier_contract() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_payload()) == "exact"
    assert helper.classify_schema(_payload(table=False, index=False)) == "missing"
    assert helper.classify_schema(_payload(index=False)) == "drift"
    assert helper.classify_schema(_payload(columns=("document_id", "tenant_id"))) == "drift"
    assert helper.classify_schema(_payload(index_columns=("tenant_id", "expires_at"))) == "drift"
    assert helper.classify_schema(
        _payload(table_sql="CREATE TABLE claw_document_metadata (document_id TEXT PRIMARY KEY)")
    ) == "drift"


def test_migration_is_additive_and_bounded() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS claw_document_metadata" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_claw_document_metadata_tenant_active" in migration
    assert "byte_length <= 10485760" in migration
    upper = migration.upper()
    assert "DROP TABLE" not in upper
    assert "DROP INDEX" not in upper
    assert "DELETE FROM" not in upper
    assert "ALTER TABLE" not in upper


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_CLAW_D1_MIGRATION_008_FROM_EXACT_MAIN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "apps/padiem-chat/migrations/008_claw_document_metadata.sql" in workflow
    assert "B62_D1_MIGRATION_008_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 008 schema is structurally different" in workflow
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
    assert "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_008'" in workflow


if __name__ == "__main__":
    test_schema_classifier_contract()
    test_migration_is_additive_and_bounded()
    test_workflow_is_exact_main_and_migration_specific()
    print("B62_D1_MIGRATION_008_GATE_TESTS=PASS")
