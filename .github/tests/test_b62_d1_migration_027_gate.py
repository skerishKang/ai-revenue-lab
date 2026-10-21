"""B62 B66 D1 migration 027 gate: source-only contract tests, never contact Cloudflare.

027 is the one table the byte-ceiling release chain still needs in the live
database. 060 rebuilds b66_template_source, so 060 cannot be applied before
027 is. These tests pin the reviewed source, the three legal live states and
the fail-closed workflow that applies it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"
HELPER = SCRIPTS / "b62_d1_migration_027_schema.py"
HELPER_060 = SCRIPTS / "b62_d1_migration_060_schema.py"
WORKFLOW = ROOT / ".github/workflows/b62-b66-d1-migration-027-gate.yml"
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"
RELEASE = MIGRATIONS / "027_b66_template_source.sql"

TABLE = "b66_template_source"
INDEX = "idx_b66_template_source_owner_workspace_status"


def _load(path: Path, name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_helper():
    return _load(HELPER, "b62_d1_027")


def _payload(helper, *, with_release: bool) -> dict:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("PRAGMA foreign_keys=ON")
        for name in helper.PREREQUISITE_MIGRATIONS:
            con.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
        if with_release:
            con.executescript(helper.assert_approved_source())
        return helper._pack(con).read_text(encoding="utf-8")
    finally:
        con.close()


def test_the_reviewed_source_is_pinned_and_additive_only() -> None:
    helper = _load_helper()
    source = helper.assert_approved_source()
    assert "CREATE TABLE IF NOT EXISTS b66_template_source" in source
    assert "CREATE INDEX IF NOT EXISTS idx_b66_template_source_owner_workspace_status" in source
    for forbidden in ("ALTER", "DROP", "UPDATE ", "INSERT", "REPLACE", "TRUNCATE"):
        assert forbidden not in source.upper(), forbidden


def test_the_060_gate_pins_the_same_027_source() -> None:
    # One authority for the merged migration: the 060 gate already treats 027 as
    # a prerequisite source, and both gates must agree on its bytes.
    helper = _load_helper()
    helper_060 = _load(HELPER_060, "b62_d1_060")
    assert helper_060.PINNED_SHA256[RELEASE.name] == helper.PINNED_SHA256
    assert hashlib.sha256(RELEASE.read_bytes()).hexdigest() == helper.PINNED_SHA256


def test_the_060_gate_cannot_run_before_027_is_applied() -> None:
    # 060 rebuilds b66_template_source, so the 060 gate's prerequisite set
    # names the table 027 creates.
    helper_060 = _load(HELPER_060, "b62_d1_060")
    tables = {entry["table"] for entry in helper_060.TABLES}
    assert TABLE in tables
    sql = (ROOT / "apps/padiem-chat/migrations/060_byte_length_capacity_ceiling_release.sql").read_text(
        encoding="utf-8"
    )
    assert f"FROM {TABLE};" in sql


def test_the_helper_refuses_an_unreviewed_source() -> None:
    helper = _load_helper()
    pinned = helper.PINNED_SHA256
    helper.PINNED_SHA256 = "0" * 64
    try:
        helper.assert_approved_source()
    except helper.GateError:
        pass
    else:
        raise AssertionError("an unreviewed 027 source must be refused")
    finally:
        helper.PINNED_SHA256 = pinned


def test_the_helper_refuses_a_mutating_source() -> None:
    helper = _load_helper()
    reviewed = helper.assert_approved_source()
    # The reviewed source itself is accepted.
    assert helper.assert_additive_only(reviewed) is None
    assert reviewed == RELEASE.read_text(encoding="utf-8")
    for statement in (
        "DROP TABLE b66_template_source;",
        "DELETE FROM b66_template_source;",
        "UPDATE b66_template_source SET status='disabled';",
        "ALTER TABLE b66_template_source RENAME TO other;",
    ):
        broken = reviewed + "\n" + statement
        try:
            helper.assert_additive_only(broken)
        except helper.GateError:
            pass
        else:
            raise AssertionError(f"a mutating statement must be refused: {statement}")


def test_the_helper_refuses_a_source_that_creates_something_else() -> None:
    helper = _load_helper()
    broken = (
        "CREATE TABLE IF NOT EXISTS b66_quote_asset (id TEXT PRIMARY KEY);\n"
        "CREATE INDEX IF NOT EXISTS idx_b66_quote_asset_owner (id);"
    )
    try:
        helper.assert_additive_only(broken)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a source that creates another table must be refused")


def test_the_classifier_accepts_only_the_three_legal_live_shapes() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as folder:
        missing = Path(folder) / "missing.json"
        missing.write_text(_payload(helper, with_release=False), encoding="utf-8")
        exact = Path(folder) / "exact.json"
        exact.write_text(_payload(helper, with_release=True), encoding="utf-8")
        assert helper.classify(str(missing)) == "MISSING"
        assert helper.classify(str(exact)) == "EXACT"


def test_the_classifier_refuses_a_changed_shape() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as folder:
        base = json.loads(_payload(helper, with_release=True))

        dropped_index = json.loads(json.dumps(base))
        dropped_index["result"][0]["results"] = [
            row
            for row in dropped_index["result"][0]["results"]
            if row.get("name") != INDEX
        ]
        path = Path(folder) / "no-index.json"
        path.write_text(json.dumps(dropped_index), encoding="utf-8")
        assert helper.classify(str(path)) == "DRIFT"

        dropped_column = json.loads(json.dumps(base))
        dropped_column["result"][1]["results"] = [
            row
            for row in dropped_column["result"][1]["results"]
            if row.get("name") != "object_key"
        ]
        path = Path(folder) / "no-column.json"
        path.write_text(json.dumps(dropped_column), encoding="utf-8")
        assert helper.classify(str(path)) == "DRIFT"

        dropped_fk = json.loads(json.dumps(base))
        dropped_fk["result"][2]["results"] = [
            row for row in dropped_fk["result"][2]["results"] if row.get("table") != "users"
        ]
        path = Path(folder) / "no-fk.json"
        path.write_text(json.dumps(dropped_fk), encoding="utf-8")
        assert helper.classify(str(path)) == "DRIFT"


def test_the_classifier_refuses_malformed_evidence() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as folder:
        base = json.loads(_payload(helper, with_release=True))
        failed = json.loads(json.dumps(base))
        failed["result"][0]["success"] = False
        path = Path(folder) / "failed.json"
        path.write_text(json.dumps(failed), encoding="utf-8")
        try:
            helper.classify(str(path))
        except helper.GateError:
            pass
        else:
            raise AssertionError("a failed D1 statement must be refused")

        truncated = json.loads(json.dumps(base))
        truncated["result"] = truncated["result"][:2]
        path = Path(folder) / "truncated.json"
        path.write_text(json.dumps(truncated), encoding="utf-8")
        try:
            helper.classify(str(path))
        except helper.GateError:
            pass
        else:
            raise AssertionError("an incomplete D1 response must be refused")


def test_the_classifier_refuses_a_missing_parent_table() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as folder:
        base = json.loads(_payload(helper, with_release=True))
        no_parent = json.loads(json.dumps(base))
        no_parent["result"][4]["results"] = []
        path = Path(folder) / "no-parent.json"
        path.write_text(json.dumps(no_parent), encoding="utf-8")
        try:
            helper.classify(str(path))
        except helper.GateError:
            pass
        else:
            raise AssertionError("a missing owner table must be refused")


def test_the_apply_payload_is_the_reviewed_migration_file() -> None:
    helper = _load_helper()
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "apply.json"
        assert helper.main(["payload", str(target)]) == 0
        payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"sql": RELEASE.read_text(encoding="utf-8")}


def test_the_offline_contract_reports_no_production_mutation() -> None:
    helper = _load_helper()
    assert helper.main(["offline"]) == 0


def test_the_workflow_is_exact_main_single_migration_and_fail_closed() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helper_source = HELPER.read_text(encoding="utf-8")
    # The exact-main pin is checked twice: once before the dispatch may act and
    # once again immediately before the mutation.
    assert workflow.count('test "$(git rev-parse origin/main)" = "${TARGET_SHA}"') == 3
    assert workflow.count('test "$(git rev-parse HEAD)" = "${TARGET_SHA}"') == 3
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_B66_D1_MIGRATION_027_FROM_EXACT_MAIN" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "padiem-chat" in workflow
    assert "027_b66_template_source.sql" in workflow
    # The reviewed source is the only SQL that can reach the database.
    assert "b62_d1_migration_027_schema.py payload" in workflow
    assert "B62_D1_MIGRATION_027_POST_APPLY=EXACT" in workflow
    assert "B62_D1_MIGRATION_027_FOREIGN_KEY_CHECK=PASS" in workflow
    assert "D1_RECOVERY_AVAILABLE=PASS" in workflow
    assert "D1_BINDING_IDENTITY_STABLE=PASS" in workflow
    assert "PREMUTATION_SCHEMA_STATE_STABLE=PASS" in workflow
    assert "D1_027_APPROVED_SOURCE_SHA=PASS" in helper_source
    assert "D1_027_ADDITIVE_SOURCE_ONLY=PASS" in helper_source
    assert "D1_027_SCHEMA_STATES=MISSING_EXACT_DRIFT_PASS" in helper_source
    # Nothing that deploys or mutates a binding.
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_CONTENT_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow

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
        assert token not in workflow, token

    # The mutation path must be dispatch-only; pull requests run source-contract.
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_027'"
        in workflow
    )
    assert "if: ${{ env.READONLY_SCHEMA_STATE == 'missing' }}" in workflow
    assert "if: ${{ env.READONLY_SCHEMA_STATE == 'exact' }}" in workflow
    # The workflow's own drift branch must stop the run, not just report it.
    assert (
        "            drift)\n"
        "              echo 'Refusing mutation: the existing 027 schema is structurally different.' >&2\n"
        "              exit 1\n"
        "              ;;"
    ) in workflow


if __name__ == "__main__":
    test_the_reviewed_source_is_pinned_and_additive_only()
    test_the_060_gate_pins_the_same_027_source()
    test_the_060_gate_cannot_run_before_027_is_applied()
    test_the_helper_refuses_an_unreviewed_source()
    test_the_helper_refuses_a_mutating_source()
    test_the_helper_refuses_a_source_that_creates_something_else()
    test_the_classifier_accepts_only_the_three_legal_live_shapes()
    test_the_classifier_refuses_a_changed_shape()
    test_the_classifier_refuses_malformed_evidence()
    test_the_classifier_refuses_a_missing_parent_table()
    test_the_apply_payload_is_the_reviewed_migration_file()
    test_the_offline_contract_reports_no_production_mutation()
    test_the_workflow_is_exact_main_single_migration_and_fail_closed()
    print("B62_D1_MIGRATION_027_GATE_TESTS=PASS")
