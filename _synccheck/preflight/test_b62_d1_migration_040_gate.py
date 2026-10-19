"""#4522: contract tests for the additive 040 receipt-release schema gate.

The exact fixture is built by executing the REAL migrations 031 and 040 in an
in-memory SQLite database, so the classifier is tested against the schema the
migrations actually produce (including SQLite's post-``ALTER TABLE`` table text)
rather than a hand-copied expectation.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-claw-d1-migration-040-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_040_schema.py"
MIGRATION_031 = ROOT / "apps/padiem-chat/migrations/031_claw_web_xlsx_p01_decision_receipts.sql"
MIGRATION_040 = ROOT / "apps/padiem-chat/migrations/040_claw_web_xlsx_p01_decision_release.sql"
TABLE = "claw_web_xlsx_p01_decision_receipts"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_040", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _live_schema(*, apply_040: bool):
    """Execute the real migrations and read back schema metadata only."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATION_031.read_text(encoding="utf-8"))
    if apply_040:
        conn.executescript(MIGRATION_040.read_text(encoding="utf-8"))
    objects = [
        {"name": row[0], "type": row[1], "sql": row[2]}
        for row in conn.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE name = ?", (TABLE,)
        )
    ]
    columns = [
        {
            "name": row[1], "type": row[2], "notnull": row[3],
            "dflt_value": row[4], "pk": row[5],
        }
        for row in conn.execute(f"PRAGMA table_info({TABLE})")
    ]
    conn.close()
    return {"success": True, "result": [_result(objects), _result(columns)]}


def _empty():
    return {"success": True, "result": [_result([]), _result([])]}


def test_real_migration_schema_classifies_exact_and_pre_040() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_live_schema(apply_040=True)) == "exact"
    assert helper.classify_schema(_live_schema(apply_040=False)) == "pre_040"


def test_absent_table_is_missing_not_pre_040() -> None:
    helper = _load_helper()
    assert helper.classify_schema(_empty()) == "missing"


def test_wrong_shape_is_drift() -> None:
    helper = _load_helper()

    def mutate(mutator):
        payload = _live_schema(apply_040=True)
        mutator(payload)
        return payload

    # A non-table object with the expected name.
    def wrong_type(payload):
        payload["result"][0]["results"][0]["type"] = "view"
    assert helper.classify_schema(mutate(wrong_type)) == "drift"

    # released_at present but declared as a non-TEXT type.
    def wrong_column_type(payload):
        for row in payload["result"][1]["results"]:
            if row["name"] == "released_at":
                row["type"] = "INTEGER"
    assert helper.classify_schema(mutate(wrong_column_type)) == "drift"

    # released_at present but NOT NULL: not the additive 040 shape.
    def wrong_nullability(payload):
        for row in payload["result"][1]["results"]:
            if row["name"] == "released_at":
                row["notnull"] = 1
    assert helper.classify_schema(mutate(wrong_nullability)) == "drift"

    # An unexpected extra column.
    def extra_column(payload):
        payload["result"][1]["results"].append(
            {"name": "extra", "type": "TEXT", "notnull": 0, "dflt_value": None, "pk": 0}
        )
    assert helper.classify_schema(mutate(extra_column)) == "drift"

    # released_at redefined inside the table body instead of added by 040.
    def redefined_table(payload):
        payload["result"][0]["results"][0]["sql"] = (
            payload["result"][0]["results"][0]["sql"]
            .replace(
                "updated_at TEXT NOT NULL, released_at TEXT,",
                "released_at TEXT, updated_at TEXT NOT NULL,",
                1,
            )
        )
    assert helper.classify_schema(mutate(redefined_table)) == "drift"

    # The 031 CHECK/FK authority is missing.
    def weakened_constraint(payload):
        payload["result"][0]["results"][0]["sql"] = payload["result"][0]["results"][0]["sql"].replace(
            "state TEXT NOT NULL CHECK(state IN ('dispatching','denied','confirmed'))",
            "state TEXT NOT NULL",
        )
    assert helper.classify_schema(mutate(weakened_constraint)) == "drift"


def test_malformed_evidence_fails_closed() -> None:
    helper = _load_helper()
    for payload in (
        {"success": False, "result": []},
        {"success": True, "result": []},
        {"success": True, "result": [_result([])]},
        {"success": True, "result": [{"success": False, "results": []}, _result([])]},
    ):
        try:
            helper.classify_schema(payload)
        except helper.SchemaEvidenceError:
            continue
        raise AssertionError(f"malformed evidence accepted: {payload!r}")


def test_migration_040_is_additive_and_bounded() -> None:
    migration = MIGRATION_040.read_text(encoding="utf-8")
    statements = [
        line.strip() for line in migration.splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    assert statements == [
        f"ALTER TABLE {TABLE} ADD COLUMN released_at TEXT;"
    ]
    upper = migration.upper()
    for token in ("DROP TABLE", "DROP INDEX", "DELETE FROM", "UPDATE ", "INSERT INTO"):
        assert token not in upper


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_CLAW_D1_MIGRATION_040_FROM_EXACT_MAIN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "apps/padiem-chat/migrations/040_claw_web_xlsx_p01_decision_release.sql" in workflow
    assert "B62_D1_MIGRATION_040_POST_READBACK=PASS" in workflow
    # Race-hardening: readonly DB identity is compared at the mutation boundary.
    assert 'db_fingerprint: ${{ steps.binding.outputs.db_fingerprint }}' in workflow
    assert 'READONLY_DB_FINGERPRINT: ${{ needs.cloudflare-readonly.outputs.db_fingerprint }}' in workflow
    assert 'D1_BINDING_CHANGED_AFTER_READONLY=STOP' in workflow
    assert 'D1_BINDING_IDENTITY_STABLE=PASS' in workflow
    assert 'D1_PREMUTATION_SCHEMA_DRIFT=STOP' in workflow
    assert 'D1_SCHEMA_PREMUTATION_RECHECK=PASS' in workflow
    assert "PREMUTATION_SCHEMA_STATE=${now}" in workflow
    assert "if: ${{ env.PREMUTATION_SCHEMA_STATE == 'pre_040' }}" in workflow
    assert "if: ${{ env.PREMUTATION_SCHEMA_STATE == 'exact' }}" in workflow
    # The runtime application payload must be the single reviewed SQL statement.
    assert 'if statements != [statement]:' in workflow
    assert 'migration 040 is not exactly one reviewed additive statement' in workflow
    recheck = workflow.index('      - name: Recheck identical D1 and schema immediately before SQL mutation')
    application = workflow.index('      - name: Apply only the additive migration 040 when absent')
    assert recheck < application
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "MIGRATION_031_NOT_APPLIED" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_DATA_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    assert "b62_d1_migration_040_schema.py" in workflow
    assert "PRAGMA table_info(claw_web_xlsx_p01_decision_receipts)" in workflow

    forbidden = (
        "wrangler d1 create",
        "d1 migrations apply",
        "pywrangler deploy",
        "wrangler deploy",
        "DROP TABLE",
        "DROP INDEX",
        "DELETE FROM",
    )
    for token in forbidden:
        assert token not in workflow

    # The mutation path must be dispatch-only; PRs run source-contract only.
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_040'"
        in workflow
    )


def test_production_deploy_gate_requires_040_before_upload() -> None:
    deploy = (
        ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
    ).read_text(encoding="utf-8")
    assert "B62_D1_MIGRATION_040_SCHEMA=EXACT" in deploy
    assert "MIGRATION_040_PREDEPLOY=EXACT" in deploy
    assert "RELEASED_AT_PRESENT=PASS" in deploy
    assert "b62_d1_migration_040_schema.py" in deploy
    assert "PRAGMA table_info(claw_web_xlsx_p01_decision_receipts)" in deploy
    # The schema probe must be a real step that precedes the upload/activate
    # mutation step, not just an assertion string inside the source contract.
    # Match the 6-space step indentation so the quoted reference inside the
    # source-contract script does not shadow the real step.
    probe = deploy.index(
        "\n      - name: Prove migration 040 receipt schema live state before deploy"
    )
    mutation = deploy.index(
        "\n      - name: Deploy production code preserving the full binding set"
    )
    assert probe < mutation
    # The probe must hard-refuse a non-exact live schema before the mutation.
    probe_step = deploy[probe:mutation]
    assert "grep -q '^B62_D1_MIGRATION_040_SCHEMA=EXACT$'" in probe_step
    assert "APPLICATION_ROW_READ=0" in probe_step
    assert "D1_IDENTIFIER_OUTPUT=0" in probe_step
    assert "PRODUCTION_MUTATION=0" in probe_step


def test_workflow_records_d1_recovery_bookmark_before_mutation() -> None:
    """#4522 CENTRAL step 1: a production schema write needs a recorded recovery point.

    The reviewed 037 precedent (b66-admin-d1-migration-037-gate) obtains a D1
    Time Travel bookmark before its ALTER and fails closed when unavailable.
    The 040 gate must do the same, in both the read-only proof and immediately
    before the single mutation.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "/time_travel/bookmark" in workflow
    assert "D1_RECOVERY_BOOKMARK_UNAVAILABLE" in workflow
    assert "D1_RECOVERY_BOOKMARK_PRESENT=PASS" in workflow
    assert "B62_D1_MIGRATION_040_PREAPPLY_RECOVERY_BOOKMARK=" in workflow
    # The bookmark must be read from the same canonical Worker-bound database.
    assert workflow.count("/d1/database/${DB_ID}/time_travel/bookmark") == 2
    # A recovery handle is recorded, never auto-applied: Time Travel restores
    # the entire database, so no automatic restore may run from this gate.
    assert "time_travel/restore" not in workflow
    assert "time_travel/info" not in workflow
    # The bookmark is read after the D1 binding is resolved (so it names the
    # same database) and the pre-mutation handle precedes the ALTER.
    resolve = workflow.index(
        "      - name: Resolve live PADIEM_CHAT_DB binding without emitting identifiers"
    )
    readonly_recovery = workflow.index(
        "      - name: Read only D1 Time Travel recovery availability"
    )
    recheck = workflow.index(
        "      - name: Recheck identical D1 and schema immediately before SQL mutation"
    )
    preapply = workflow.index(
        "      - name: Record D1 Time Travel recovery bookmark immediately before SQL mutation"
    )
    application = workflow.index(
        "      - name: Apply only the additive migration 040 when absent"
    )
    assert resolve < readonly_recovery
    assert recheck < preapply < application
    # Fail-closed bookmark validation must require the API success/result shape.
    assert "payload.get('success') is True else None" in workflow
    assert "[A-Za-z0-9_-]{12,130}" in workflow


if __name__ == "__main__":
    test_real_migration_schema_classifies_exact_and_pre_040()
    test_absent_table_is_missing_not_pre_040()
    test_wrong_shape_is_drift()
    test_malformed_evidence_fails_closed()
    test_migration_040_is_additive_and_bounded()
    test_workflow_is_exact_main_and_migration_specific()
    test_production_deploy_gate_requires_040_before_upload()
    print("B62_D1_MIGRATION_040_GATE_TESTS=PASS")
