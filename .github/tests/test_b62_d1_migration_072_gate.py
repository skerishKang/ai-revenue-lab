"""Two additive PC pairing tables and one reviewed release gate (migration 072)."""
from __future__ import annotations
import importlib.util
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("migration_072",
    ROOT / ".github/scripts/b62_d1_migration_072_schema.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _query(sql: str):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
    if sql.strip():
        db.executescript(sql)
    blocks = []
    for statement in module.QUERY.strip().split(";"):
        if statement.strip():
            try:
                rows = [dict(row) for row in db.execute(statement)]
            except sqlite3.Error:
                rows = []
            blocks.append({"success": True, "results": rows})
    db.close()
    return {"success": True, "result": blocks}


def test_exact_additive_pairing_schema_and_partial_drift():
    source = module.source()
    assert module.classify(_query(source)) == "EXACT"
    assert module.classify(_query("")) == "MISSING"
    assert module.classify(
        _query("CREATE TABLE pc_pairing_codes(code_id TEXT);")) == "DRIFT"
    # Half a migration applied is drift, not a reusable state: the second table
    # is what dispatch reads, and it must never be missing silently.
    partial = re.search(r"CREATE TABLE IF NOT EXISTS pc_pairing_codes.*?\n\);",
                        source, re.DOTALL).group(0)
    assert module.classify(_query(partial)) == "DRIFT"
    # Statement-position refusal, so a column named updated_at never trips it.
    for forbidden in ("DROP TABLE", "ALTER TABLE", "INSERT INTO", "UPDATE ", "DELETE FROM",
                      "CREATE TRIGGER", "CREATE VIEW"):
        assert forbidden not in source.upper()
    for table in ("CREATE TABLE IF NOT EXISTS pc_pairing_codes",
                  "CREATE TABLE IF NOT EXISTS pc_device_links"):
        assert table in source


def test_canonical_production_pairing_gate():
    workflow = (ROOT / ".github/workflows/b62-d1-migration-072-gate.yml"
                ).read_text(encoding="utf-8")
    assert "b62_d1_migration_072_schema.py" in workflow
    assert "072_pc_device_pairing.sql" in workflow
    assert "APPLY_B62_PC_PAIRING_D1_MIGRATION_072_FROM_EXACT_MAIN" in workflow
    assert "environment: production" in workflow
    assert "Exact current main and production D1 binding" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert 'PADIEM_CHAT_DB' in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply_migration_072" in workflow
    assert "PRODUCTION_MUTATION=0" in workflow
    # Nothing existing is rebuilt: the gate is only ever allowed to create.
    assert "STATE == 'EXACT'" not in workflow
    assert "rowid" not in workflow.lower()


if __name__ == "__main__":
    test_exact_additive_pairing_schema_and_partial_drift()
    test_canonical_production_pairing_gate()
    print("B62_PC_PAIRING_D1_072_SOURCE=PASS")
