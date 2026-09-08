"""Contract tests for the B54 engine D1 provision gate workflow (WO-8 PR-A, #1621).

Proves statically that the gate:
  1. is dispatch-only (a pull request can never trigger a provisioning mutation);
  2. requires the exact confirmation phrase PROVISION_B54_ENGINE_D1 and the
     production environment;
  3. carries the exact-SHA + account premutation assertions, fail-closed
     (same §Premutation block as the engine deploy gate);
  4. is idempotent (create skipped when padiem-engine already exists) and
     applies migrations 0001 + 0002 verbatim without editing wrangler.toml;
  5. asserts both contract tables exist before reporting D1_PROVISION=PASS;
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
    # Regression (CTO review #2019): create output shape varies by wrangler
    # version ({"d1_databases":[...]} or TOML snippet) — never parse it;
    # re-query d1 list for the uuid instead.
    assert "d1-create.txt" not in text
    assert "database_id'" not in text.replace('"database_id"', "")
    assert "d1-list-after-create.json" in text


def test_migrations_applied_verbatim_without_binding_or_toml_edit() -> None:
    text = _workflow_text()
    assert "migrations/0001_engine_idempotency.sql" in text
    assert "migrations/0002_engine_continuations.sql" in text
    assert "D1_MIGRATIONS=0001,0002" in text
    # PR-A must not touch wrangler.toml nor use binding-resolved migration apply.
    assert "migrations apply" not in text
    assert "[[d1_databases]]" not in text


def test_schema_assertion_covers_both_tables() -> None:
    text = _workflow_text()
    assert "padiem_engine_idempotency" in text
    assert "padiem_engine_continuations" in text
    assert "D1_TABLES_ASSERT=PASS" in text


def test_final_evidence_markers_present() -> None:
    text = _workflow_text()
    assert "D1_PROVISION=PASS" in text
    assert "D1_DATABASE_ID=" in text
    assert "WORKER_DEPLOYED=0" in text


def test_workflow_never_deploys_worker() -> None:
    text = _workflow_text()
    for forbidden in ("pywrangler deploy", "wrangler@4 deploy", "d1_migrations", "[[d1_databases]]"):
        assert forbidden not in text, f"provision gate must not contain: {forbidden}"
