"""Schema-only D1 045 and guarded exact-main release regressions."""
from __future__ import annotations
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b62_d1_migration_045_schema.py"
WORKFLOW = ROOT / ".github/workflows/b62-b66-d1-migration-045-gate.yml"
spec = importlib.util.spec_from_file_location("b62_d1_045", HELPER)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def dbnew():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
    return db


def snapshot(db):
    statements = [x for x in guard.QUERY.split(";") if x.strip()]
    blocks = [{"success":True,"results":[dict(r) for r in db.execute(sql).fetchall()]}
              for sql in statements]
    return {"success":True,"result":blocks}


def test_exact_missing_idempotent():
    db = dbnew()
    assert guard.classify(snapshot(db)) == "missing"
    db.executescript(guard.source_sql())
    assert guard.classify(snapshot(db)) == "exact"
    db.executescript(guard.source_sql())
    assert guard.classify(snapshot(db)) == "exact"
    db.close()


def test_drift_and_parent_fail_closed():
    db = dbnew()
    db.executescript(guard.source_sql())
    db.execute("CREATE INDEX unexpected_idx ON b66_guided_transcript(updated_at)")
    assert guard.classify(snapshot(db)) == "drift"
    db.close()
    empty = sqlite3.connect(":memory:")
    empty.row_factory = sqlite3.Row
    assert guard.classify(snapshot(empty)) == "drift"
    empty.close()
    for bad in ({}, {"success": False, "result": []},
                {"success": True, "result": []},
                {"success": True, "result": [{"success":False,"results":[]}]*5}):
        try:
            guard.classify(bad)
        except ValueError:
            continue
        raise AssertionError("045 D1 classifier accepted invalid evidence")


def test_workflow_guards():
    source = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "workflow_dispatch:", "pull_request:", "environment: production",
        "APPLY_B62_B66_D1_MIGRATION_045_FROM_EXACT_MAIN",
        "test \"$(git rev-parse origin/main)\" = \"${TARGET_SHA}\"",
        "PADIEM_CHAT_DB", "B62_D1_MIGRATION_045_SCHEMA=EXACT",
        "CUSTOMER_ROW_MUTATION=0", "cancel-in-progress: false",
        "b62_d1_migration_045_schema.py classify",
        "b62_d1_migration_045_schema.py check-apply",
    ):
        assert required in source, required
    assert source.count("environment: production") == 1
    assert "pull_request_target:" not in source


if __name__ == "__main__":
    for test in [test_exact_missing_idempotent,test_drift_and_parent_fail_closed,test_workflow_guards]:
        test()
        print(test.__name__.upper()+"=PASS")
    print("B62_D1_045_SOURCE_CONTRACT=PASS")
