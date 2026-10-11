from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / ".github/scripts/b62_claw_automation_migrations_schema.py"
_spec = importlib.util.spec_from_file_location("b62_claw_automation_migrations_schema", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = module
_spec.loader.exec_module(module)


def entry(rows):
    return {"success": True, "results": rows}


def table(name, sql):
    return {"name": name, "type": "table", "sql": sql}


def index(name, sql):
    return {"name": name, "type": "index", "sql": sql}


def columns(names):
    return [{"name": name, "type": "TEXT"} for name in names]


def exact_018():
    return {
        "success": True,
        "result": [
            entry([
                table("claw_rules", "CREATE TABLE claw_rules (rule_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL)"),
                table("claw_runs", "CREATE TABLE claw_runs (run_id TEXT PRIMARY KEY)"),
                table("claw_occurrences", "CREATE TABLE claw_occurrences (occurrence_key TEXT PRIMARY KEY)"),
                table("claw_proposals", "CREATE TABLE claw_proposals (proposal_id TEXT PRIMARY KEY)"),
                index("idx_claw_rules_workspace", "CREATE INDEX idx_claw_rules_workspace ON claw_rules (workspace_id)"),
                index("idx_claw_runs_workspace_status", "CREATE INDEX idx_claw_runs_workspace_status ON claw_runs (workspace_id, status)"),
                index("idx_claw_occurrences_workspace", "CREATE INDEX idx_claw_occurrences_workspace ON claw_occurrences (workspace_id)"),
                index("idx_claw_proposals_workspace", "CREATE INDEX idx_claw_proposals_workspace ON claw_proposals (workspace_id)"),
            ]),
            entry(columns(module.RULE_COLUMNS)),
            entry(columns(module.RUN_COLUMNS)),
            entry(columns(module.OCCURRENCE_COLUMNS)),
            entry(columns(module.PROPOSAL_COLUMNS)),
            entry([{"name": "workspace_id"}]),
            entry([{"name": "workspace_id"}, {"name": "status"}]),
            entry([{"name": "workspace_id"}]),
            entry([{"name": "workspace_id"}]),
        ],
    }


def exact_019():
    return {
        "success": True,
        "result": [entry(columns(module.RULE_COLUMNS + ("canonical_subject_id",)))],
    }


def test_migration_018_classifies_exact_missing_and_drift() -> None:
    assert module.classify_migration_018(exact_018()) == "exact"
    assert module.classify_migration_018({"success": True, "result": [entry([])] * 9}) == "missing"
    drifted = exact_018()
    drifted["result"][1]["results"][0]["name"] = "unexpected"
    assert module.classify_migration_018(drifted) == "drift"
    index_drift = exact_018()
    index_drift["result"][5]["results"] = []
    assert module.classify_migration_018(index_drift) == "drift"


def test_migration_019_requires_exact_additive_column() -> None:
    assert module.classify_migration_019(exact_019()) == "exact"
    assert module.classify_migration_019({"success": True, "result": [entry(columns(module.RULE_COLUMNS))]}) == "missing"
    drifted = exact_019()
    drifted["result"][0]["results"].append({"name": "unexpected", "type": "TEXT"})
    assert module.classify_migration_019(drifted) == "drift"


def test_schema_gate_rejects_row_data_and_shape_drift() -> None:
    try:
        module.classify_migration_018({"success": True, "result": [{"success": True, "results": "bad"}]})
    except module.AutomationSchemaError:
        pass
    else:
        raise AssertionError("malformed D1 evidence must fail closed")


def test_migrations_workflow_is_readiness_only() -> None:
    workflow = (
        ROOT / ".github/workflows/b62-claw-automation-migrations-gate.yml"
    ).read_text(encoding="utf-8")
    assert "PRODUCTION_MUTATION=0" in workflow
    assert "MIGRATION_APPLY=0" in workflow
    assert "apply_migration_018" in workflow
    assert "apply_migration_019" in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_CLAW_AUTOMATION_MIGRATION_018_FROM_EXACT_MAIN" in workflow
    assert "APPLY_B62_CLAW_AUTOMATION_MIGRATION_019_FROM_EXACT_MAIN" in workflow
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in workflow
    assert "wrangler deploy" not in workflow
    assert "d1 migrations apply" not in workflow
