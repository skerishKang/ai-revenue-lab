"""#5015: one additive preferred-PC table and one reviewed release gate (054)."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "migration_054", ROOT / ".github/scripts/b62_d1_migration_054_schema.py"
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
    # No table at all is the applicable pre-054 state.
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


@pytest.mark.parametrize(("original", "replacement"), (
    (" CHECK(length(workspace_id) BETWEEN 1 AND 160)", ""),
    (" CHECK(length(device_id) BETWEEN 1 AND 128)", ""),
    ("BETWEEN 1 AND 160", "BETWEEN 1 AND 159"),
    ("BETWEEN 1 AND 128", "BETWEEN 1 AND 129"),
    ("updated_at TEXT NOT NULL,",
     "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"),
))
def test_check_or_default_drift_is_not_exact(original, replacement):
    # These changes preserve columns/PK/FK, so metadata-only checks miss them.
    reviewed = module.source()
    assert original in reviewed
    assert module.classify(_query(reviewed.replace(original, replacement))) == "drift"


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
        ROOT / ".github/workflows/b62-claw-d1-migration-054-gate.yml"
    ).read_text(encoding="utf-8")
    assert "b62_d1_migration_054_schema.py" in workflow
    assert "054_claw_pc_device_selection.sql" in workflow
    assert "APPLY_B62_CLAW_D1_MIGRATION_054_FROM_EXACT_MAIN" in workflow
    assert "workflow_dispatch" in workflow
    assert "environment: production" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply_migration_054" in workflow
    # Applying is a separate dispatched mode, never a push/PR path.
    assert "push:" not in workflow.split("permissions:", 1)[0]
    assert "mode == 'apply_migration_054'" in workflow


def test_production_deploy_gate_connects_the_054_schema_precheck():
    workflow = (
        ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
    ).read_text(encoding="utf-8")
    assert "b62_d1_migration_054_schema.py" in workflow
    assert "test_b62_d1_migration_054_gate.py" in workflow
    assert "claw_pc_device_selection" in workflow
    assert "MIGRATION_054_PREDEPLOY" in workflow
    assert "B62_D1_MIGRATION_054_SCHEMA=EXACT" in workflow
