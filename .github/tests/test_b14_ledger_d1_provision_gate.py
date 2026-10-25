"""Contract tests for the B14 ledger D1 provision gate workflow.

Proves statically that the gate:
  1. is dispatch-only (a pull request can never trigger provisioning);
  2. requires the exact confirmation phrase and the production environment;
  3. carries exact-SHA + account premutation assertions, fail-closed;
  4. refuses when the ledger database is absent — it never creates one, and it
     never emits the database identifier or any secret value;
  5. applies through wrangler's migrations mechanism from the B14 app directory;
  6. verifies the applied shape by readback: 42/27 columns and the 7 indexes the
     migration itself declares, schema names only, never row content;
  7. never deploys the worker and never edits wrangler.toml.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b14-ledger-d1-provision-gate.yml"
APP_DIR = ROOT / "apps" / "korean-ai-platform"
WRANGLER = APP_DIR / "wrangler.toml"
MIGRATIONS = APP_DIR / "migrations"
LEDGER_MIGRATION = MIGRATIONS / "0001_b14_model_call_ledger.sql"
DATABASE_NAME = "padiem-b14-call-ledger"
BINDING = "B14_CALL_LEDGER_D1"


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


def test_migration_directory_holds_exactly_the_ledger_migration() -> None:
    files = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
    assert files == ["0001_b14_model_call_ledger.sql"], (
        f"a new migration changes what `migrations apply` mutates; update the "
        f"gate and this pin together: {files}"
    )


def test_ledger_migration_is_idempotent_ddl_only() -> None:
    sql = LEDGER_MIGRATION.read_text(encoding="utf-8")
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
    indexes = re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", sql)
    assert tables == ["b14_model_call", "b14_model_call_attempt"], tables
    assert len(indexes) == 7, indexes
    assert "CREATE TABLE " not in sql.replace("CREATE TABLE IF NOT EXISTS ", "")
    assert "CREATE INDEX " not in sql.replace("CREATE INDEX IF NOT EXISTS ", "")
    assert re.search(r"^\s*(ALTER|DROP|DELETE|UPDATE|INSERT)\b", sql, re.M) is None


def test_gate_index_readback_matches_the_migration_declares_them() -> None:
    """Drift guard: the set the gate asserts against the remote must be exactly
    the set the migration creates, read from the migration itself."""
    sql = LEDGER_MIGRATION.read_text(encoding="utf-8")
    declared = set(re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", sql))
    block = re.search(r"DECLARED_INDEXES = \{(.*?)\}", _workflow_text(), re.S)
    assert block, "the gate must pin the declared index set"
    pinned = set(re.findall(r"'(\w+)'", block.group(1)))
    assert pinned == declared, f"gate pins {sorted(pinned)} but SQL creates {sorted(declared)}"
    assert len(pinned) == 7


def test_schema_readback_asserts_the_expected_column_shape() -> None:
    text = _workflow_text()
    assert "assert len(call) == 42" in text
    assert "assert len(attempt) == 27" in text
    assert "assert len(declared) == 7" in text
    assert "not name.startswith('sqlite_autoindex')" in text
    # The apply-readback step and the final evidence step must both carry the
    # numbers: a stale marker in either place would misreport what was verified.
    assert text.count("B14_LEDGER_COLUMNS=42,27") == 2
    assert text.count("B14_LEDGER_INDEXES=7") == 2
    assert "B14_LEDGER_COLUMN_ASSERT=PASS" in text
    assert "B14_LEDGER_INDEX_ASSERT=PASS" in text


def test_remote_readback_is_schema_names_only() -> None:
    """Content-blind contract: the gate reads schema *names*, never rows and
    never values, so a ledger that later holds request data stays unread."""
    commands = re.findall(r'--command "([^"]*)"', _workflow_text())
    assert len(commands) == 3, commands
    for sql in commands:
        assert re.match(r"^(PRAGMA table_info\(|SELECT name FROM sqlite_master WHERE type='index'$)", sql), sql
        assert "*" not in sql
    joined = " ".join(commands).lower()
    for forbidden in ("select *", "count(", " limit ", "estimated_usd", "subject_ref", "hex("):
        assert forbidden not in joined, forbidden


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
        "D1_MIGRATIONS=0001",
        "D1_MIGRATION_0001=APPLIED_OR_REPLAY_SAFE",
        "D1_DATABASE_CREATED=0",
        "WORKER_DEPLOYED=0",
        "WRANGLER_TOML_MODIFIED=0",
    ):
        assert marker in text, marker
    # Markers that must survive in exactly the two places they belong.
    assert text.count("D1_MIGRATIONS=0001") == 2


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
