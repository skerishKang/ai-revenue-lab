"""Contract tests for the B14 ledger D1 provision gate workflow.

Proves statically that the gate:
  1. is dispatch-only (a pull request can never trigger provisioning);
  2. requires the exact confirmation phrase and the production environment;
  3. carries exact-SHA + account premutation assertions, fail-closed;
  4. refuses when the ledger database is absent — it never creates one, and it
     never emits the database identifier or any secret value;
  5. applies through wrangler's migrations mechanism from the B14 app directory;
  6. replays every migration against a blank SQLite database, compares the
     remote schema names with that result, and pins the expected schema here;
  7. never deploys the worker and never edits wrangler.toml.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
import sqlite3
import tempfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b14-ledger-d1-provision-gate.yml"
APP_DIR = ROOT / "apps" / "korean-ai-platform"
WRANGLER = APP_DIR / "wrangler.toml"
MIGRATIONS = APP_DIR / "migrations"
SCHEMA_SCRIPT = ROOT / ".github" / "scripts" / "b14_ledger_d1_schema.py"
_SCHEMA_SPEC = importlib.util.spec_from_file_location("b14_ledger_d1_schema", SCHEMA_SCRIPT)
assert _SCHEMA_SPEC and _SCHEMA_SPEC.loader
b14_schema = importlib.util.module_from_spec(_SCHEMA_SPEC)
_SCHEMA_SPEC.loader.exec_module(b14_schema)
LEDGER_MIGRATION = MIGRATIONS / "0001_b14_model_call_ledger.sql"
CREDENTIAL_MIGRATION = MIGRATIONS / "0002_credential_source.sql"
PC_METRICS_MIGRATION = MIGRATIONS / "0003_pc_work_metrics.sql"
DATABASE_NAME = "padiem-b14-call-ledger"
BINDING = "B14_CALL_LEDGER_D1"
EXPECTED_TABLE_COLUMNS = {
    "b14_model_call": [
        "log_id", "request_id", "endpoint", "product", "origin_source",
        "origin_request_id", "subject_ref", "tenant_ref", "membership_tier",
        "client_app", "client_version", "session_ref", "requested_model_id",
        "selected_model_id", "selected_provider", "selected_upstream_model",
        "selected_route_id", "actual_response_model", "route_mode", "streaming",
        "protocol", "outcome", "http_status", "error_code", "finish_reason",
        "started_at", "finished_at", "elapsed_ms", "latency_source", "ttft_ms",
        "attempt_count", "fallback_used", "fallback_depth", "prompt_tokens",
        "completion_tokens", "total_tokens", "reasoning_tokens", "token_source",
        "estimated_usd", "estimated_krw", "cost_basis", "currency",
        "credential_source", "pc_work_metrics_json", "pc_work_metrics_recorded_at",
    ],
    "b14_model_call_attempt": [
        "log_id", "attempt_index", "provider", "model_id", "upstream_model",
        "route_id", "outcome", "error_code", "retry_index",
        "actual_response_model", "finish_reason", "provider_request_id",
        "started_at", "finished_at", "elapsed_ms", "latency_source",
        "prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens",
        "token_source", "estimated_usd", "estimated_krw", "cost_basis",
        "endpoint", "protocol", "dispatched", "timeout_reason", "reasoning_effort",
        "thought_summary_count", "thought_summary_chars", "http_status",
    ],
}
EXPECTED_INDEXES = {
    "b14_model_call_started", "b14_model_call_request", "b14_model_call_outcome",
    "b14_model_call_model", "b14_model_call_product", "b14_model_call_subject",
    "b14_model_call_attempt_log", "b14_model_call_pc_turn",
}


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    data = yaml.safe_load(_workflow_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {
        "triggers": trigger,
        "jobs": data["jobs"],
        "permissions": data.get("permissions"),
    }


def _steps() -> list[dict]:
    return _workflow()["jobs"]["provision-d1"]["steps"]


def _step(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"step not found: {name}")


def test_workflow_parses_and_is_dispatch_only() -> None:
    wf = _workflow()
    assert set(wf["triggers"]) == {"workflow_dispatch"}
    inputs = wf["triggers"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation"}
    assert all(spec["required"] is True for spec in inputs.values())
    assert wf["permissions"] == {"contents": "read"}


def test_provision_job_requires_exact_confirmation_phrase() -> None:
    job = _workflow()["jobs"]["provision-d1"]
    assert job["if"] == "github.event.inputs.confirmation == 'PROVISION_B14_LEDGER_D1'"
    assert job["environment"] == "production"
    assert job["runs-on"] == "ubuntu-latest"


def test_premutation_assertions_are_fail_closed() -> None:
    text = _workflow_text()
    premutation = _step("Premutation exact-main and account assertions")["run"]
    assert "set -euo pipefail" in premutation
    assert re.search(
        r'test "\$\(git rev-parse HEAD\)" = "\$\{\{ github\.event\.inputs\.target_sha \}\}"',
        premutation,
    )
    assert re.search(
        r'test "\$\(git rev-parse origin/main\)" = "\$\{\{ github\.event\.inputs\.target_sha \}\}"',
        premutation,
    )
    assert "'9be14bb7b8974e65d0afba647ab16932'" in premutation
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in text
    assert "PREMUTATION_TARGET_ACCOUNT=PASS" in text


def test_database_must_already_exist_and_is_never_created() -> None:
    text = _workflow_text()
    assert "d1 list --json" in text
    assert "D1_DATABASE_PRESENT=YES" in text
    assert f"'{DATABASE_NAME}' in names" in text
    for forbidden in ("d1 create", "D1_CREATE=PASS", "D1_CREATE=SKIPPED_ALREADY_EXISTS"):
        assert forbidden not in text, f"the ledger gate must not create the database: {forbidden}"


def test_database_identifier_is_never_emitted() -> None:
    """Names only. The listing payload is read from a file that the step deletes,
    and the identifier itself is never indexed or echoed by this gate."""
    text = _workflow_text()
    assert "D1_DATABASE_ID=" not in text
    assert re.search(r"""\[['"][Uu]uid['"]\]|\.get\(['"][Uu]uid['"]\)""", text) is None
    config = WRANGLER.read_text(encoding="utf-8")
    database_id = re.search(r'database_id\s*=\s*"([^"]+)"', config)
    assert database_id, f"{BINDING} must stay declared in the wrangler config"
    assert database_id.group(1) not in text, "the gate must not hardcode the database identifier"
    assert "DATABASE_UUID_OUTPUT=0" in text


def test_secrets_reach_the_runner_only_as_env_and_never_inside_a_script() -> None:
    """A secret interpolated into a shell body could be echoed by `set -x` or a
    debugging echo; passed as an env value it stays out of the log."""
    text = _workflow_text()
    names = set(re.findall(r"secrets\.([A-Z0-9_]+)", text))
    assert names == {"CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"}, names
    for step in _steps():
        assert "secrets." not in str(step.get("run", "")), step.get("name")
        assert "set -x" not in str(step.get("run", "")), step.get("name")
    assert "SECRET_VALUE_OUTPUT=0" in text


def test_ledger_gate_runs_wrangler_from_the_b14_app_directory() -> None:
    """The migrations folder and the d1 binding both resolve relative to
    apps/korean-ai-platform, so every wrangler call must start there."""
    for step in _steps():
        run = str(step.get("run", ""))
        if "wrangler@4" in run:
            assert step.get("working-directory") == "apps/korean-ai-platform", step.get("name")


def test_migrations_apply_uses_the_wrangler_migrations_mechanism_once() -> None:
    text = _workflow_text()
    apply_cmd = f"d1 migrations apply {DATABASE_NAME} --remote"
    list_cmd = f"d1 migrations list {DATABASE_NAME} --remote"
    assert text.count(apply_cmd) == 1
    # Pre-apply and post-apply listings bracket the mutation, per the order.
    assert text.count(list_cmd) == 2
    assert text.index(list_cmd) < text.index(apply_cmd) < text.rindex(list_cmd)
    assert "D1_MIGRATIONS_LIST_PRE=PASS" in text
    assert "D1_MIGRATIONS_LIST_POST=PASS" in text
    # Ad-hoc file execution would bypass the migrations table entirely.
    assert "--file=" not in text


def test_migration_directory_is_read_dynamically() -> None:
    files = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
    assert files
    assert b14_schema.migration_names(MIGRATIONS) == files

    apply_run = _step("Apply ledger migrations to the remote database")["run"]
    final_run = _step("Final evidence")["run"]
    assert "b14_ledger_d1_schema.py --print-migrations" in apply_run
    assert "b14_ledger_d1_schema.py --print-migrations" in final_run
    assert "D1_MIGRATIONS=0001," not in _workflow_text()


def test_migrations_replay_to_the_handwritten_schema_contract() -> None:
    """The lists stay explicit here and must match the SQL replay result."""
    schema = b14_schema.schema_from_migrations(MIGRATIONS)
    assert schema["tables"] == EXPECTED_TABLE_COLUMNS
    assert schema["indexes"] == sorted(EXPECTED_INDEXES)


def test_credential_source_migration_is_one_guarded_alter() -> None:
    """0002 is the first file that mutates, so its shape is pinned here.

    It may add exactly one column, it may not touch the rows or the table 0001
    created, and the CHECK is what keeps the label a two-state category rather
    than free text a caller could write.
    """
    sql = CREDENTIAL_MIGRATION.read_text(encoding="utf-8")
    statements = [
        line.strip() for line in re.findall(
            r"(?m)^(?!--)\s*(ALTER|CREATE|DROP|UPDATE|DELETE|INSERT|PRAGMA)\b", sql
        )
    ]
    assert statements == ["ALTER"], statements
    assert "b14_model_call_attempt" not in sql
    assert re.search(
        r"ALTER TABLE b14_model_call ADD COLUMN credential_source TEXT NOT NULL"
        r" DEFAULT 'pool'\s*CHECK \(credential_source IN \('pool','user'\)\)",
        sql,
    ), sql


def test_ledger_migration_is_idempotent_ddl_only() -> None:
    sql = LEDGER_MIGRATION.read_text(encoding="utf-8")
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
    indexes = re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", sql)
    assert tables == ["b14_model_call", "b14_model_call_attempt"], tables
    assert len(indexes) == 7, indexes
    assert "CREATE TABLE " not in sql.replace("CREATE TABLE IF NOT EXISTS ", "")
    assert "CREATE INDEX " not in sql.replace("CREATE INDEX IF NOT EXISTS ", "")
    assert re.search(r"^\s*(ALTER|DROP|DELETE|UPDATE|INSERT)\b", sql, re.M) is None


def test_pc_metrics_migration_adds_only_two_nullable_columns_and_lookup_index() -> None:
    sql = PC_METRICS_MIGRATION.read_text(encoding="utf-8")
    assert re.findall(r"ALTER TABLE b14_model_call ADD COLUMN (\w+) TEXT;", sql) == [
        "pc_work_metrics_json", "pc_work_metrics_recorded_at",
    ]
    assert re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", sql) == ["b14_model_call_pc_turn"]
    assert re.search(r"^\s*(DROP|DELETE|UPDATE|INSERT|CREATE TABLE)\b", sql, re.M) is None


def test_gate_schema_readback_uses_the_migration_replay() -> None:
    readback = _step("Post-apply migrations list and schema readback")["run"]
    assert "b14_ledger_d1_schema.py" in readback
    assert "--remote-columns" in readback and "--remote-indexes" in readback
    assert "DECLARED_INDEXES" not in _workflow_text()


def test_schema_evidence_is_derived_from_replayed_sql(capsys) -> None:
    schema = b14_schema.schema_from_migrations(MIGRATIONS)
    assert len(schema["indexes"]) == len(EXPECTED_INDEXES)

    b14_schema._report_schema(schema)
    output = capsys.readouterr().out
    assert "B14_LEDGER_SCHEMA_ASSERT=PASS" in output
    assert "B14_LEDGER_TABLE_ASSERT=PASS" in output
    assert "B14_LEDGER_TABLES=" + ",".join(schema["tables"]) in output
    expected_counts = ",".join(
        f"{table}:{len(columns)}" for table, columns in schema["tables"].items()
    )
    assert f"B14_LEDGER_COLUMNS={expected_counts}" in output
    assert "B14_LEDGER_INDEX_ASSERT=PASS" in output
    assert f"B14_LEDGER_INDEXES={len(schema['indexes'])}" in output
    assert re.search(r"B14_LEDGER_COLUMNS=\d+,\d+", _workflow_text()) is None
    assert re.search(r"B14_LEDGER_INDEXES=\d+", _workflow_text()) is None


def test_remote_readback_is_schema_names_only() -> None:
    """Content-blind contract: the gate reads schema *names*, never rows and
    never values, so a ledger that later holds request data stays unread."""
    commands = re.findall(r'--command "([^"]*)"', _workflow_text())
    assert len(commands) == 2, commands
    assert "JOIN pragma_table_info(m.name)" in commands[0]
    assert "SELECT m.name AS table_name, p.name AS column_name" in commands[0]
    assert "d1_migrations" in commands[0]
    assert "SELECT name FROM sqlite_master WHERE type = 'index'" in commands[1]
    for sql in commands:
        assert "*" not in sql
    joined = " ".join(commands).lower()
    for forbidden in ("select *", "count(", " limit ", "estimated_usd", "subject_ref", "hex("):
        assert forbidden not in joined, forbidden


def test_remote_schema_queries_compare_only_names_from_the_migration_schema() -> None:
    commands = re.findall(r'--command "([^"]*)"', _workflow_text())
    db = sqlite3.connect(":memory:")
    try:
        db.execute("PRAGMA foreign_keys = ON")
        for migration in b14_schema.migration_files(MIGRATIONS):
            db.executescript(migration.read_text(encoding="utf-8"))
        db.execute("CREATE TABLE d1_migrations (id INTEGER PRIMARY KEY, name TEXT)")

        columns_cursor = db.execute(commands[0])
        columns = [
            dict(zip((item[0] for item in columns_cursor.description), row))
            for row in columns_cursor.fetchall()
        ]
        indexes_cursor = db.execute(commands[1])
        indexes = [
            dict(zip((item[0] for item in indexes_cursor.description), row))
            for row in indexes_cursor.fetchall()
        ]
    finally:
        db.close()

    with tempfile.TemporaryDirectory(dir=ROOT / ".github" / "tests") as temp_dir:
        temp_root = Path(temp_dir)
        columns_path = temp_root / "columns.json"
        indexes_path = temp_root / "indexes.json"
        columns_path.write_text(json.dumps([{"results": columns}]), encoding="utf-8")
        indexes_path.write_text(json.dumps([{"results": indexes}]), encoding="utf-8")
        verified = b14_schema.verify_remote_schema(columns_path, indexes_path)
        assert verified["tables"] == EXPECTED_TABLE_COLUMNS
        assert verified["indexes"] == sorted(EXPECTED_INDEXES)

        columns.pop()
        columns_path.write_text(json.dumps([{"results": columns}]), encoding="utf-8")
        with pytest.raises(b14_schema.SchemaError, match="B14_REMOTE_TABLE_COLUMN_MISMATCH"):
            b14_schema.verify_remote_schema(columns_path, indexes_path)


def test_d1_internal_objects_are_excluded_from_readback_and_comparison() -> None:
    commands = re.findall(r'--command "([^"]*)"', _workflow_text())
    db = sqlite3.connect(":memory:")
    try:
        for migration in b14_schema.migration_files(MIGRATIONS):
            db.executescript(migration.read_text(encoding="utf-8"))
        db.execute('CREATE TABLE "_cf_KV" (key TEXT)')
        db.execute('CREATE INDEX "_cf_internal_index" ON "_cf_KV" (key)')
        db.execute('CREATE INDEX "user_named_internal_index" ON "_cf_KV" (key)')
        db.execute('CREATE TABLE "_cfXordinary" (value TEXT)')
        seen_pragmas = []

        def authorize(action, name, argument, _database, _source):
            if action == sqlite3.SQLITE_PRAGMA and name == "table_info":
                seen_pragmas.append(argument)
                if argument == "_cf_KV":
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db.set_authorizer(authorize)
        columns = db.execute(commands[0]).fetchall()
        indexes = db.execute(commands[1]).fetchall()
        assert "_cf_KV" not in seen_pragmas
        assert "_cfXordinary" in seen_pragmas
        assert ("_cf_KV", "key") not in columns
        assert ("_cfXordinary", "value") in columns
        assert ("_cf_internal_index",) not in indexes
        assert ("user_named_internal_index",) not in indexes
    finally:
        db.close()

    expected = b14_schema.schema_from_migrations()
    column_rows = [
        {"table_name": table, "column_name": column}
        for table, columns in expected["tables"].items() for column in columns
    ]
    column_rows.append({"table_name": "_cf_KV", "column_name": "key"})
    index_rows = [{"name": name} for name in expected["indexes"]]
    index_rows.append({"name": "_cf_internal_index"})
    with tempfile.TemporaryDirectory(dir=ROOT / ".github" / "tests") as temp_dir:
        columns_path = Path(temp_dir) / "columns.json"
        indexes_path = Path(temp_dir) / "indexes.json"
        columns_path.write_text(json.dumps([{"results": column_rows}]), encoding="utf-8")
        indexes_path.write_text(json.dumps([{"results": index_rows}]), encoding="utf-8")
        assert b14_schema.verify_remote_schema(columns_path, indexes_path) == expected
        column_rows.append({"table_name": "_cfXordinary", "column_name": "value"})
        columns_path.write_text(json.dumps([{"results": column_rows}]), encoding="utf-8")
        with pytest.raises(b14_schema.SchemaError, match="B14_REMOTE_TABLE_COLUMN_MISMATCH"):
            b14_schema.verify_remote_schema(columns_path, indexes_path)


def test_binding_still_targets_the_canonical_ledger_database() -> None:
    """The gate is only meaningful while wrangler routes the ledger binding at
    the same database it provisions."""
    config = WRANGLER.read_text(encoding="utf-8")
    block = config[config.index(f'binding = "{BINDING}"') :]
    head = block[: block.find("[[")]
    assert f'database_name = "{DATABASE_NAME}"' in head


def test_final_evidence_markers_present() -> None:
    text = _workflow_text()
    for marker in (
        "B14_LEDGER_D1_PROVISION=PASS",
        "D1_PROVISION_TARGET=padiem-b14-call-ledger",
        "D1_DATABASE_CREATED=0",
        "WORKER_DEPLOYED=0",
        "WRANGLER_TOML_MODIFIED=0",
    ):
        assert marker in text, marker
    # The dynamic inventory is emitted before and after migration application.
    assert text.count("b14_ledger_d1_schema.py --print-migrations") == 2
    assert "D1_MIGRATIONS=0001," not in text


def test_workflow_never_deploys_worker_or_edits_config() -> None:
    text = _workflow_text()
    for forbidden in (
        "wrangler deploy",
        "wrangler@4 deploy",
        "wrangler@4 pages deploy",
        "cloudflare/pages-action",
        "[[d1_databases]]",
        "secret put",
        "secret bulk",
        "secrets-store",
    ):
        assert forbidden not in text, f"provision gate must not contain: {forbidden}"
    # Scoped to executable content: the header comment legitimately names the
    # config file it is pinned against, which is not the same act as editing it.
    for step in _steps():
        run = str(step.get("run", ""))
        for forbidden in ("wrangler.toml", "sed -i", "cat >", "tee "):
            assert forbidden not in run, f"{step.get('name')} must not rewrite: {forbidden}"
