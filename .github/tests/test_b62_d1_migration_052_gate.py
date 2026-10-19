"""#5015: one additive preferred-PC table and one reviewed release gate (052)."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "migration_052", ROOT / ".github/scripts/b62_d1_migration_052_schema.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _query(*extras: str):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    for sql in extras:
        db.executescript(sql)
    blocks = []
    for statement in module.QUERY.strip().split(";"):
        if statement.strip():
            blocks.append({
                "success": True,
                "results": [dict(row) for row in db.execute(statement)],
            })
    db.close()
    return {"success": True, "result": blocks}


def test_additive_table_is_exact_and_absent_is_missing():
    source = module.source()
    assert module.classify(_query(source)) == "exact"
    # No table at all is the applicable pre-052 state.
    assert module.classify(_query()) == "missing"


def test_reshaped_or_partial_table_is_drift():
    # Missing columns / wrong PK / wrong FK all stay drift; the gate never
    # mutates an existing different table.
    for sql in (
        "CREATE TABLE claw_pc_device_selection (user_id TEXT);",
        "CREATE TABLE claw_pc_device_selection ("
        "user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, device_id TEXT, "
        "updated_at TEXT NOT NULL, PRIMARY KEY(user_id, workspace_id));",
        "CREATE TABLE claw_pc_device_selection ("
        "user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, device_id TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, PRIMARY KEY(user_id, workspace_id));",
    ):
        assert module.classify(_query(sql)) == "drift", sql


def test_source_is_additive_only():
    source = module.source()
    upper = module.norm(source)
    assert upper.count("create table if not exists claw_pc_device_selection") == 1
    for forbidden in (
        "drop table", "delete from", "alter table", "create trigger",
        "create index", "insert into",
    ):
        assert forbidden not in upper
    assert "references users(id) on delete cascade" in upper
    assert "primary key(user_id, workspace_id)" in upper


def test_malformed_schema_responses_fail_closed():
    for payload in (
        None, {}, {"success": False}, {"success": True, "result": []},
        {"success": True, "result": [{"success": True, "results": "x"}] * 3},
    ):
        with pytest.raises((ValueError, TypeError)):
            module.classify(payload)


def test_canonical_migration_gate_is_dispatch_only_and_confirmed():
    workflow = (
        ROOT / ".github/workflows/b62-claw-d1-migration-052-gate.yml"
    ).read_text(encoding="utf-8")
    assert "b62_d1_migration_052_schema.py" in workflow
    assert "052_claw_pc_device_selection.sql" in workflow
    assert "APPLY_B62_CLAW_D1_MIGRATION_052_FROM_EXACT_MAIN" in workflow
    assert "workflow_dispatch" in workflow
    assert "environment: production" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply_migration_052" in workflow
    # Applying is a separate dispatched mode, never a push/PR path.
    assert "push:" not in workflow.split("permissions:", 1)[0]
    assert "mode == 'apply_migration_052'" in workflow


def test_production_deploy_gate_connects_the_052_schema_precheck():
    workflow = (
        ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
    ).read_text(encoding="utf-8")
    assert "b62_d1_migration_052_schema.py" in workflow
    assert "test_b62_d1_migration_052_gate.py" in workflow
    assert "claw_pc_device_selection" in workflow
    assert "MIGRATION_052_PREDEPLOY" in workflow
    assert "B62_D1_MIGRATION_052_SCHEMA=EXACT" in workflow
