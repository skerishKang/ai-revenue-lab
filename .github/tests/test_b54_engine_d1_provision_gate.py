"""Contract tests for the B54 engine D1 provision gate workflow.

Proves statically that the gate:
  1. is dispatch-only (a pull request can never trigger provisioning);
  2. requires the exact confirmation phrase and production environment;
  3. carries exact-SHA + account premutation assertions, fail-closed;
  4. is idempotent for database creation and migration replay;
  5. applies migrations 0001-0005 in order, with 0005 schema-readback guarded;
  6. asserts the required tables and Drive capability column before PASS;
  7. never deploys the worker.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-d1-provision-gate.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    data = yaml.safe_load(_workflow_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def test_workflow_parses_and_is_dispatch_only() -> None:
    wf = _workflow()
    assert set(wf["triggers"]) == {"workflow_dispatch"}
    inputs = wf["triggers"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation"}
    assert all(spec["required"] is True for spec in inputs.values())


def test_provision_job_requires_exact_confirmation_phrase() -> None:
    job = _workflow()["jobs"]["provision-d1"]
    assert job["if"] == "github.event.inputs.confirmation == 'PROVISION_B54_ENGINE_D1'"
    assert job["environment"] == "production"


def test_premutation_assertions_are_fail_closed() -> None:
    text = _workflow_text()
    assert "set -euo pipefail" in text
    assert re.search(r'test "\$\(git rev-parse HEAD\)" = "\$\{\{ github\.event\.inputs\.target_sha \}\}"', text)
    assert re.search(r'test "\$\(git rev-parse origin/main\)" = "\$\{\{ github\.event\.inputs\.target_sha \}\}"', text)
    assert "9be14bb7b8974e65d0afba647ab16932" in text
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in text
    assert "PREMUTATION_TARGET_ACCOUNT=PASS" in text


def test_create_step_is_idempotent() -> None:
    text = _workflow_text()
    assert "d1 list --json" in text
    assert "D1_CREATE=SKIPPED_ALREADY_EXISTS" in text
    assert "d1 create padiem-engine" in text
    assert "d1-list-after-create.json" in text
    # Regression guard from #2019: create output shape varies by wrangler
    # version, so it must never become the authority for the database id.
    assert "d1-create.txt" not in text
    assert "database_id'" not in text.replace('"database_id"', "")


def test_migrations_0001_through_0005_are_applied_in_order() -> None:
    text = _workflow_text()
    paths = [
        "migrations/0001_engine_idempotency.sql",
        "migrations/0002_engine_continuations.sql",
        "migrations/0003_engine_connector_grants.sql",
        "migrations/0004_engine_attachment_images.sql",
        "migrations/0005_engine_connector_drive_capabilities.sql",
    ]
    positions = [text.index(path) for path in paths]
    assert positions == sorted(positions)
    assert "D1_MIGRATIONS=0001,0002,0003,0004,0005" in text
    assert "migrations apply" not in text
    assert "[[d1_databases]]" not in text


def test_migration_0005_is_remote_schema_guarded_and_replay_safe() -> None:
    text = _workflow_text()
    before = "PRAGMA table_info(padiem_engine_connector_grants)"
    migration = "migrations/0005_engine_connector_drive_capabilities.sql"
    assert text.index(before) < text.index(migration)
    assert "d1-grant-columns-before-0005.json" in text
    assert "D1_MIGRATION_0005=SKIPPED_ALREADY_APPLIED" in text
    assert "D1_MIGRATION_0005=APPLIED" in text
    assert "sys.exit(0 if 'granted_capabilities_json' in columns else 1)" in text


def test_schema_assertion_covers_tables_and_drive_capability_column() -> None:
    text = _workflow_text()
    for table in (
        "padiem_engine_idempotency",
        "padiem_engine_continuations",
        "padiem_engine_connector_grants",
        "padiem_engine_attachment_images",
    ):
        assert table in text
    assert "PRAGMA table_info(padiem_engine_connector_grants)" in text
    assert "granted_capabilities_json" in text
    assert "D1_TABLES_ASSERT=PASS" in text
    assert "D1_DRIVE_CAPABILITY_COLUMN_ASSERT=PASS" in text


def test_final_evidence_markers_present() -> None:
    text = _workflow_text()
    assert "D1_PROVISION=PASS" in text
    assert "D1_DATABASE_ID=" in text
    assert "D1_MIGRATIONS=0001,0002,0003,0004,0005" in text
    assert "D1_DRIVE_CAPABILITY_COLUMN_ASSERT=PASS" in text
    assert "WORKER_DEPLOYED=0" in text


def test_workflow_never_deploys_worker() -> None:
    text = _workflow_text()
    for forbidden in ("pywrangler deploy", "wrangler@4 deploy", "d1_migrations", "[[d1_databases]]"):
        assert forbidden not in text, f"provision gate must not contain: {forbidden}"
