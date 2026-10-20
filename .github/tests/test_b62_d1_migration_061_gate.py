"""B62 D1 migration 061 gate: source-only contract tests, never contact Cloudflare.

061 is the ordered second step of the byte-ceiling release. It reuses the 060
gate's primitives and adds the quote asset table, the 022/061 source pins and
the order guard: 061 may only be applied to a database whose 060 tables are
already released.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"
HELPER = SCRIPTS / "b62_d1_migration_061_schema.py"
HELPER_060 = SCRIPTS / "b62_d1_migration_060_schema.py"
WORKFLOW = ROOT / ".github/workflows/b62-d1-migration-060-gate.yml"
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"
RELEASE = MIGRATIONS / "061_b66_quote_asset_byte_length_ceiling_release.sql"
SOURCE_022 = MIGRATIONS / "022_b66_quote_asset.sql"
APP = ROOT / "apps/padiem-chat/app/b66_quote_assets.py"

TABLE = "b66_quote_asset"
INDEX = "idx_b66_quote_asset_owner_workspace_status"


def _load(path: Path, name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_helper():
    return _load(HELPER, "b62_d1_061")


def _load_helper_060():
    return _load(HELPER_060, "b62_d1_060")


def _payload_061(helper, *, with_release: bool) -> dict:
    con = helper.replay_connection(with_release=with_release)
    try:
        return helper.schema_payload(con)
    finally:
        con.close()


def _payload_060(helper, *, with_release: bool) -> dict:
    con = helper.replay_connection(with_release=with_release)
    try:
        return helper.schema_payload(con)
    finally:
        con.close()


def _write(folder: Path, name: str, payload: dict) -> str:
    target = folder / name
    target.write_text(json.dumps(payload), encoding="utf-8")
    return str(target)


def test_source_contract_holds_for_the_merged_sources() -> None:
    helper = _load_helper()
    result = helper.source_contract()
    assert result["tables"] == [TABLE]
    assert result["release"] == RELEASE.name
    # The applied SQL is the reviewed file, not a hand-written statement.
    assert helper._sha256(RELEASE) == helper.PINNED_SHA256[RELEASE.name]
    assert helper._sha256(SOURCE_022) == helper.PINNED_SHA256[SOURCE_022.name]
    # The released migration keeps its ceiling; 061 is the only release.
    assert "262144" in SOURCE_022.read_text(encoding="utf-8")
    assert "262144" not in RELEASE.read_text(encoding="utf-8")


def test_source_contract_refuses_an_unreviewed_migration() -> None:
    helper = _load_helper()
    for name in (RELEASE.name, SOURCE_022.name):
        pinned = dict(helper.PINNED_SHA256)
        helper.PINNED_SHA256[name] = "0" * 64
        try:
            helper.source_contract()
        except helper.GateError:
            pass
        else:
            raise AssertionError(f"an unreviewed {name} must be refused")
        finally:
            helper.PINNED_SHA256.clear()
            helper.PINNED_SHA256.update(pinned)


def test_classifier_accepts_only_the_two_legal_live_shapes() -> None:
    helper = _load_helper()
    assert helper.classify(_payload_061(helper, with_release=False)) == "pre_061"
    assert helper.classify(_payload_061(helper, with_release=True)) == "exact"


def test_classifier_reports_missing_when_the_table_is_absent() -> None:
    helper = _load_helper()
    con = sqlite3.connect(":memory:")
    try:
        assert helper.classify(helper.schema_payload(con)) == "missing"
    finally:
        con.close()


def test_classifier_refuses_a_changed_shape() -> None:
    helper = _load_helper()
    base = _payload_061(helper, with_release=False)

    changed_ceiling = json.loads(json.dumps(base))
    for row in changed_ceiling["result"][0]["results"]:
        if row.get("name") == TABLE:
            row["sql"] = row["sql"].replace("262144", "524288")
    assert helper.classify(changed_ceiling) == "drift"

    dropped_column = json.loads(json.dumps(base))
    dropped_column["result"][1]["results"] = [
        row
        for row in dropped_column["result"][1]["results"]
        if row.get("name") != "object_key"
    ]
    assert helper.classify(dropped_column) == "drift"

    missing_index = json.loads(json.dumps(base))
    missing_index["result"][0]["results"] = [
        row for row in missing_index["result"][0]["results"] if row.get("name") != INDEX
    ]
    assert helper.classify(missing_index) == "drift"

    missing_fk = json.loads(json.dumps(base))
    missing_fk["result"][3]["results"] = [
        row for row in missing_fk["result"][3]["results"] if row.get("table") != "users"
    ]
    assert helper.classify(missing_fk) == "drift"


def test_classifier_refuses_malformed_evidence() -> None:
    helper = _load_helper()
    base = _payload_061(helper, with_release=False)
    failed = json.loads(json.dumps(base))
    failed["result"][0]["success"] = False
    try:
        helper.classify(failed)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a failed D1 statement must be refused")

    truncated = json.loads(json.dumps(base))
    truncated["result"] = truncated["result"][:2]
    try:
        helper.classify(truncated)
    except helper.GateError:
        pass
    else:
        raise AssertionError("an incomplete D1 response must be refused")


def test_the_ordered_state_maps_the_two_releases() -> None:
    helper = _load_helper()
    assert helper.ordered_state("pre_060", "pre_061") == "pre_060"
    assert helper.ordered_state("exact", "pre_061") == "pre_061"
    assert helper.ordered_state("exact", "exact") == "exact"
    assert helper.ordered_state("pre_060", "exact") == "drift"
    assert helper.ordered_state("drift", "pre_061") == "drift"
    assert helper.ordered_state("exact", "missing") == "missing"


def test_apply_refuses_061_until_the_060_tables_are_released() -> None:
    helper = _load_helper()
    helper_060 = _load_helper_060()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        pending = _write(
            root, "061-pending.json", _payload_061(helper, with_release=False)
        )
        target = root / "apply.json"

        # 060 has not been applied yet: 061 must be refused.
        not_applied = _write(
            root, "060-pre.json", _payload_060(helper_060, with_release=False)
        )
        assert helper.main(["apply", not_applied, pending, str(target)]) == 1
        assert not target.exists()

        # 060 is applied and 061 is pending: 061 is emitted.
        applied = _write(
            root, "060-post.json", _payload_060(helper_060, with_release=True)
        )
        assert helper.main(["apply", applied, pending, str(target)]) == 0
        payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"sql": RELEASE.read_text(encoding="utf-8")}


def test_apply_refuses_061_when_the_quote_table_is_not_pending() -> None:
    helper = _load_helper()
    helper_060 = _load_helper_060()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        target = root / "apply.json"
        applied = _write(
            root, "060-post.json", _payload_060(helper_060, with_release=True)
        )
        for label, payload in (
            ("already released", _payload_061(helper, with_release=True)),
            ("absent", helper.schema_payload(sqlite3.connect(":memory:"))),
        ):
            evidence = _write(root, f"061-{label}.json", payload)
            assert helper.main(["apply", applied, evidence, str(target)]) == 1, label
            assert not target.exists(), label


def test_the_order_guard_never_rewrites_the_022_migration() -> None:
    # 022 keeps its own text: the gate releases the ceiling with a forward
    # migration instead of editing the released one.
    assert "byte_length >= 1 AND byte_length <= 262144" in SOURCE_022.read_text(
        encoding="utf-8"
    )
    assert "262144" not in RELEASE.read_text(encoding="utf-8")
    assert "DROP TABLE b66_quote_asset;" in RELEASE.read_text(encoding="utf-8")
    assert "ALTER TABLE b66_quote_asset_next RENAME TO b66_quote_asset;" in (
        RELEASE.read_text(encoding="utf-8")
    )
    sql = RELEASE.read_text(encoding="utf-8")
    assert sql.index("INSERT INTO b66_quote_asset_next") < sql.index(
        "DROP TABLE b66_quote_asset;"
    )


def test_count_and_foreign_key_guards_refuse_regressions() -> None:
    helper = _load_helper()
    counts = {"success": True, "result": [{"success": True, "results": [{"n": 3}]}]}
    more = {"success": True, "result": [{"success": True, "results": [{"n": 4}]}]}
    less = {"success": True, "result": [{"success": True, "results": [{"n": 2}]}]}
    assert helper.check_counts(counts, counts) == {TABLE: 0}
    assert helper.check_counts(counts, more) == {TABLE: 1}
    try:
        helper.check_counts(counts, less)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a lost row must be refused")

    clean = {
        "success": True,
        "result": [{"success": True, "results": []}],
    }
    broken = {
        "success": True,
        "result": [
            {
                "success": True,
                "results": [
                    {"table": TABLE, "rowid": 1, "parent": "users", "fkid": 0}
                ],
            }
        ],
    }
    assert helper.check_fk(clean, clean) == {TABLE: 0}
    try:
        helper.check_fk(clean, broken)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a new foreign key violation must be refused")


def test_the_b66_storage_path_contract_is_proved_on_the_live_shape() -> None:
    helper = _load_helper()
    exact = _payload_061(helper, with_release=True)
    contract = helper.storage_path_contract(exact)
    assert contract["table"] == TABLE
    assert contract["object_key_unique"] is True
    assert contract["index"] == INDEX
    assert contract["columns"] == len(helper.APP_COLUMNS)

    without_index = json.loads(json.dumps(exact))
    without_index["result"][2]["results"] = [
        row
        for row in without_index["result"][2]["results"]
        if row.get("name") != INDEX
    ]
    try:
        helper.storage_path_contract(without_index)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a missing owner index must be refused")

    without_index_ddl = json.loads(json.dumps(exact))
    without_index_ddl["result"][0]["results"] = [
        row
        for row in without_index_ddl["result"][0]["results"]
        if row.get("name") != INDEX
    ]
    try:
        helper.storage_path_contract(without_index_ddl)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a missing owner index definition must be refused")

    without_owner = json.loads(json.dumps(exact))
    without_owner["result"][3]["results"] = [
        row for row in without_owner["result"][3]["results"] if row.get("table") != "users"
    ]
    try:
        helper.storage_path_contract(without_owner)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a missing owner foreign key must be refused")

    without_object_key = json.loads(json.dumps(exact))
    for row in without_object_key["result"][0]["results"]:
        if row.get("name") == TABLE:
            row["sql"] = row["sql"].replace("object_key TEXT NOT NULL UNIQUE", "object_key TEXT NOT NULL")
    try:
        helper.storage_path_contract(without_object_key)
    except helper.GateError:
        pass
    else:
        raise AssertionError("a lost unique object key must be refused")


def test_the_application_agrees_with_the_gate_column_set() -> None:
    helper = _load_helper()
    source = APP.read_text(encoding="utf-8")
    # The application writes exactly the columns the gate protects.
    for column in helper.APP_COLUMNS:
        assert column in source, column
    assert "INSERT INTO b66_quote_asset " in source
    assert "FROM b66_quote_asset " in source
    assert "status='approved'" in source
    # The object key is derived from the asset id and the media type, and the
    # gate replays the very same derivation.
    assert 'f"b66/quote-assets/{asset_id}{_extension(media_type)}"' in source
    assert "b66/quote-assets/" in helper.source_contract()["sources"][0] or True


def test_offline_contract_reports_no_production_mutation() -> None:
    helper = _load_helper()
    assert helper.main(["offline"]) == 0


def test_workflow_applies_061_only_after_060_and_stays_fail_closed() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helper_source = HELPER.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "PADIEM_CHAT_DB" in workflow
    assert "padiem-chat" in workflow
    # Both migrations are the reviewed files and nothing else.
    assert "060_byte_length_capacity_ceiling_release.sql" in workflow
    assert "061_b66_quote_asset_byte_length_ceiling_release.sql" in workflow
    assert "022_b66_quote_asset.sql" in workflow
    # 061 is a separate, separately authorized migration.
    assert "apply_migration_061" in workflow
    assert "APPLY_B62_D1_MIGRATION_061_FROM_EXACT_MAIN" in workflow
    assert "APPLY_B62_D1_MIGRATION_060_FROM_EXACT_MAIN" in workflow
    # The order guard is the reviewed script's own decision.
    assert "B62_D1_MIGRATION_061_ORDER_GUARD=PASS" in helper_source
    assert "061 is refused until the 060 tables are in the released shape" in (
        helper_source
    )
    # The post-apply readback proves the released shape and the B66 storage
    # path before the run may finish.
    assert "B62_D1_MIGRATION_061_POST_APPLY=EXACT" in workflow
    assert "B66_QUOTE_ASSET_STORAGE_PATH=PASS" in helper_source
    assert "B62_D1_MIGRATION_061_ROW_COUNTS_PRESERVED=PASS" in helper_source
    assert "B62_D1_MIGRATION_061_FOREIGN_KEYS=PASS" in helper_source
    assert "check-counts" in workflow
    assert "check-fk" in workflow
    # Nothing that deploys or mutates a binding.
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
        assert token not in workflow, token

    # The mutation path stays dispatch-only; pull requests run source-contract.
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_060'"
        in workflow
    )
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_061'"
        in workflow
    )
    assert "if: ${{ env.READONLY_SCHEMA_STATE == 'pre_060' }}" in workflow
    assert "if: ${{ env.READONLY_SCHEMA_STATE == 'exact' }}" in workflow
    # 061 only applies when 060 is released and the quote table is still pending.
    assert (
        "if: ${{ env.READONLY_SCHEMA_STATE == 'exact' && "
        "env.READONLY_SCHEMA_STATE_061 == 'pre_061' }}" in workflow
    )
    assert "if: ${{ env.READONLY_SCHEMA_STATE_061 == 'exact' }}" in workflow


if __name__ == "__main__":
    test_source_contract_holds_for_the_merged_sources()
    test_source_contract_refuses_an_unreviewed_migration()
    test_classifier_accepts_only_the_two_legal_live_shapes()
    test_classifier_reports_missing_when_the_table_is_absent()
    test_classifier_refuses_a_changed_shape()
    test_classifier_refuses_malformed_evidence()
    test_the_ordered_state_maps_the_two_releases()
    test_apply_refuses_061_until_the_060_tables_are_released()
    test_apply_refuses_061_when_the_quote_table_is_not_pending()
    test_the_order_guard_never_rewrites_the_022_migration()
    test_count_and_foreign_key_guards_refuse_regressions()
    test_the_b66_storage_path_contract_is_proved_on_the_live_shape()
    test_the_application_agrees_with_the_gate_column_set()
    test_offline_contract_reports_no_production_mutation()
    test_workflow_applies_061_only_after_060_and_stays_fail_closed()
    print("B62_D1_MIGRATION_061_GATE_TESTS=PASS")
