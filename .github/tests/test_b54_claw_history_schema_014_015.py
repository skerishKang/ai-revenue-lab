"""Network-free contract for #4072's read-only 014/015 production classifier."""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
import b54_claw_history_schema_014_015 as audit


def source_sql(name: str) -> str:
    return (ROOT / "apps" / "padiem-chat" / "migrations" / name).read_text(encoding="utf-8")


def metadata(db: sqlite3.Connection) -> dict:
    db.row_factory = sqlite3.Row
    sets = [
        list(db.execute(
            "SELECT name,type,sql FROM sqlite_master WHERE name "
            "IN ('claw_run_history','idx_claw_run_history_user_created') ORDER BY name"
        )),
        list(db.execute("PRAGMA table_info(claw_run_history)")),
        list(db.execute("PRAGMA index_info(idx_claw_run_history_user_created)")),
    ]
    return {"success": True, "result": [
        {"success": True, "results": [dict(x) for x in rows]} for rows in sets
    ]}


class ClawHistory014015Tests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def tearDown(self):
        self.db.close()

    def test_missing(self):
        self.assertEqual(audit.classify(metadata(self.db)), "MISSING")

    def test_real_source_migrations_are_additive_in_order(self):
        self.db.executescript(source_sql("009_claw_run_history.sql"))
        self.assertEqual(audit.classify(metadata(self.db)), "BASE_009")
        with self.assertRaisesRegex(sqlite3.OperationalError, "no such column: conversation_id"):
            self.db.execute("SELECT conversation_id FROM claw_run_history LIMIT 1").fetchall()
        self.db.executescript(source_sql("014_claw_run_history_conversation.sql"))
        self.assertEqual(audit.classify(metadata(self.db)), "CONVERSATION_014")
        self.db.execute("SELECT conversation_id FROM claw_run_history LIMIT 1").fetchall()
        self.db.executescript(source_sql("015_claw_run_history_workspace.sql"))
        self.assertEqual(audit.classify(metadata(self.db)), "READY_015")
        self.db.execute("SELECT conversation_id,workspace_id FROM claw_run_history LIMIT 1").fetchall()

    def test_preexisting_rows_preserved_by_actual_migrations(self):
        self.db.executescript(source_sql("009_claw_run_history.sql"))
        self.db.execute(
            "INSERT INTO claw_run_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("synthetic", "owner-fixture", "run-fixture", "claw", "execute",
             "test", "failed", "a", "a", None, None, None, None),
        )
        before = self.db.execute("SELECT COUNT(*) FROM claw_run_history").fetchone()[0]
        self.db.executescript(source_sql("014_claw_run_history_conversation.sql"))
        self.db.executescript(source_sql("015_claw_run_history_workspace.sql"))
        after = self.db.execute(
            "SELECT COUNT(*) FROM claw_run_history"
        ).fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(self.db.execute(
            "SELECT conversation_id,workspace_id FROM claw_run_history "
            "WHERE id='synthetic'"
        ).fetchone(), (None, None))

    def test_unexpected_column_drift_fails_closed(self):
        self.db.executescript(source_sql("009_claw_run_history.sql"))
        self.db.execute("ALTER TABLE claw_run_history ADD COLUMN unexpected TEXT")
        self.assertEqual(audit.classify(metadata(self.db)), "DRIFT")

    def test_wrong_additive_order_fails_closed(self):
        self.db.executescript(source_sql("009_claw_run_history.sql"))
        self.db.executescript(source_sql("015_claw_run_history_workspace.sql"))
        self.assertEqual(audit.classify(metadata(self.db)), "DRIFT")

    def test_missing_index_is_drift(self):
        self.db.executescript(source_sql("009_claw_run_history.sql"))
        self.db.execute("DROP INDEX idx_claw_run_history_user_created")
        self.assertEqual(audit.classify(metadata(self.db)), "DRIFT")

    def test_query_error_fails_closed(self):
        self.db.executescript(source_sql("009_claw_run_history.sql"))
        p = metadata(self.db)
        p["result"][1]["success"] = False
        with self.assertRaises(audit.SchemaEvidenceError):
            audit.classify(p)

    def test_no_owner_row_data_in_metadata(self):
        self.db.executescript(source_sql("009_claw_run_history.sql"))
        self.assertNotIn("owner-fixture", json.dumps(metadata(self.db)))


if __name__ == "__main__":
    unittest.main()
