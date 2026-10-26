"""071 source-only release gate: exact schemas, two counts, unchanged receipts."""
import copy
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_d1_migration_071_schema.py"
WORKFLOW = ROOT / ".github/workflows/b62-d1-migration-071-gate.yml"
spec = importlib.util.spec_from_file_location("migration_071", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def payload(db):
    db.row_factory = sqlite3.Row
    return {"success": True, "result": [
        {"success": True, "results": [dict(row) for row in db.execute(sql)]}
        for sql in module.QUERY.split(";") if sql.strip()
    ]}


def database():
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    parent, receipt, _ = module.source()
    db.executescript(parent + receipt)
    return db


def seed(db):
    row = ("sel_test", "owner_test", "workspace_test", "doc_test", "a" * 64,
           "test.xlsx", 1048576, "source_selected_p01_not_started", "created", "expires")
    receipt = (row[0], row[1], row[2], "run_test", row[3], row[4], "workcopy_test",
               "b" * 64, "school_test", 100, "confirmed", "revision_test", "c" * 64,
               "created", "updated")
    db.execute("INSERT INTO claw_web_xlsx_selections VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    db.execute("INSERT INTO claw_web_xlsx_quote_edit_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", receipt)
    return row, receipt


class Gate071Tests(unittest.TestCase):
    def setUp(self):
        self.db = database()
        self.addCleanup(self.db.close)

    def migrate(self):
        self.db.executescript("BEGIN;" + module.source()[2] + "COMMIT;")

    def test_reference_old_and_new_classify_both_tables(self):
        self.assertEqual(module.classify(payload(self.db)), ("029", dict.fromkeys(module.TABLES, 0)))
        self.migrate()
        self.assertEqual(module.classify(payload(self.db)), ("071", dict.fromkeys(module.TABLES, 0)))

    def test_transaction_keeps_exact_rows_grants_indexes_and_foreign_keys(self):
        row, receipt = seed(self.db)
        before = payload(self.db)
        self.migrate()
        module.verify_preservation(before, payload(self.db))
        self.assertEqual(tuple(self.db.execute("SELECT * FROM claw_web_xlsx_selections").fetchone()), row)
        self.assertEqual(tuple(self.db.execute("SELECT * FROM claw_web_xlsx_quote_edit_receipts").fetchone()), receipt)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        names = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("idx_claw_web_xlsx_selections_owner", names)
        self.assertIn("idx_claw_web_xlsx_quote_edit_owner", names)

    def test_old_one_mib_and_new_ten_mib_boundaries(self):
        seed(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE claw_web_xlsx_selections SET size_bytes=1048577")
        self.migrate()
        self.db.execute("UPDATE claw_web_xlsx_selections SET size_bytes=10485760")
        for invalid in (0, 10485761):
            with self.subTest(invalid=invalid), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute("UPDATE claw_web_xlsx_selections SET size_bytes=?", (invalid,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE claw_web_xlsx_selections SET source_sha256='bad'")

    def test_parent_sql_drift_fails(self):
        value = payload(self.db)
        for row in value["result"][0]["results"]:
            if row["name"] == module.TABLES[0]:
                row["sql"] = row["sql"].replace("1048576", "2097152")
        self.assertEqual(module.classify(value)[0], "DRIFT")

    def test_receipt_sql_drift_fails_even_with_valid_parent(self):
        self.migrate()
        value = payload(self.db)
        for row in value["result"][0]["results"]:
            if row["name"] == module.TABLES[1]:
                row["sql"] = row["sql"].replace("supply_amount>0", "supply_amount>=0")
        self.assertEqual(module.classify(value)[0], "DRIFT")

    def test_missing_duplicate_or_wrong_type_table_fails(self):
        value = payload(self.db)
        for rows in (value["result"][0]["results"][:1],
                     value["result"][0]["results"][:1] * 2,
                     [{"name": module.TABLES[0], "type": "view", "sql": "SELECT 1"}]):
            modified = copy.deepcopy(value)
            modified["result"][0]["results"] = rows
            self.assertEqual(module.classify(modified)[0], "DRIFT")

    def test_foreign_key_violations_fail(self):
        value = payload(self.db)
        value["result"][3]["results"] = [{"table": module.TABLES[1], "rowid": 1}]
        self.assertEqual(module.classify(value)[0], "DRIFT")

    def test_counts_reject_invalid_values(self):
        for index in (1, 2):
            for count in (-1, True, 1.0, "1"):
                value = payload(self.db)
                value["result"][index]["results"] = [{"n": count}]
                self.assertEqual(module.classify(value)[0], "DRIFT")

    def test_failed_or_incomplete_api_payload_fails(self):
        for value in ({}, {"success": False}, {"success": True, "result": []},
                      {"success": True, "result": [{"success": False}] * 4}):
            with self.assertRaises(ValueError):
                module.classify(value)

    def test_each_table_count_is_compared_independently(self):
        seed(self.db)
        before = payload(self.db)
        self.migrate()
        after = payload(self.db)
        for index in (1, 2):
            modified = copy.deepcopy(after)
            modified["result"][index]["results"][0]["n"] += 1
            with self.assertRaises(ValueError):
                module.verify_preservation(before, modified)
        with self.assertRaises(ValueError):
            module.verify_preservation(before, before)
        module.verify_preservation(after, after)  # Already 071 is a verified no-op.

    def test_partial_apply_response_is_not_success(self):
        for value in ({}, {"success": True, "result": []},
                      {"success": True, "result": [{"success": True}, {"success": False}]}):
            with self.assertRaises(ValueError):
                module.check_apply(value)
        module.check_apply({"success": True, "result": [{"success": True}]})

    def test_cli_query_and_apply_are_source_only_and_apply_requires_029(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            subprocess.run([sys.executable, str(SCRIPT), "query", str(path)], check=True, capture_output=True)
            self.assertEqual(json.loads(path.read_text())["sql"], module.QUERY)
            subprocess.run([sys.executable, str(SCRIPT), "apply", str(path), "029"], check=True, capture_output=True)
            self.assertEqual(json.loads(path.read_text())["sql"], module.source()[2])
            result = subprocess.run([sys.executable, str(SCRIPT), "apply", str(path), "071"], capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_workflow_exact_main_confirmation_and_two_count_guards(self):
        text = WORKFLOW.read_text()
        for required in ("repository_preflight", "- readonly", "apply_migration_071",
                         "environment: production", "APPLY_B62_WEB_XLSX_071_FROM_EXACT_MAIN",
                         "PADIEM_CHAT_DB", "029|071", "env.STATE != '071'",
                         'test "${POST_SELECTION_COUNT}" = "${BEFORE_SELECTION_COUNT}"',
                         'test "${POST_RECEIPT_COUNT}" = "${BEFORE_RECEIPT_COUNT}"',
                         "verify-preservation", "032_claw_web_xlsx_quote_edit_receipts.sql",
                         "071_claw_web_xlsx_selection_limit.sql"):
            self.assertIn(required, text)
        self.assertGreaterEqual(text.count('test "$(git rev-parse origin/main)" = "${TARGET_SHA}"'), 4)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.mode != 'repository_preflight'", text)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_071'", text)
        self.assertNotIn("curl --verbose", text)
        self.assertNotIn("set -x", text)


if __name__ == "__main__":
    unittest.main()
