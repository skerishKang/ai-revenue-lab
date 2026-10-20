"""#5222: one additive account model selection table and one reviewed release gate (059)."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "migration_059", ROOT / ".github/scripts/b62_d1_migration_059_schema.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

WORKFLOW = ROOT / ".github/workflows/b62-claw-d1-migration-059-gate.yml"


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
    # No table at all is the applicable pre-059 state: the deployed worker
    # answers the account model selection routes with 503 and the browser
    # keeps its server-verified Free default.
    assert module.classify(_query()) == "missing"


def test_reshaped_or_partial_table_is_drift():
    # Missing columns / wrong PK / wrong FK / wrong tier vocabulary / a
    # nullable account column all stay drift; the gate never mutates an
    # existing different table.
    for sql in (
        "CREATE TABLE padiem_account_model_selections (user_id TEXT);",
        # A nullable account column is a different authority shape.
        "CREATE TABLE padiem_account_model_selections ("
        "user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, "
        "tier TEXT NOT NULL CHECK (tier IN ('free','plus','pro','max','admin')), "
        "updated_at TEXT NOT NULL);",
        # A wider tier vocabulary would accept a lane the product never offers.
        "CREATE TABLE padiem_account_model_selections ("
        "user_id TEXT NOT NULL PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, "
        "tier TEXT NOT NULL CHECK (tier IN ('free','plus','pro','max','admin','enterprise')), "
        "updated_at TEXT NOT NULL);",
        # No foreign key to the canonical account table.
        "CREATE TABLE padiem_account_model_selections ("
        "user_id TEXT NOT NULL PRIMARY KEY, "
        "tier TEXT NOT NULL CHECK (tier IN ('free','plus','pro','max','admin')), "
        "updated_at TEXT NOT NULL);",
        # A default value changes the reviewed shape.
        "CREATE TABLE padiem_account_model_selections ("
        "user_id TEXT NOT NULL PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, "
        "tier TEXT NOT NULL DEFAULT 'free' CHECK (tier IN ('free','plus','pro','max','admin')), "
        "updated_at TEXT NOT NULL);",
    ):
        assert module.classify(_query(sql)) == "drift", sql


def test_an_extra_index_is_drift():
    # The reviewed table carries only the implicit primary-key index.
    reviewed = module.source()
    with_extra_index = reviewed + (
        "CREATE INDEX idx_padiem_account_model_selections_tier "
        "ON padiem_account_model_selections (tier);"
    )
    assert module.classify(_query(with_extra_index)) == "drift"


@pytest.mark.parametrize(("original", "replacement"), (
    (" CHECK (tier IN ('free', 'plus', 'pro', 'max', 'admin'))", ""),
    ("'max'", "'max','enterprise'"),
    ("user_id TEXT NOT NULL PRIMARY KEY", "user_id TEXT PRIMARY KEY"),
    ("updated_at TEXT NOT NULL", "updated_at TEXT"),
    ("ON DELETE CASCADE", ""),
))
def test_check_or_column_drift_is_not_exact(original, replacement):
    # These changes preserve the column names, so metadata-only checks miss
    # them; the DDL-level check must catch them.
    reviewed = module.source()
    assert original in reviewed
    assert module.classify(_query(reviewed.replace(original, replacement))) == "drift"


def test_source_is_additive_only():
    source = module.source()
    upper = module.norm(source)
    assert upper.count("create table if not exists padiem_account_model_selections") == 1
    for forbidden in (
        "drop table", "drop index", "delete from", "alter table",
        "create trigger", "create index", "insert into", "update ",
    ):
        assert forbidden not in upper
    assert "references users(id) on delete cascade" in upper
    assert "primary key" in upper


def test_the_migration_creates_exactly_one_table_and_nothing_else():
    """The apply payload must be the reviewed 059 table and nothing else.

    A migration that also created, altered or dropped another table would
    mutate Production state beyond the reviewed change.
    """
    source = module.source()
    # Strip the comment lines: only executable SQL may create anything.
    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [part for part in executable.split(";") if part.strip()]
    assert len(statements) == 1
    assert statements[0].strip().lower().startswith(
        "create table if not exists padiem_account_model_selections"
    )
    lowered = module.norm(executable)
    # No other table may be named by the applied statement.
    for other in (
        "b66_memberships", "platform_admin_roles", "central_model_policy",
        "claw_pc_device_selection", "padiem_android_auth_handoffs",
        "users (",
    ):
        assert other not in lowered
    assert lowered.count("create table") == 1


def test_apply_payload_is_the_reviewed_migration_text(tmp_path):
    target = tmp_path / "apply.json"
    module.main(["apply", str(target)])
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"sql": module.source()}


def test_query_payload_reads_schema_metadata_only(tmp_path):
    target = tmp_path / "query.json"
    module.main(["query", str(target)])
    payload = json.loads(target.read_text(encoding="utf-8"))
    lowered = payload["sql"].lower()
    assert "sqlite_master" in lowered
    assert "pragma table_info" in lowered
    assert "pragma foreign_key_list" in lowered
    # No row read and no mutation may travel with the schema query.
    for forbidden in ("select * from", "delete ", "update ", "insert "):
        assert forbidden not in lowered


def test_malformed_schema_responses_fail_closed():
    for payload in (
        None, {}, {"success": False}, {"success": True, "result": []},
        {"success": True, "result": [{"success": True, "results": "x"}] * 4},
        {"success": True, "result": [{"success": False, "results": []}] * 4},
    ):
        with pytest.raises((ValueError, TypeError)):
            module.classify(payload)


def test_check_apply_rejects_an_unsuccessful_mutation(tmp_path):
    target = tmp_path / "apply-response.json"
    target.write_text(json.dumps({"success": True, "result": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        module.main(["check-apply", str(target)])


def test_the_canonical_gate_is_dispatch_only_confirmed_and_mode_separated():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "b62_d1_migration_059_schema.py" in workflow
    assert "059_account_model_selection.sql" in workflow
    assert "APPLY_B62_CLAW_D1_MIGRATION_059_FROM_EXACT_MAIN" in workflow
    assert "workflow_dispatch" in workflow
    assert "environment: production" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    # The three modes stay separate: a repository preflight, a read-only live
    # proof and the single owner-authorized apply.
    assert "repository_preflight" in workflow
    assert "cloudflare_readonly" in workflow
    assert "apply_migration_059" in workflow
    assert "source-contract" in workflow and "cloudflare-readonly" in workflow
    assert "apply-migration-059" in workflow
    # Applying is a separate dispatched mode, never a push/PR path.
    assert "push:" not in workflow.split("permissions:", 1)[0]
    assert "mode == 'apply_migration_059'" in workflow
    # The gate must not deploy a Worker, create a database or read row data.
    assert "wrangler deploy" not in workflow
    assert "d1 create" not in workflow
    assert "ROW_DATA_READ=0" in workflow


def test_the_gate_never_emits_the_database_identifier():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "::add-mask::" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    # The live database id is resolved from the worker binding, never guessed.
    assert "workers/scripts/${B62_WORKER}/settings" in workflow


def test_the_apply_reuses_the_proven_binding_and_rechecks_the_schema():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # The same canonical binding is re-resolved immediately before the
    # mutation and must be the same database as the read-only proof.
    assert "D1_BINDING_CHANGED_AFTER_READONLY=STOP" in workflow
    assert "D1_BINDING_IDENTITY_STABLE=PASS" in workflow
    # The schema is re-proved immediately before the SQL mutation.
    assert "b62-d1-059-schema-premutation-query.json" in workflow
    assert "Refusing mutation: schema changed after readonly proof." in workflow
    # The apply payload is produced by the reviewed helper, and the result is
    # read back as an exact schema.
    assert "b62_d1_migration_059_schema.py apply" in workflow
    assert "b62_d1_migration_059_schema.py check-apply" in workflow
    assert "B62_D1_MIGRATION_059_POST_APPLY=EXACT" in workflow
    assert "grep -qx 'B62_D1_MIGRATION_059_SCHEMA=EXACT'" in workflow


def test_recovery_bookmark_is_read_with_get_and_never_created():
    """The recovery bookmark must be READ, never created, by the 059 gate.

    POST on ``/d1/database/{id}/time_travel/bookmark`` CREATES a recovery
    bookmark, and Cloudflare refuses it on the read path (HTTP 405). The same
    defect made the first real 058 gate dispatch fail in its read-only step.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "time_travel/bookmark" in workflow
    lines = workflow.splitlines()
    bookmark_calls = []
    for index, line in enumerate(lines):
        if "time_travel/bookmark" not in line:
            continue
        # The curl invocation carries the URL on its own continuation line.
        invocation = "\n".join(lines[max(0, index - 3):index])
        assert "curl" in invocation, invocation
        bookmark_calls.append(invocation)
    assert bookmark_calls, "the recovery bookmark readback must exist"
    for invocation in bookmark_calls:
        assert "-X POST" not in invocation, invocation
        assert "-X DELETE" not in invocation, invocation
        assert "-X PUT" not in invocation, invocation
    # The read-only proof must not read row data and must not leak identifiers.
    assert "ROW_DATA_READ=0" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "D1_RECOVERY_BOOKMARK_PRESENT=PASS" in workflow
