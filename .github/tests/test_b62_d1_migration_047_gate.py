"""One additive Oracle Mesh dispatch schema and one reviewed release gate."""
from __future__ import annotations
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("migration_047",
    ROOT / ".github/scripts/b62_d1_migration_047_schema.py")
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


def test_exact_additive_dispatch_schema_and_partial_drift():
    source = module.source()
    assert module.classify(_query(source)) == "exact"
    assert module.classify(_query("")) == "missing"
    assert module.classify(
        _query("CREATE TABLE oracle_mesh_dispatch(dispatch_id TEXT);")) == "drift"
    assert "DROP" not in source.upper()
    assert "CREATE TABLE IF NOT EXISTS oracle_mesh_dispatch" in source
    assert "UNIQUE (user_id, run_id)" in source
    assert "nonce_sha256 TEXT" in source
    assert "result_sha256 TEXT" in source
    # The nullable owner columns are deliberate: no fabricated binding/evidence.
    for column in ("binding_ref TEXT", "evidence_ref TEXT"):
        assert column in source
        assert column + " NOT NULL" not in source


def test_canonical_production_dispatch_gate():
    workflow = (ROOT / ".github/workflows/b62-claw-mesh-d1-migration-047-gate.yml"
                ).read_text(encoding="utf-8")
    assert "b62_d1_migration_047_schema.py" in workflow
    assert "047_oracle_mesh_dispatch.sql" in workflow
    assert "APPLY_B62_CLAW_MESH_D1_MIGRATION_047_FROM_EXACT_MAIN" in workflow
    assert "environment: production" in workflow
    assert "Exact current main and production D1 binding" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert 'PADIEM_CHAT_DB' in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply_migration_047" in workflow


if __name__ == "__main__":
    test_exact_additive_dispatch_schema_and_partial_drift()
    test_canonical_production_dispatch_gate()
    print("B62_CLAW_MESH_D1_047_SOURCE=PASS")