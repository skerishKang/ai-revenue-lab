"""Contract tests for the B54 engine D1 provision gate workflow.

Proves statically that the gate:
  1. is dispatch-only (a pull request can never trigger provisioning);
  2. requires the exact confirmation phrase and production environment;
  3. carries exact-SHA + account premutation assertions, fail-closed;
  4. is idempotent for database creation and migration replay;
  5. applies migrations 0001-0007 in order, with 0005 schema-readback guarded;
  6. asserts the required tables, the durable document-bytes schema objects, the
     evidence retention schema objects and the Drive capability column before PASS;
  7. never deploys the worker.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-d1-provision-gate.yml"
WRANGLER = ROOT / "apps" / "padiem-ai-engine" / "wrangler.toml"
MANIFEST = ROOT / "apps" / "padiem-ai-engine" / "app" / "contract_manifest.py"


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


def test_migrations_0001_through_0007_are_applied_in_order() -> None:
    text = _workflow_text()
    paths = [
        "migrations/0001_engine_idempotency.sql",
        "migrations/0002_engine_continuations.sql",
        "migrations/0003_engine_connector_grants.sql",
        "migrations/0004_engine_attachment_images.sql",
        "migrations/0005_engine_connector_drive_capabilities.sql",
        "migrations/0006_engine_document_bytes.sql",
        "migrations/0007_engine_evidence.sql",
    ]
    positions = [text.index(path) for path in paths]
    assert positions == sorted(positions)
    assert "D1_MIGRATIONS=0001,0002,0003,0004,0005,0006,0007" in text
    assert "migrations apply" not in text
    assert "[[d1_databases]]" not in text


def test_migration_0006_is_applied_exactly_once_and_is_not_renamed() -> None:
    text = _workflow_text()
    path = "migrations/0006_engine_document_bytes.sql"
    assert text.count(path) == 1
    assert text.index("migrations/0005_engine_connector_drive_capabilities.sql") < text.index(path)
    migration = (ROOT / "apps/padiem-ai-engine/migrations/0006_engine_document_bytes.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS padiem_engine_document_bytes" in migration
    assert "ALTER TABLE" not in migration
    assert re.search(r"^\s*(DROP|DELETE|UPDATE|INSERT)\b", migration, re.M) is None


def test_migration_0006_apply_is_unconditional_not_schema_guarded() -> None:
    """0006 must replay directly, unlike 0005's readback guard."""
    text = _workflow_text()
    apply_line = "--file=apps/padiem-ai-engine/migrations/0006_engine_document_bytes.sql"
    assert text.count(apply_line) == 1

    guard_open = text.index("if python3 - <<'PY'")
    guard_close = text.index("fi\n", guard_open)
    apply_at = text.index(apply_line)
    assert apply_at > guard_close, "0006 must apply after the 0005 guard closes"

    between = text[guard_close:apply_at]
    assert re.search(r"^\s*if\b", between, re.M) is None, "0006 apply must be unconditional"
    assert "PRAGMA" not in between, "0006 needs no schema readback to decide apply"


def test_migration_0007_is_applied_exactly_once_after_0006_and_is_not_renamed() -> None:
    text = _workflow_text()
    path = "migrations/0007_engine_evidence.sql"
    assert text.count(path) == 1
    assert text.index("migrations/0006_engine_document_bytes.sql") < text.index(path)
    # The migration itself must be the canonical source, unmodified by this gate.
    migration = (ROOT / "apps/padiem-ai-engine/migrations/0007_engine_evidence.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS padiem_engine_evidence" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_padiem_engine_evidence_created_at" in migration
    assert "ALTER TABLE" not in migration
    assert re.search(r"^\s*(DROP|DELETE|UPDATE|INSERT)\b", migration, re.M) is None


def test_migration_0007_apply_is_unconditional_not_schema_guarded() -> None:
    """0007 must replay directly, unlike 0005's readback guard."""
    text = _workflow_text()
    apply_line = "--file=apps/padiem-ai-engine/migrations/0007_engine_evidence.sql"
    assert text.count(apply_line) == 1

    guard_open = text.index("if python3 - <<'PY'")
    guard_close = text.index("fi\n", guard_open)
    apply_at = text.index(apply_line)
    assert apply_at > guard_close, "0007 must apply after the 0005 guard closes"

    between = text[guard_close:apply_at]
    assert re.search(r"^\s*if\b", between, re.M) is None, "0007 apply must be unconditional"
    assert "PRAGMA" not in between, "0007 needs no schema readback to decide apply"


def test_migration_0005_is_remote_schema_guarded_and_replay_safe() -> None:
    text = _workflow_text()
    before = "PRAGMA table_info(padiem_engine_connector_grants)"
    migration = "migrations/0005_engine_connector_drive_capabilities.sql"
    assert text.index(before) < text.index(migration)
    assert "d1-grant-columns-before-0005.json" in text
    assert "D1_MIGRATION_0005=SKIPPED_ALREADY_APPLIED" in text
    assert "D1_MIGRATION_0005=APPLIED" in text
    assert "sys.exit(0 if 'granted_capabilities_json' in columns else 1)" in text


def test_schema_assertion_covers_tables_document_bytes_evidence_and_drive_column() -> None:
    text = _workflow_text()
    for table in (
        "'padiem_engine_idempotency'",
        "'padiem_engine_continuations'",
        "'padiem_engine_connector_grants'",
        "'padiem_engine_attachment_images'",
    ):
        assert table in text
    # A6 durable document store: table plus both declared indexes are asserted.
    for document_object in (
        "'padiem_engine_document_bytes'",
        "'idx_padiem_engine_document_bytes_expires_at'",
        "'idx_padiem_engine_document_bytes_scope'",
    ):
        assert document_object in text, document_object
    assert "D1_DOCUMENT_BYTES_TABLE_ASSERT=PASS" in text
    # A6 durable evidence retention: table plus created_at index are asserted.
    for evidence_object in (
        "'padiem_engine_evidence'",
        "'idx_padiem_engine_evidence_created_at'",
    ):
        assert evidence_object in text, evidence_object
    assert "D1_EVIDENCE_TABLE_ASSERT=PASS" in text
    assert "PRAGMA table_info(padiem_engine_connector_grants)" in text
    assert "granted_capabilities_json" in text
    assert "D1_TABLES_ASSERT=PASS" in text
    assert "D1_DRIVE_CAPABILITY_COLUMN_ASSERT=PASS" in text


def test_document_evidence_stays_schema_name_only() -> None:
    """Content-blind contract: the gate reads schema *names*, never values.

    Scoped to the remote commands themselves, not to surrounding prose: the
    words "document bytes" legitimately appear in the assertion message and in
    the marker name, so a whole-file substring scan would match its own subject.
    """
    commands = re.findall(r'--command "([^"]*)"', _workflow_text())
    assert commands, "gate must read schema back from the remote"
    for sql in commands:
        assert re.match(r"^(SELECT name FROM sqlite_master|PRAGMA table_info\()", sql), sql
        assert "*" not in sql
        assert " WHERE type IN ('table','index')" in sql or sql.startswith("PRAGMA")
    joined = " ".join(commands).lower()
    for forbidden in ("select *", "content", "text", "blob", "hex(", "length(", " limit "):
        assert forbidden not in joined, forbidden


def test_engine_document_store_binding_targets_canonical_database() -> None:
    """The provision gate is only meaningful while wrangler still routes
    ENGINE_DOCUMENT_STORE at the same provisioned `padiem-engine` database."""
    config = WRANGLER.read_text(encoding="utf-8")
    block = config[config.index('binding = "ENGINE_DOCUMENT_STORE"'):]
    head = block[: block.find("[[")]
    assert 'database_name = "padiem-engine"' in head
    assert 'binding = "ENGINE_IMAGE_STORE"' in config
    image_head = config[
        config.index('binding = "ENGINE_IMAGE_STORE"'):
    ]
    assert 'database_name = "padiem-engine"' in image_head[: image_head.find("[[")]


def test_engine_evidence_store_binding_targets_canonical_database() -> None:
    """The provision gate is only meaningful while wrangler still routes
    ENGINE_EVIDENCE_STORE at the same provisioned `padiem-engine` database."""
    config = WRANGLER.read_text(encoding="utf-8")
    block = config[config.index('binding = "ENGINE_EVIDENCE_STORE"'):]
    head = block[: block.find("[[")]
    assert 'database_name = "padiem-engine"' in head
    assert 'database_id = "6b77ad02-bc27-488f-bb97-6325f6750cba"' in head


def test_manifest_document_features_remain_deferred() -> None:
    """Static contract: document features remain truthfully DEFERRED
    in the Engine contract manifest until live production activation is complete."""
    manifest_text = MANIFEST.read_text(encoding="utf-8")
    assert 'EngineFeatureContract("document_admission", EngineFeatureState.DEFERRED)' in manifest_text
    assert 'EngineFeatureContract("document_projection", EngineFeatureState.DEFERRED)' in manifest_text


def test_final_evidence_markers_present() -> None:
    text = _workflow_text()
    assert "D1_PROVISION=PASS" in text
    assert "D1_DATABASE_ID=" in text
    assert "D1_MIGRATIONS=0001,0002,0003,0004,0005,0006,0007" in text
    assert "D1_DRIVE_CAPABILITY_COLUMN_ASSERT=PASS" in text
    assert "D1_DOCUMENT_BYTES_TABLE_ASSERT=PASS" in text
    assert "D1_EVIDENCE_TABLE_ASSERT=PASS" in text
    assert "WORKER_DEPLOYED=0" in text
    # Both the apply step and the final evidence step must carry the full list:
    # a stale marker in either place would misreport what was provisioned.
    assert text.count("D1_MIGRATIONS=0001,0002,0003,0004,0005,0006,0007") == 2
    assert "D1_MIGRATIONS=0001,0002,0003,0004,0005,0006'" not in text
    assert "D1_MIGRATIONS=0001,0002,0003,0004,0005,0006\n" not in text


def test_workflow_never_deploys_worker() -> None:
    text = _workflow_text()
    for forbidden in ("pywrangler deploy", "wrangler@4 deploy", "d1_migrations", "[[d1_databases]]"):
        assert forbidden not in text, f"provision gate must not contain: {forbidden}"

