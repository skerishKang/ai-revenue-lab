"""One additive GitHub owner OAuth schema and one reviewed release gate."""
from __future__ import annotations
import importlib.util
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("migration_046",
    ROOT/".github/scripts/b62_d1_migration_046_schema.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def _query(sql: str):
    db=sqlite3.connect(":memory:")
    db.row_factory=sqlite3.Row
    db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
    db.executescript(sql)
    blocks=[]
    for statement in module.QUERY.strip().split(";"):
        if statement.strip():
            blocks.append({"success":True,"results":[dict(row) for row in db.execute(statement)]})
    db.close()
    return {"success":True,"result":blocks}

def test_exact_additive_owner_authority_and_partial_drift():
    source=module.source()
    assert module.classify(_query(source))=="exact"
    assert module.classify(_query(""))=="missing"
    assert module.classify(_query("CREATE TABLE claw_github_connections(user_id TEXT);"))=="drift"
    assert "DROP" not in source.upper()
    assert "ON DELETE CASCADE" in source.upper()
    assert "sealed_credential TEXT NOT NULL" in source

def test_canonical_production_dispatch_gate():
    workflow=(ROOT/".github/workflows/b62-claw-github-d1-migration-046-gate.yml").read_text(encoding="utf-8")
    assert "b62_d1_migration_046_schema.py" in workflow
    assert "046_claw_github_app_oauth.sql" in workflow
    assert "APPLY_B62_CLAW_GITHUB_D1_MIGRATION_046_FROM_EXACT_MAIN" in workflow
    assert "environment: production" in workflow
    assert "Exact current main and production D1 binding" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert 'PADIEM_CHAT_DB' in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply_migration_046" in workflow

if __name__ == "__main__":
    test_exact_additive_owner_authority_and_partial_drift()
    test_canonical_production_dispatch_gate()
    print("B62_CLAW_GITHUB_D1_046_SOURCE=PASS")
