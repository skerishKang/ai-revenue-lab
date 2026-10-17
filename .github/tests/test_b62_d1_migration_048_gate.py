"""One additive command-dispatch schema and one reviewed release gate (048)."""
from __future__ import annotations
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("migration_048",
    ROOT / ".github/scripts/b62_d1_migration_048_schema.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

BASE_047 = (ROOT / "apps/padiem-chat/migrations/047_oracle_mesh_dispatch.sql").read_text(
    encoding="utf-8")


def _query(sql: str):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(BASE_047)
    if sql:
        db.executescript(sql)
    blocks = []
    for statement in module.QUERY.strip().split(";"):
        if statement.strip():
            blocks.append({"success": True,
                           "results": [dict(row) for row in db.execute(statement)]})
    db.close()
    return {"success": True, "result": blocks}


def test_additive_command_columns_and_partial_drift():
    source = module.source()
    assert module.classify(_query(source)) == "exact"
    # 047-only table is the applicable state, never drift.
    assert module.classify(_query("")) == "missing"
    # Half-applied (one of two columns) is drift, not "missing".
    assert module.classify(_query(
        "ALTER TABLE oracle_mesh_dispatch ADD COLUMN kind TEXT NOT NULL DEFAULT 'read';"
    )) == "drift"
    # A reshaped column is drift.
    assert module.classify(_query(
        "ALTER TABLE oracle_mesh_dispatch ADD COLUMN kind TEXT;"
        "ALTER TABLE oracle_mesh_dispatch ADD COLUMN command_text TEXT;"
    )) == "drift"
    # No table at all is drift.
    assert module.classify({"success": True, "result": [
        {"success": True, "results": []},
        {"success": True, "results": []},
    ]}) == "drift"


def test_migration_is_additive_only():
    source = module.source().upper()
    assert "ALTER TABLE ORACLE_MESH_DISPATCH ADD COLUMN KIND" in source
    assert "ALTER TABLE ORACLE_MESH_DISPATCH ADD COLUMN COMMAND_TEXT" in source
    for forbidden in ("DROP TABLE", "DELETE FROM", "CREATE TABLE", "CREATE TRIGGER"):
        assert forbidden not in source
    # The default keeps every pre-048 row on the read lane.
    assert "DEFAULT 'READ'" in source


def test_canonical_production_command_migration_gate():
    workflow = (ROOT / ".github/workflows/b62-claw-mesh-d1-migration-048-gate.yml"
                ).read_text(encoding="utf-8")
    assert "b62_d1_migration_048_schema.py" in workflow
    assert "048_oracle_mesh_command.sql" in workflow
    assert "APPLY_B62_CLAW_MESH_D1_MIGRATION_048_FROM_EXACT_MAIN" in workflow
    assert "environment: production" in workflow
    assert "Exact current main and production D1 binding" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply_migration_048" in workflow


if __name__ == "__main__":
    test_additive_command_columns_and_partial_drift()
    test_migration_is_additive_only()
    test_canonical_production_command_migration_gate()
    print("B62_CLAW_MESH_D1_048_SOURCE=PASS")
