"""B62 D1 migration 060 gate: source-only contract tests, never contact Cloudflare."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"
HELPER = SCRIPTS / "b62_d1_migration_060_schema.py"
WORKFLOW = ROOT / ".github/workflows/b62-d1-migration-060-gate.yml"
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"
RELEASE = MIGRATIONS / "060_byte_length_capacity_ceiling_release.sql"
SOURCE_008 = MIGRATIONS / "008_claw_document_metadata.sql"
SOURCE_027 = MIGRATIONS / "027_b66_template_source.sql"
SOURCE_026 = MIGRATIONS / "026_claw_conversation_artifact_index.sql"

TABLES = (
    "claw_document_metadata",
    "claw_conversation_artifact_index",
    "b66_template_source",
)


def _load_helper():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("b62_d1_060", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(helper, *, with_release: bool) -> dict:
    con = helper.replay_connection(with_release=with_release)
    try:
        return helper.schema_payload(con)
    finally:
        con.close()


def _counts_payload(*values: int) -> dict:
    return {
        "success": True,
        "result": [
            {"success": True, "results": [{"n": value}]} for value in values
        ],
    }


def _fk_payload(*rows_per_table: int) -> dict:
    rows = []
    for table, count in zip(TABLES, rows_per_table):
        for index in range(count):
            rows.append({"table": table, "rowid": index, "parent": "users", "fkid": 0})
    return {"success": True, "result": [{"success": True, "results": rows}]}


def test_source_contract_holds_for_the_merged_sources() -> None:
    helper = _load_helper()
    result = helper.source_contract()
    assert result["tables"] == list(TABLES)
    # The applied SQL is the reviewed file, not a hand-written statement.
    assert helper._sha256(RELEASE) == helper.PINNED_SHA256[RELEASE.name]
    assert helper._sha256(SOURCE_008) == helper.PINNED_SHA256[SOURCE_008.name]
    assert helper._sha256(SOURCE_027) == helper.PINNED_SHA256[SOURCE_027.name]
    # The released migrations keep their ceiling; 060 is the only release.
    assert "10485760" in SOURCE_008.read_text(encoding="utf-8")
    assert "10485760" in SOURCE_027.read_text(encoding="utf-8")
    assert "10485760" in SOURCE_026.read_text(encoding="utf-8")
    assert "10485760" not in RELEASE.read_text(encoding="utf-8")


def test_source_contract_refuses_an_unreviewed_migration() -> None:
    helper = _load_helper()
    pinned = dict(helper.PINNED_SHA256)
    helper.PINNED_SHA256[RELEASE.name] = "0" * 64
    try:
        helper.source_contract()
    except helper.GateError:
        pass
    else:
        raise AssertionError("an unreviewed 060 source must be refused")
    finally:
        helper.PINNED_SHA256.clear()
        helper.PINNED_SHA256.update(pinned)


def test_classifier_accepts_only_the_two_legal_live_shapes() -> None:
    helper = _load_helper()
    assert helper.classify(_payload(helper, with_release=False)) == "pre_060"
    assert helper.classify(_payload(helper, with_release=True)) == "exact"


def test_classifier_reports_missing_when_the_prerequisites_are_absent() -> None:
    helper = _load_helper()
    con = sqlite3.connect(":memory:")
    try:
        assert helper.classify(helper.schema_payload(con)) == "missing"
    finally:
        con.close()


def test_the_absent_tables_are_named_so_the_next_step_is_unambiguous() -> None:
    helper = _load_helper()
    con = sqlite3.connect(":memory:")
    try:
        payload = helper.schema_payload(con)
        states = helper.table_states(payload)
        assert states == {table: "missing" for table in TABLES}
        assert helper.missing_tables(payload) == list(TABLES)
    finally:
        con.close()

    present = _payload(helper, with_release=False)
    assert helper.missing_tables(present) == []
    assert set(helper.table_states(present).values()) == {"pre_060"}


def test_counting_rows_in_an_absent_table_is_a_sql_error() -> None:
    """The HTTP 400 of the readonly gate, reproduced offline.

    The D1 API answers a SQL error with HTTP 400, so a row count against a
    table that is not there fails the whole read. The gate must learn which
    tables are absent before it reads any row count.
    """
    helper = _load_helper()
    con = sqlite3.connect(":memory:")
    try:
        with pytest.raises(sqlite3.OperationalError) as caught:
            con.execute(
                "SELECT COUNT(*) AS n FROM claw_document_metadata"
            ).fetchall()
        assert "no such table" in str(caught.value)
        # The gate's own count query is the statement that failed live.
        assert helper.COUNTS_STATEMENTS[0].startswith(
            "SELECT COUNT(*) AS n FROM claw_document_metadata"
        )
    finally:
        con.close()


def test_the_row_count_read_never_runs_against_absent_tables() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # The row count read is skipped when the prerequisite tables are absent,
    # because a SQL error there is the HTTP 400 that stopped the readonly gate.
    assert (
        "if: ${{ steps.schema.outputs.schema_state != 'missing' }}"
        in workflow
    )
    assert "Report the absent prerequisite tables instead of counting rows" in workflow
    assert "B62_D1_MIGRATION_060_ROW_COUNTS_READ=SKIPPED_TABLES_ABSENT" in workflow
    assert "missing-tables" in workflow
    # The absent tables are named by the reviewed script, not by the workflow.
    helper_source = HELPER.read_text(encoding="utf-8")
    assert "B62_D1_MIGRATION_060_MISSING_TABLES=" in helper_source
    assert "def missing_tables(" in helper_source
    # The mutation path still refuses an absent prerequisite set.
    assert "prerequisite tables are not in place" in workflow


def test_classifier_refuses_a_partially_released_schema() -> None:
    helper = _load_helper()
    con = helper.replay_connection(with_release=True)
    try:
        con.execute("DROP TABLE claw_document_metadata")
        con.executescript(SOURCE_008.read_text(encoding="utf-8"))
        assert helper.classify(helper.schema_payload(con)) == "drift"
    finally:
        con.close()


def test_classifier_refuses_a_changed_shape() -> None:
    helper = _load_helper()
    base = _payload(helper, with_release=False)

    changed_ceiling = json.loads(json.dumps(base))
    for row in changed_ceiling["result"][0]["results"]:
        if row.get("name") == "claw_document_metadata":
            row["sql"] = row["sql"].replace("10485760", "20971520")
    assert helper.classify(changed_ceiling) == "drift"

    dropped_column = json.loads(json.dumps(base))
    dropped_column["result"][1]["results"] = [
        row
        for row in dropped_column["result"][1]["results"]
        if row.get("name") != "filename"
    ]
    assert helper.classify(dropped_column) == "drift"

    missing_index = json.loads(json.dumps(base))
    missing_index["result"][0]["results"] = [
        row
        for row in missing_index["result"][0]["results"]
        if row.get("name") != "idx_claw_document_metadata_tenant_active"
    ]
    assert helper.classify(missing_index) == "drift"

    missing_fk = json.loads(json.dumps(base))
    missing_fk["result"][6]["results"] = [
        row
        for row in missing_fk["result"][6]["results"]
        if row.get("table") != "users"
    ]
    assert helper.classify(missing_fk) == "drift"


def test_classifier_refuses_malformed_evidence() -> None:
    helper = _load_helper()
    base = _payload(helper, with_release=False)
    failed = json.loads(json.dumps(base))
    failed["result"][0]["success"] = False
    try:
        helper.classify(failed)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a failed D1 statement must be refused")

    truncated = json.loads(json.dumps(base))
    truncated["result"] = truncated["result"][:3]
    try:
        helper.classify(truncated)
    except helper.GateError:
        pass
    else:
        raise AssertionError("an incomplete D1 response must be refused")


def test_count_and_foreign_key_guards_refuse_regressions() -> None:
    helper = _load_helper()
    assert helper.check_counts(_counts_payload(3, 3, 3), _counts_payload(3, 3, 3)) == {
        "claw_document_metadata": 0,
        "claw_conversation_artifact_index": 0,
        "b66_template_source": 0,
    }
    assert helper.check_counts(_counts_payload(3, 3, 3), _counts_payload(4, 3, 3))[
        "claw_document_metadata"
    ] == 1
    try:
        helper.check_counts(_counts_payload(3, 3, 3), _counts_payload(2, 3, 3))
    except helper.GateError:
        pass
    else:
        raise AssertionError("a lost row must be refused")

    assert helper.check_fk(_fk_payload(0, 0, 0), _fk_payload(0, 0, 0)) == {
        "claw_document_metadata": 0,
        "claw_conversation_artifact_index": 0,
        "b66_template_source": 0,
    }
    try:
        helper.check_fk(_fk_payload(0, 0, 0), _fk_payload(1, 0, 0))
    except helper.GateError:
        pass
    else:
        raise AssertionError("a new foreign key violation must be refused")


def test_foreign_key_evidence_must_be_readable() -> None:
    helper = _load_helper()
    malformed = {
        "success": True,
        "result": [{"success": True, "results": [{"unexpected": "column"}]}],
    }
    try:
        helper.classify_fk(malformed)
    except helper.GateError:
        pass
    else:
        raise AssertionError("malformed foreign key evidence must be refused")


def test_apply_payload_is_the_reviewed_migration_file() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "apply.json"
        assert helper.main(["apply", str(target)]) == 0
        payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"sql": RELEASE.read_text(encoding="utf-8")}


def test_offline_contract_reports_no_production_mutation() -> None:
    helper = _load_helper()
    assert helper.main(["offline"]) == 0


def test_rebuild_scope_refuses_a_drop_before_copy_order() -> None:
    helper = _load_helper()
    sql = RELEASE.read_text(encoding="utf-8")
    insert_start = sql.index("INSERT INTO claw_document_metadata_next")
    insert_end = sql.index(
        "FROM claw_document_metadata;", insert_start
    ) + len("FROM claw_document_metadata;")
    drop_start = sql.index("DROP TABLE claw_document_metadata;")
    drop_end = drop_start + len("DROP TABLE claw_document_metadata;")
    broken = (
        sql[:insert_start]
        + sql[drop_start:drop_end]
        + "\n\n"
        + sql[insert_start:insert_end]
        + sql[drop_end:]
    )
    try:
        helper._rebuild_scope(broken)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a drop-before-copy order must be refused")


def test_rebuild_scope_refuses_a_table_outside_the_reviewed_scope() -> None:
    helper = _load_helper()
    broken = (
        RELEASE.read_text(encoding="utf-8")
        + "\nCREATE TABLE IF NOT EXISTS unrelated_table (id TEXT);\n"
    )
    try:
        helper._rebuild_scope(broken)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a table outside the reviewed scope must be refused")


def test_workflow_is_exact_main_single_migration_and_fail_closed() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helper_source = HELPER.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_D1_MIGRATION_060_FROM_EXACT_MAIN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "padiem-chat" in workflow
    assert "060_byte_length_capacity_ceiling_release.sql" in workflow
    assert "B62_D1_MIGRATION_060_POST_APPLY=EXACT" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "B62_D1_MIGRATION_060_ROW_COUNTS_PRESERVED=PASS" in helper_source
    assert "B62_D1_MIGRATION_060_FOREIGN_KEYS=PASS" in helper_source
    assert "check-counts" in workflow
    assert "check-fk" in workflow
    assert "prerequisite tables are not in place" in workflow
    assert "is not the reviewed shape" in workflow
    # The apply branch admits only the two reviewed states, and the readback
    # must prove the released shape before the run is allowed to finish.
    assert "pre_060|exact) ;;" in workflow
    assert "grep -qx 'B62_D1_MIGRATION_060_SCHEMA=EXACT'" in workflow
    assert "test \"${state}\" = \"${READONLY_SCHEMA_STATE}\"" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_CONTENT_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    assert "D1_BINDING_IDENTITY_STABLE=PASS" in workflow
    assert "PREMUTATION_SCHEMA_STATE_STABLE=PASS" in workflow
    assert "D1_RECOVERY_AVAILABLE=PASS" in workflow

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

    # The mutation path must be dispatch-only; pull requests run source-contract.
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_060'"
        in workflow
    )
    assert "if: ${{ env.READONLY_SCHEMA_STATE == 'pre_060' }}" in workflow
    assert "if: ${{ env.READONLY_SCHEMA_STATE == 'exact' }}" in workflow


if __name__ == "__main__":
    test_source_contract_holds_for_the_merged_sources()
    test_source_contract_refuses_an_unreviewed_migration()
    test_classifier_accepts_only_the_two_legal_live_shapes()
    test_classifier_reports_missing_when_the_prerequisites_are_absent()
    test_the_absent_tables_are_named_so_the_next_step_is_unambiguous()
    test_counting_rows_in_an_absent_table_is_a_sql_error()
    test_the_row_count_read_never_runs_against_absent_tables()
    test_classifier_refuses_a_partially_released_schema()
    test_classifier_refuses_a_changed_shape()
    test_classifier_refuses_malformed_evidence()
    test_count_and_foreign_key_guards_refuse_regressions()
    test_foreign_key_evidence_must_be_readable()
    test_apply_payload_is_the_reviewed_migration_file()
    test_offline_contract_reports_no_production_mutation()
    test_rebuild_scope_refuses_a_drop_before_copy_order()
    test_rebuild_scope_refuses_a_table_outside_the_reviewed_scope()
    test_workflow_is_exact_main_single_migration_and_fail_closed()
    print("B62_D1_MIGRATION_060_GATE_TESTS=PASS")
