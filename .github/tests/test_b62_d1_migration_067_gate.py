"""One additive Mesh device presence schema and one reviewed release gate."""
from __future__ import annotations
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("migration_067",
    ROOT / ".github/scripts/b62_d1_migration_067_schema.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _query(sql: str):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
    db.executescript(sql)
    blocks = []
    for statement in module.QUERY.strip().split(";"):
        if statement.strip():
            blocks.append({"success": True,
                           "results": [dict(row) for row in db.execute(statement)]})
    db.close()
    return {"success": True, "result": blocks}


def test_exact_additive_presence_schema_and_partial_drift():
    source = module.source()
    assert module.classify(_query(source)) == "exact"
    assert module.classify(_query("")) == "missing"
    assert module.classify(
        _query("CREATE TABLE mesh_device_presence(device_id TEXT);")) == "drift"
    assert "DROP" not in source.upper()
    assert "ALTER" not in source.upper()
    assert "CREATE TABLE IF NOT EXISTS mesh_device_presence" in source
    for column in ("device_id TEXT PRIMARY KEY", "connected INTEGER NOT NULL",
                   "received_at TEXT NOT NULL",
                   "credential_generation INTEGER NOT NULL"):
        assert column in source


def test_canonical_production_presence_gate():
    workflow = (ROOT / ".github/workflows/b62-claw-mesh-d1-migration-067-gate.yml"
                ).read_text(encoding="utf-8")
    assert "b62_d1_migration_067_schema.py" in workflow
    assert "067_mesh_device_presence.sql" in workflow
    assert "APPLY_B62_CLAW_MESH_D1_MIGRATION_067_FROM_EXACT_MAIN" in workflow
    assert "environment: production" in workflow
    assert "Exact current main and production D1 binding" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert 'PADIEM_CHAT_DB' in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply_migration_067" in workflow


if __name__ == "__main__":
    test_exact_additive_presence_schema_and_partial_drift()
    test_canonical_production_presence_gate()
    print("B62_CLAW_MESH_D1_067_SOURCE=PASS")
