"""Contract tests for the B54 engine D1 provision gate workflow.

Proves statically that the gate:
  1. is dispatch-only (a pull request can never trigger provisioning);
  2. requires the exact confirmation phrase and production environment;
  3. carries exact-SHA + account premutation assertions, fail-closed;
  4. is idempotent for database creation and applies migrations 0001-0005
     verbatim without editing wrangler.toml;
  5. asserts the required tables and Drive capability column before PASS;
  6. never deploys the worker.
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
    # YAML 1.1 parses bare `on:` as True; normalise the key for portability.
    data = yaml.safe_load(_workflow_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def test_workflow_parses_and_is_dispatch_only() -> None:
    wf = _workflow()
    assert set(wf["triggers"]) == {"workflow_dispatch"}, (
        "provision gate must be workflow_dispatch-only: an ordinary pull "
        "request must never create cloud resources"
    )
    inputs = wf["triggers"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation"}
    for spec in inputs.values():
        assert spec["required"] is True


def test_provision_job_requires_exact_confirmation_phrase() -> None:
    wf = _workflow()
    job = wf["jobs"]["provision-d1"]
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
    assert "padiem-engine" in text
    assert "D1_CREATE=SKIPPED_ALREADY_EXISTS" in text
    assert "d1 create padiem-engine" in text
    assert "d1-create.txt" not in text
    assert "database_id'" not in text.replace('"database_id"', "")
    assert "d1-list-after-create.json" in text


def test_migrations_0001_through_0005_are_applied_verbatim_in_order() -> None:
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
    # The owner gate applies reviewed files verbatim; it does not mutate
    # wrangler.toml or switch to binding-resolved migration authority.
    assert "migrations apply" not in text
    assert "[[d1_databases]]" not in text


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
